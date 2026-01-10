from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_workspace_member
from models import (
    Room as RoomORM,
    RoomMember as RoomMemberORM,
    Message as MessageORM,
    User as UserORM,
    UserAction as UserActionORM,
    Notification as NotificationORM,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ActivityStats(BaseModel):
    total_actions_7d: int
    messages_7d: int
    active_members_7d: int


class HealthMetrics(BaseModel):
    overdue_tasks: int
    conflicts: int
    avg_sentiment: float = 0.0


class RoomNode(BaseModel):
    id: str
    name: str
    member_count: int
    member_ids: List[str]
    activity_stats: ActivityStats
    health_metrics: HealthMetrics


class RoomEdge(BaseModel):
    source_room_id: str
    target_room_id: str
    overlap_count: int
    interaction_strength: float


class UserInfo(BaseModel):
    id: str
    email: str
    name: Optional[str] = None


class OrgGraphResponse(BaseModel):
    rooms: List[RoomNode]
    edges: List[RoomEdge]
    members: Dict[str, UserInfo]
    request_id: str


@router.get("/workspaces/{workspace_id}/org-graph", response_model=OrgGraphResponse)
def get_org_graph(
    workspace_id: str,
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Organization graph for a workspace (rooms in same org).
    """
    import uuid

    request_id = str(uuid.uuid4())
    logger.info(
        "[ORG_GRAPH] Request for workspace_id=%s (UUID) from user_id=%s",
        workspace_id,
        getattr(current_user, "id", None),
    )

    workspace = db.query(RoomORM).filter(RoomORM.id == workspace_id).first()
    if not workspace:
        logger.warning("[ORG_GRAPH] Workspace %s not found", workspace_id)
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check membership after verifying workspace exists to avoid double-404 noise
    require_workspace_member(workspace_id, current_user, db)

    # OPTION A: Show only rooms in the same org (original logic)
    # org_rooms = (
    #     db.query(RoomORM)
    #     .filter(RoomORM.org_id == workspace.org_id)
    #     .all()
    # )

    # OPTION B: Show ALL rooms the user is a member of (regardless of org_id)
    # This is useful if workspaces have different/null org_ids
    user_room_ids = (
        db.query(RoomMemberORM.room_id)
        .filter(RoomMemberORM.user_id == current_user.id)
        .all()
    )
    room_ids_list = [rid[0] for rid in user_room_ids]
    org_rooms = (
        db.query(RoomORM)
        .filter(RoomORM.id.in_(room_ids_list))
        .all()
    )

    room_ids = [r.id for r in org_rooms]
    room_member_rows = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id.in_(room_ids))
        .all()
    )

    # Index members
    room_to_members: Dict[str, List[RoomMemberORM]] = {}
    member_ids_set = set()
    for rm in room_member_rows:
        room_to_members.setdefault(rm.room_id, []).append(rm)
        member_ids_set.add(rm.user_id)

    # Fetch member info
    members = {
        u.id: UserInfo(id=u.id, email=u.email, name=u.name)
        for u in db.query(UserORM).filter(UserORM.id.in_(member_ids_set)).all()
    }

    # Activity windows
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    actions = (
        db.query(UserActionORM.user_id, UserActionORM.room_id, func.count(UserActionORM.id))
        .filter(UserActionORM.room_id.in_(room_ids), UserActionORM.timestamp >= cutoff)
        .group_by(UserActionORM.user_id, UserActionORM.room_id)
        .all()
    )
    actions_by_room = {}
    active_members_by_room = {}
    for uid, rid, cnt in actions:
        actions_by_room[rid] = actions_by_room.get(rid, 0) + int(cnt)
        active_members_by_room.setdefault(rid, set()).add(uid)

    messages_7d = (
        db.query(MessageORM.room_id, func.count(MessageORM.id))
        .filter(MessageORM.room_id.in_(room_ids), MessageORM.created_at >= cutoff)
        .group_by(MessageORM.room_id)
        .all()
    )
    messages_by_room = {rid: int(cnt) for rid, cnt in messages_7d}

    # Conflicts: count notifications with conflict source_type for members of each room
    conflict_notifs = (
        db.query(NotificationORM.user_id, func.count(NotificationORM.id))
        .filter(
            NotificationORM.user_id.in_(member_ids_set),
            NotificationORM.source_type.in_(["conflict_file", "conflict_semantic"]),
        )
        .group_by(NotificationORM.user_id)
        .all()
    )
    conflicts_by_user = {uid: int(cnt) for uid, cnt in conflict_notifs}

    rooms_payload: List[RoomNode] = []
    for room in org_rooms:
        member_ids = [rm.user_id for rm in room_to_members.get(room.id, [])]
        member_count = len(member_ids)
        total_actions = actions_by_room.get(room.id, 0)
        msg_count = messages_by_room.get(room.id, 0)
        active_members = len(active_members_by_room.get(room.id, set()))
        conflicts = sum(conflicts_by_user.get(uid, 0) for uid in member_ids)

        rooms_payload.append(
            RoomNode(
                id=room.id,
                name=room.name,
                member_count=member_count,
                member_ids=member_ids,
                activity_stats=ActivityStats(
                    total_actions_7d=total_actions,
                    messages_7d=msg_count,
                    active_members_7d=active_members,
                ),
                health_metrics=HealthMetrics(
                    overdue_tasks=0,
                    conflicts=conflicts,
                    avg_sentiment=0.0,
                ),
            )
        )

    # Edges: shared members
    edges: List[RoomEdge] = []
    for i, r1 in enumerate(org_rooms):
        for r2 in org_rooms[i + 1:]:
            mem1 = set([rm.user_id for rm in room_to_members.get(r1.id, [])])
            mem2 = set([rm.user_id for rm in room_to_members.get(r2.id, [])])
            overlap = mem1 & mem2
            if not overlap:
                continue
            edges.append(
                RoomEdge(
                    source_room_id=r1.id,
                    target_room_id=r2.id,
                    overlap_count=len(overlap),
                    interaction_strength=float(len(overlap)),
                )
            )

    return OrgGraphResponse(
        rooms=rooms_payload,
        edges=edges,
        members=members,
        request_id=request_id,
    )
