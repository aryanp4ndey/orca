"""Optional Redis cache.

Same contract as :class:`MemoryCache`, including the rule that a cached value
keeps its original timestamps and is re-classified for freshness on read.
Enable with ``ORCA_CACHE_BACKEND=redis`` and ``ORCA_REDIS_URL``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.cache.base import Cache, CacheEntry
from app.core.clock import utcnow


class RedisCache(Cache):
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis   # imported lazily: optional dependency
        self._client = redis.from_url(url, decode_responses=True)
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> CacheEntry | None:
        raw = await self._client.get(key)
        if raw is None:
            self._misses += 1
            return None
        payload = json.loads(raw)
        self._hits += 1
        return CacheEntry(key=key, value=payload["value"],
                          stored_at=datetime.fromisoformat(payload["stored_at"]),
                          ttl_seconds=payload["ttl"])

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._client.set(
            key,
            json.dumps({"value": value, "stored_at": utcnow().isoformat(),
                        "ttl": ttl_seconds}),
            ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def clear(self) -> None:
        await self._client.flushdb()

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {"backend": "redis", "hits": self._hits, "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0}
