"""Timeouts, retries and circuit breaking.

Every external call in ORCA goes through :func:`call_with_resilience`.  The
policy is intentionally conservative for a safety-adjacent system:

* one bounded attempt, one optional retry, hard deadline on the total;
* a circuit breaker so a dead source stops costing every user 1.8 s;
* failures are *returned*, never raised into an agent.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

from app.core.errors import ProviderTimeout
from app.observability.logging import get_logger

T = TypeVar("T")
log = get_logger("orca.resilience")


@dataclass
class BreakerState:
    failures: int = 0
    opened_at: float | None = None
    half_open: bool = False


@dataclass
class CircuitBreaker:
    """Per-provider breaker. Opens after N consecutive failures."""

    failure_threshold: int = 4
    reset_seconds: float = 30.0
    _states: dict[str, BreakerState] = field(default_factory=dict)

    def _state(self, key: str) -> BreakerState:
        return self._states.setdefault(key, BreakerState())

    def is_open(self, key: str) -> bool:
        st = self._state(key)
        if st.opened_at is None:
            return False
        if (time.monotonic() - st.opened_at) >= self.reset_seconds:
            st.half_open = True      # allow one probe through
            return False
        return True

    def record_success(self, key: str) -> None:
        self._states[key] = BreakerState()

    def record_failure(self, key: str) -> None:
        st = self._state(key)
        st.failures += 1
        if st.half_open or st.failures >= self.failure_threshold:
            st.opened_at = time.monotonic()
            st.half_open = False

    def snapshot(self) -> dict[str, dict]:
        return {
            k: {"failures": v.failures, "open": self.is_open(k)}
            for k, v in self._states.items()
        }


class CircuitOpen(RuntimeError):
    pass


async def call_with_resilience(
    fn: Callable[[], Awaitable[T]],
    *,
    key: str,
    timeout_ms: int,
    attempts: int = 1,
    backoff_ms: int = 120,
    breaker: CircuitBreaker | None = None,
    deadline_ms: int | None = None,
    retry_on_timeout: bool = False,
) -> T:
    """Run *fn* with a hard timeout, bounded retries and breaker protection.

    ``retry_on_timeout`` defaults to False on purpose. A source that timed out
    is slow, not flaky: retrying it spends the caller's remaining budget to ask
    the same slow thing again, and on a coastal link that budget is the whole
    user experience. Connection-level faults *are* worth one retry, and those
    still get one.

    ``deadline_ms`` bounds the total across all attempts, so a retry can never
    double the worst case.
    """
    if breaker is not None and breaker.is_open(key):
        raise CircuitOpen(f"circuit open for {key}")

    started = time.perf_counter()
    last_exc: Exception | None = None

    for attempt in range(max(1, attempts)):
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        remaining = timeout_ms
        if deadline_ms is not None:
            remaining = min(remaining, max(1, deadline_ms - elapsed_ms))
        try:
            result = await asyncio.wait_for(fn(), timeout=remaining / 1000.0)
            if breaker is not None:
                breaker.record_success(key)
            return result
        except asyncio.TimeoutError as exc:
            last_exc = ProviderTimeout(f"{key} timed out after {remaining:.0f} ms")
            last_exc.__cause__ = exc
            if not retry_on_timeout:
                break
        except Exception as exc:  # noqa: BLE001 - provider faults are data here
            last_exc = exc

        if attempt + 1 < attempts:
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep((backoff_ms * (2 ** attempt) * jitter) / 1000.0)

    if breaker is not None:
        breaker.record_failure(key)
    assert last_exc is not None
    raise last_exc
