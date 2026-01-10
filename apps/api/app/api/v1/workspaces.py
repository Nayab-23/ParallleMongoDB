from typing import List, Optional
from datetime import datetime, timedelta
import uuid
import time
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_workspace_member
from models import RoomMember, User, Room, UserCanonicalPlan, Message

logger = logging.getLogger(__name__)

router = APIRouter()


class WorkspaceOut(BaseModel):
    id: str
    name: str
    role: Optional[str] = None

    class Config:
        from_attributes = True


class WorkspaceCreate(BaseModel):
    name: str


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "member"


class RoomDetailResponse(BaseModel):
    id: str
    name: str
    status: str
    member_count: int
    daily_goals: List[dict] = []
    weekly_goals: List[dict] = []
    monthly_goals: List[dict] = []
    active_challenges: List[dict] = []
    blockers: List[dict] = []
    recent_messages: List[dict] = []
    last_active: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/workspaces", response_model=List[WorkspaceOut])
def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_time = time.time()
    logger.info("[PERF] /workspaces request started for user_id=%s", getattr(current_user, "id", None))

    memberships = (
        db.query(Room.id, Room.name, RoomMember.role_in_room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .filter(RoomMember.user_id == current_user.id)
        .all()
    )
    elapsed = time.time() - start_time
    logger.info("[PERF] /workspaces took %.2fs, memberships=%d", elapsed, len(memberships))
    return [WorkspaceOut(id=rid, name=rname or "", role=rrole) for rid, rname, rrole in memberships]


# Compatibility alias for legacy clients expecting /rooms
@router.get("/rooms", response_model=List[WorkspaceOut])
def list_rooms_alias(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_workspaces(current_user=current_user, db=db)


@router.get("/workspaces/{workspace_id}/details", response_model=RoomDetailResponse)
async def get_workspace_details(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed information about a workspace including goals, challenges, blockers."""
    logger.info("[ROOM_DETAILS] Fetching details for workspace %s", workspace_id)

    workspace = db.query(Room).filter(Room.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    require_workspace_member(workspace_id, current_user, db)

    member_count = db.query(RoomMember).filter(RoomMember.room_id == workspace_id).count()

    # Collect member ids
    member_rows = db.query(RoomMember.user_id).filter(RoomMember.room_id == workspace_id).all()
    member_ids = [m[0] for m in member_rows]

    daily_goals: List[dict] = []
    weekly_goals: List[dict] = []
    monthly_goals: List[dict] = []

    if member_ids:
        plans = db.query(UserCanonicalPlan).filter(UserCanonicalPlan.user_id.in_(member_ids)).all()
        for plan in plans:
            timeline = plan.approved_timeline or {}
            if isinstance(timeline, dict):
                one_d = timeline.get("1d", {})
                seven_d = timeline.get("7d", {})
                twenty_eight_d = timeline.get("28d", {})

                if isinstance(one_d, dict):
                    goals = one_d.get("normal", [])
                    if isinstance(goals, list):
                        daily_goals.extend(goals)

                if isinstance(seven_d, dict):
                    goals = seven_d.get("normal", [])
                    if isinstance(goals, list):
                        weekly_goals.extend(goals)

                if isinstance(twenty_eight_d, dict):
                    goals = twenty_eight_d.get("normal", [])
                    if isinstance(goals, list):
                        monthly_goals.extend(goals)

    active_challenges: List[dict] = []
    blockers: List[dict] = []

    recent_messages = (
        db.query(Message)
        .filter(Message.room_id == workspace_id)
        .order_by(Message.created_at.desc())
        .limit(5)
        .all()
    )
    recent_messages_data = [
        {
            "id": msg.id,
            "content": (msg.content[:100] + "...") if msg.content and len(msg.content) > 100 else (msg.content or ""),
            "sender_id": msg.user_id,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
        for msg in recent_messages
    ]
    last_message = recent_messages[0] if recent_messages else None
    last_active = last_message.created_at.isoformat() if last_message and last_message.created_at else None

    logger.info(
        "[ROOM_DETAILS] Workspace %s goals daily=%d weekly=%d monthly=%d",
        workspace_id,
        len(daily_goals),
        len(weekly_goals),
        len(monthly_goals),
    )

    return RoomDetailResponse(
        id=workspace.id,
        name=workspace.name,
        status="healthy",
        member_count=member_count,
        daily_goals=daily_goals[:10],
        weekly_goals=weekly_goals[:10],
        monthly_goals=monthly_goals[:10],
        active_challenges=active_challenges,
        blockers=blockers,
        recent_messages=recent_messages_data,
        last_active=last_active,
    )


@router.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(
    workspace_in: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = Room(
        id=str(uuid.uuid4()),
        name=workspace_in.name,
        org_id=current_user.org_id,
        created_at=datetime.utcnow(),
    )
    db.add(room)
    db.commit()
    db.refresh(room)

    membership = RoomMember(
        id=str(uuid.uuid4()),
        room_id=room.id,
        user_id=current_user.id,
        role_in_room="admin",
        joined_at=datetime.utcnow(),
    )
    db.add(membership)
    db.commit()

    return WorkspaceOut(id=room.id, name=room.name, role=membership.role_in_room)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.warning("[ROOM_DELETE] User %s attempting to delete workspace %s", current_user.id, workspace_id)
    membership = (
        db.query(RoomMember)
        .filter(
            RoomMember.room_id == workspace_id,
            RoomMember.user_id == current_user.id,
            RoomMember.role_in_room == "admin",
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.query(RoomMember).filter(RoomMember.room_id == workspace_id).delete()
    db.query(Room).filter(Room.id == workspace_id).delete()
    db.commit()

    logger.warning("[ROOM_DELETE] Workspace %s deleted by user %s", workspace_id, current_user.id)
    return {"status": "deleted", "workspace_id": workspace_id}


@router.post("/workspaces/{workspace_id}/members")
def add_workspace_member(
    workspace_id: str,
    member_in: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)

    membership = RoomMember(
        id=str(uuid.uuid4()),
        room_id=workspace_id,
        user_id=member_in.user_id,
        role_in_room=member_in.role,
        joined_at=datetime.utcnow(),
    )
    db.add(membership)
    db.commit()

    return {"status": "added"}


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)

    db.query(RoomMember).filter(
        RoomMember.room_id == workspace_id,
        RoomMember.user_id == user_id,
    ).delete()
    db.commit()

    return {"status": "removed"}
