"""
Admin API middleware for request tracking and debugging.
"""
import time
import uuid
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class AdminDebugMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds debugging context to all /api/admin/* requests.

    Features:
    - Generates request_id for each request
    - Tracks request duration
    - Captures user identity safely
    - Adds debug headers to response
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        # Only apply to admin routes
        if not path.startswith("/api/admin"):
            return await call_next(request)

        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        start_time = time.time()
        request.state._start_time = start_time
        request.state.request_id = request_id
        request.state.debug = {
            "method": request.method,
            "path": path,
            "query_string": str(request.query_params),
            "user_email": None,
            "user_id": None,
        }

        try:
            if hasattr(request.state, "current_user"):
                user = request.state.current_user
                request.state.debug["user_email"] = getattr(user, "email", None)
                request.state.debug["user_id"] = getattr(user, "id", None)
        except Exception:
            pass

        logger.info(
            f"[ADMIN] ➡️  {request.method} {path}",
            extra={"request_id": request_id}
        )

        try:
            response = await call_next(request)
            duration_ms = int((time.time() - start_time) * 1000)
            handler_name = getattr(response, "_admin_handler_name", None) or request.scope.get("endpoint", None)
            handler_str = getattr(handler_name, "__name__", None) if handler_name else None
            snapshot_info = getattr(request.state, "timeline_snapshot_info", {}) if hasattr(request.state, "timeline_snapshot_info") else {}
            git_sha = os.getenv("GIT_SHA") or "unknown"

            # Add debug headers
            response.headers["X-Admin-Request-Id"] = request_id
            response.headers["X-Admin-Duration-Ms"] = str(duration_ms)
            response.headers["X-Admin-Route"] = path
            if handler_str:
                response.headers["X-Admin-Handler"] = handler_str
            if snapshot_info:
                if snapshot_info.get("snapshot_key"):
                    response.headers["X-Admin-Snapshot-Key"] = snapshot_info.get("snapshot_key")
                if snapshot_info.get("snapshot_age_seconds") is not None:
                    response.headers["X-Admin-Snapshot-Age"] = str(snapshot_info.get("snapshot_age_seconds"))
            response.headers["X-Admin-Backend-Revision"] = git_sha

            log_payload = {
                "kind": "admin_request",
                "request_id": request_id,
                "path": path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "handler": handler_str,
                "user_email": request.state.debug.get("user_email"),
                "snapshot_key": snapshot_info.get("snapshot_key"),
                "snapshot_age_seconds": snapshot_info.get("snapshot_age_seconds"),
                "error_code": getattr(response, "_admin_error_code", None),
            }
            logger.info(log_payload)

            return response

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            git_sha = os.getenv("GIT_SHA") or "unknown"
            logger.error(
                f"[ADMIN] ❌ {request.method} {path} - ERROR after {duration_ms}ms: {str(e)}",
                extra={"request_id": request_id, "duration_ms": duration_ms},
                exc_info=True
            )
            # Best-effort headers even on error
            from fastapi.responses import JSONResponse
            payload = {
                "success": False,
                "data": None,
                "error": {"code": "ADMIN_ROUTE_ERROR", "message": str(e), "details": {}},
                "debug": {"request_id": request_id},
                "request_id": request_id,
                "duration_ms": duration_ms,
            }
            response = JSONResponse(status_code=500, content=payload)
            response.headers["X-Admin-Request-Id"] = request_id
            response.headers["X-Admin-Duration-Ms"] = str(duration_ms)
            response.headers["X-Admin-Route"] = path
            response.headers["X-Admin-Backend-Revision"] = git_sha
            return response
