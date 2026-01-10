import uuid
from typing import List, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import SessionLocal
from models import Room as RoomORM, Message as MessageORM, RoomMember as RoomMemberORM

router = APIRouter(prefix="/org", tags=["org-graph"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_user(request: Request, db: Session):
    from main import require_user as _require_user
    return _require_user(request, db)


def _compute_status(fires: int, overdue: int) -> str:
    if fires > 2 or overdue > 5:
        return "critical"
    if fires > 0 or overdue > 2:
        return "strained"
    return "healthy"


@router.get("/graph")
def org_graph(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    perms = getattr(user, "permissions", {}) or {}
    if not perms.get("backend"):
        raise HTTPException(status_code=403, detail="Managers only")

    if not getattr(user, "org_id", None):
        return {"nodes": [], "edges": []}

    rooms: List[RoomORM] = (
        db.query(RoomORM)
        .filter(RoomORM.org_id == user.org_id)
        .all()
    )

    # message fires
    keyword_filter = func.lower(MessageORM.content).op("similar to")(".*(urgent|blocker|problem).*")
    fires_by_room = dict(
        db.query(MessageORM.room_id, func.count(MessageORM.id))
        .join(RoomORM, RoomORM.id == MessageORM.room_id)
        .filter(RoomORM.org_id == user.org_id)
        .filter(keyword_filter)
        .group_by(MessageORM.room_id)
        .all()
    )

    # members per room
    members_by_room: Dict[str, List[str]] = {}
    memberships = (
        db.query(RoomMemberORM.room_id, RoomMemberORM.user_id)
        .join(RoomORM, RoomORM.id == RoomMemberORM.room_id)
        .filter(RoomORM.org_id == user.org_id)
        .all()
    )
    for room_id, user_id in memberships:
        members_by_room.setdefault(room_id, []).append(user_id)

    nodes_map = {}
    for r in rooms:
        canonical = (r.name or "").strip().lower()
        fires = int(fires_by_room.get(r.id, 0))
        sentiment = 0.5  # placeholder
        overdue = 0
        status = _compute_status(fires, overdue)
        if canonical not in nodes_map:
            nodes_map[canonical] = {
                "id": canonical or r.id,
                "name": r.name,
                "fires": fires,
                "sentiment": sentiment,
                "overdue": overdue,
                "status": status,
            }
        else:
            # merge fires status if duplicate name casing
            nodes_map[canonical]["fires"] += fires
            nodes_map[canonical]["status"] = _compute_status(nodes_map[canonical]["fires"], overdue)

    nodes = list(nodes_map.values())

    edges = []
    room_list = list(rooms)
    for i in range(len(room_list)):
        for j in range(i + 1, len(room_list)):
            a = room_list[i]
            b = room_list[j]
            members_a = set(members_by_room.get(a.id, []))
            members_b = set(members_by_room.get(b.id, []))
            if not members_a and not members_b:
                continue
            overlap = members_a & members_b
            denom = max(len(members_a), len(members_b))
            weight = (len(overlap) / denom) if denom else 0
            if weight > 0:
                from_id = (a.name or "").strip().lower() or a.id
                to_id = (b.name or "").strip().lower() or b.id
                edges.append(
                    {"from_room_id": from_id, "to_room_id": to_id, "weight": weight}
                )

    return {
        "legend": "Edges represent dependencies between rooms. weight is a normalized value between 0 and 1.",
        "nodes": nodes,
        "edges": edges,
    }
