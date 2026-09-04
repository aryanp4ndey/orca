"""Fisheries / Potential Fishing Zone Agent.

A PFZ answer is only useful with four things attached: where it is (bearing and
distance from a named landing centre), how long it is valid, what it was derived
from, and whether the sea between here and there is survivable.  This agent
produces the first three and defers the fourth to the ocean agent and the risk
engine - which is why the PFZ route in the planner includes both.

Coordinates are never invented: distance and bearing are computed by the
deterministic geodesy module from the advisory the provider actually returned.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.clock import utcnow
from app.geo.gazetteer import get_gazetteer
from app.geo.geodesy import compass_point, distance_km, distance_nm, initial_bearing_deg
from app.observability.trace import Trace
from app.reasoning.evidence_builder import computed_evidence, source_report
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability, DataOrigin, Freshness
from app.schemas.evidence import Evidence
from app.schemas.marine import ProviderQuery


class PFZAgent(BaseAgent):
    name = "pfz_agent"
    capability = Capability.PFZ
    responsibility = (
        "Find the applicable Potential Fishing Zone advisories, compute bearing "
        "and distance from the user's landing centre, and report validity and basis")
    consumes = ("resolved marine point", "date")
    produces = ("pfz advisories", "nearest zone", "distance/bearing", "validity")
    sources = ("INCOIS",)
    failure_behaviour = (
        "If no PFZ advisory is retrievable, ORCA says none was available for that "
        "date and area. It never synthesises coordinates")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        point = request.point or (ctx.location.point if ctx.location else None)
        if point is None:
            return AgentResponse(agent=self.name, capability=self.capability,
                                 status=AgentStatus.SKIPPED, confidence=0.0,
                                 warnings=["no location resolved"])

        providers = [p for p in self.deps.registry.providers
                     if p.capability.supports_pfz]
        if not providers:
            return AgentResponse(
                agent=self.name, capability=self.capability,
                status=AgentStatus.FAILED, confidence=0.0,
                warnings=["No PFZ-capable source is configured in this deployment. "
                          "INCOIS is the authority for PFZ advisories."],
                error="no_pfz_provider")

        specs = [(p, ProviderQuery(point=point, variables=[],
                                   valid_time=ctx.time.target if ctx.time else None,
                                   extras={"want_pfz": True})) for p in providers]
        results = await self.deps.registry.fetch_many(specs, trace)

        zones, evidence, reports, warnings = [], [], [], []
        now = utcnow()
        for result in results:
            reports.append(source_report(result))
            if not result.ok:
                warnings.append(f"{result.source.value} PFZ unavailable "
                                f"({result.status.value})")
                continue
            for advisory in result.pfz:
                bearing = initial_bearing_deg(point, advisory.centroid)
                d_km = distance_km(point, advisory.centroid, precise=True)
                expired = advisory.valid_to < now
                zones.append({
                    "advisory_id": advisory.advisory_id,
                    "centroid": advisory.centroid.model_dump(),
                    "geometry": advisory.geometry.model_dump() if advisory.geometry else None,
                    "distance_km": round(d_km, 2),
                    "distance_nm": round(distance_nm(point, advisory.centroid, True), 2),
                    "bearing_deg": round(bearing, 1),
                    "compass": compass_point(bearing),
                    "landing_centre": advisory.landing_centre,
                    "bearing_from_landing_deg": advisory.bearing_from_landing_deg,
                    "distance_from_landing_km": advisory.distance_from_landing_km,
                    "depth_m": advisory.depth_m,
                    "valid_from": advisory.valid_from.isoformat(),
                    "valid_to": advisory.valid_to.isoformat(),
                    "expired": expired,
                    "basis": advisory.basis,
                    "source": result.source.value,
                    "origin": result.origin.value,
                    "dataset": advisory.dataset,
                })
                evidence.append(Evidence(
                    evidence_id=f"ev_pfz_{advisory.advisory_id}",
                    source=result.source, provider=result.provider_id,
                    dataset=advisory.dataset or result.dataset,
                    variable="pfz_advisory", value=advisory.advisory_id, unit=None,
                    kind="ADVISORY", origin=result.origin, location=advisory.centroid,
                    issued_at=advisory.issued_at, retrieved_at=result.retrieved_at or now,
                    age_seconds=(now - advisory.issued_at).total_seconds(),
                    freshness=Freshness.STALE if expired else result.freshness,
                    agent=self.name,
                    notes=(f"valid {advisory.valid_from.isoformat()} to "
                           f"{advisory.valid_to.isoformat()}"),
                ))
                evidence.append(computed_evidence(
                    "pfz_distance_km", round(d_km, 2), "km", self.name,
                    transformation="Vincenty inverse from the user's point to the advisory centroid",
                    location=point))

        zones.sort(key=lambda z: z["distance_km"])
        active = [z for z in zones if not z["expired"]]
        if zones and not active:
            warnings.append("All retrieved PFZ advisories have expired for this date.")
        if not zones:
            warnings.append("No PFZ advisory was available for this location and date.")

        return AgentResponse(
            agent=self.name, capability=self.capability,
            status=AgentStatus.OK if active else AgentStatus.PARTIAL,
            data={"zones": zones, "active": active,
                  "nearest": active[0] if active else None,
                  "sources": [r.model_dump(mode="json") for r in reports]},
            evidence=evidence, warnings=warnings,
            confidence=0.85 if active else 0.4,
            source_status={r.source.value: r.status for r in reports})
