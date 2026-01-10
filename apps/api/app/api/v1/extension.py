import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from models import AgentClient, AgentInbox, User, CodeEvent

router = APIRouter(prefix="/extension", tags=["extension"])
logger = logging.getLogger(__name__)

HEARTBEAT_TTL_MINUTES = 5
MAX_INBOX_LIMIT = 50
VALID_STATUSES = {"pending", "accepted", "done", "rejected", "error"}
APPLY_PATCH_TYPE = "APPLY_PATCH"
NOTIFY_TYPE = "NOTIFY"
MAX_NOTIFY_BYTES = 20_000


class HeartbeatRequest(BaseModel):
    device_id: str = Field(..., description="Client device identifier, e.g. vscode-<uuid>")
    repo_id: str = Field(..., description="Stable repository identifier")
    branch: Optional[str] = None
    head_sha: Optional[str] = None
    capabilities: Dict = Field(default_factory=dict)


class InboxAckRequest(BaseModel):
    status: str = Field(..., description="accepted|done|rejected|error")
    result: Optional[Dict] = None


class SendTaskRequest(BaseModel):
    to_user_id: Optional[str] = None
    repo_id: Optional[str] = None
    task_type: str
    payload: Dict = Field(default_factory=dict)


def _error_response(request: Request, status_code: int, error_code: str, message: str) -> JSONResponse:
    req_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error_code": error_code,
            "message": message,
            "request_id": req_id,
        },
    )


def _require_same_org(db: Session, sender: User, target_user_id: str) -> Optional[User]:
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        return None
    if not sender.org_id or not target.org_id or sender.org_id != target.org_id:
        return None
    return target


def _active_clients_for_user(
    db: Session,
    user_id: str,
    fresh_seconds: int,
) -> List[AgentClient]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=fresh_seconds)
    return (
        db.query(AgentClient)
        .filter(
            AgentClient.user_id == user_id,
            AgentClient.last_seen_at >= cutoff,
        )
        .order_by(AgentClient.last_seen_at.desc())
        .all()
    )


@router.post("/heartbeat")
def heartbeat(
    request: Request,
    body: HeartbeatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.org_id:
        return _error_response(request, 403, "ORG_REQUIRED", "User must belong to an org to send heartbeats.")

    existing = (
        db.query(AgentClient)
        .filter(
            AgentClient.user_id == current_user.id,
            AgentClient.device_id == body.device_id,
            AgentClient.repo_id == body.repo_id,
        )
        .first()
    )
    now_ts = datetime.now(timezone.utc)
    if existing:
        existing.branch = body.branch
        existing.head_sha = body.head_sha
        existing.capabilities = body.capabilities or {}
        existing.last_seen_at = now_ts
        client = existing
    else:
        client = AgentClient(
            org_id=current_user.org_id,
            user_id=current_user.id,
            device_id=body.device_id,
            repo_id=body.repo_id,
            branch=body.branch,
            head_sha=body.head_sha,
            capabilities=body.capabilities or {},
            last_seen_at=now_ts,
        )
        db.add(client)
    db.commit()
    logger.info(
        "[ExtensionHeartbeat] user_id=%s repo_id=%s device_id=%s",
        current_user.id,
        body.repo_id,
        body.device_id,
    )
    return {"ok": True}


@router.get("/clients")
def list_clients(
    request: Request,
    fresh_seconds: int = Query(300, ge=1, le=86400),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = _active_clients_for_user(db, current_user.id, fresh_seconds)
    serialized = [
        {
            "repo_id": row.repo_id,
            "device_id": row.device_id,
            "branch": row.branch,
            "head_sha": row.head_sha,
            "last_seen_at": row.last_seen_at,
            "capabilities": row.capabilities or {},
        }
        for row in items
    ]
    return {"ok": True, "items": serialized}


def _record_apply_patch_event(
    *,
    task: AgentInbox,
    result: Dict,
    current_user: User,
    db: Session,
) -> None:
    """Persist a CodeEvent for an apply_patch completion."""
    try:
        if not task.org_id:
            return
        summary = (result.get("summary") or "").strip()
        if not summary:
            summary = "Apply patch completed"
        applied = result.get("applied")
        if applied is False:
            summary = f"[not applied] {summary}"
        details = result.get("details")
        if details:
            details = str(details)[:4000]
        event = CodeEvent(
            id=uuid.uuid4(),
            org_id=task.org_id,
            user_id=current_user.id,
            device_id=str(result.get("device_id") or task.from_user_id or "vscode-extension"),
            repo_id=task.repo_id,
            branch=result.get("branch"),
            head_sha_before=result.get("head_sha_before"),
            head_sha_after=result.get("head_sha_after"),
            event_type="apply_patch",
            files_touched=(result.get("files_changed") or [])[:50],
            systems_touched=result.get("systems_touched") or [],
            impact_tags=result.get("impact_tags") or [],
            summary=summary[:500],
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        logger.info(
            "[ApplyPatchEvent] task_id=%s event_id=%s repo_id=%s applied=%s",
            task.id,
            event.id,
            task.repo_id,
            applied,
        )
    except Exception as exc:
        logger.warning("[ApplyPatchEvent] failed to record event for task_id=%s error=%s", task.id, exc)


@router.get("/inbox")
def get_inbox(
    request: Request,
    repo_id: Optional[str] = Query(None, description="Filter by repo_id"),
    status: str = Query("pending", description="pending|accepted|done|rejected|error"),
    limit: int = Query(20, ge=1, le=MAX_INBOX_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    status_value = (status or "").lower()
    if status_value not in VALID_STATUSES:
        return _error_response(request, 400, "INVALID_STATUS", "Invalid status filter.")

    query = db.query(AgentInbox).filter(AgentInbox.to_user_id == current_user.id)
    if repo_id:
        query = query.filter(AgentInbox.repo_id == repo_id)
    if status_value:
        query = query.filter(AgentInbox.status == status_value)
    items = (
        query.order_by(AgentInbox.created_at.desc())
        .limit(min(limit, MAX_INBOX_LIMIT))
        .all()
    )
    serialized = [
        {
            "id": item.id,
            "task_type": item.task_type,
            "payload": item.payload or {},
            "status": item.status,
            "created_at": item.created_at,
            "from_user_id": item.from_user_id,
            "repo_id": item.repo_id,
        }
        for item in items
    ]
    return {"ok": True, "items": serialized}


@router.post("/inbox/{task_id}/ack")
def ack_inbox_task(
    task_id: str,
    request: Request,
    body: InboxAckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(AgentInbox).filter(AgentInbox.id == task_id).first()
    if not task:
        return _error_response(request, 404, "NOT_FOUND", "Task not found.")
    if task.to_user_id != current_user.id:
        return _error_response(request, 403, "FORBIDDEN", "Cannot modify tasks for another user.")
    new_status = body.status.lower()
    if new_status not in VALID_STATUSES:
        return _error_response(request, 400, "INVALID_STATUS", "Invalid status transition.")

    current = task.status or "pending"
    allowed = {
        "pending": {"accepted", "done", "rejected", "error"},
        "accepted": {"done", "rejected", "error"},
    }
    if current not in allowed:
        return _error_response(request, 400, "INVALID_STATE", f"Cannot transition from {current}.")
    if new_status not in allowed[current]:
        return _error_response(request, 400, "INVALID_TRANSITION", f"{current} -> {new_status} not allowed.")

    now_ts = datetime.now(timezone.utc)
    task.status = new_status
    task.updated_at = now_ts
    if body.result is not None:
        task.result = body.result
    if new_status == "error" and isinstance(body.result, dict) and body.result.get("error_code"):
        task.error_code = str(body.result.get("error_code"))
    if new_status in {"done", "rejected", "error"}:
        task.handled_at = now_ts
    # Best-effort: creating CodeEvent must not block ACK
    if task.task_type == APPLY_PATCH_TYPE and new_status == "done" and isinstance(body.result, dict):
        _record_apply_patch_event(task=task, result=body.result, current_user=current_user, db=db)
    db.add(task)
    db.commit()
    logger.info(
        "[ExtensionAck] user_id=%s task_id=%s status=%s",
        current_user.id,
        task_id,
        new_status,
    )
    return {"ok": True}


@router.post("/send-task")
def send_task(
    request: Request,
    body: SendTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_user_id = body.to_user_id or current_user.id
    if target_user_id == current_user.id:
        if not current_user.org_id:
            return _error_response(request, 403, "ORG_REQUIRED", "User must belong to an org to send tasks.")
        recipient = current_user
    else:
        recipient = _require_same_org(db, current_user, target_user_id)
        if recipient is None:
            return _error_response(request, 403, "ORG_MISMATCH", "Recipient must exist and share the same org.")
        if not recipient.org_id:
            return _error_response(request, 400, "ORG_REQUIRED", "Recipient is not associated with an org.")

    task_type = (body.task_type or "AGENT_TASK").upper()

    resolved_repo_id = body.repo_id
    if not resolved_repo_id:
        if recipient.id != current_user.id:
            return _error_response(request, 400, "REPO_REQUIRED", "Specify repo_id for other users.")
        active_clients = _active_clients_for_user(db, current_user.id, HEARTBEAT_TTL_MINUTES * 60)
        if len(active_clients) == 1:
            resolved_repo_id = active_clients[0].repo_id
        else:
            return _error_response(
                request,
                400,
                "REPO_REQUIRED",
                "Select a repo_id; multiple or zero active extensions detected.",
            )

    freshness_cutoff = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_TTL_MINUTES)
    active_client = (
        db.query(AgentClient)
        .filter(
            AgentClient.user_id == recipient.id,
            AgentClient.repo_id == resolved_repo_id,
            AgentClient.org_id == recipient.org_id,
            AgentClient.last_seen_at >= freshness_cutoff,
        )
        .order_by(AgentClient.last_seen_at.desc())
        .first()
    )
    if not active_client:
        return _error_response(
            request,
            409,
            "EXTENSION_OFFLINE",
            "Recipient extension is offline for this repo.",
        )

    # Optional payload size cap for NOTIFY tasks
    if task_type == NOTIFY_TYPE:
        try:
            import json
            payload_size = len(json.dumps(body.payload or {}).encode("utf-8"))
            if payload_size > MAX_NOTIFY_BYTES:
                return _error_response(
                    request,
                    400,
                    "PAYLOAD_TOO_LARGE",
                    f"notify payload exceeds {MAX_NOTIFY_BYTES} bytes",
                )
        except Exception:
            return _error_response(
                request,
                400,
                "INVALID_NOTIFY_PAYLOAD",
                "Unable to serialize notify payload",
            )

    task = AgentInbox(
        org_id=recipient.org_id,
        to_user_id=recipient.id,
        from_user_id=current_user.id,
        repo_id=resolved_repo_id,
        task_type=task_type,
        payload=body.payload or {},
        status="pending",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(
        "[ExtensionSendTask] task_type=%s from_user_id=%s to_user_id=%s task_id=%s repo_id=%s",
        task_type,
        current_user.id,
        recipient.id,
        task.id,
        resolved_repo_id,
    )
    return {"ok": True, "task_id": task.id}


@router.get("/tasks/{task_id}")
def get_task_status(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(AgentInbox).filter(AgentInbox.id == task_id).first()
    if not task:
        return _error_response(request, 404, "NOT_FOUND", "Task not found.")
    if task.to_user_id not in {current_user.id} and task.from_user_id not in {current_user.id}:
        return _error_response(request, 403, "FORBIDDEN", "Not authorized for this task.")
    if task.org_id and current_user.org_id and task.org_id != current_user.org_id:
        return _error_response(request, 403, "ORG_MISMATCH", "Task is scoped to a different org.")
    return {
        "ok": True,
        "task": {
            "id": task.id,
            "status": task.status,
            "task_type": task.task_type,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "handled_at": task.handled_at,
            "result": task.result,
            "error_code": task.error_code,
            "to_user_id": task.to_user_id,
            "from_user_id": task.from_user_id,
            "repo_id": task.repo_id,
        },
    }
