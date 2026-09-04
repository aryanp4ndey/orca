"""Route Optimisation / Passage Risk Agent.

Scope, stated plainly: this is **risk annotation of a straight-line passage**,
not route optimisation and not a navigation system.  It samples the great-circle
corridor between two points, retrieves conditions at each sample in parallel,
scores each segment with the same deterministic risk engine, and reports which
segments are the problem.

It does not do obstacle avoidance, does not know about depth, traffic separation
schemes or notices to mariners, and must not be presented as a route planner.
The abstraction is built so a real routing engine can replace the sampling step
without changing anything downstream.
"""

from __future__ import annotations

from datetime import timedelta

from app.agents.base import BaseAgent
from app.agents.data_agent import OCEAN_VARIABLES, WEATHER_VARIABLES
from app.core.clock import utcnow
from app.geo.geodesy import compass_point, densify, distance_km, initial_bearing_deg
from app.geo.layers import zones_near
from app.observability.trace import Trace
from app.reasoning.evidence_builder import from_provider_result
from app.reasoning.fusion import fuse
from app.safety.risk_engine import RiskInputs, assess
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability, Freshness, RiskLevel
from app.schemas.marine import ProviderQuery

KNOTS_TO_KMH = 1.852


class RouteAgent(BaseAgent):
    name = "route_agent"
    capability = Capability.ROUTE
    responsibility = (
        "Sample a passage corridor, retrieve conditions along it in parallel, and "
        "score each segment so hazardous stretches can be identified")
    consumes = ("start point", "destination point", "departure time", "speed")
    produces = ("segments", "per-segment risk", "hazardous segments", "route geojson")
    sources = ("IMD", "INCOIS", "ORCA boundary layers")
    optional = True
    failure_behaviour = (
        "Falls back to whichever samples returned data and marks the rest as "
        "unassessed; never reports a corridor as clear when it could not be checked")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        if ctx.location is None or ctx.destination is None:
            return AgentResponse(agent=self.name, capability=self.capability,
                                 status=AgentStatus.SKIPPED, confidence=0.0,
                                 warnings=["route scoring needs a start and a destination"])

        start = ctx.location.point
        end = ctx.destination.point
        samples = int(request.options.get("samples", 7))
        speed_kmh = float(request.options.get("speed_knots", 8.0)) * KNOTS_TO_KMH
        depart = ctx.time.target if ctx.time else utcnow()

        total_km = distance_km(start, end, precise=True)
        points = densify(start, end, samples)
        duration_h = total_km / max(1e-6, speed_kmh)

        specs = []
        sample_times = []
        for i, p in enumerate(points):
            leg_fraction = i / max(1, len(points) - 1)
            when = depart + timedelta(hours=duration_h * leg_fraction)
            sample_times.append(when)
            for provider in self.deps.registry.providers:
                supported = provider.supports(list(WEATHER_VARIABLES + OCEAN_VARIABLES))
                if supported:
                    specs.append((provider, ProviderQuery(
                        point=p, variables=supported, valid_time=when)))

        with trace.span("route_sampling", "compute", samples=len(points)):
            results = await self.deps.registry.fetch_many(specs, trace)

        # Regroup results by sample point.
        per_point: dict[str, list] = {}
        for (provider, query), result in zip(specs, results):
            key = f"{query.point.lat:.4f},{query.point.lon:.4f}"
            per_point.setdefault(key, []).append(result)

        segments = []
        hazardous = []
        all_evidence = []
        worst = RiskLevel.LOW
        # A passage is as risky as its worst stretch, so the overall verdict is
        # the worst segment's assessment - NOT a fusion across the whole
        # corridor. Fusing there would treat ordinary spatial variation (calmer
        # at one end than the other) as sources disagreeing, and gate the
        # advisory for no good reason.
        worst_assessment = None
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            key = f"{b.lat:.4f},{b.lon:.4f}"
            results_here = per_point.get(key, [])
            evidence = []
            for r in results_here:
                if r.ok:
                    evidence.extend(from_provider_result(r, self.name))
            all_evidence.extend(evidence)
            fused, conflicts = fuse(evidence)
            zones = [z for z in zones_near(b, 25.0)
                     if z.category in ("restricted", "fishing_ban")]

            if fused:
                assessment = assess(RiskInputs(
                    activity=ctx.activity.value, vessel=ctx.vessel.value,
                    values=fused, evidence=evidence, conflicts=conflicts,
                    worst_freshness=Freshness.FRESH))
                level = assessment.risk_level
                score = assessment.risk_score
                top = assessment.factors[0].label if assessment.factors else None
            else:
                assessment = None
                level, score, top = RiskLevel.INSUFFICIENT_DATA, 0.0, None

            if level.rank > worst.rank:
                worst = level
                worst_assessment = assessment
            if level in (RiskLevel.HIGH, RiskLevel.CRITICAL) or zones:
                hazardous.append(i)

            bearing = initial_bearing_deg(a, b)
            segments.append({
                "index": i,
                "start": a.model_dump(), "end": b.model_dump(),
                "length_km": round(distance_km(a, b), 2),
                "bearing_deg": round(bearing, 1), "compass": compass_point(bearing),
                "eta": sample_times[i + 1].isoformat(),
                "risk_level": level.value, "risk_score": score,
                "dominant_factor": top,
                "values": {k: {"value": v.value, "unit": v.unit,
                               "source": v.source.value} for k, v in fused.items()},
                "zones": [z.model_dump(mode="json") for z in zones],
            })

        geojson = {
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[p.lon, p.lat] for p in points]},
            "properties": {"total_distance_km": round(total_km, 2),
                           "duration_hours": round(duration_h, 2),
                           "worst_segment_risk": worst.value},
        }

        warnings = [
            "This is a straight-line passage annotated with marine risk. It is not "
            "a navigational route: it does not account for depth, traffic "
            "separation, notices to mariners or obstacles."]
        if hazardous:
            warnings.append(
                f"{len(hazardous)} of {len(segments)} segments are high risk or "
                "cross a caution area.")

        return AgentResponse(
            agent=self.name, capability=self.capability, status=AgentStatus.OK,
            data={"segments": segments, "hazardous_segments": hazardous,
                  "total_distance_km": round(total_km, 2),
                  "duration_hours": round(duration_h, 2),
                  "worst_segment_risk": worst.value, "geojson": geojson,
                  "overall_assessment": (worst_assessment.model_dump(mode="json")
                                         if worst_assessment is not None else None)},
            evidence=all_evidence, warnings=warnings,
            confidence=0.75 if segments else 0.2,
            source_status={"ROUTE": "OK"})
