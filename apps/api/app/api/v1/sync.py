from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_scope, require_workspace_member, resolve_workspace_chat_ids
from models import Message, Task, User

router = APIRouter()


def _parse_cursor(cursor: Optional[str]):
    if not cursor or "|" not in cursor:
        return None
    ts_str, rid = cursor.split("|", 1)
    try:
        ts_val = datetime.fromisoformat(ts_str)
    except Exception:
        return None
    return ts_val, rid


def _make_cursor(ts: datetime, rid: str) -> str:
    return f"{ts.isoformat()}|{rid}"


class SyncMessage(BaseModel):
    id: str
    chat_id: str
    room_id: str
    sender_id: str
    sender_name: str
    role: str
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    metadata: dict = {}

    class Config:
        from_attributes = True


class SyncTask(BaseModel):
    id: str
    workspace_id: str
    title: str
    status: str
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SyncEnvelope(BaseModel):
    messages: List[SyncMessage]
    message_tombstones: List[dict]
    tasks: List[SyncTask]
    task_tombstones: List[dict]
    next_cursor: Optional[str] = None


@router.get("/workspaces/{workspace_id}/sync", response_model=SyncEnvelope)
def sync_workspace(
    workspace_id: str,
    since: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("read")),
):
    require_workspace_member(workspace_id, current_user, db)

    since_cursor = since or cursor
    parsed = _parse_cursor(since_cursor)
    chat_ids = resolve_workspace_chat_ids(workspace_id, db)

    msg_query = db.query(Message)
    if chat_ids:
        msg_query = msg_query.filter(Message.chat_instance_id.in_(chat_ids))
    else:
        msg_query = msg_query.filter(Message.room_id == workspace_id)
    task_query = db.query(Task).filter(Task.workspace_id == workspace_id)

    if parsed:
        ts, rid = parsed
        # Note: Message doesn't have updated_at column, use created_at instead
        msg_query = msg_query.filter(
            or_(Message.created_at > ts, and_(Message.created_at == ts, Message.id > rid))
        )
        task_query = task_query.filter(
            or_(Task.updated_at > ts, and_(Task.updated_at == ts, Task.id > rid))
        )

    msg_rows = msg_query.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit + 1).all()
    task_rows = task_query.order_by(Task.updated_at.asc(), Task.id.asc()).limit(limit + 1).all()

    merged = []
    i = j = 0
    while len(merged) < limit and (i < len(msg_rows) or j < len(task_rows)):
        m = msg_rows[i] if i < len(msg_rows) else None
        t = task_rows[j] if j < len(task_rows) else None
        if m and not t:
            merged.append(("m", m))
            i += 1
        elif t and not m:
            merged.append(("t", t))
            j += 1
        else:
            m_key = (getattr(m, "updated_at", None) or m.created_at, m.id)
            t_key = (t.updated_at or t.created_at, t.id)
            if m_key <= t_key:
                merged.append(("m", m))
                i += 1
            else:
                merged.append(("t", t))
                j += 1

    more_results = (i < len(msg_rows)) or (j < len(task_rows))
    next_cursor = None
    if more_results and merged:
        last_kind, last_obj = merged[-1]
        last_ts = getattr(last_obj, "updated_at", None) or last_obj.created_at
        next_cursor = _make_cursor(last_ts, last_obj.id)

    messages = []
    tasks = []
    for kind, obj in merged:
        if kind == "m":
            messages.append(
                SyncMessage(
                    id=obj.id,
                    chat_id=obj.chat_instance_id,
                    room_id=obj.room_id,
                    sender_id=obj.sender_id,
                    sender_name=obj.sender_name,
                    role=obj.role,
                    content=obj.content,
                    created_at=obj.created_at,
                    updated_at=None,  # Column doesn't exist in DB
                    deleted_at=None,  # Column doesn't exist in DB
                    metadata={},  # Column doesn't exist in DB
                )
            )
        else:
            tasks.append(
                SyncTask(
                    id=obj.id,
                    workspace_id=obj.workspace_id or workspace_id,
                    title=obj.title,
                    status=obj.status,
                    updated_at=obj.updated_at or obj.created_at,
                    deleted_at=obj.deleted_at,
                )
            )

    # Messages don't have deleted_at column in DB - always empty
    message_tombstones = []
    task_tombstones = [
        {"id": t.id, "deleted_at": t.deleted_at}
        for kind, t in merged
        if kind == "t" and t.deleted_at is not None
    ]

    return SyncEnvelope(
        messages=messages,
        message_tombstones=message_tombstones,
        tasks=tasks,
        task_tombstones=task_tombstones,
        next_cursor=next_cursor,
    )
