"""
Shared admin response utilities and JSON sanitization.
"""
import time
from typing import Any, Optional, Dict

from fastapi import Request
from fastapi.responses import JSONResponse


def _get_request_context(request: Request) -> tuple[Optional[str], Optional[int]]:
    """Extract request_id and duration from request state."""
    request_id = getattr(request.state, "request_id", None)

    start_time = getattr(request.state, "_start_time", None)
    duration_ms = None
    if start_time:
        duration_ms = int((time.time() - start_time) * 1000)
    else:
        duration_ms = None

    return request_id, duration_ms


def admin_ok(
    *,
    data: Any,
    request: Request,
    debug: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
) -> JSONResponse:
    """
    Standard successful admin response envelope.
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
        },
    )


def admin_fail(
    *,
    code: str,
    message: str,
    request: Request,
    details: Optional[Dict[str, Any]] = None,
    debug: Optional[Dict[str, Any]] = None,
    status_code: int = 500,
) -> JSONResponse:
    """
    Standard failure admin response envelope.
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
        },
    )


def sanitize_for_json(value: Any) -> Any:
    """
    Convert common non-JSON-serializable types to safe representations.
    - datetime -> isoformat string
    - set/tuple -> list
    - objects -> str(value)
    """
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict, str, int, float, bool)):
        return value
    if isinstance(value, (set, tuple)):
        return [sanitize_for_json(v) for v in value]
    try:
        return str(value)
    except Exception:
        return "<unserializable>"
