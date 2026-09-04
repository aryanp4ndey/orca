"""Hazard / Alert Agent.

Collects every warning in force for the point: authority advisories from the
atmospheric and ocean sources, plus zone-based hazards from the boundary layers.

Note on cost: this agent asks the same providers, for the same variables, at the
same instant as the weather and ocean agents.  Because the registry quantises
cache keys and collapses identical in-flight requests, that costs zero extra
network calls - the three agents share one upstream response each.  Hazard
checking is therefore free in latency terms, which is why it is *required* for
every safety query rather than optional.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.data_agent import OCEAN_VARIABLES, WEATHER_VARIABLES
from app.geo.layers import zones_near
from app.observability.trace import Trace
from app.reasoning.evidence_builder import from_provider_result, source_report
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability
from app.schemas.marine import ProviderQuery

SEVERITY_ORDER = ["none", "watch", "advisory", "warning", "severe"]


class HazardAgent(BaseAgent):
    name = "hazard_agent"
    capability = Capability.HAZARD
    responsibility = (
        "Surface every warning in force for the location: cyclone, squall, "
        "thunderstorm, high-wave and swell-surge advisories from the authorities, "
        "plus restricted and closure zones from the boundary layers")
    consumes = ("resolved marine point", "valid time")
    produces = ("advisories", "max_severity", "hazard_zones")
    sources = ("IMD", "INCOIS", "ORCA boundary layers")
    failure_behaviour = (
        "If an authority cannot be reached, ORCA states that warnings could not be "
        "checked. Absence of a retrieved warning is never reported as 'no warning'")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        point = request.point or (ctx.location.point if ctx.location else None)
        if point is None:
            return AgentResponse(agent=self.name, capability=self.capability,
                                 status=AgentStatus.SKIPPED, confidence=0.0,
                                 warnings=["no location resolved"])

        valid = ctx.time.target if ctx.time else None
        specs = []
        for provider in self.deps.registry.providers:
            if not provider.capability.supports_advisories:
                continue
            # Use the same variable list the data agents use, so the request
            # deduplicates against theirs instead of costing another call.
            pool = (WEATHER_VARIABLES if provider.source.value == "IMD"
                    else OCEAN_VARIABLES)
            supported = provider.supports(list(pool))
            if supported:
                specs.append((provider, ProviderQuery(
                    point=point, variables=supported, valid_time=valid)))

        results = await self.deps.registry.fetch_many(specs, trace)

        advisories, evidence, reports, warnings = [], [], [], []
        checked_sources, failed_sources = [], []
        for result in results:
            reports.append(source_report(result))
            if result.ok:
                checked_sources.append(result.source.value)
                advisories.extend(a.model_dump(mode="json") for a in result.advisories)
                evidence.extend(e for e in from_provider_result(result, self.name)
                                if e.variable.startswith("advisory:"))
            else:
                failed_sources.append(result.source.value)
                warnings.append(
                    f"Warnings could not be checked with {result.source.value} "
                    f"({result.status.value}). Absence of a warning here does not "
                    "mean none is in force.")

        zones = [z for z in zones_near(point, 80.0)
                 if z.category in ("restricted", "fishing_ban")]

        severities = [a.get("severity", "none") for a in advisories]
        max_severity = max(severities, key=lambda s: SEVERITY_ORDER.index(s)
                           if s in SEVERITY_ORDER else 0) if severities else "none"

        status = AgentStatus.OK
        if failed_sources and checked_sources:
            status = AgentStatus.PARTIAL
        elif failed_sources and not checked_sources:
            status = AgentStatus.FAILED

        return AgentResponse(
            agent=self.name, capability=self.capability, status=status,
            data={
                "advisories": advisories,
                "max_severity": max_severity,
                "headlines": [a["headline"] for a in advisories],
                "hazard_zones": [z.model_dump(mode="json") for z in zones],
                "sources_checked": checked_sources,
                "sources_unavailable": failed_sources,
                "sources": [r.model_dump(mode="json") for r in reports],
            },
            evidence=evidence, warnings=warnings,
            confidence=0.9 if not failed_sources else 0.6,
            source_status={r.source.value: r.status for r in reports})
