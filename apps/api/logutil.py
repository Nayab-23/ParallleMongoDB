"""
Unified logging utilities for hackathon observability
Provides structured JSON logging and error response helpers
"""

import json
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse


def _now_iso() -> str:
    """Get current timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()


def log_event(
    tag: str,
    request_id: Optional[str] = None,
    **fields: Any
) -> None:
    """
    Log a structured JSON event to stdout

    Args:
        tag: Event category (e.g., REQUEST_START, MONGO_QUERY, FIREWORKS_CHAT)
        request_id: Request ID for correlation
        **fields: Additional fields to include in the log
    """
    log_entry = {
        "ts": _now_iso(),
        "tag": tag,
        "request_id": request_id,
        **fields
    }
    # Print as single-line JSON for easy parsing
    print(json.dumps(log_entry), file=sys.stdout, flush=True)


def log_error(
    tag: str,
    exc: Exception,
    request_id: Optional[str] = None,
    **context: Any
) -> None:
    """
    Log an error with full stacktrace

    Args:
        tag: Error category (e.g., MONGO_ERROR, FIREWORKS_ERROR)
        exc: The exception that occurred
        request_id: Request ID for correlation
        **context: Additional context fields
    """
    log_entry = {
        "ts": _now_iso(),
        "tag": tag,
        "request_id": request_id,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": traceback.format_exc(),
        **context
    }
    print(json.dumps(log_entry), file=sys.stderr, flush=True)


def fail(
    status_code: int,
    error_code: str,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> HTTPException:
    """
    Create a standardized error response

    Args:
        status_code: HTTP status code
        error_code: Machine-readable error code (e.g., MONGO_UNAVAILABLE)
        message: Human-readable error message
        request_id: Request ID for correlation
        details: Optional additional error details

    Returns:
        HTTPException with standardized JSON body
    """
    error_body = {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        error_body["details"] = details

    # Log the error
    log_event(
        "API_ERROR",
        request_id=request_id,
        status_code=status_code,
        error_code=error_code,
        message=message,
        details=details
    )

    return HTTPException(
        status_code=status_code,
        detail=error_body
    )


def create_error_response(
    status_code: int,
    error_code: str,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """
    Create a standardized JSON error response

    Args:
        status_code: HTTP status code
        error_code: Machine-readable error code
        message: Human-readable error message
        request_id: Request ID for correlation
        details: Optional additional error details

    Returns:
        JSONResponse with standardized error body
    """
    error_body = {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        error_body["details"] = details

    # Log the error
    log_event(
        "API_ERROR",
        request_id=request_id,
        status_code=status_code,
        error_code=error_code,
        message=message,
        details=details
    )

    return JSONResponse(
        status_code=status_code,
        content=error_body
    )


# Request ID middleware helpers
def get_request_id(request: Request) -> str:
    """Get or create request ID from request state"""
    return getattr(request.state, "request_id", "unknown")


def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
