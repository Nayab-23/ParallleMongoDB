"""Admin API endpoints."""

import logging
import os

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import require_platform_admin
from models import User
from app.api.admin.utils import admin_ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# === CANARY ENDPOINT FOR ADMIN DASHBOARD ===
@router.get("/_ping")
async def admin_ping(request: Request, current_user: User = Depends(require_platform_admin)):
    """
    Health check endpoint for admin dashboards.

    Returns 200 OK if the user is authenticated and is a platform admin.
    Used by frontend to verify admin access without touching business logic.

    Returns:
        - ok: Always true if endpoint succeeds
        - email: Admin user's email
        - is_platform_admin: Always true (enforced by dependency)

    Raises:
        - 401: If not authenticated
        - 403: If authenticated but not platform admin
    """
    return admin_ok(
        request=request,
        data={
            "ok": True,
            "email": current_user.email,
            "is_platform_admin": True,
        },
        debug={"input": {"query_params": dict(request.query_params)}},
    )


@router.get("/_version")
async def admin_version(
    request: Request,
    current_user: User = Depends(require_platform_admin),
):
    """
    Deployment verification endpoint to confirm build metadata.
    """
    git_sha = os.getenv("GIT_SHA") or "unknown"
    build_time = os.getenv("BUILD_TIME") or "unknown"
    parallel_env = os.getenv("PARALLEL_ENV") or "unknown"

    data = {
        "git_sha": git_sha,
        "build_time": build_time,
        "env": parallel_env,
    }

    return admin_ok(
        request=request,
        data=data,
        debug={
            "input": {"query_params": dict(request.query_params)},
            "output": {
                "has_git_sha": git_sha != "unknown",
                "has_build_time": build_time != "unknown",
                "has_env": parallel_env != "unknown",
            },
        },
    )


# Import timeline debug endpoints (admin/timeline.py)
try:
    from . import timeline as timeline_router

    logger.info("[Admin API] ✅ Successfully imported timeline router")

    # Include timeline router WITHOUT /timeline prefix to match frontend expectations
    # Frontend calls: /api/admin/timeline-debug/{email}
    # So we include it directly under /admin (no nested prefix)
    router.include_router(
        timeline_router.router,
        tags=["admin-timeline-debug"],
    )
    logger.info("[Admin API] ✅ Timeline router registered - endpoints available at /admin/timeline-debug/...")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin timeline router: {exc}", exc_info=True)
    try:
        from app.services import log_buffer

        log_buffer.log_event(
            "error",
            "admin",
            "Failed to import admin timeline router",
            {"error": str(exc)},
        )
    except Exception:
        pass

# Import VSCode debug endpoints (admin/vscode.py)
try:
    from . import vscode as vscode_router

    logger.info("[Admin API] ✅ Successfully imported VSCode router")

    # Include VSCode router
    # Frontend calls: /api/admin/vscode-debug/{email}
    router.include_router(
        vscode_router.router,
        tags=["admin-vscode-debug"],
    )
    logger.info("[Admin API] ✅ VSCode router registered - endpoints available at /admin/vscode-debug/...")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin VSCode router: {exc}", exc_info=True)

# Import Collaboration debug endpoints (admin/collaboration.py)
try:
    from . import collaboration as collaboration_router

    logger.info("[Admin API] ✅ Successfully imported Collaboration router")

    # Include Collaboration router
    # Frontend calls: /api/admin/collaboration-debug?users=...
    router.include_router(
        collaboration_router.router,
        tags=["admin-collaboration-debug"],
    )
    logger.info("[Admin API] ✅ Collaboration router registered - endpoints available at /admin/collaboration-debug")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin Collaboration router: {exc}", exc_info=True)

# Import Waitlist admin endpoints
try:
    from . import waitlist as waitlist_router

    router.include_router(waitlist_router.router, tags=["admin-waitlist"])
    logger.info("[Admin API] ✅ Waitlist router registered - endpoints available at /admin/waitlist")
except Exception as exc:  # pragma: no cover
    logger.error(f"[Admin API] ❌ Could not import admin Waitlist router: {exc}", exc_info=True)

# Import shared endpoints (users, shared auth helper)
try:
    from . import shared as shared_router

    logger.info("[Admin API] ✅ Successfully imported Shared admin router")

    router.include_router(
        shared_router.router,
        tags=["admin-shared"],
    )
    logger.info("[Admin API] ✅ Shared router registered - endpoints available at /admin/users")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin Shared router: {exc}", exc_info=True)

# Import System overview endpoints (admin/system.py)
try:
    from . import system as system_router

    logger.info("[Admin API] ✅ Successfully imported System router")

    # Include System router
    # Frontend calls: /api/admin/system-overview?days=7
    router.include_router(
        system_router.router,
        tags=["admin-system"],
    )
    logger.info("[Admin API] ✅ System router registered - endpoints available at /admin/system-overview")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin System router: {exc}", exc_info=True)

# Import Admin settings/logs endpoints
try:
    from . import settings as settings_router

    logger.info("[Admin API] ✅ Successfully imported Settings router")

    router.include_router(
        settings_router.router,
        tags=["admin-settings"],
    )
    logger.info("[Admin API] ✅ Settings router registered - endpoints available at /admin/settings and /admin/logs")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin Settings router: {exc}", exc_info=True)

# Import Admin events endpoint
try:
    from . import events as events_router

    logger.info("[Admin API] ✅ Successfully imported Events router")

    router.include_router(
        events_router.router,
        tags=["admin-events"],
    )
    logger.info("[Admin API] ✅ Events router registered - endpoints available at /admin/events")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin Events router: {exc}", exc_info=True)

# Import diagnostics (_routes, _health)
try:
    from . import diagnostics as diagnostics_router

    logger.info("[Admin API] ✅ Successfully imported Diagnostics router")

    router.include_router(
        diagnostics_router.router,
        tags=["admin-diagnostics"],
    )
    logger.info("[Admin API] ✅ Diagnostics router registered - endpoints available at /admin/_routes and /admin/_health")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin Diagnostics router: {exc}", exc_info=True)

# Import debug headers endpoint
try:
    from . import debug_headers as debug_headers_router

    router.include_router(debug_headers_router.router, tags=["admin-debug"])
    logger.info("[Admin API] ✅ Debug headers router registered - endpoint /admin/_debug_headers")
except Exception as exc:  # pragma: no cover
    logger.error(f"[Admin API] ❌ Could not import admin debug headers router: {exc}", exc_info=True)

# Import selftest endpoints (_selftest, _health, _routes)
try:
    from . import selftest as selftest_router

    logger.info("[Admin API] ✅ Successfully imported Selftest router")

    router.include_router(
        selftest_router.router,
        tags=["admin-system"],
    )
    logger.info("[Admin API] ✅ Selftest router registered - endpoints available at /admin/_selftest, /admin/_health, /admin/_routes")
except Exception as exc:  # pragma: no cover - best-effort import
    logger.error(f"[Admin API] ❌ Could not import admin Selftest router: {exc}", exc_info=True)
