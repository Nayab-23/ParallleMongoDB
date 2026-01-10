"""
Admin settings and logs endpoints.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from app.api.dependencies import require_platform_admin
from app.api.admin.utils import admin_ok, admin_fail
from app.services import runtime_settings, log_buffer

router = APIRouter()
logger = logging.getLogger(__name__)


class SettingsPayload(BaseModel):
    timeline_verbose_logging: Optional[bool] = None


@router.get("/settings")
async def get_settings(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_admin),
):
    """Get admin settings with debugging."""
    try:
        query_params = dict(request.query_params)
        timeline_verbose = runtime_settings.is_timeline_verbose(db)
        settings = {
            "timeline_verbose_logging": timeline_verbose,
        }
        settings_keys = list(settings.keys())

        return admin_ok(
            request=request,
            data={"settings": settings},
            debug={
                "input": {
                    "query_params": query_params,
                    "defaults_applied": {},
                },
                "output": {
                    "settings_count": len(settings),
                    "settings_keys": settings_keys,
                },
                "db": {"tables_queried": ["settings"]},
            }
        )

    except Exception as e:
        logger.exception("Failed to fetch admin settings")
        return admin_fail(
            request=request,
            code="SETTINGS_FETCH_FAILED",
            message="Failed to fetch admin settings",
            details={"exception": str(e)},
            debug={"input": {"query_params": query_params}},
            status_code=500
        )


@router.post("/settings")
async def update_settings(
    request: Request,
    payload: Optional[SettingsPayload] = Body(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_admin),
):
    """Update admin settings with debugging."""
    payload_dict = payload.dict() if payload is not None else None

    # Validate payload
    if payload is None:
        return admin_fail(
            request=request,
            code="VALIDATION_ERROR",
            message="Request body is required",
            details={"field": "body", "error": "missing"},
            debug={"input": {"payload": payload_dict}},
            status_code=400
        )

    if payload.timeline_verbose_logging is None:
        return admin_fail(
            request=request,
            code="VALIDATION_ERROR",
            message="timeline_verbose_logging is required",
            details={"field": "timeline_verbose_logging", "error": "missing"},
            debug={"input": {"payload": payload_dict}},
            status_code=400
        )

    try:
        updated = runtime_settings.set_timeline_verbose(payload.timeline_verbose_logging, db)
        settings = {"timeline_verbose_logging": updated}

        # Log the change
        context = {
            "value": updated,
            "admin_id": getattr(current_user, "id", None),
            "admin_email": getattr(current_user, "email", None),
        }
        logger.info("[Admin Settings] timeline_verbose_logging updated", extra={"context": context})
        log_buffer.log_event("info", "admin", "timeline_verbose_logging updated", context)

        settings_keys = list(settings.keys())
        return admin_ok(
            request=request,
            data={"settings": settings},
            debug={
                "input": {"payload": payload_dict},
                "output": {
                    "updated_value": updated,
                    "settings_keys": settings_keys,
                },
                "db": {"tables_queried": ["settings"]},
                "notes": ["setting persisted to database"],
            }
        )

    except Exception as e:
        logger.exception("Failed to update admin settings")
        return admin_fail(
            request=request,
            code="SETTINGS_UPDATE_FAILED",
            message="Failed to update admin settings",
            details={"exception": str(e)},
            debug={"input": {"payload": payload_dict}},
            status_code=500
        )


@router.get("/logs")
async def get_admin_logs(
    request: Request,
    source: Optional[str] = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=2000),
    current_user=Depends(require_platform_admin),
):
    """Get application logs with debugging."""
    # Validate source parameter
    valid_sources = ["all", "admin", "timeline", "notifications", "api", "system", "auth", "request"]
    if source not in valid_sources:
        return admin_fail(
            request=request,
            code="INVALID_SOURCE",
            message=f"Invalid source: {source}",
            details={"allowed_sources": valid_sources, "provided": source},
            status_code=422
        )

    try:
        # Get logs with proper filtering
        source_filter = None if source == "all" else source
        capped_limit = max(1, min(limit, log_buffer.LOG_BUFFER_MAX))
        logs = log_buffer.get_logs(source=source_filter, limit=capped_limit)

        return admin_ok(
            request=request,
            data={"logs": logs},
            debug={
                "input": {"source": source, "limit": limit},
                "output": {"count": len(logs)},
                "notes": [f"filter: {source_filter or 'none (all sources)'}"],
            }
        )

    except Exception as e:
        logger.exception("Failed to fetch admin logs")
        return admin_fail(
            request=request,
            code="LOG_FETCH_FAILED",
            message="Failed to fetch logs",
            details={"exception": str(e)},
            status_code=500
        )


@router.post("/logs/test")
async def test_admin_log(
    request: Request,
    current_user=Depends(require_platform_admin)
):
    """Test admin logging system."""
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        message = f"[Admin Log Test] {timestamp}"

        log_buffer.log_event(
            "info",
            "admin",
            message,
            {
                "admin_id": getattr(current_user, "id", None),
                "admin_email": getattr(current_user, "email", None),
                "timestamp": timestamp,
            },
        )

        return admin_ok(
            request=request,
            data={"logged": True, "message": message},
            debug={
                "output": {"timestamp": timestamp},
                "notes": ["test log written to buffer"],
            }
        )

    except Exception as e:
        logger.exception("Failed to write test log")
        return admin_fail(
            request=request,
            code="LOG_WRITE_FAILED",
            message="Failed to write test log",
            details={"exception": str(e)},
            status_code=500
        )
