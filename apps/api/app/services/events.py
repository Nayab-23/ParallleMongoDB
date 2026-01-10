import asyncio
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from models import WorkspaceEvent


def record_workspace_event(
    db: Session,
    *,
    workspace_id: str,
    event_type: str,
    resource_id: str,
    user_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    payload: Optional[Dict] = None,
) -> WorkspaceEvent:
    """
    Persist a workspace-scoped event. Caller is responsible for committing.
    """
    bind = db.get_bind()
    evt = WorkspaceEvent(
        workspace_id=workspace_id,
        type=event_type,
        resource_id=resource_id,
        user_id=user_id,
        entity_type=entity_type,
        payload=payload or {},
        created_at=datetime.now(timezone.utc),
    )
    if bind and bind.dialect.name == "sqlite":
        evt.id = int(evt.created_at.timestamp() * 1000)
    db.add(evt)
    db.flush()
    return evt


async def poll_events(
    db_factory,
    *,
    workspace_id: str,
    start_id: int,
    stop_event: asyncio.Event,
    poll_interval: float = 1.0,
    batch_size: int = 50,
) -> Iterable[WorkspaceEvent]:
    """
    Simple polling generator for SSE/WebSocket streams.
    Uses a factory to create short-lived sessions to avoid holding locks.
    """
    last_id = start_id
    while not stop_event.is_set():
        session: Session = db_factory()
        try:
            rows: List[WorkspaceEvent] = (
                session.query(WorkspaceEvent)
                .filter(WorkspaceEvent.workspace_id == workspace_id, WorkspaceEvent.id > last_id)
                .order_by(WorkspaceEvent.id.asc())
                .limit(batch_size)
                .all()
            )
            if rows:
                last_id = rows[-1].id
                for row in rows:
                    yield row
            else:
                await asyncio.sleep(poll_interval)
        finally:
            session.close()
