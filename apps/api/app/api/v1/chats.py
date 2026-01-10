import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.v1.deps import (
    get_chat_for_user_m2m,
    get_current_user,
    get_db,
    require_scope,
    require_workspace_member,
    resolve_workspace_chat_ids,
)
from app.api.dependencies.auth import parse_admin_emails, is_platform_admin_user
from app.models.graph_agent import GraphAgent
from models import ChatRoomAccess, AgentClient, AgentInbox
from app.services.system_agent import ensure_system_agent_exists
from app.services.events import record_workspace_event
from models import ChatInstance, Message, User, RoomMember, Task, CodeEvent, AgentCursor

router = APIRouter()
logger = logging.getLogger(__name__)


DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class ChatOut(BaseModel):
    id: str
    workspace_id: str = Field(..., alias="room_id")
    name: str
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class ChatListResponse(BaseModel):
    items: List[ChatOut]
    next_cursor: Optional[str] = None


class ChatAccessOut(BaseModel):
    id: str
    name: str
    room_id: Optional[str] = None
    room_ids: List[str] = []
    updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatAccessResponse(BaseModel):
    items: List[ChatAccessOut]
    next_cursor: Optional[str] = None


class ChatRoomsPayload(BaseModel):
    room_ids: List[str]


class MessageOut(BaseModel):
    id: str
    chat_id: str = Field(..., alias="chat_instance_id")
    room_id: str
    sender_id: str
    sender_name: str
    role: str
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    metadata: Dict = Field(default_factory=dict)

    class Config:
        from_attributes = True
        populate_by_name = True


class MessageCreate(BaseModel):
    content: str
    metadata: Dict = Field(default_factory=dict)
    source: Optional[str] = None
    file_path: Optional[str] = None
    selection: Optional[Dict] = None
    room_id: Optional[str] = None


class ChatCreateRequest(BaseModel):
    name: str

    @validator("name")
    def _validate_name(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Chat name is required")
        return cleaned


class ChatCreateResponse(BaseModel):
    id: str
    room_id: str
    name: str
    created_at: datetime
    last_message_at: Optional[datetime] = None


def _parse_cursor(cursor: Optional[str]):
    if not cursor:
        return None
    if "|" not in cursor:
        return None
    ts_str, cid = cursor.split("|", 1)
    try:
        ts_val = datetime.fromisoformat(ts_str)
    except Exception:
        return None
    return ts_val, cid


def _make_cursor(ts: datetime, cid: str) -> str:
    return f"{ts.isoformat()}|{cid}"


@router.get("/chats", response_model=ChatAccessResponse)
def list_all_user_chats(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all chats the current user can access across their rooms using chat_room_access.
    """
    import traceback
    import uuid
    from sqlalchemy.exc import ProgrammingError, OperationalError

    trace_id = str(uuid.uuid4())

    try:
        logger.info(
            "[list_all_user_chats] trace_id=%s user=%s limit=%s",
            trace_id,
            getattr(current_user, "email", None),
            limit,
        )

        # Quick table accessibility check
        try:
            db.query(ChatRoomAccess).limit(1).all()
            logger.info("[list_all_user_chats] trace_id=%s ChatRoomAccess table accessible", trace_id)
        except Exception as table_err:
            logger.error("[list_all_user_chats] trace_id=%s ChatRoomAccess table error: %s", trace_id, table_err)
            raise

        # Fetch memberships
        user_room_ids = [
            rid for (rid,) in db.query(RoomMember.room_id).filter(RoomMember.user_id == current_user.id).all()
        ]
        logger.info(
            "[list_all_user_chats] trace_id=%s user has %d rooms: %s",
            trace_id,
            len(user_room_ids),
            user_room_ids,
        )
        if not user_room_ids:
            logger.warning("[list_all_user_chats] trace_id=%s user has no room memberships", trace_id)
            return ChatAccessResponse(items=[], next_cursor=None)

        # Build base query (respect deleted_at only if present)
        chat_ids_subq = (
            db.query(ChatRoomAccess.chat_id)
            .filter(ChatRoomAccess.room_id.in_(user_room_ids))
            .distinct()
            .subquery()
        )
        chats_query = db.query(ChatInstance).filter(ChatInstance.id.in_(chat_ids_subq))
        if hasattr(ChatInstance, "deleted_at"):
            chats_query = chats_query.filter(ChatInstance.deleted_at.is_(None))
        chats = (
            chats_query.order_by(
                func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at).desc(),
                ChatInstance.id.asc(),
            )
            .limit(limit + 1)
            .all()
        )
        logger.info("[list_all_user_chats] trace_id=%s found %d chats", trace_id, len(chats))

        chat_ids = [c.id for c in chats]
        access_map = {}
        if chat_ids:
            rows = (
                db.query(ChatRoomAccess.chat_id, ChatRoomAccess.room_id)
                .filter(ChatRoomAccess.chat_id.in_(chat_ids))
                .all()
            )
            for cid, rid in rows:
                access_map.setdefault(cid, []).append(rid)

        items = []
        for chat in chats[:limit]:
            logger.debug("[list_all_user_chats] trace_id=%s processing chat %s", trace_id, chat.id)
            items.append(
                ChatAccessOut(
                    id=chat.id,
                    name=chat.name,
                    room_id=getattr(chat, "room_id", None),
                    room_ids=access_map.get(chat.id, []) or [],
                    updated_at=chat.last_message_at or chat.created_at,
                    last_message_at=chat.last_message_at,
                )
            )

        next_cursor = None
        if len(chats) > limit:
            last = chats[limit - 1]
            next_cursor = _make_cursor(last.last_message_at or last.created_at, last.id)

        logger.info(
            "[list_all_user_chats] trace_id=%s returning %d items next_cursor=%s",
            trace_id,
            len(items),
            next_cursor,
        )
        return ChatAccessResponse(items=items, next_cursor=next_cursor)

    except (ProgrammingError, OperationalError) as exc:
        logger.error(
            "[list_all_user_chats] DB ERROR trace_id=%s user=%s params(limit=%s) error=%s",
            trace_id,
            getattr(current_user, "email", None),
            limit,
            exc,
        )
        logger.error("[list_all_user_chats] Traceback: %s", traceback.format_exc())
        raise HTTPException(
            status_code=503,
            detail={
                "error": f"{type(exc).__name__}: {str(exc)}",
                "traceback": traceback.format_exc(),
                "trace_id": trace_id,
                "context": {
                    "trace_id": trace_id,
                    "user_id": getattr(current_user, "id", None),
                    "user_email": getattr(current_user, "email", None),
                    "limit": limit,
                },
            },
        )
    except Exception as exc:
        logger.error(
            "[list_all_user_chats] ERROR trace_id=%s: %s | user=%s params(limit=%s)",
            trace_id,
            exc,
            getattr(current_user, "email", None),
            limit,
        )
        logger.error("[list_all_user_chats] Traceback: %s", traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail={
                "error": f"{type(exc).__name__}: {str(exc)}",
                "traceback": traceback.format_exc(),
                "trace_id": trace_id,
                "context": {
                    "trace_id": trace_id,
                    "user_id": getattr(current_user, "id", None),
                    "user_email": getattr(current_user, "email", None),
                    "limit": limit,
                },
            },
        )


@router.post("/chats/{chat_id}/rooms")
def set_chat_room_access(
    chat_id: str,
    payload: ChatRoomsPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Set which rooms a chat can access. User must own the chat and be a member of all specified rooms.
    """
    chat = db.query(ChatInstance).filter(ChatInstance.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if chat.created_by_user_id and chat.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat")

    requested_room_ids = list(set(payload.room_ids or []))
    if requested_room_ids:
        member_room_ids = {
            rid
            for (rid,) in db.query(RoomMember.room_id).filter(RoomMember.user_id == current_user.id).all()
        }
        for rid in requested_room_ids:
            if rid not in member_room_ids:
                raise HTTPException(status_code=403, detail=f"Not member of room {rid}")

    db.query(ChatRoomAccess).filter(ChatRoomAccess.chat_id == chat_id).delete()
    for rid in requested_room_ids:
        db.add(ChatRoomAccess(chat_id=chat_id, room_id=rid))
    db.commit()

    return {
        "success": True,
        "chat_id": chat_id,
        "room_ids": requested_room_ids,
    }


@router.get("/workspaces/{workspace_id}/chats", response_model=ChatListResponse)
def list_chats(
    workspace_id: str,
    updated_after: Optional[str] = Query(None, description="ISO timestamp to delta-sync"),
    cursor: Optional[str] = Query(None, description="Opaque cursor from previous page"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("chats:read")),
):
    require_workspace_member(workspace_id, current_user, db)

    chat_ids = resolve_workspace_chat_ids(workspace_id, db, logger_obj=logger)
    if not chat_ids:
        return ChatListResponse(items=[], next_cursor=None)

    query = db.query(ChatInstance).filter(ChatInstance.id.in_(chat_ids))

    if updated_after:
        try:
            dt = datetime.fromisoformat(updated_after)
            query = query.filter(func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at) >= dt)
        except Exception:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid updated_after")

    parsed_cursor = _parse_cursor(cursor)
    if parsed_cursor:
        ts, cid = parsed_cursor
        query = query.filter(
            or_(
                func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at) < ts,
                and_(
                    func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at) == ts,
                    ChatInstance.id > cid,
                ),
            )
        )

    chats = (
        query.order_by(
            func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at).desc(),
            ChatInstance.id.asc(),
        )
        .limit(limit + 1)
        .all()
    )

    next_cursor = None
    if len(chats) > limit:
        last = chats[limit - 1]
        next_cursor = _make_cursor(last.last_message_at or last.created_at, last.id)
        chats = chats[:limit]

    items = [
        ChatOut(
            id=chat.id,
            room_id=chat.room_id,
            name=chat.name,
            updated_at=chat.last_message_at or chat.created_at,
            deleted_at=None,  # ChatInstance has no deleted_at column in DB
            last_message_at=chat.last_message_at,
        )
        for chat in chats
    ]

    # Prepend System Agent chat for platform admins
    logger.info(
        f"[System Agent Debug] Starting admin check for user {current_user.id} ({current_user.email})"
    )

    admin_emails = parse_admin_emails()
    logger.info(f"[System Agent Debug] Admin emails configured: {admin_emails}")

    try:
        admin = is_platform_admin_user(current_user, admin_emails)
        logger.info(
            f"[System Agent Debug] Admin check result: {admin} "
            f"(is_platform_admin={getattr(current_user, 'is_platform_admin', False)}, "
            f"email={current_user.email})"
        )
    except Exception as e:
        logger.error(f"[System Agent Debug] Admin check failed: {e}", exc_info=True)
        admin = False

    if admin:
        logger.info(f"[System Agent Debug] User is admin, checking for System Agent")
        try:
            agent = (
                db.query(GraphAgent)
                .filter(GraphAgent.user_id == current_user.id, GraphAgent.name == "System Agent")
                .first()
            )

            if not agent:
                logger.info(f"[System Agent Debug] System Agent not found, creating...")
                agent = ensure_system_agent_exists(current_user.id, db)
                logger.info(
                    f"[System Agent Debug] System Agent created: "
                    f"id={agent.id}, name={agent.name}, version={agent.version}"
                )
            else:
                logger.info(
                    f"[System Agent Debug] System Agent found: "
                    f"id={agent.id}, name={agent.name}, version={agent.version}, "
                    f"created_at={agent.created_at}, updated_at={agent.updated_at}"
                )

            system_chat = ChatOut(
                id=f"system-agent-{agent.id}",
                room_id=workspace_id,
                name="🧪 System Agent (Experimental)",
                updated_at=agent.updated_at or agent.created_at,
                deleted_at=None,
                last_message_at=agent.updated_at or agent.created_at,
            )
            items.insert(0, system_chat)
            logger.info(
                f"[System Agent Debug] System Agent chat prepended to list: "
                f"chat_id={system_chat.id}, name={system_chat.name}"
            )
        except Exception as e:
            logger.error(
                f"[System Agent Debug] Failed to add System Agent to chat list: {e}",
                exc_info=True
            )
    else:
        logger.info(f"[System Agent Debug] User is not admin, skipping System Agent")

    logger.info(
        f"[System Agent Debug] Returning {len(items)} chats "
        f"(admin={admin}, workspace_id={workspace_id})"
    )
    return ChatListResponse(items=items, next_cursor=next_cursor)


@router.post(
    "/workspaces/{workspace_id}/chats",
    response_model=ChatCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_chat(
    workspace_id: str,
    payload: ChatCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("chats:write")),
):
    require_workspace_member(workspace_id, current_user, db)

    existing = (
        db.query(ChatInstance)
        .filter(
            ChatInstance.room_id == workspace_id,
            func.lower(ChatInstance.name) == payload.name.lower(),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A chat with that name already exists in this workspace",
        )

    now = datetime.now(timezone.utc)
    chat = ChatInstance(
        id=str(uuid.uuid4()),
        room_id=workspace_id,
        name=payload.name,
        created_by_user_id=current_user.id,
        created_at=now,
        last_message_at=None,
    )
    db.add(chat)

    welcome_msg = Message(
        id=str(uuid.uuid4()),
        room_id=workspace_id,
        chat_instance_id=chat.id,
        sender_id="system",
        sender_name="Parallel OS",
        role="assistant",
        content="Hey! How can I help you today?",
        user_id=current_user.id,
        created_at=now,
    )
    db.add(welcome_msg)
    chat.last_message_at = welcome_msg.created_at
    record_workspace_event(
        db,
        workspace_id=workspace_id,
        event_type="chat.message.created",
        resource_id=welcome_msg.id,
        entity_type="message",
        user_id=current_user.id,
        payload={"chat_id": chat.id},
    )
    db.add(ChatRoomAccess(chat_id=chat.id, room_id=workspace_id))
    db.commit()
    db.refresh(chat)

    return ChatCreateResponse(
        id=chat.id,
        room_id=chat.room_id,
        name=chat.name,
        created_at=chat.created_at,
        last_message_at=chat.last_message_at,
    )


@router.get("/chats/{chat_id}/messages", response_model=List[MessageOut])
def list_messages(
    chat: ChatInstance = Depends(get_chat_for_user_m2m),
    after_message_id: Optional[str] = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("chats:read")),
):
    query = db.query(Message).filter(Message.chat_instance_id == chat.id)

    if after_message_id:
        anchor = db.query(Message).filter(Message.id == after_message_id).first()
        if anchor:
            query = query.filter(
                or_(
                    Message.created_at > anchor.created_at,
                    and_(Message.created_at == anchor.created_at, Message.id > anchor.id),
                )
            )

    rows = query.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit).all()
    return [
        MessageOut(
            id=row.id,
            chat_instance_id=row.chat_instance_id,
            room_id=row.room_id,
            sender_id=row.sender_id,
            sender_name=row.sender_name,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            updated_at=None,  # Column doesn't exist in DB
            deleted_at=None,  # Column doesn't exist in DB
            metadata={},  # Column doesn't exist in DB
        )
        for row in rows
    ]


@router.post("/chats/{chat_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def create_message(
    payload: MessageCreate,
    chat: ChatInstance = Depends(get_chat_for_user_m2m),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("chats:write")),
):
    now = datetime.now(timezone.utc)
    response_metadata = payload.metadata or {}
    user_room_ids = {
        rid for (rid,) in db.query(RoomMember.room_id).filter(RoomMember.user_id == current_user.id).all()
    }
    access_rids = [
        rid for (rid,) in db.query(ChatRoomAccess.room_id).filter(ChatRoomAccess.chat_id == chat.id).all()
    ]

    requested_room_id = payload.room_id
    if requested_room_id:
        if requested_room_id not in access_rids and requested_room_id != chat.room_id:
            raise HTTPException(status_code=403, detail="Room is not linked to this chat")
        if requested_room_id not in user_room_ids:
            raise HTTPException(status_code=403, detail="User is not a member of the requested room")
        msg_room_id = requested_room_id
    else:
        msg_room_id = chat.room_id or (access_rids[0] if access_rids else None)
        if not msg_room_id:
            raise HTTPException(status_code=400, detail="Chat has no accessible room")
        if msg_room_id not in user_room_ids:
            raise HTTPException(status_code=403, detail="User is not a member of the resolved room")

    msg = Message(
        id=str(uuid.uuid4()),
        room_id=msg_room_id,
        chat_instance_id=chat.id,
        sender_id=current_user.id,
        sender_name=current_user.name,
        role="user",
        content=payload.content,
        user_id=current_user.id,
        created_at=now,
        # Note: updated_at and metadata_json columns don't exist in DB
        # Metadata is not stored, but can be added later if needed
    )
    chat.last_message_at = now

    db.add(msg)
    db.add(chat)
    record_workspace_event(
        db,
        workspace_id=msg_room_id,
        event_type="chat.message.created",
        resource_id=msg.id,
        entity_type="message",
        user_id=current_user.id,
        payload={"chat_id": chat.id},
    )
    db.commit()
    db.refresh(msg)
    return MessageOut(
        id=msg.id,
        chat_instance_id=msg.chat_instance_id,
        room_id=msg.room_id,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        role=msg.role,
        content=msg.content,
        created_at=msg.created_at,
        updated_at=None,  # Column doesn't exist in DB
        deleted_at=None,  # Column doesn't exist in DB
        metadata=response_metadata,
    )


# =============================================================================
# DISPATCH ENDPOINT - Unified Chat Routing (Site vs VS Code Mode)
# =============================================================================

class PatchPayload(BaseModel):
    format: str = Field(..., description="Patch format, must be 'unified_diff'")
    diff: str = Field(..., description="Unified diff text")
    base_sha: Optional[str] = Field(None, description="Optional base commit SHA")
    files: Optional[List[str]] = Field(None, description="Optional list of files touched")


class RelevantUpdatesHint(BaseModel):
    count: int
    top: List[Dict[str, Any]]
    focus_systems: Optional[List[str]] = None
    focus_impacts: Optional[List[str]] = None


class DispatchRequest(BaseModel):
    mode: str = Field(..., description="site|vscode")
    content: str = Field(..., description="User message content")
    repo_id: Optional[str] = Field(None, description="Target repo for vscode mode")
    task_type: Optional[str] = Field(None, description="AGENT_TASK|APPLY_PATCH (vscode mode only)")
    patch: Optional[PatchPayload] = Field(None, description="Patch payload when task_type=APPLY_PATCH")


class DispatchResponse(BaseModel):
    ok: bool
    mode: str
    task_id: Optional[str] = None
    repo_id: Optional[str] = None
    picked_repo: Optional[bool] = None
    message: Optional[str] = None
    relevant_updates_hint: Optional[RelevantUpdatesHint] = None


@router.post("/chats/{chat_id}/dispatch", response_model=DispatchResponse)
def dispatch_chat_message(
    chat_id: str,
    payload: DispatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("chats:write")),
):
    """
    Unified chat dispatch endpoint.

    Routes messages to either:
    - site: On-site agent processing (traditional)
    - vscode: VS Code extension via agent inbox

    VS Code mode packages workspace context into the task payload.
    """
    # Validate chat access using M2M logic
    chat = db.query(ChatInstance).filter(ChatInstance.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Check M2M access
    user_room_ids = {
        rid for (rid,) in db.query(RoomMember.room_id).filter(RoomMember.user_id == current_user.id).all()
    }
    access_rids = [
        rid for (rid,) in db.query(ChatRoomAccess.room_id).filter(ChatRoomAccess.chat_id == chat_id).all()
    ]

    chat_room_id = getattr(chat, "room_id", None)
    has_access = chat_room_id in user_room_ids or any(rid in user_room_ids for rid in access_rids)
    if not has_access:
        raise HTTPException(status_code=403, detail="Not authorized to access this chat")

    mode = payload.mode.lower()

    # -------------------------------------------------------------------------
    # MODE: SITE - Traditional on-site processing
    # -------------------------------------------------------------------------
    if mode == "site":
        logger.info(
            "[ChatDispatch] mode=site chat_id=%s user=%s - forwarding to site agent",
            chat_id,
            current_user.email,
        )
        # TODO: Forward to existing /api/chats/{chat_id}/ask or similar
        # For now, return a placeholder response
        return DispatchResponse(
            ok=True,
            mode="site",
            message="Site mode not yet implemented - would forward to on-site agent",
        )

    # -------------------------------------------------------------------------
    # MODE: VSCODE - Extension dispatch via agent inbox
    # -------------------------------------------------------------------------
    elif mode == "vscode":
        if not current_user.org_id:
            raise HTTPException(status_code=403, detail="User must belong to an org for VS Code mode")

        # Determine workspace/room_id for context
        workspace_id = chat_room_id or (access_rids[0] if access_rids else None)
        if not workspace_id or workspace_id not in user_room_ids:
            raise HTTPException(
                status_code=400,
                detail="Cannot determine valid workspace for context building"
            )

        logger.info(
            "[ChatDispatch] mode=vscode chat_id=%s user=%s workspace=%s - building context",
            chat_id,
            current_user.email,
            workspace_id,
        )

        # Resolve repo_id (auto-pick if exactly one active client)
        resolved_repo_id = payload.repo_id
        picked_repo = False

        if not resolved_repo_id:
            # Find active clients (fresh within last 5 minutes)
            HEARTBEAT_TTL_SECONDS = 300
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
            active_clients = (
                db.query(AgentClient)
                .filter(
                    AgentClient.user_id == current_user.id,
                    AgentClient.last_seen_at >= cutoff,
                )
                .order_by(AgentClient.last_seen_at.desc())
                .all()
            )

            if len(active_clients) == 0:
                raise HTTPException(
                    status_code=409,
                    detail="No active VS Code extensions found. Please open VS Code and ensure the extension is running.",
                )
            elif len(active_clients) == 1:
                resolved_repo_id = active_clients[0].repo_id
                picked_repo = True
                logger.info(
                    "[ChatDispatch] Auto-picked repo_id=%s from single active client",
                    resolved_repo_id,
                )
            else:
                # Multiple repos - require explicit selection
                available_repos = [{"repo_id": c.repo_id, "branch": c.branch} for c in active_clients]
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_code": "REPO_REQUIRED",
                        "message": "Multiple VS Code repos detected. Please specify repo_id.",
                        "available_repos": available_repos,
                    },
                )

        # Verify target repo has active client
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
        active_client = (
            db.query(AgentClient)
            .filter(
                AgentClient.user_id == current_user.id,
                AgentClient.repo_id == resolved_repo_id,
                AgentClient.org_id == current_user.org_id,
                AgentClient.last_seen_at >= cutoff,
            )
            .order_by(AgentClient.last_seen_at.desc())
            .first()
        )

        if not active_client:
            raise HTTPException(
                status_code=409,
                detail=f"VS Code extension offline for repo {resolved_repo_id}. Please ensure VS Code is running with this repo open.",
            )

        # Build compact context brief with repo_id and user content
        # Now that we have resolved_repo_id, we can include code activity and conflict signals
        context_brief = _build_compact_context(
            db=db,
            user=current_user,
            workspace_id=workspace_id,
            chat_id=chat_id,
            repo_id=resolved_repo_id,
            user_content=payload.content,
        )

        # Task type + patch validation
        MAX_PATCH_DIFF_BYTES = 200_000
        task_type = (payload.task_type or "AGENT_TASK").upper()
        patch_payload = None
        if task_type == "APPLY_PATCH":
            if not payload.patch:
                raise HTTPException(
                    status_code=400,
                    detail={"error_code": "INVALID_PATCH_PAYLOAD", "message": "patch is required for APPLY_PATCH"},
                )
            if payload.patch.format != "unified_diff":
                raise HTTPException(
                    status_code=400,
                    detail={"error_code": "INVALID_PATCH_PAYLOAD", "message": "patch.format must be unified_diff"},
                )
            if not payload.patch.diff or len(payload.patch.diff.encode("utf-8")) > MAX_PATCH_DIFF_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_code": "INVALID_PATCH_PAYLOAD",
                        "message": f"patch.diff must be non-empty and <= {MAX_PATCH_DIFF_BYTES} bytes",
                    },
                )
            patch_payload = {
                "format": payload.patch.format,
                "diff": payload.patch.diff,
                "base_sha": payload.patch.base_sha,
                "files": (payload.patch.files or [])[:50],
            }
        else:
            # Ignore patch if provided when not applying patch
            task_type = "AGENT_TASK"

        # Create agent inbox task
        task = AgentInbox(
            org_id=current_user.org_id,
            to_user_id=current_user.id,
            from_user_id=current_user.id,
            repo_id=resolved_repo_id,
            task_type=task_type,
            payload={
                "text": payload.content,
                "chat_id": chat_id,
                "context_brief": context_brief,
                "patch": patch_payload,
                "created_from": "site_dispatch",
            },
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        hint = _build_relevant_updates_hint(
            db=db,
            current_user=current_user,
            repo_id=resolved_repo_id,
            content=payload.content,
        )

        logger.info(
            "[ChatDispatch] Created task_id=%s repo_id=%s picked_repo=%s",
            task.id,
            resolved_repo_id,
            picked_repo,
        )

        return DispatchResponse(
            ok=True,
            mode="vscode",
            task_id=task.id,
            repo_id=resolved_repo_id,
            picked_repo=picked_repo,
            relevant_updates_hint=hint,
        )

    else:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Must be 'site' or 'vscode'")


def _extract_systems_from_content(content: str) -> List[str]:
    """
    Extract system tags from user message content based on keyword matching.

    Simple MVP mapping:
    - auth/login/session/jwt -> "auth"
    - billing/stripe -> "billing"
    - migrations/alembic/db -> "database"
    - api/routes/endpoint -> "api"
    - ui/react/component -> "frontend"
    """
    if not content:
        return []

    content_lower = content.lower()
    systems = set()

    # Auth system
    if any(kw in content_lower for kw in ["auth", "login", "session", "jwt"]):
        systems.add("auth")

    # Billing system
    if any(kw in content_lower for kw in ["billing", "stripe"]):
        systems.add("billing")

    # Database system
    if any(kw in content_lower for kw in ["migrations", "alembic", "db", "database"]):
        systems.add("database")

    # API system
    if any(kw in content_lower for kw in ["api", "routes", "endpoint"]):
        systems.add("api")

    # Frontend system
    if any(kw in content_lower for kw in ["ui", "react", "component", "frontend"]):
        systems.add("frontend")

    return list(systems)


def _extract_focus_from_content(content: str) -> tuple[List[str], List[str]]:
    """
    Determine focus systems and impact tags based on keywords in the content.
    """
    if not content:
        return [], []
    content_lower = content.lower()
    systems: set[str] = set()
    impacts: set[str] = set()

    if any(kw in content_lower for kw in ["auth", "login", "session", "jwt"]):
        systems.add("auth")
        impacts.add("auth_flow")
    if any(kw in content_lower for kw in ["api", "route", "endpoint"]):
        systems.add("api")
        impacts.add("api_contract")
    if any(kw in content_lower for kw in ["alembic", "migration", "db", "database", "schema"]):
        systems.add("database")
        impacts.add("db_schema")
    if any(kw in content_lower for kw in ["ui", "react", "component", "frontend"]):
        systems.add("frontend")
    if any(kw in content_lower for kw in ["config", "settings", "env"]):
        impacts.add("config")
    if any(kw in content_lower for kw in ["deps", "dependency", "requirements", "package.json", "poetry"]):
        impacts.add("deps")
    return list(systems), list(impacts)


def _build_relevant_updates_hint(
    db: Session,
    current_user: User,
    repo_id: str,
    content: str,
) -> Optional[Dict[str, Any]]:
    """
    Build a small hint of recent code events relevant to the user's focus.
    """
    if not current_user.org_id:
        return None

    focus_systems, focus_impacts = _extract_focus_from_content(content or "")

    cursor = (
        db.query(AgentCursor)
        .filter(
            AgentCursor.org_id == current_user.org_id,
            AgentCursor.user_id == current_user.id,
            AgentCursor.repo_id == repo_id,
            AgentCursor.cursor_name == "code_events",
        )
        .first()
    )
    since_dt = cursor.last_seen_at if cursor and cursor.last_seen_at else datetime.now(timezone.utc) - timedelta(minutes=60)

    query = db.query(CodeEvent).filter(
        CodeEvent.org_id == current_user.org_id,
        CodeEvent.repo_id == repo_id,
        CodeEvent.created_at > since_dt,
    )

    filters = []
    if focus_systems:
        filters.append(CodeEvent.systems_touched.op("&&")(focus_systems))
    if focus_impacts:
        filters.append(CodeEvent.impact_tags.op("&&")(focus_impacts))

    if filters:
        query = query.filter(or_(*filters))

    events = (
        query.order_by(CodeEvent.created_at.desc())
        .limit(10)
        .all()
    )
    if not events:
        return None

    # Fetch user names for display
    user_ids = {e.user_id for e in events if e.user_id}
    user_map = {}
    if user_ids:
        rows = db.query(User.id, User.name).filter(User.id.in_(user_ids)).all()
        user_map = {uid: uname for uid, uname in rows}

    top_items = []
    for ev in events[:3]:
        top_items.append(
            {
                "id": str(ev.id),
                "summary": (ev.summary or "")[:300],
                "user_id": ev.user_id,
                "user_name": user_map.get(ev.user_id),
                "impact_tags": ev.impact_tags or [],
                "systems_touched": ev.systems_touched or [],
                "created_at": ev.created_at,
            }
        )

    return {
        "count": len(events),
        "top": top_items,
        "focus_systems": focus_systems or None,
        "focus_impacts": focus_impacts or None,
    }


def _build_compact_context(
    db: Session,
    user: User,
    workspace_id: str,
    chat_id: str,
    repo_id: Optional[str] = None,
    user_content: Optional[str] = None,
) -> Dict:
    """
    Build a compact context brief for VS Code agent dispatch.

    Includes:
    - Recent chat messages (last 10)
    - Open tasks
    - Basic workspace metadata
    - Code activity (if repo_id provided)
    - Conflict signals (if repo_id and user_content provided)

    Does NOT call OpenAI - just packages existing data.
    """
    # Get last N messages from the chat
    MAX_MESSAGES = 10
    messages = (
        db.query(Message)
        .filter(Message.chat_instance_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(MAX_MESSAGES)
        .all()
    )

    # Get open tasks in workspace
    MAX_TASKS = 5
    tasks = (
        db.query(Task)
        .filter(
            Task.workspace_id == workspace_id,
            Task.deleted_at.is_(None),
            Task.status.notin_(["done", "completed", "closed"]),
        )
        .order_by(Task.updated_at.desc())
        .limit(MAX_TASKS)
        .all()
    )

    context = {
        "workspace_id": workspace_id,
        "chat_id": chat_id,
        "user_email": user.email,
        "recent_messages": [
            {
                "message_id": m.id,
                "created_at": m.created_at.isoformat(),
                "author": m.sender_name,
                "content": m.content[:500],  # Truncate long messages
            }
            for m in reversed(messages)  # Reverse to get chronological order
        ],
        "open_tasks": [
            {
                "task_id": t.id,
                "title": t.title,
                "status": t.status,
            }
            for t in tasks
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Add code activity if repo_id is available
    if repo_id and user.org_id:
        # Query recent code events (last 120 minutes, max 10 events)
        CODE_ACTIVITY_MINUTES = 120
        CODE_ACTIVITY_LIMIT = 10
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=CODE_ACTIVITY_MINUTES)

        code_events = (
            db.query(CodeEvent)
            .filter(
                CodeEvent.org_id == user.org_id,
                CodeEvent.repo_id == repo_id,
                CodeEvent.created_at >= cutoff,
            )
            .order_by(CodeEvent.created_at.desc())
            .limit(CODE_ACTIVITY_LIMIT)
            .all()
        )

        context["code_activity"] = [
            {
                "user_id": event.user_id,
                "device_id": event.device_id,
                "branch": event.branch,
                "head_sha_after": event.head_sha_after,
                "event_type": event.event_type,
                "systems_touched": event.systems_touched or [],
                "files_touched": (event.files_touched or [])[:5],  # Max 5 files
                "summary": event.summary,
                "created_at": event.created_at.isoformat(),
            }
            for event in code_events
        ]

        # Add conflict signals if user_content is available
        if user_content:
            systems_hint = _extract_systems_from_content(user_content)

            if systems_hint:
                # Query events touching the same systems in last 24h
                CONFLICT_MINUTES = 1440  # 24 hours
                CONFLICT_LIMIT = 5
                conflict_cutoff = datetime.now(timezone.utc) - timedelta(minutes=CONFLICT_MINUTES)

                conflict_events = (
                    db.query(CodeEvent)
                    .filter(
                        CodeEvent.org_id == user.org_id,
                        CodeEvent.repo_id == repo_id,
                        CodeEvent.created_at >= conflict_cutoff,
                        CodeEvent.systems_touched.op("&&")(systems_hint),  # Array overlap
                    )
                    .order_by(CodeEvent.created_at.desc())
                    .limit(CONFLICT_LIMIT)
                    .all()
                )

                context["conflict_signals"] = [
                    {
                        "system": ", ".join(event.systems_touched or []),
                        "summary": event.summary,
                        "user_id": event.user_id,
                        "branch": event.branch,
                        "created_at": event.created_at.isoformat(),
                    }
                    for event in conflict_events
                ]

    return context
