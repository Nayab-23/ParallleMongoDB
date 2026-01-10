import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_current_user, require_workspace_member, rate_limit_dep
from app.services.events import poll_events
from database import SessionLocal
from models import User

router = APIRouter()


@router.get("/events")
async def stream_events(
    workspace_id: str,
    since_event_id: Optional[int] = Query(0, ge=0),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_dep("sse_stream", max_calls=30, window_seconds=60)),
):
    """
    Server-Sent Events stream scoped to a workspace.
    """
    db = SessionLocal()
    try:
        require_workspace_member(workspace_id, current_user, db)
    finally:
        db.close()
    stop_event = asyncio.Event()

    async def event_generator():
        try:
            start_id = since_event_id or 0
            if request is not None:
                hdr_last_id = request.headers.get("last-event-id")
                if hdr_last_id:
                    try:
                        start_id = int(hdr_last_id)
                    except ValueError:
                        start_id = since_event_id or 0

            async for evt in poll_events(
                SessionLocal,
                workspace_id=workspace_id,
                start_id=start_id,
                stop_event=stop_event,
            ):
                base_ts = evt.created_at.isoformat() if evt.created_at else None
                payload = evt.payload or {}
                data = {
                    "event_id": evt.id,
                    "type": evt.type,
                    "entity_type": evt.entity_type or evt.type.split(".")[0],
                    "workspace_id": evt.workspace_id,
                    "resource_id": evt.resource_id,
                    "room_id": payload.get("room_id") if isinstance(payload, dict) else None,
                    "ts": base_ts,
                    "payload": payload if isinstance(payload, dict) else {},
                }
                # Promote graph fields if present in payload
                if isinstance(payload, dict):
                    for key in ("graph_id", "execution_id", "node_id"):
                        if key in payload and key not in data:
                            data[key] = payload.get(key)
                    # Legacy timestamp alias
                    if "timestamp" in payload and not data.get("ts"):
                        data["ts"] = payload.get("timestamp")

                yield f"id: {evt.id}\nevent: {evt.type}\ndata: {json.dumps(data)}\n\n"
                # heartbeat comment to keep connection alive
                yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            stop_event.set()
            raise
        finally:
            stop_event.set()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
