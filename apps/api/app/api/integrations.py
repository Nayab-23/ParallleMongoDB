import os
import logging
import uuid
import jwt
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from models import (
    User as UserORM,
    Room as RoomORM,
    RoomMember as RoomMemberORM,
    ActivityLog,
)
from app.services.notifications import create_smart_team_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="")

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"


def require_user_token(request: Request, db: Session) -> UserORM:
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                user = db.get(UserORM, user_id)
                if user:
                    return user
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _default_room_for_user(db: Session, user: UserORM, explicit_room_id: Optional[str]) -> Optional[RoomORM]:
    if explicit_room_id:
        room = db.get(RoomORM, explicit_room_id)
        if room:
            return room
    membership = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.user_id == user.id)
        .first()
    )
    if membership:
        return db.get(RoomORM, membership.room_id)
    return None


class VSCodeActivityPayload(BaseModel):
    file_path: str
    lines_changed: int
    language: Optional[str] = None
    event_type: Optional[str] = "edit"  # edit, save, delete
    room_id: Optional[str] = None


class VSCodeHeartbeatPayload(BaseModel):
    active_file: Optional[str] = None
    language: Optional[str] = None


@router.post("/integrations/vscode/activity")
def vscode_activity(
    payload: VSCodeActivityPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user_token(request, db)
    room = _default_room_for_user(db, user, payload.room_id)

    # Create UserAction record for conflict detection
    from models import UserAction
    user_action = UserAction(
        user_id=user.id,
        tool="vscode",
        action_type=payload.event_type or "file_edit",
        action_data={
            "file_path": payload.file_path,
            "lines_changed": payload.lines_changed,
            "language": payload.language,
        },
        room_id=room.id if room else None,
        timestamp=datetime.utcnow(),
        activity_summary=f"{payload.event_type or 'edit'} {payload.file_path} ({payload.lines_changed} lines)",
    )
    db.add(user_action)
    db.commit()

    description = f"{payload.event_type or 'edit'} {payload.file_path} ({payload.lines_changed} lines)"
    if room:
        try:
            create_smart_team_update(
                actor_user_id=user.id,
                room_id=room.id,
                update_type=payload.event_type or "edit",
                description=description,
                db=db,
            )
            logger.info(f"[Smart Update Trigger] vscode_activity by {user.id}")
        except Exception as exc:
            logger.warning(f"[Smart Update Trigger] vscode_activity failed for {user.id}: {exc}")
    else:
        logger.warning(f"[Smart Update Trigger] vscode_activity skipped team update, no room for {user.id}")
    return {"status": "ok"}


@router.get("/integrations/vscode/context")
def vscode_context(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user_token(request, db)
    from main import get_or_create_canonical_plan  # lazy import to avoid circular at module load
    canon = get_or_create_canonical_plan(user.id, db)
    timeline = canon.approved_timeline or {}
    room_ids = [rm.room_id for rm in db.query(RoomMemberORM).filter(RoomMemberORM.user_id == user.id).all()]
    activities = []
    if room_ids:
        activities = (
            db.query(ActivityLog)
            .filter(ActivityLog.room_id.in_(room_ids))
            .order_by(ActivityLog.updated_at.desc())
            .limit(10)
            .all()
        )
    team_activity = [
        {
            "description": act.description,
            "updated_at": act.updated_at.isoformat() if act.updated_at else None,
            "room_id": act.room_id,
            "user_id": act.user_id,
        }
        for act in activities
    ]
    suggestions = []
    today = timeline.get("1d", {})
    if today:
        for section in ["critical", "high", "normal"]:
            for item in today.get(section, [])[:2]:
                title = item.get("title") or item.get("subject") or "Untitled"
                suggestions.append(f"Focus on {title}")
    if not suggestions:
        suggestions.append("Check recent team updates")
    current_tasks = today
    return {
        "current_tasks": current_tasks,
        "team_activity": team_activity,
        "suggestions": suggestions,
    }


@router.post("/integrations/vscode/heartbeat")
def vscode_heartbeat(
    payload: VSCodeHeartbeatPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user_token(request, db)
    logger.info(f"[VSCode Heartbeat] user={user.id} file={payload.active_file} lang={payload.language}")
    return {"status": "ok"}


@router.get("/vscode/auth/token")
def vscode_auth_token(code: str, db: Session = Depends(get_db)):
    """
    Placeholder OAuth callback: returns a JWT for the user id matching the code (if exists).
    In a real flow, exchange code for user identity. Here we attempt to treat `code` as user_id.
    """
    user = db.get(UserORM, code)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid auth code")
    token = jwt.encode({"sub": user.id, "exp": datetime.now(timezone.utc)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "user_id": user.id}
