from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from models import Notification, User

router = APIRouter()


class NotificationOut(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str
    created_at: datetime
    is_read: bool
    read: Optional[bool] = None
    data: dict

    class Config:
        from_attributes = True


def _build_notifications_envelope(
    db: Session, user_id: str, *, limit: int = 50, unread_only: bool = False
) -> dict:
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.is_read == False)

    total_count = query.count()
    urgent_count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,
            ((Notification.severity == "urgent") | (Notification.type.ilike("%conflict%"))),
        )
        .count()
    )

    notifications = (
        query.order_by(Notification.created_at.desc()).limit(limit).all()
    )

    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "severity": getattr(n, "severity", "normal"),
                "title": n.title,
                "message": n.message,
                "data": n.data,
                "read": n.is_read,
                "is_read": n.is_read,
                "source_type": getattr(n, "source_type", None),
                "created_at": n.created_at,
            }
            for n in notifications
        ],
        "total": total_count,
        "urgent_count": urgent_count,
    }


def _get_unread_count(db: Session, user_id: str) -> int:
    return (
        db.query(Notification)
        .filter_by(user_id=user_id, is_read=False)
        .count()
    )


def _mark_all_read(db: Session, user_id: str) -> int:
    marked_read = (
        db.query(Notification)
        .filter_by(user_id=user_id, is_read=False)
        .update({"is_read": True})
    )
    db.commit()
    return marked_read


def _mark_one_read(db: Session, user_id: str, notification_id: str) -> None:
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404)
    notif.is_read = True
    db.commit()


@router.get("/notifications")
async def get_notifications(
    limit: int = 50,
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _build_notifications_envelope(
        db, current_user.id, limit=limit, unread_only=unread_only
    )


@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _mark_one_read(db, current_user.id, notification_id)
    return {"status": "ok"}


@router.get("/notifications/unread-count")
async def get_unread_notification_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"count": _get_unread_count(db, current_user.id)}


@router.patch("/notifications/mark-all-read")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    marked_read = _mark_all_read(db, current_user.id)
    return {"status": "success", "marked_read": marked_read}
