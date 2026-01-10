from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_workspace_member, resolve_workspace_chat_ids
from models import ChatInstance, Message, Task, User

router = APIRouter()
logger = logging.getLogger(__name__)


class ContextChat(BaseModel):
    id: str
    title: str
    updated_at: Optional[datetime] = None


class ContextMessage(BaseModel):
    chat_id: str
    message_id: str
    created_at: datetime
    content: str
    author: str
    metadata: Dict = {}


class ContextTask(BaseModel):
    id: str
    title: str
    status: str
    updated_at: datetime


class ContextBundle(BaseModel):
    recent_chats: List[ContextChat]
    recent_messages: List[ContextMessage]
    open_tasks: List[ContextTask]


@router.get("/workspaces/{workspace_id}/context-bundle", response_model=ContextBundle)
def context_bundle(
    workspace_id: str,
    max_chats: int = Query(5, ge=1, le=50),
    max_messages: int = Query(50, ge=1, le=200),
    max_tasks: int = Query(20, ge=1, le=100),
    recent_hours: Optional[int] = Query(None, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)

    cutoff = None
    if recent_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=recent_hours)

    chat_ids = resolve_workspace_chat_ids(workspace_id, db, logger_obj=logger)
    chats = []
    if chat_ids:
        chats = (
            db.query(ChatInstance)
            .filter(ChatInstance.id.in_(chat_ids))
            .order_by(
                func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at).desc(),
                ChatInstance.id.asc(),
            )
            .limit(max_chats)
            .all()
        )
    chat_ids = [c.id for c in chats]

    messages: list[Message] = []
    if chat_ids:
        msg_query = db.query(Message).filter(Message.chat_instance_id.in_(chat_ids))
        if cutoff:
            msg_query = msg_query.filter(Message.created_at >= cutoff)
        messages = (
            msg_query.order_by(Message.created_at.desc(), Message.id.desc())
            .limit(max_messages)
            .all()
        )

    tasks = (
        db.query(Task)
        .filter(Task.workspace_id == workspace_id, Task.deleted_at.is_(None))
        .order_by(Task.updated_at.desc())
        .limit(max_tasks)
        .all()
    )

    return ContextBundle(
        recent_chats=[
            ContextChat(id=c.id, title=c.name, updated_at=c.last_message_at or c.created_at)
            for c in chats
        ],
        recent_messages=[
            ContextMessage(
                chat_id=m.chat_instance_id,
                message_id=m.id,
                created_at=m.created_at,
                content=m.content,
                author=m.sender_name,
                metadata={},  # Column doesn't exist in DB
            )
            for m in messages
        ],
        open_tasks=[
            ContextTask(
                id=t.id,
                title=t.title,
                status=t.status,
                updated_at=t.updated_at or t.created_at,
            )
            for t in tasks
            if t.status not in {"done", "completed", "closed"}
        ],
    )
