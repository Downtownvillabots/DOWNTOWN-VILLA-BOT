"""
Group config TTL cache.
Avoids hammering MongoDB on every callback.
Invalidate on any write.
"""
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigCache:
    def __init__(self, ttl: int = 300, max_entries: int = 500):
        self._ttl = ttl
        self._max = max_entries
        self._data: Dict[int, Dict[str, Any]] = {}
        self._ts: Dict[int, float] = {}

    def get(self, chat_id: int) -> Optional[Dict[str, Any]]:
        ts = self._ts.get(chat_id)
        if ts is None:
            return None
        if time.time() - ts > self._ttl:
            self._data.pop(chat_id, None)
            self._ts.pop(chat_id, None)
            return None
        return self._data.get(chat_id)

    def set(self, chat_id: int, config: Dict[str, Any]) -> None:
        if len(self._data) >= self._max:
            # evict oldest
            oldest = min(self._ts.items(), key=lambda kv: kv[1])[0]
            self._data.pop(oldest, None)
            self._ts.pop(oldest, None)
        self._data[chat_id] = config
        self._ts[chat_id] = time.time()

    def invalidate(self, chat_id: int) -> None:
        self._data.pop(chat_id, None)
        self._ts.pop(chat_id, None)

    def invalidate_all(self) -> None:
        self._data.clear()
        self._ts.clear()

    def size(self) -> int:
        return len(self._data)


config_cache = ConfigCache()
