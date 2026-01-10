from datetime import datetime, timezone
from typing import List, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import SessionLocal
from models import Room as RoomORM, Message as MessageORM, RoomMember as RoomMemberORM

router = APIRouter(prefix="/org", tags=["org-stats"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_user(request: Request, db: Session):
    from main import require_user as _require_user
    return _require_user(request, db)


def _room_health(fires: int) -> str:
    if fires > 2:
        return "critical"
    if fires > 0:
        return "strained"
    return "healthy"


@router.get("/stats")
def org_stats(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    perms = getattr(user, "permissions", {}) or {}
    if not perms.get("backend"):
        raise HTTPException(status_code=403, detail="Managers only")

    if not getattr(user, "org_id", None):
        return {
            "fires": 0,
            "overdue": 0,
            "sentiment": 0.5,
            "room_health": [],
            "bottlenecks": [],
            "opportunities": [],
        }

    rooms: List[RoomORM] = (
        db.query(RoomORM)
        .filter(RoomORM.org_id == user.org_id)
        .all()
    )

    keyword_filter = func.lower(MessageORM.content).op("similar to")(".*(urgent|blocker|problem).*")
    fires_by_room = dict(
        db.query(MessageORM.room_id, func.count(MessageORM.id))
        .join(RoomORM, RoomORM.id == MessageORM.room_id)
        .filter(RoomORM.org_id == user.org_id)
        .filter(keyword_filter)
        .group_by(MessageORM.room_id)
        .all()
    )

    room_health = []
    total_fires = 0
    for r in rooms:
        fires = int(fires_by_room.get(r.id, 0))
        total_fires += fires
        room_health.append(
            {
                "room_id": r.id,
                "status": _room_health(fires),
                "fires": fires,
                "sentiment": 0.5,
            }
        )

    return {
        "fires": total_fires,
        "overdue": 0,
        "sentiment": 0.5,
        "room_health": room_health,
        "bottlenecks": [],
        "opportunities": [],
    }
