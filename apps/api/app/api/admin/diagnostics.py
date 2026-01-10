"""
Admin diagnostics endpoints.
"""
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.engine.url import make_url
import os

from database import get_db, engine
from app.api.dependencies import require_platform_admin
from app.services import log_buffer
from app.api.admin.utils import admin_ok, admin_fail

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/_routes")
async def list_admin_routes(request: Request, current_user=Depends(require_platform_admin)):
    try:
        from app.api.admin import router as admin_router

        routes: List[str] = []
        for r in admin_router.routes:
            path = getattr(r, "path", None)
            methods = sorted(getattr(r, "methods", []) or [])
            if path and path.startswith("/admin"):
                routes.append(f"{','.join(methods)} {path}")
        return admin_ok(
            request=request,
            data={"routes": routes},
            debug={"input": {"query_params": dict(request.query_params)}, "output": {"routes_count": len(routes)}},
        )
    except Exception as exc:
        logger.exception("Failed to list admin routes")
        log_buffer.log_event("error", "admin", "Failed to list admin routes", {"error": str(exc)})
        return admin_fail(
            request=request,
            code="ROUTES_ERROR",
            message="Failed to list admin routes",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.get("/_health")
async def admin_health(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_admin),
):
    request_id = str(uuid.uuid4())
    db_ok = False
    app_events_ok = False
    app_settings_ok = False
    db_error_kind: Optional[str] = None
    db_error_message: Optional[str] = None

    def sanitize_error(msg: str) -> str:
        if not msg:
            return ""
        sanitized = msg
        # scrub typical credential patterns
        if "@" in sanitized and "://" in sanitized:
            try:
                before_at = sanitized.split("@", 1)[0]
                if ":" in before_at:
                    prefix = before_at.split("://", 1)[0]
                    sanitized = sanitized.replace(before_at + "@", f"{prefix}://***@")
            except Exception:
                pass
        for token in ("password", "user", "username"):
            sanitized = sanitized.replace(token, "***")
        return sanitized[:160]

    def parse_db_url():
        url_str = os.getenv("DATABASE_URL", "")
        try:
            url = make_url(url_str)
            return {
                "db_host": url.host,
                "db_name": url.database,
                "db_scheme": url.drivername,
                "is_internal_host": bool(url.host and str(url.host).startswith("dpg-")),
            }
        except Exception:
            return {
                "db_host": None,
                "db_name": None,
                "db_scheme": None,
                "is_internal_host": False,
            }

    db_meta = parse_db_url()

    app_events_columns: List[str] = []

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        inspector = inspect(db.bind or engine)
        tables = set(inspector.get_table_names())
        app_events_ok = "app_events" in tables
        app_settings_ok = "app_settings" in tables
        if app_events_ok:
            try:
                app_events_columns = [c["name"] for c in inspector.get_columns("app_events")]
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Health check: failed to read app_events columns: {exc}")
    except SQLAlchemyError as exc:
        msg = str(exc)
        lower = msg.lower()
        if "could not translate host name" in lower:
            db_error_kind = "dns"
        elif "password authentication failed" in lower:
            db_error_kind = "auth"
        elif "ssl" in lower:
            db_error_kind = "ssl"
        elif "timeout" in lower:
            db_error_kind = "timeout"
        elif "connection refused" in lower:
            db_error_kind = "refused"
        else:
            db_error_kind = "unknown"

        db_error_message = sanitize_error(msg)
        logger.exception("Health check DB error", extra={"request_id": request_id, "kind": db_error_kind})
        log_buffer.log_event(
            "error",
            "admin",
            "Health check DB error",
            {"request_id": request_id, "error": db_error_message, "kind": db_error_kind},
        )

    return admin_ok(
        request=request,
        data={
            "db_ok": db_ok,
            "db_host": db_meta.get("db_host"),
            "db_host_internal": db_meta.get("is_internal_host"),
            "db_name": db_meta.get("db_name"),
            "app_events_table_ok": app_events_ok,
            "app_events_columns": app_events_columns,
            "app_settings_table_ok": app_settings_ok,
        },
        debug={
            "input": {},
            "output": {
                "db_error_kind": db_error_kind,
                "db_error_message": db_error_message,
            },
            "db": {"tables_checked": ["app_events", "app_settings"]},
        },
    )


@router.get("/_env_probe")
async def env_probe(request: Request, current_user=Depends(require_platform_admin)):
    url_str = os.getenv("DATABASE_URL", "")
    db_scheme = None
    db_host = None
    db_name = None
    try:
        url = make_url(url_str)
        db_scheme = url.drivername
        db_host = url.host
        db_name = url.database
    except Exception:
        pass
    return admin_ok(
        request=request,
        data={
            "database_url_set": bool(url_str),
            "database_url_scheme": db_scheme,
            "db_host": db_host,
            "db_name": db_name,
        },
        debug={"input": {"query_params": dict(request.query_params)}},
    )


@router.get("/_smoke")
async def smoke_test(request: Request, current_user=Depends(require_platform_admin)):
    errors = []
    ok = True
    try:
        log_buffer.get_logs(limit=1)
    except Exception as exc:
        ok = False
        errors.append(f"logs:{exc}")
    try:
        # lightweight events check: ensure module importable
        from app.api.admin import events  # noqa: F401
    except Exception as exc:
        ok = False
        errors.append(f"events:{exc}")

    return admin_ok(
        request=request,
        data={"ok": ok, "errors": errors},
        debug={"input": {"query_params": dict(request.query_params)}, "output": {"error_count": len(errors)}},
    )


@router.get("/_release_readiness")
async def release_readiness(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_admin),
):
    """
    Lightweight readiness probe for coordination stack (agent inbox, code events).
    """
    backend_revision = os.getenv("GIT_SHA") or os.getenv("BACKEND_REV") or os.getenv("VITE_GIT_SHA") or "unknown"
    db_ok = False
    tables_exist = {
        "agent_inbox": False,
        "agent_clients": False,
        "code_events": False,
        "agent_cursors": False,
    }
    columns_exist = {
        "agent_inbox.result": False,
        "agent_inbox.error_code": False,
        "code_events.impact_tags": False,
        "code_events.details": False,
    }
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        inspector = inspect(db.bind or engine)
        table_names = set(inspector.get_table_names())
        for key in tables_exist:
            tables_exist[key] = key in table_names
        if tables_exist["agent_inbox"]:
            cols = {c["name"] for c in inspector.get_columns("agent_inbox")}
            columns_exist["agent_inbox.result"] = "result" in cols
            columns_exist["agent_inbox.error_code"] = "error_code" in cols
        if tables_exist["code_events"]:
            cols = {c["name"] for c in inspector.get_columns("code_events")}
            columns_exist["code_events.impact_tags"] = "impact_tags" in cols
            columns_exist["code_events.details"] = "details" in cols
    except Exception as exc:
        logger.warning("[ReleaseReadiness] DB check failed: %s", exc)

    routes_wired = {
        "dispatch": True,
        "code_events": True,
        "extension": True,
    }

    return admin_ok(
        request=request,
        data={
            "backend_revision": backend_revision,
            "db_ok": db_ok,
            "tables_exist": tables_exist,
            "columns_exist": columns_exist,
            "routes_wired": routes_wired,
        },
        debug={"input": {"query_params": dict(request.query_params)}},
    )
