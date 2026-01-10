"""
Admin events stream for System Overview.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import inspect
from sqlalchemy.exc import ProgrammingError

from database import get_db
from models import AppEvent, User
from app.api.dependencies import require_platform_admin
from app.api.admin.utils import admin_ok, admin_fail, sanitize_for_json
from app.services import log_buffer, event_emitter

router = APIRouter()
logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None
def _sanitize_metadata(metadata: dict) -> dict:
    if not isinstance(metadata, dict):
        return sanitize_for_json(metadata)
    return {k: sanitize_for_json(v) for k, v in metadata.items()}


def _parse_user_ids(user_ids: Optional[str]) -> List[str]:
    if not user_ids:
        return []
    return [u.strip() for u in user_ids.split(",") if u.strip()]


@router.get("/events")
async def get_admin_events(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=200, ge=1, le=2000),
    user_ids: Optional[str] = Query(default=None),
    event_types: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Get application events with full debugging.

    Query params:
    - days: Number of days to look back (default: 7, max: 30)
    - limit: Max events to return (default: 200, max: 2000)
    - user_ids: Comma-separated user emails to filter by
    - event_types: Comma-separated event types to filter by
    """
    try:
        inspector = None
        column_names: List[str] = []
        # Validate parameters
        if days is None:
            days = 7
        if limit is None:
            limit = 200

        days = max(1, min(days, 30))
        limit = max(1, min(limit, 2000))

        # Check if app_events table exists
        try:
            inspector = inspect(db.bind)
            all_tables = inspector.get_table_names()
        except Exception as e:
            logger.error(f"Failed to inspect database: {e}")
            return admin_fail(
                request=request,
                code="DB_INSPECTION_FAILED",
                message="Failed to inspect database tables",
                details={"exception": str(e)},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=500
            )

        if "app_events" not in all_tables:
            return admin_fail(
                request=request,
                code="MIGRATIONS_MISSING",
                message="app_events table missing; run alembic upgrade head",
                details={"available_tables": all_tables},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=503
            )

        try:
            column_names = [col["name"] for col in inspector.get_columns("app_events")]
        except Exception as e:
            logger.error(f"Failed to inspect app_events columns: {e}")
            return admin_fail(
                request=request,
                code="DB_INSPECTION_FAILED",
                message="Failed to inspect app_events columns",
                details={"exception": str(e)},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=503
            )

        if "event_data" not in column_names:
            return admin_fail(
                request=request,
                code="MIGRATIONS_OUT_OF_SYNC",
                message="Database schema out of sync with AppEvent model",
                details={
                    "missing_column": "event_data",
                    "app_events_columns": column_names,
                    "hint": "run alembic upgrade head",
                },
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=503,
            )

        # Query events
        since = datetime.now(timezone.utc) - timedelta(days=days)
        ids_filter = _parse_user_ids(user_ids)
        types_filter = _parse_user_ids(event_types)  # Reuse same parsing logic

        try:
            q = db.query(AppEvent).filter(AppEvent.created_at >= since)

            if ids_filter:
                q = q.filter(AppEvent.user_email.in_(ids_filter))

            if types_filter:
                q = q.filter(AppEvent.event_type.in_(types_filter))

            events_db = q.order_by(AppEvent.created_at.desc()).limit(limit).all()
        except ProgrammingError as e:
            logger.error(f"Schema mismatch querying app_events: {e}")
            return admin_fail(
                request=request,
                code="MIGRATIONS_OUT_OF_SYNC",
                message="Database schema out of sync with AppEvent model",
                details={
                    "exception": str(e),
                    "table": "app_events",
                    "hint": "run alembic upgrade head",
                },
                debug={"input": {"query_params": dict(request.query_params)}, "db": {"app_events_columns": column_names}},
                status_code=503,
            )
        except Exception as e:
            logger.error(f"Failed to query app_events table: {e}")
            return admin_fail(
                request=request,
                code="DB_QUERY_FAILED",
                message="Failed to query app_events table",
                details={"exception": str(e), "table": "app_events"},
                debug={"input": {"query_params": dict(request.query_params)}, "db": {"app_events_columns": column_names}},
                status_code=500
            )

        # Build response
        events = []
        try:
            for ev in events_db:
                events.append({
                    "id": ev.id,
                    "ts": _iso(ev.created_at),
                    "type": ev.event_type,
                    "actor_user_id": ev.user_email,
                    "target_user_id": ev.target_email,
                    "org_id": None,
                    "metadata": _sanitize_metadata(ev.event_data or {}),
                    "request_id": ev.request_id,
                })
        except Exception as e:
            logger.error(f"Failed to serialize events: {e}")
            return admin_fail(
                request=request,
                code="SERIALIZATION_FAILED",
                message="Failed to serialize events",
                details={"exception": str(e)},
                status_code=500
            )

        # Track data source
        data_source = "database"
        used_fallback = False

        # Try fallback to in-memory buffer if no events found
        if not events:
            try:
                buffer_events = event_emitter.get_events(limit=limit, db=None, since=since)
                if buffer_events:
                    sanitized_buffer = []
                    for ev in buffer_events:
                        meta = ev.get("metadata") or ev.get("event_data") or {}
                        sanitized_buffer.append(
                            {
                                "id": ev.get("id"),
                                "ts": ev.get("ts") or ev.get("created_at"),
                                "type": ev.get("event_type"),
                                "actor_user_id": ev.get("user_email"),
                                "target_user_id": ev.get("target_email"),
                                "org_id": ev.get("org_id"),
                                "metadata": _sanitize_metadata(meta if isinstance(meta, dict) else {}),
                                "request_id": ev.get("request_id"),
                            }
                        )
                    events = sanitized_buffer
                    used_fallback = True
                    data_source = "in-memory buffer"
            except Exception as e:
                logger.warning(f"Failed to fetch fallback events from buffer: {e}")
                # Continue with empty events - not a fatal error

        if not events:
            data_source = "empty"

        return admin_ok(
            request=request,
            data={"events": events},
            debug={
                "input": {
                    "days": days,
                    "limit": limit,
                    "user_ids": ids_filter if ids_filter else None,
                    "event_types": types_filter if types_filter else None,
                },
                "output": {
                    "count": len(events),
                    "newest_ts": events[0]["ts"] if events else None,
                    "oldest_ts": events[-1]["ts"] if events else None,
                },
                "notes": [data_source],
                "db": {"tables_queried": ["app_events"], "columns": column_names},
            }
        )

    except Exception as e:
        logger.exception("Unexpected error in get_admin_events")
        return admin_fail(
            request=request,
            code="INTERNAL_ERROR",
            message="Unexpected error fetching events",
            details={"exception": str(e)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500
        )
