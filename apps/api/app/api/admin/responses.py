"""
Standard response helpers for admin endpoints.

All admin endpoints should use these helpers to ensure consistent response format.
"""
import time
from typing import Any, Optional, Dict
from fastapi import Request
from fastapi.responses import JSONResponse


def _get_request_context(request: Request) -> tuple[str, int]:
    """Extract request_id and duration from request state."""
    request_id = getattr(request.state, "request_id", "unknown")

    # Calculate duration if start_time was set
    start_time = getattr(request.state, "_start_time", None)
    if start_time:
        duration_ms = int((time.time() - start_time) * 1000)
    else:
        duration_ms = 0

    return request_id, duration_ms


def admin_ok(
    request: Request,
    data: Any,
    debug: Optional[Dict[str, Any]] = None,
    status_code: int = 200
) -> JSONResponse:
    """
    Return a successful admin response.

    Args:
        request: FastAPI request object
        data: Response data
        debug: Debug metadata (counts, filters, etc.)
        status_code: HTTP status code (default 200)

    Returns:
        JSONResponse with standard envelope
    """
    request_id, duration_ms = _get_request_context(request)

    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "data": data,
            "debug": debug or {},
            "error": None,
        }
    )


def admin_fail(
    request: Request,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    debug: Optional[Dict[str, Any]] = None,
    status_code: int = 400
) -> JSONResponse:
    """
    Return a failed admin response.

    Args:
        request: FastAPI request object
        code: Error code (e.g., "MIGRATIONS_MISSING", "INVALID_SOURCE")
        message: Human-readable error message
        details: Additional error details
        debug: Debug metadata
        status_code: HTTP status code (default 400)

    Returns:
        JSONResponse with standard error envelope
    """
    request_id, duration_ms = _get_request_context(request)

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "data": None,
            "debug": debug or {},
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
        }
    )


def admin_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unexpected exceptions in admin endpoints.

    Converts crashes into structured error responses.
    """
    import traceback

    request_id, duration_ms = _get_request_context(request)

    # Log the full exception
    import logging
    logger = logging.getLogger(__name__)
    logger.exception(
        f"[ADMIN] Unhandled exception in {request.url.path}",
        extra={"request_id": request_id}
    )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "data": None,
            "debug": {
                "exception_type": type(exc).__name__,
                "path": request.url.path,
                "method": request.method,
            },
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {
                    "exception": str(exc),
                    "traceback": traceback.format_exc().split("\n")[-10:],  # Last 10 lines
                },
            },
        }
    )
