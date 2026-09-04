"""In-process LRU+TTL cache.

Chosen as the default because a hackathon prototype should start with one
command.  ``Cache`` is the seam: swapping in Redis is a config change, not a
rewrite (see ``app/cache/redis_cache.py``).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from app.cache.base import Cache, CacheEntry
from app.core.clock import utcnow


class MemoryCache(Cache):
    def __init__(self, max_entries: int = 4096) -> None:
        self._data: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max = max_entries
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    async def get(self, key: str) -> CacheEntry | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expired:
                del self._data[key]
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return entry

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._lock:
            self._data[key] = CacheEntry(key, value, utcnow(), ttl_seconds)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self._evictions += 1

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "backend": "memory",
            "entries": len(self._data),
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
        }
