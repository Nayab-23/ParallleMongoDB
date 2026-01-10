from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from models import ChatInstance, Room, RoomMember, User

router = APIRouter()


class WorkspaceBrief(BaseModel):
    id: str
    name: str
    summary_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BootstrapResponse(BaseModel):
    user: dict
    workspaces: List[WorkspaceBrief]
    sync_cursors: dict


def _make_cursor(ts, rid):
    if ts is None:
        return ""
    return f"{ts.isoformat()}|{rid}"


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memberships = (
        db.query(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .filter(RoomMember.user_id == current_user.id)
        .all()
    )
    workspaces = [
        WorkspaceBrief(
            id=ws.id,
            name=ws.name,
            summary_updated_at=ws.summary_updated_at or ws.created_at,
        )
        for ws in memberships
    ]

    # PERFORMANCE FIX: Batch load all latest messages in one query with GROUP BY
    # Previously: N individual queries (one per workspace)
    # Now: Single query for all workspaces
    sync_cursors = {}
    if memberships:
        room_ids = [ws.id for ws in memberships]
        latest_messages = (
            db.query(
                ChatInstance.room_id,
                func.max(ChatInstance.last_message_at).label('latest_msg')
            )
            .filter(ChatInstance.room_id.in_(room_ids))
            .group_by(ChatInstance.room_id)
            .all()
        )

        # Build lookup map: room_id -> latest_msg
        latest_map = {row[0]: row[1] for row in latest_messages}

        # Generate sync cursors using pre-loaded data
        for ws in memberships:
            latest_msg = latest_map.get(ws.id)
            sync_cursors[ws.id] = _make_cursor(latest_msg or ws.created_at, ws.id)

    # Cache-friendly for a short window
    response.headers["Cache-Control"] = "private, max-age=30"

    return BootstrapResponse(
        user={
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "org_id": current_user.org_id,
        },
        workspaces=workspaces,
        sync_cursors=sync_cursors,
    )
