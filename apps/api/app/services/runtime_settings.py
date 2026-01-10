import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import AppSetting

logger = logging.getLogger(__name__)

TIMELINE_VERBOSE_KEY = "timeline_verbose_logging"
DEFAULT_CACHE_TTL_SECONDS = 20

_cache: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if not entry:
        return None
    if entry["expires_at"] > _now():
        return entry["value"]
    return entry["value"]  # stale but better than None if DB unavailable


def _cache_set(key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
    _cache[key] = {"value": value, "expires_at": _now() + timedelta(seconds=ttl_seconds)}


def get_setting(
    key: str,
    db: Session | None = None,
    default: Any = None,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> Any:
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if db is None:
        return default

    try:
        setting = db.get(AppSetting, key)
        value = default if setting is None else setting.value
        _cache_set(key, value, ttl_seconds)
        return value
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Failed to load runtime setting",
            extra={"key": key, "error": str(exc)},
        )
        return default if cached is None else cached


def set_setting(
    key: str,
    value: Any,
    db: Session,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> Any:
    try:
        setting = db.get(AppSetting, key)
        if setting is None:
            setting = AppSetting(key=key, value=value)
        else:
            setting.value = value
        db.add(setting)
        db.commit()
        _cache_set(key, value, ttl_seconds)
        return value
    except Exception as exc:
        logger.exception(
            "Failed to persist runtime setting",
            extra={"key": key, "error": str(exc)},
        )
        try:
            db.rollback()
        except Exception:
            pass
        raise


def get_cached_setting(key: str, default: Any = None) -> Any:
    cached = _cache_get(key)
    return default if cached is None else cached


def is_timeline_verbose(db: Session | None = None) -> bool:
    value = get_setting(TIMELINE_VERBOSE_KEY, db=db, default=False)
    return bool(value)


def set_timeline_verbose(value: bool, db: Session) -> bool:
    return bool(set_setting(TIMELINE_VERBOSE_KEY, bool(value), db=db))
