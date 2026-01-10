import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class _CacheItem:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int = 60, max_items: int = 512):
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._store: Dict[str, _CacheItem] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        if item.expires_at < time.time():
            self._store.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        if len(self._store) >= self.max_items:
            self._prune()
        self._store[key] = _CacheItem(value=value, expires_at=time.time() + ttl)

    def _prune(self) -> None:
        now = time.time()
        expired = [key for key, item in self._store.items() if item.expires_at < now]
        for key in expired:
            self._store.pop(key, None)
        if len(self._store) < self.max_items:
            return
        # Fallback: drop oldest expirations to cap memory.
        survivors = sorted(self._store.items(), key=lambda kv: kv[1].expires_at)
        for key, _ in survivors[: max(1, len(self._store) - self.max_items + 1)]:
            self._store.pop(key, None)
