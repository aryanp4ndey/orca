"""Direct capability endpoints.

``/api/v1/query`` is the conversational door. These are the structured doors,
for a map screen or a widget that wants one thing and does not want to phrase a
sentence to get it. They reuse exactly the same agents, providers, evidence and
risk engine - there is no second pipeline to keep in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.core.clock import utcnow
from app.geo.gazetteer import get_gazetteer
from app.geo.layers import maritime_band
from app.observability.trace import Trace
from app.schemas.agent import AgentRequest, QueryContext, TimeSpec
from app.schemas.api import (
    MarineStatusResponse,
    RouteRiskRequest,
    RouteRiskResponse,
)
from app.schemas.common import Activity, Capability, Intent, Language, VesselClass
from app.schemas.evidence import SourceReport
from app.schemas.geo import GeoPoint, ResolvedLocation
from app.schemas.risk import RiskAssessment
from app.services.container import Container
from app.services.query_service import QueryService


def _resolve(place: str | None, lat: float | None, lon: float | None
             ) -> ResolvedLocation | None:
    gz = get_gazetteer()
    if place:
        found = gz.find(place) or (gz.search_in_text(place) or [None])[0]
        if found:
            return gz.to_resolved(found, place)
    if lat is not None and lon is not None:
        point = GeoPoint(lat=lat, lon=lon)
        nearest = gz.nearest(point, limit=1)
        _, band_label, coast_km = maritime_band(point)
        return ResolvedLocation(
            query=f"{lat},{lon}",
            name=(f"{nearest[0][1]:.0f} km from {nearest[0][0].name}"
                  if nearest else f"{lat:.3f},{lon:.3f}"),
            point=point, kind="coordinates",
            state=nearest[0][0].state if nearest else None, is_marine_point=True,
            distance_to_coast_km=round(coast_km, 2), resolver="coordinates",
            confidence=1.0, source_dataset="client-supplied coordinates")
    return None


def _context(location: ResolvedLocation, intent: Intent, activity: str, vessel: str,
             when: datetime | None, query: str) -> QueryContext:
    from datetime import timedelta
    target = when or utcnow()
    return QueryContext(
        query_id="q_" + uuid.uuid4().hex[:12], raw_query=query,
        language=Language.EN, intent=intent, intent_confidence=1.0,
        activity=Activity(activity), vessel=VesselClass(vessel), location=location,
        time=TimeSpec(target=target, window_start=target - timedelta(minutes=30),
                      window_end=target + timedelta(hours=3), is_explicit=when is not None,
                      resolver="api"),
        created_at=utcnow())


class MarineService:
    def __init__(self, container: Container) -> None:
        self.c = container

    async def marine_status(self, place: str | None, lat: float | None, lon: float | None,
                            when: datetime | None, activity: str, vessel: str
                            ) -> MarineStatusResponse | None:
        location = _resolve(place, lat, lon)
        if location is None:
            return None
        ctx = _context(location, Intent.MARINE_SAFETY, activity, vessel, when,
                       f"marine status for {place or f'{lat},{lon}'}")
        trace = Trace(query_id=ctx.query_id)
        from app.agents.planner.routing import steps_for
        from app.schemas.agent import ExecutionPlan, PlanStep
        plan = ExecutionPlan(
            query_id=ctx.query_id, intent=Intent.MARINE_SAFETY,
            steps=[PlanStep(capability=s.capability, required=s.required,
                            depends_on=list(s.depends_on), reason=s.reason,
                            deadline_ms=s.deadline_ms)
                   for s in steps_for(Intent.MARINE_SAFETY)
                   if s.capability is not Capability.RESPONSE],
            total_budget_ms=self.c.settings.budget_total_ms)
        results = await self.c.orchestrator.execute(ctx, plan, trace)

        weather = (results.get(Capability.WEATHER).data if results.get(Capability.WEATHER) else {}) or {}
        ocean = (results.get(Capability.OCEAN).data if results.get(Capability.OCEAN) else {}) or {}
        risk_data = (results.get(Capability.RISK).data if results.get(Capability.RISK) else {}) or {}
        risk = (RiskAssessment.model_validate(risk_data["assessment"])
                if risk_data.get("assessment") else None)

        sources: dict[str, SourceReport] = {}
        evidence = []
        for response in results.values():
            evidence.extend(response.evidence)
            for raw in (response.data or {}).get("sources", []) or []:
                report = SourceReport.model_validate(raw)
                sources[f"{report.source.value}:{report.provider}"] = report

        service = QueryService(self.c)
        return MarineStatusResponse(
            location=location.model_dump(mode="json"), point=location.point,
            valid_time=ctx.time.target,
            weather=weather.get("values", {}), ocean=ocean.get("values", {}),
            risk=risk, sources=list(sources.values()),
            freshness=service._freshness_summary(evidence, sources),
            latency=service._latency(trace))

    async def route_risk(self, request: RouteRiskRequest) -> RouteRiskResponse:
        gz = get_gazetteer()
        start_near = gz.nearest(request.start, 1)
        end_near = gz.nearest(request.end, 1)
        start = ResolvedLocation(
            query="start", name=start_near[0][0].name if start_near else "start",
            point=request.start, kind="coordinates", resolver="coordinates",
            confidence=1.0, source_dataset="client-supplied coordinates")
        end = ResolvedLocation(
            query="end", name=end_near[0][0].name if end_near else "destination",
            point=request.end, kind="coordinates", resolver="coordinates",
            confidence=1.0, source_dataset="client-supplied coordinates")

        ctx = _context(start, Intent.ROUTE_RISK, request.activity, request.vessel,
                       request.depart_at, "route risk")
        ctx.destination = end
        trace = Trace(query_id=ctx.query_id)

        route_agent = self.c.agents[Capability.ROUTE]
        agent_request = AgentRequest(
            request_id=ctx.query_id, capability=Capability.ROUTE, context=ctx,
            point=request.start, deadline_ms=self.c.settings.budget_agent_ms,
            options={"samples": request.samples, "speed_knots": request.speed_knots})
        route_response = await route_agent.execute(agent_request, trace)
        data = route_response.data or {}

        # The overall passage verdict is the worst segment's assessment, computed
        # by the agent from that segment's own evidence. Re-fusing every sample
        # point together would read normal spatial variation along a 360 km
        # corridor as sources disagreeing, and withhold the advisory for it.
        overall_raw = data.get("overall_assessment")
        if overall_raw:
            overall = RiskAssessment.model_validate(overall_raw)
        else:
            from app.safety.risk_engine import RiskInputs, assess
            overall = assess(RiskInputs(
                activity=request.activity, vessel=request.vessel, values={},
                evidence=[]))

        service = QueryService(self.c)
        return RouteRiskResponse(
            query_id=ctx.query_id, start=request.start, end=request.end,
            total_distance_km=data.get("total_distance_km", 0.0),
            estimated_duration_hours=data.get("duration_hours", 0.0),
            overall_risk=overall, segments=data.get("segments", []),
            hazardous_segments=data.get("hazardous_segments", []),
            geojson=data.get("geojson", {}), warnings=route_response.warnings,
            sources=[], latency=service._latency(trace),
            disclaimer=("Straight-line passage annotated with marine risk. Not a "
                        "navigational route and not a substitute for official charts, "
                        "notices to mariners or a certified navigation system."))
