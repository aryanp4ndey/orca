"""K/L. Timeouts, retries, circuit breaking and partial failure."""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import ProviderTimeout
from app.core.resilience import CircuitBreaker, CircuitOpen, call_with_resilience


async def test_fast_call_succeeds():
    async def fn():
        return "ok"
    assert await call_with_resilience(fn, key="k", timeout_ms=100) == "ok"


async def test_slow_call_times_out_rather_than_hanging():
    async def fn():
        await asyncio.sleep(1.0)
    with pytest.raises(ProviderTimeout):
        await call_with_resilience(fn, key="k", timeout_ms=40)


async def test_retry_recovers_from_a_transient_failure():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")
        return "ok"

    result = await call_with_resilience(fn, key="k", timeout_ms=200,
                                        attempts=2, backoff_ms=1)
    assert result == "ok" and attempts["n"] == 2


async def test_retries_are_bounded():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        await call_with_resilience(fn, key="k", timeout_ms=200, attempts=3, backoff_ms=1)
    assert attempts["n"] == 3


async def test_breaker_opens_after_repeated_failures_and_then_short_circuits():
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=60)

    async def fn():
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await call_with_resilience(fn, key="dead", timeout_ms=50, breaker=breaker)
    assert breaker.is_open("dead")
    with pytest.raises(CircuitOpen):
        await call_with_resilience(fn, key="dead", timeout_ms=50, breaker=breaker)


async def test_breaker_half_opens_after_the_reset_window():
    breaker = CircuitBreaker(failure_threshold=1, reset_seconds=0.05)

    async def bad():
        raise RuntimeError("down")

    async def good():
        return "ok"

    with pytest.raises(RuntimeError):
        await call_with_resilience(bad, key="k", timeout_ms=50, breaker=breaker)
    assert breaker.is_open("k")
    await asyncio.sleep(0.06)
    assert await call_with_resilience(good, key="k", timeout_ms=50, breaker=breaker) == "ok"
    assert not breaker.is_open("k")


async def test_success_resets_the_failure_count():
    breaker = CircuitBreaker(failure_threshold=3)

    async def bad():
        raise RuntimeError("x")

    async def good():
        return 1

    with pytest.raises(RuntimeError):
        await call_with_resilience(bad, key="k", timeout_ms=50, breaker=breaker)
    await call_with_resilience(good, key="k", timeout_ms=50, breaker=breaker)
    assert breaker.snapshot()["k"]["failures"] == 0


async def test_a_provider_never_raises_into_an_agent():
    """The contract that makes graceful degradation possible."""
    from app.providers.base import MarineDataProvider, ProviderCapability
    from app.schemas.common import SourceStatus
    from app.schemas.geo import GeoPoint
    from app.schemas.marine import ProviderQuery

    class Exploding(MarineDataProvider):
        provider_id = "boom"

        def __init__(self):
            super().__init__(ProviderCapability(
                variables=("wind_speed_10m",), datasets=("d",),
                update_frequency_seconds=60, max_acceptable_age_seconds=120,
                cache_ttl_seconds=60))

        async def _fetch(self, query):
            raise ValueError("upstream exploded")

    result = await Exploding().fetch(ProviderQuery(point=GeoPoint(lat=9.9, lon=76.2)))
    assert result.status is SourceStatus.ERROR
    assert "upstream exploded" in result.error


async def test_registry_returns_a_typed_failure_for_a_dead_provider(container):
    from app.providers.base import MarineDataProvider, ProviderCapability
    from app.schemas.common import SourceStatus
    from app.schemas.geo import GeoPoint
    from app.schemas.marine import ProviderQuery

    class Slow(MarineDataProvider):
        provider_id = "slow"

        def __init__(self):
            super().__init__(ProviderCapability(
                variables=("wind_speed_10m",), datasets=("d",),
                update_frequency_seconds=60, max_acceptable_age_seconds=120,
                cache_ttl_seconds=60))

        async def _fetch(self, query):
            await asyncio.sleep(5)

    container.settings.budget_provider_ms = 60
    results = await container.registry.fetch_many(
        [(Slow(), ProviderQuery(point=GeoPoint(lat=9.9, lon=76.2)))])
    assert results[0].status in (SourceStatus.TIMEOUT, SourceStatus.ERROR)
    assert results[0].measurements == []
