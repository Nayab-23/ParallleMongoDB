"""
Admin self-test endpoint to validate system health.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from database import get_db
from models import User
from app.api.dependencies import require_platform_admin
from app.api.admin.responses import admin_ok, admin_fail
from app.services import log_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/_selftest")
async def admin_selftest(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Admin self-test endpoint to validate system components.

    Checks:
    - Database connectivity
    - Required tables exist (app_events, app_settings)
    - Can write test log + event
    - Returns diagnostic info

    Returns standard admin envelope with test results.
    """
    results = {
        "db_connected": False,
        "tables_exist": {},
        "test_log_written": False,
        "test_event_written": False,
        "tests_passed": 0,
        "tests_failed": 0,
    }

    debug = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": current_user.email,
    }

    # Test 1: Database connectivity
    try:
        db.execute(text("SELECT 1"))
        results["db_connected"] = True
        results["tests_passed"] += 1
        debug["db_test"] = "ok"
    except Exception as e:
        results["tests_failed"] += 1
        debug["db_test"] = f"failed: {str(e)}"

    # Test 2: Check required tables
    try:
        inspector = inspect(db.bind)
        all_tables = inspector.get_table_names()

        for table in ["app_events", "app_settings", "users", "notifications"]:
            exists = table in all_tables
            results["tables_exist"][table] = exists
            if exists:
                results["tests_passed"] += 1
            else:
                results["tests_failed"] += 1

        debug["all_tables_count"] = len(all_tables)
    except Exception as e:
        results["tests_failed"] += 1
        debug["table_check"] = f"failed: {str(e)}"

    # Test 3: Write test log
    try:
        log_buffer.log_event(
            level="info",
            source="admin_selftest",
            message=f"Self-test executed by {current_user.email}",
            data={"request_id": request.state.request_id}
        )
        results["test_log_written"] = True
        results["tests_passed"] += 1
        debug["log_test"] = "ok"
    except Exception as e:
        results["tests_failed"] += 1
        debug["log_test"] = f"failed: {str(e)}"

    # Test 4: Write test event (if table exists)
    if results["tables_exist"].get("app_events"):
        try:
            from models import AppEvent
            test_event = AppEvent(
                event_type="admin_selftest",
                source="admin",
                user_id=current_user.id,
                data={
                    "request_id": request.state.request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            db.add(test_event)
            db.commit()
            results["test_event_written"] = True
            results["tests_passed"] += 1
            debug["event_test"] = "ok"
        except Exception as e:
            db.rollback()
            results["tests_failed"] += 1
            debug["event_test"] = f"failed: {str(e)}"
    else:
        debug["event_test"] = "skipped (app_events table missing)"

    # Overall status
    results["overall_status"] = "healthy" if results["tests_failed"] == 0 else "degraded"

    return admin_ok(
        request=request,
        data=results,
        debug=debug,
        status_code=200 if results["tests_failed"] == 0 else 503
    )


@router.get("/_routes")
async def list_admin_routes(
    request: Request,
    current_user: User = Depends(require_platform_admin),
):
    """
    List all registered admin routes.

    Useful for debugging which endpoints are available.
    """
    from main import app

    admin_routes = []
    for route in app.routes:
        if hasattr(route, 'path') and route.path.startswith("/api/admin"):
            route_info = {
                "path": route.path,
                "methods": list(route.methods) if hasattr(route, 'methods') else [],
                "name": route.name if hasattr(route, 'name') else None,
            }
            admin_routes.append(route_info)

    return admin_ok(
        request=request,
        data={"routes": admin_routes, "count": len(admin_routes)},
        debug={"filter": "paths starting with /api/admin"}
    )


@router.get("/_health")
async def admin_health(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Quick health check for admin API.

    Returns:
    - Database status
    - Current time
    - User info
    """
    try:
        # Test DB
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return admin_ok(
        request=request,
        data={
            "status": "ok" if db_status == "connected" else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": db_status,
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "is_admin": True,
            }
        },
        debug={"check_performed": "database_connectivity"}
    )
