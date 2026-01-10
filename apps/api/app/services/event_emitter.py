import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models import AppEvent

EVENT_BUFFER_MAX = 2000
_event_buffer: deque = deque(maxlen=EVENT_BUFFER_MAX)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def emit_event(
    event_type: str,
    user_email: Optional[str] = None,
    target_email: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Emit an event to the DB (if available) and in-memory buffer.
    """
    event_id = str(uuid.uuid4())
    payload = {
        "id": event_id,
        "event_type": event_type,
        "user_email": user_email,
        "target_email": target_email,
        "metadata": metadata or {},
        "request_id": request_id,
        "created_at": _now().isoformat(),
    }

    _event_buffer.append(payload)

    if db is not None:
        try:
            db_event = AppEvent(
                id=event_id,
                event_type=event_type,
                user_email=user_email,
                target_email=target_email,
                event_data=metadata or {},
                request_id=request_id,
                created_at=_now(),
            )
            db.add(db_event)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    return payload


def get_events(limit: int = 500, db: Optional[Session] = None, since: Optional[datetime] = None):
    """
    Fetch events from DB if available, otherwise from memory.
    """
    limit = max(1, min(limit, EVENT_BUFFER_MAX))

    if db is not None:
        try:
            q = db.query(AppEvent)
            if since is not None:
                q = q.filter(AppEvent.created_at >= since)
            events_db = q.order_by(AppEvent.created_at.desc()).limit(limit).all()
            events = [
                {
                    "id": ev.id,
                    "ts": ev.created_at.isoformat() if ev.created_at else None,
                    "event_type": ev.event_type,
                    "user_email": ev.user_email,
                    "target_email": ev.target_email,
                    "metadata": ev.metadata or {},
                    "request_id": ev.request_id,
                }
                for ev in events_db
            ]
            return events
        except Exception:
            pass

    result = []
    for ev in reversed(_event_buffer):
        if since and datetime.fromisoformat(ev["created_at"]) < since:
            continue
        result.append(ev)
        if len(result) >= limit:
            break
    return result
