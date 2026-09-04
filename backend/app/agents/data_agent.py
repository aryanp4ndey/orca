"""Shared retrieval behaviour for the weather, ocean and satellite agents.

Each of those three has a different responsibility and a different authority,
but the same shape: ask every provider that can serve its canonical variables,
in parallel; normalise; build evidence; fuse across sources with explicit
conflict handling; report per-source status.

The variable lists below are the contract.  An agent asks for canonical names -
never an upstream API's field name - which is what lets a provider be swapped
without touching an agent.
"""

from __future__ import annotations

from datetime import datetime

from app.agents.base import BaseAgent
from app.observability.trace import Trace
from app.reasoning.evidence_builder import from_provider_result, source_report
from app.reasoning.fusion import fuse
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Freshness, SourceStatus
from app.schemas.marine import ProviderQuery

WEATHER_VARIABLES = (
    "wind_speed_10m", "wind_gust_10m", "wind_direction_10m", "precipitation",
    "visibility", "cloud_cover", "temperature_2m", "cape", "thunderstorm_probability",
)
OCEAN_VARIABLES = (
    "wave_height_significant", "wave_period", "wave_direction",
    "swell_height", "swell_period", "swell_direction",
    "sea_surface_temperature", "current_speed", "current_direction",
)
SATELLITE_VARIABLES = ("sea_surface_temperature", "chlorophyll_a", "cloud_cover")


class DataRetrievalAgent(BaseAgent):
    variables: tuple[str, ...] = ()
    provider_extras: dict | None = None
    #: Source families this agent is allowed to consult. Keeps each agent inside
    #: its own domain of authority and stops, for example, the satellite agent
    #: paying for an IMD call just because IMD also reports cloud cover.
    allowed_sources: tuple[str, ...] = ()

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        point = request.point or (ctx.location.point if ctx.location else None)
        if point is None:
            return AgentResponse(
                agent=self.name, capability=self.capability,
                status=AgentStatus.SKIPPED, confidence=0.0,
                warnings=[f"{self.name}: no location was resolved, nothing to retrieve"])

        targets: list[datetime] = []
        if ctx.analysis_windows:
            targets = [w.target for w in ctx.analysis_windows]
        elif ctx.time is not None:
            targets = [ctx.time.target]

        providers = self.deps.registry.for_variables(list(self.variables))
        if self.allowed_sources:
            providers = [p for p in providers if p.source.value in self.allowed_sources]
        if not providers:
            return AgentResponse(
                agent=self.name, capability=self.capability,
                status=AgentStatus.FAILED, confidence=0.0,
                warnings=[f"{self.name}: no provider can serve {self.variables[0]} "
                          "in this deployment"])

        specs = []
        for target in targets or [None]:
            for provider in providers:
                supported = provider.supports(list(self.variables))
                if not supported:
                    continue
                specs.append((provider, ProviderQuery(
                    point=point, variables=supported, valid_time=target,
                    extras=dict(self.provider_extras or {}))))

        results = await self.deps.registry.fetch_many(specs, trace)

        evidence = []
        reports = []
        warnings: list[str] = []
        unavailable: list[str] = []
        for result in results:
            reports.append(source_report(result))
            if result.ok:
                evidence.extend(from_provider_result(result, self.name))
                if result.status is SourceStatus.DEGRADED and result.error:
                    warnings.append(f"{result.source.value}: {result.error}")
            else:
                unavailable.append(result.source.value)
                warnings.append(
                    f"{result.source.value} unavailable ({result.status.value})"
                    + (f": {result.error}" if result.error else ""))

        fused, conflicts = fuse(evidence)
        usable = {k: v for k, v in fused.items() if k in self.variables}

        if not usable:
            return AgentResponse(
                agent=self.name, capability=self.capability,
                status=AgentStatus.FAILED, confidence=0.0, evidence=evidence,
                warnings=warnings or [f"{self.name}: no usable values retrieved"],
                source_status={r.source.value: r.status for r in reports},
                data={"sources": [r.model_dump(mode="json") for r in reports],
                      "unavailable": unavailable})

        freshnesses = [e.freshness for e in evidence]
        worst = Freshness.FRESH
        order = [Freshness.FRESH, Freshness.AGING, Freshness.STALE, Freshness.UNAVAILABLE]
        for f in freshnesses:
            if order.index(f) > order.index(worst):
                worst = f

        partial = bool(unavailable) or len(usable) < len(self.variables)
        confidence = max(0.2, 1.0 - 0.15 * len(unavailable)
                         - sum(c.confidence_penalty for c in conflicts))

        by_window = {}
        if ctx.analysis_windows:
            by_window = _group_by_window(evidence, ctx.analysis_windows)

        return AgentResponse(
            agent=self.name, capability=self.capability,
            status=AgentStatus.PARTIAL if partial else AgentStatus.OK,
            data={
                "values": {k: {"value": v.value, "unit": v.unit,
                               "source": v.source.value, "provider": v.provider,
                               "evidence_id": v.evidence_id}
                           for k, v in usable.items()},
                "conflicts": [c.model_dump(mode="json") for c in conflicts],
                "sources": [r.model_dump(mode="json") for r in reports],
                "unavailable": unavailable,
                "worst_freshness": worst.value,
                "windows": by_window,
            },
            evidence=evidence, warnings=warnings, confidence=round(confidence, 3),
            source_status={r.source.value: r.status for r in reports})


def _group_by_window(evidence, windows) -> dict:
    """Values per requested comparison window (used by analytical queries)."""
    out: dict[str, dict] = {}
    for w in windows:
        key = w.target.isoformat()
        subset = [e for e in evidence
                  if (e.forecast_time or e.observation_time) == w.target]
        fused, _ = fuse(subset)
        out[key] = {k: {"value": v.value, "unit": v.unit, "source": v.source.value}
                    for k, v in fused.items()}
    return out
