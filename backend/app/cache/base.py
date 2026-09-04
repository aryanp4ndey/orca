"""Cache interface.

A cached marine value is still a marine value: it keeps its original
``retrieved_at`` and source timestamps, and the freshness layer re-evaluates it
on read.  Caching in ORCA can make an answer *faster*; it is never allowed to
make an answer *look newer than it is*.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.clock import utcnow


@dataclass
class CacheEntry:
    key: str
    value: Any
    stored_at: datetime
    ttl_seconds: int

    @property
    def age_seconds(self) -> float:
        return (utcnow() - self.stored_at).total_seconds()

    @property
    def expired(self) -> bool:
        return self.age_seconds > self.ttl_seconds


class Cache(abc.ABC):
    @abc.abstractmethod
    async def get(self, key: str) -> CacheEntry | None: ...

    @abc.abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def clear(self) -> None: ...

    @abc.abstractmethod
    def stats(self) -> dict[str, Any]: ...
