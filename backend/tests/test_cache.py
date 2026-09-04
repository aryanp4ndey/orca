"""J. Caching - fast, deduplicated, and never able to hide staleness."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.cache.keys import geocode_key, provider_key, quantise_point, quantise_time
from app.cache.memory import MemoryCache
from app.providers.imd.demo import DemoIMDProvider
from app.schemas.common import DataOrigin
from app.schemas.geo import GeoPoint
from app.schemas.marine import ProviderQuery

POINT = GeoPoint(lat=9.9312, lon=76.2125)
WHEN = dt.datetime(2026, 9, 3, 1, 30, tzinfo=dt.timezone.utc)


async def test_set_get_and_miss():
    cache = MemoryCache()
    assert await cache.get("nope") is None
    await cache.set("k", {"v": 1}, 60)
    entry = await cache.get("k")
    assert entry.value == {"v": 1} and entry.age_seconds >= 0


async def test_ttl_expiry(frozen_clock):
    """Expiry is driven by the clock, so the test advances the clock."""
    from app.core import clock
    cache = MemoryCache()
    await cache.set("k", 1, 60)
    assert await cache.get("k") is not None
    clock.freeze(frozen_clock + dt.timedelta(seconds=61))
    assert await cache.get("k") is None


async def test_lru_eviction():
    cache = MemoryCache(max_entries=2)
    await cache.set("a", 1, 60)
    await cache.set("b", 2, 60)
    await cache.set("c", 3, 60)
    assert await cache.get("a") is None
    assert await cache.get("c") is not None


async def test_stats_track_hit_rate():
    cache = MemoryCache()
    await cache.set("k", 1, 60)
    await cache.get("k")
    await cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1 and stats["hit_rate"] == 0.5


def test_nearby_points_share_a_cache_key():
    """Two boats a few km apart must not each trigger an upstream call."""
    a = GeoPoint(lat=9.93, lon=76.21)
    b = GeoPoint(lat=9.95, lon=76.23)
    assert quantise_point(a) == quantise_point(b)
    assert provider_key("p", "d", a, WHEN, ["x"]) == provider_key("p", "d", b, WHEN, ["x"])


def test_distant_points_do_not_share_a_cache_key():
    far = GeoPoint(lat=13.08, lon=80.27)
    assert quantise_point(POINT) != quantise_point(far)


def test_times_bucket_to_the_hour():
    t1 = dt.datetime(2026, 9, 3, 1, 5, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2026, 9, 3, 1, 55, tzinfo=dt.timezone.utc)
    t3 = dt.datetime(2026, 9, 3, 3, 5, tzinfo=dt.timezone.utc)
    assert quantise_time(t1) == quantise_time(t2) != quantise_time(t3)


def test_variable_set_is_part_of_the_key():
    assert provider_key("p", "d", POINT, WHEN, ["a"]) != provider_key("p", "d", POINT, WHEN, ["b"])
    assert provider_key("p", "d", POINT, WHEN, ["a", "b"]) == provider_key("p", "d", POINT, WHEN, ["b", "a"])


def test_geocode_key_is_case_insensitive():
    assert geocode_key(" Kochi ") == geocode_key("kochi")


async def test_cached_result_keeps_its_original_timestamps(container):
    """A cache hit must never make a value look newer than it is."""
    registry = container.registry
    provider = DemoIMDProvider()
    query = ProviderQuery(point=POINT, valid_time=WHEN,
                          variables=list(provider.capability.variables))
    first = await registry.fetch(provider, query)
    second = await registry.fetch(provider, query)
    assert second.cache.hit is True
    assert first.cache.hit is False
    assert [m.issued_at for m in second.measurements] == \
           [m.issued_at for m in first.measurements]
    assert second.retrieved_at == first.retrieved_at


async def test_cached_live_data_is_relabelled_not_disguised(container):
    """A cached live reading is reported as CACHED_LIVE, never as LIVE."""
    from app.providers.base import ProviderCapability
    from app.schemas.common import Source, SourceStatus
    from app.schemas.marine import ProviderResult
    from app.providers.base import MarineDataProvider

    class FakeLive(MarineDataProvider):
        provider_id = "fake_live"
        source = Source.OPEN_METEO
        origin = DataOrigin.LIVE

        def __init__(self):
            super().__init__(ProviderCapability(
                variables=("wind_speed_10m",), datasets=("fake",),
                update_frequency_seconds=3600, max_acceptable_age_seconds=7200,
                cache_ttl_seconds=60))

        async def _fetch(self, q):
            return ProviderResult(
                provider_id=self.provider_id, source=self.source, origin=self.origin,
                dataset="fake", status=SourceStatus.OK, measurements=[])

    provider = FakeLive()
    query = ProviderQuery(point=POINT, valid_time=WHEN, variables=["wind_speed_10m"])
    first = await container.registry.fetch(provider, query)
    assert first.origin is DataOrigin.LIVE
    # An empty result is not cached, so seed the cache with a usable one.
    from app.schemas.marine import Measurement
    from app.schemas.common import QualityFlag, VariableKind
    from app.core.clock import utcnow
    seeded = first.model_copy(deep=True)
    seeded.measurements = [Measurement(
        variable="wind_speed_10m", value=10.0, unit="km/h", kind=VariableKind.FORECAST,
        valid_time=WHEN, issued_at=utcnow(), location=POINT, quality=QualityFlag.GOOD)]
    key = container.registry.cache_key_for(provider, query)
    await container.cache.set(key, seeded.model_dump(mode="json"), 60)
    cached = await container.registry.fetch(provider, query)
    assert cached.cache.hit is True
    assert cached.origin is DataOrigin.CACHED_LIVE


async def test_identical_concurrent_requests_collapse_to_one_upstream_call(container):
    """Request de-duplication: a burst of identical questions costs one call."""
    calls = {"n": 0}
    provider = DemoIMDProvider()
    original = provider._fetch

    async def counting(query):
        calls["n"] += 1
        await asyncio.sleep(0.02)
        return await original(query)

    provider._fetch = counting
    query = ProviderQuery(point=POINT, valid_time=WHEN,
                          variables=list(provider.capability.variables))
    await asyncio.gather(*(container.registry.fetch(provider, query) for _ in range(6)))
    assert calls["n"] == 1
