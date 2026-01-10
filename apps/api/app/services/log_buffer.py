import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.services import runtime_settings

LOG_BUFFER_MAX = 2000
_buffer: deque = deque(maxlen=LOG_BUFFER_MAX)
_handler_attached = False

logger = logging.getLogger("parallel-backend")

SENSITIVE_KEYS = {"token", "secret", "cookie", "authorization", "password", "session"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sensitive(key: str) -> bool:
    key_lower = key.lower()
    return any(marker in key_lower for marker in SENSITIVE_KEYS)


def _stringify(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


def _sanitize_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not context or not isinstance(context, dict):
        return {}
    safe = {}
    for key, val in context.items():
        if _is_sensitive(str(key)):
            continue
        safe[str(key)] = _stringify(val)
    return safe


def _infer_source(logger_name: str) -> str:
    name = (logger_name or "").lower()
    if "canon" in name or "timeline" in name:
        return "timeline"
    if "admin" in name:
        return "admin"
    if "auth" in name:
        return "auth"
    return "app"


def _add_entry(level: str, source: str, message: str, context: Dict[str, Any]) -> None:
    _buffer.append(
        {
            "timestamp": _now_iso(),
            "level": level.lower(),
            "source": source,
            "message": message,
            "context": context,
        }
    )


class InAppLogHandler(logging.Handler):
    """Logging handler that mirrors logs into the in-app ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            source = getattr(record, "source", None) or _infer_source(record.name)
            level = record.levelname.lower()

            if source == "timeline" and record.levelno < logging.ERROR:
                if not runtime_settings.get_cached_setting(runtime_settings.TIMELINE_VERBOSE_KEY, False):
                    return

            context = getattr(record, "context", None)
            message = record.getMessage()
            _add_entry(level, source, message, _sanitize_context(context))
        except Exception:
            # Never raise from logging handler
            return


def attach_in_app_log_handler() -> None:
    """Attach the in-app ring buffer handler to the root logger (idempotent)."""
    global _handler_attached
    if _handler_attached:
        return
    root_logger = logging.getLogger()
    handler = InAppLogHandler()
    handler.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.addHandler(handler)
        uv_logger.propagate = True
        if uv_logger.level > logging.INFO:
            uv_logger.setLevel(logging.INFO)

    _handler_attached = True


def log_event(
    level: str,
    source: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log an event to both the in-app buffer and standard logging.

    Timeline info logs are gated by the runtime toggle; errors always log.
    """
    sanitized_context = _sanitize_context(context)
    extra = {"source": source, "context": sanitized_context}

    if source == "timeline":
        is_verbose = runtime_settings.get_cached_setting(runtime_settings.TIMELINE_VERBOSE_KEY, False)
        if level.lower() not in {"error", "critical", "exception"} and not is_verbose:
            return

    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(f"[{source}] {message}", extra=extra)


def get_logs(source: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, LOG_BUFFER_MAX))
    if source:
        filtered: Iterable = (entry for entry in reversed(_buffer) if entry["source"] == source)
    else:
        filtered = reversed(_buffer)
    result: List[Dict[str, Any]] = []
    for entry in filtered:
        result.append(entry)
        if len(result) >= limit:
            break
    return result
