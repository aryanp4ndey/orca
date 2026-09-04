"""Provider registry: selection, caching, resilience and parallel retrieval.

This is where the latency answer lives.  Agents do not call providers directly;
they hand the registry a list of (provider, query) pairs and get results back.
The registry then:

* checks the quantised cache first (so two boats 2 km apart share one upstream
  call within the same hour bucket);
* de-duplicates identical in-flight requests, so a burst of users asking about
  Kochi at 07:00 produces exactly one network call;
* runs everything that has no dependency on everything else concurrently;
* enforces a per-provider timeout and a circuit breaker;
* returns a typed failure instead of raising, so one dead source never takes the
  answer down.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

from app.cache.base import Cache
from app.cache.keys import provider_key
from app.config.settings import Settings
from app.core.clock import utcnow
from app.core.resilience import CircuitBreaker, CircuitOpen, call_with_resilience
from app.observability.logging import get_logger
from app.observability.trace import Trace
from app.providers.base import MarineDataProvider, NotConfiguredProvider
from app.providers.gis.local import LocalGISProvider
from app.providers.imd.demo import DemoIMDProvider
from app.providers.imd.live import IMDLiveProvider
from app.providers.incois.demo import DemoINCOISProvider
from app.providers.incois.live import INCOISLiveProvider
from app.providers.mosdac.demo import DemoMOSDACProvider
from app.providers.mosdac.live import MOSDACLiveProvider
from app.providers.openmeteo.live import OpenMeteoMarineProvider, OpenMeteoWeatherProvider
from app.providers.openweathermap.live import OpenWeatherMapProvider
from app.reasoning import freshness as freshness_mod
from app.schemas.common import DataOrigin, Source, SourceStatus
from app.schemas.marine import ProviderQuery, ProviderResult

log = get_logger("orca.registry")

# Which source family is authoritative for what, for Indian waters. The conflict
# resolver uses this order; it is configuration, not an accident of import order.
SOURCE_PRIORITY: dict[str, list[Source]] = {
    # IMD is the authority for Indian waters. The two free sources below are
    # cross-checks, and become the primary only when IMD is unreachable.
    "atmosphere": [Source.IMD, Source.OPEN_METEO, Source.OPEN_WEATHER_MAP],
    "ocean": [Source.INCOIS, Source.OPEN_METEO],
    "satellite": [Source.MOSDAC],
}
VARIABLE_DOMAIN = {
    "wind_speed_10m": "atmosphere", "wind_gust_10m": "atmosphere",
    "wind_direction_10m": "atmosphere", "precipitation": "atmosphere",
    "visibility": "atmosphere", "cloud_cover": "atmosphere",
    "temperature_2m": "atmosphere", "cape": "atmosphere",
    "thunderstorm_probability": "atmosphere",
    "wave_height_significant": "ocean", "wave_period": "ocean",
    "wave_direction": "ocean", "swell_height": "ocean", "swell_period": "ocean",
    "swell_direction": "ocean", "sea_surface_temperature": "ocean",
    "current_speed": "ocean", "current_direction": "ocean",
    "chlorophyll_a": "satellite",
}


class ProviderRegistry:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self.settings = settings
        self.cache = cache
        self.breaker = CircuitBreaker(
            failure_threshold=settings.breaker_failure_threshold,
            reset_seconds=settings.breaker_reset_seconds)
        self._inflight: dict[str, asyncio.Future] = {}
        self.providers: list[MarineDataProvider] = self._build(settings)
        self.gis = LocalGISProvider()

    # ---- construction ----------------------------------------------------
    @staticmethod
    def _build(s: Settings) -> list[MarineDataProvider]:
        if s.demo_mode:
            return [DemoIMDProvider(), DemoINCOISProvider(), DemoMOSDACProvider()]
        out: list[MarineDataProvider] = []
        pairs = (
            (s.imd_enabled, IMDLiveProvider, "ORCA_IMD_ENABLED is false"),
            (s.incois_enabled, INCOISLiveProvider, "ORCA_INCOIS_ENABLED is false"),
            (s.mosdac_enabled, MOSDACLiveProvider, "ORCA_MOSDAC_ENABLED is false"),
        )
        for enabled, cls, reason in pairs:
            provider = cls()
            out.append(provider if enabled else NotConfiguredProvider(provider, reason))
        if s.openmeteo_enabled:
            out.append(OpenMeteoWeatherProvider())
            out.append(OpenMeteoMarineProvider())
        if s.openweathermap_enabled:
            out.append(OpenWeatherMapProvider())
        return out

    # ---- selection -------------------------------------------------------
    def for_variables(self, variables: Sequence[str]) -> list[MarineDataProvider]:
        """Providers that can serve at least one requested variable.

        Ordered by authority for the dominant domain of the request, so the
        primary source is attempted first and wins conflicts by default.
        """
        domain = _dominant_domain(variables)
        order = SOURCE_PRIORITY.get(domain, [])
        candidates = [p for p in self.providers if p.supports(variables)]
        candidates.sort(key=lambda p: (order.index(p.source) if p.source in order
                                       else len(order)))
        return candidates

    def describe_all(self) -> list[dict]:
        out = []
        for p in self.providers:
            d = p.describe()
            out.append({
                "provider_id": d.provider_id, "source": d.source.value,
                "origin": d.origin.value, "role": d.role,
                "verified_access": d.verified,
                "verification_note": d.verification_note,
                "access_mechanism": d.access_mechanism,
                "attribution": d.attribution,
                "variables": list(d.capability.variables),
                "datasets": list(d.capability.datasets),
                "update_frequency_seconds": d.capability.update_frequency_seconds,
                "max_acceptable_age_seconds": d.capability.max_acceptable_age_seconds,
                "not_configured": isinstance(p, NotConfiguredProvider),
            })
        out.append({
            "provider_id": self.gis.provider_id, "source": Source.GIS.value,
            "origin": DataOrigin.COMPUTED.value, "role": "Location, boundaries, geofencing",
            "verified_access": self.gis.verified_access, "verification_note": "",
            "access_mechanism": self.gis.access_mechanism,
            "attribution": self.gis.attribution,
            "variables": [], "datasets": ["orca_gazetteer", "orca_boundary_layers"],
            "update_frequency_seconds": None, "max_acceptable_age_seconds": None,
            "not_configured": False,
        })
        return out

    # ---- retrieval -------------------------------------------------------
    def cache_key_for(self, provider: MarineDataProvider,
                      query: ProviderQuery) -> str:
        """The single definition of a provider cache key. Used by tests too."""
        return provider_key(
            provider.provider_id,
            provider.capability.datasets[0] if provider.capability.datasets else "d",
            query.point, query.valid_time,
            list(query.variables) or list(provider.capability.variables),
            variant=self._cache_variant(query))

    async def fetch(self, provider: MarineDataProvider, query: ProviderQuery,
                    trace: Trace | None = None) -> ProviderResult:
        key = self.cache_key_for(provider, query)

        cached = await self.cache.get(key)
        if cached is not None:
            if trace:
                trace.cache_hit(key)
            result = ProviderResult.model_validate(cached.value)
            result.cache.hit = True
            result.cache.key = key
            result.cache.stored_at = cached.stored_at
            result.cache.ttl_seconds = cached.ttl_seconds
            if result.origin is DataOrigin.LIVE:
                result.origin = DataOrigin.CACHED_LIVE
            # Re-evaluate freshness on read: a cache hit never freezes time.
            return freshness_mod.annotate(result)

        if trace:
            trace.cache_miss(key)

        # Collapse identical concurrent requests into one upstream call.
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[key] = fut
        try:
            result = await self._fetch_uncached(provider, query)
            if result.ok and (result.measurements or result.advisories or result.pfz):
                await self.cache.set(key, result.model_dump(mode="json"),
                                     provider.capability.cache_ttl_seconds)
            result.cache.key = key
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as exc:  # noqa: BLE001
            if not fut.done():
                fut.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch_uncached(self, provider: MarineDataProvider,
                              query: ProviderQuery) -> ProviderResult:
        try:
            result = await call_with_resilience(
                lambda: provider.fetch(query),
                key=provider.provider_id,
                timeout_ms=self.settings.budget_provider_ms,
                attempts=1 + self.settings.provider_retry_attempts,
                backoff_ms=self.settings.provider_retry_backoff_ms,
                breaker=self.breaker,
                deadline_ms=self.settings.budget_provider_ms,
            )
        except CircuitOpen:
            return provider.empty_result(
                SourceStatus.CIRCUIT_OPEN,
                error=("source has failed repeatedly and is temporarily bypassed "
                       "to protect response time"))
        except Exception as exc:  # noqa: BLE001
            status = (SourceStatus.TIMEOUT
                      if "timed out" in str(exc).lower() else SourceStatus.ERROR)
            return provider.empty_result(status, error=f"{type(exc).__name__}: {exc}")
        return freshness_mod.annotate(result)

    async def fetch_many(self, specs: Iterable[tuple[MarineDataProvider, ProviderQuery]],
                         trace: Trace | None = None) -> list[ProviderResult]:
        """Run independent provider calls concurrently. This is the fan-out."""
        specs = list(specs)
        if not specs:
            return []

        async def one(provider: MarineDataProvider, q: ProviderQuery) -> ProviderResult:
            if trace is None:
                return await self.fetch(provider, q)
            with trace.span(provider.provider_id, "provider",
                            source=provider.source.value,
                            variables=list(q.variables)) as span:
                r = await self.fetch(provider, q, trace)
                span.status = r.status.value
                span.attributes["cache_hit"] = r.cache.hit
                span.attributes["freshness"] = r.freshness.value
                return r

        results = await asyncio.gather(*(one(p, q) for p, q in specs),
                                       return_exceptions=True)
        out: list[ProviderResult] = []
        for (provider, _), r in zip(specs, results):
            if isinstance(r, BaseException):
                out.append(provider.empty_result(
                    SourceStatus.ERROR, error=f"{type(r).__name__}: {r}"))
            else:
                out.append(r)
        return out

    def _cache_variant(self, query: ProviderQuery) -> str | None:
        """Extra key material for inputs that are not point/time/variables."""
        parts: list[str] = []
        if query.extras:
            parts.append("|".join(f"{k}={v}" for k, v in sorted(query.extras.items())))
        if self.settings.demo_mode:
            from app.providers.demo_controls import get_demo_controls
            controls = get_demo_controls()
            parts.append("sc=" + controls.scenario)
            if controls.fail_sources:
                parts.append("fail=" + ",".join(sorted(controls.fail_sources)))
            if controls.stale_sources:
                parts.append("stale=" + ",".join(sorted(controls.stale_sources)))
            if controls.inject_conflict:
                parts.append("conflict=1")
        return "|".join(parts) or None

    def breaker_snapshot(self) -> dict:
        return self.breaker.snapshot()


def _dominant_domain(variables: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    for v in variables:
        d = VARIABLE_DOMAIN.get(v)
        if d:
            counts[d] = counts.get(d, 0) + 1
    return max(counts, key=counts.get) if counts else "atmosphere"
