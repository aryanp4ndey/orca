"""The end-to-end query pipeline.

    natural language
        -> NLU (deterministic, ~0.5 ms)
        -> conversation context
        -> planner: intent -> capability DAG
        -> orchestrator: parallel waves of specialist agents
        -> providers (cached, deduplicated, timeout-bounded)
        -> evidence ledger + freshness + conflict resolution
        -> deterministic risk engine
        -> grounded explanation in the user's language
        -> structured response + trace

Every stage is timed and every stage appears in the trace.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.clock import utcnow
from app.observability.logging import get_logger, request_id_var
from app.observability.trace import Trace
from app.reasoning.context import Turn
from app.schemas.agent import AgentResponse, QueryContext
from app.schemas.api import (
    FreshnessSummary,
    LatencyBreakdown,
    MapLayerOut,
    QueryRequest,
    QueryResponse,
    Visualizations,
)
from app.schemas.common import (
    AgentStatus,
    Capability,
    DataOrigin,
    Freshness,
    Intent,
    RiskLevel,
)
from app.schemas.evidence import Conflict, Evidence, SourceReport
from app.schemas.risk import RiskAssessment
from app.services.container import Container

log = get_logger("orca.query")

FRESHNESS_ORDER = [Freshness.FRESH, Freshness.AGING, Freshness.STALE, Freshness.UNAVAILABLE]


class QueryService:
    def __init__(self, container: Container) -> None:
        self.c = container

    async def handle(self, request: QueryRequest) -> QueryResponse:
        query_id = "q_" + uuid.uuid4().hex[:12]
        session_id = request.session_id or ("s_" + uuid.uuid4().hex[:10])
        request_id_var.set(query_id)
        trace = Trace(query_id=query_id)
        now = utcnow()

        session = self.c.sessions.get(session_id)
        ctx, plan = await self.c.planner.plan(request, session, trace, now=now)
        results = await self.c.orchestrator.execute(ctx, plan, trace)

        response = self._assemble(request, ctx, results, trace, session_id, query_id)
        self.c.sessions.append(session_id, Turn(
            query_id=query_id, raw_query=request.query, intent=ctx.intent,
            location=ctx.location, destination=ctx.destination,
            activity=ctx.activity, vessel=ctx.vessel, language=ctx.language,
            time=ctx.time, answer_summary=response.answer[:200],
            risk_level=response.risk.risk_level.value if response.risk else None))
        return response

    # ------------------------------------------------------------------
    def _assemble(self, request: QueryRequest, ctx: QueryContext,
                  results: dict[Capability, AgentResponse], trace: Trace,
                  session_id: str, query_id: str) -> QueryResponse:
        evidence: list[Evidence] = []
        sources: dict[str, SourceReport] = {}
        conflicts: list[Conflict] = []
        warnings: list[str] = []

        # Two agents legitimately consult the same provider for the same values -
        # the hazard agent shares the weather agent's IMD response, which is what
        # makes hazard checking free. Their evidence rows are therefore identical,
        # and the ledger must carry each fact once: a duplicated row would make
        # the evidence panel look padded and would double-count in the UI.
        seen_evidence: set[str] = set()
        seen_conflicts: set[str] = set()

        for capability, response in results.items():
            for row in response.evidence:
                if row.evidence_id in seen_evidence:
                    continue
                seen_evidence.add(row.evidence_id)
                evidence.append(row)
            warnings.extend(response.warnings)
            for raw in (response.data or {}).get("sources", []) or []:
                report = SourceReport.model_validate(raw)
                key = f"{report.source.value}:{report.provider}"
                existing = sources.get(key)
                if existing is None or (report.latency_ms or 0) > (existing.latency_ms or 0):
                    sources[key] = report
            for raw in (response.data or {}).get("conflicts", []) or []:
                conflict = Conflict.model_validate(raw)
                key = f"{conflict.variable}:{conflict.severity}:{conflict.spread}"
                if key in seen_conflicts:
                    continue
                seen_conflicts.add(key)
                conflicts.append(conflict)

        risk_data = (results.get(Capability.RISK).data
                     if results.get(Capability.RISK) else None) or {}
        risk = (RiskAssessment.model_validate(risk_data["assessment"])
                if risk_data.get("assessment") else None)

        response_data = (results.get(Capability.RESPONSE).data
                         if results.get(Capability.RESPONSE) else None) or {}
        answer = response_data.get("answer", "")
        factors = response_data.get("factors", [])

        origin = self._origin(evidence)
        freshness = self._freshness_summary(evidence, sources)
        confidence = self._confidence(risk, results)

        visualizations = (Visualizations() if request.low_bandwidth
                          else self._visualizations(ctx, results))
        if request.low_bandwidth:
            visualizations.cards = self._cards(ctx, risk, sources)

        include_trace = (request.include_trace
                         if request.include_trace is not None
                         else self.c.settings.expose_trace_in_response)

        return QueryResponse(
            query_id=query_id, session_id=session_id, answer=answer,
            answer_language=ctx.language, data_origin=origin,
            demo_mode=self.c.settings.demo_mode,
            intent={"value": ctx.intent.value, "confidence": ctx.intent_confidence,
                    "resolver": ctx.nlu_resolver,
                    "inherited": ctx.inherited_fields,
                    "scores": ctx.constraints.get("intent_scores", {})},
            location=(ctx.location.model_dump(mode="json") if ctx.location else None),
            time=(ctx.time.model_dump(mode="json") if ctx.time else None),
            activity=ctx.activity.value, risk=risk, factors=factors,
            evidence=evidence, sources=list(sources.values()), conflicts=conflicts,
            warnings=_dedupe(warnings), confidence=confidence, freshness=freshness,
            visualizations=visualizations,
            latency=self._latency(trace),
            trace=trace.to_schema() if include_trace else None,
            disclaimer=response_data.get("disclaimer", ""),
            generated_at=utcnow(),
            follow_up_suggestions=response_data.get("follow_up_suggestions", []),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _origin(evidence: list[Evidence]) -> DataOrigin:
        origins = {e.origin for e in evidence}
        origins.discard(DataOrigin.COMPUTED)
        if not origins:
            return DataOrigin.COMPUTED
        if origins == {DataOrigin.DEMO}:
            return DataOrigin.DEMO
        if DataOrigin.DEMO in origins:
            return DataOrigin.MIXED
        if origins == {DataOrigin.CACHED_LIVE}:
            return DataOrigin.CACHED_LIVE
        return DataOrigin.LIVE

    @staticmethod
    def _freshness_summary(evidence: list[Evidence],
                           sources: dict[str, SourceReport]) -> FreshnessSummary:
        # Rows with no value carry freshness UNAVAILABLE by construction (a
        # cloud-blocked chlorophyll retrieval, say). Letting those dominate would
        # report a perfectly current answer as UNAVAILABLE, so the overall verdict
        # is taken over the evidence that actually carries a value; the missing
        # ones are reported separately as unavailable sources.
        used = [e for e in evidence if e.value is not None]
        if not used:
            return FreshnessSummary(overall=Freshness.UNAVAILABLE)
        overall = Freshness.FRESH
        for e in used:
            if FRESHNESS_ORDER.index(e.freshness) > FRESHNESS_ORDER.index(overall):
                overall = e.freshness
        ages = [e.age_seconds for e in used if e.age_seconds != float("inf")]
        per_source = {r.source.value: r.freshness.value for r in sources.values()}
        stale = [s for s, f in per_source.items() if f in ("STALE", "UNAVAILABLE")]
        return FreshnessSummary(
            overall=overall,
            oldest_evidence_age_seconds=round(max(ages), 1) if ages else None,
            per_source=per_source, stale_sources=stale)

    @staticmethod
    def _confidence(risk: RiskAssessment | None,
                    results: dict[Capability, AgentResponse]) -> float:
        if risk is not None:
            return risk.confidence
        values = [r.confidence for r in results.values()
                  if r.status in (AgentStatus.OK, AgentStatus.PARTIAL)]
        return round(sum(values) / len(values), 3) if values else 0.0

    @staticmethod
    def _latency(trace: Trace) -> LatencyBreakdown:
        provider_sum = trace.sum_kind("provider")
        provider_wall = trace.wall_clock_of_kind("provider")
        return LatencyBreakdown(
            total_ms=round(trace.total_ms(), 2),
            nlu_ms=round(sum(s.duration_ms for s in trace.spans if s.name == "nlu"), 2),
            planning_ms=round(trace.sum_kind("reasoning"), 2),
            agents_ms=round(trace.wall_clock_of_kind("agent"), 2),
            providers_ms=round(provider_wall, 2),
            risk_ms=round(sum(s.duration_ms for s in trace.spans
                              if s.name in ("risk_engine", "risk_fuse")), 2),
            response_ms=round(sum(s.duration_ms for s in trace.spans
                                  if s.name == "response_agent"), 2),
            per_agent_ms=trace.per_name("agent"),
            per_provider_ms=trace.per_name("provider"),
            parallel_saving_ms=round(max(0.0, provider_sum - provider_wall), 2),
            llm_ms=round(trace.sum_kind("llm"), 2),
        )

    def _cards(self, ctx: QueryContext, risk: RiskAssessment | None,
               sources: dict[str, SourceReport]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        if risk is not None:
            cards.append({
                "kind": "risk", "level": risk.risk_level.value,
                "score": risk.risk_score, "confidence": risk.confidence,
                "decision": risk.decision_status.value,
                "dominant_factor": risk.dominant_factor,
                "activity": risk.activity, "ruleset": f"{risk.ruleset_id}@{risk.ruleset_version}",
            })
        for report in sources.values():
            cards.append({
                "kind": "source", "source": report.source.value,
                "provider": report.provider, "origin": report.origin.value,
                "status": report.status, "freshness": report.freshness.value,
                "latency_ms": report.latency_ms, "cache_hit": report.cache_hit,
                "retrieved_at": report.retrieved_at.isoformat() if report.retrieved_at else None,
                "attribution": report.attribution,
            })
        return cards

    def _visualizations(self, ctx: QueryContext,
                        results: dict[Capability, AgentResponse]) -> Visualizations:
        viz = Visualizations()
        risk_response = results.get(Capability.RISK)
        risk = None
        if risk_response and risk_response.data.get("assessment"):
            risk = RiskAssessment.model_validate(risk_response.data["assessment"])

        geo = (results.get(Capability.GEOSPATIAL).data
               if results.get(Capability.GEOSPATIAL) else {}) or {}
        if geo.get("point"):
            viz.markers.append({
                "id": "query_point", "kind": "query",
                "lat": geo["point"]["lat"], "lon": geo["point"]["lon"],
                "label": ctx.location.name if ctx.location else "query point",
                "risk_level": risk.risk_level.value if risk else None,
            })
        for zone in geo.get("zones", [])[:12]:
            viz.layers.append(MapLayerOut(
                layer_id=zone["zone_id"], name=zone["zone_name"], kind="polygon",
                geojson={"type": "Feature",
                         "geometry": _zone_geometry(zone),
                         "properties": {"category": zone["category"],
                                        "relation": zone["relation"],
                                        "distance_km": zone["distance_km"],
                                        "authoritative": zone["authoritative"]}},
                style_hint=zone["category"], source=zone["layer_id"]))

        pfz = (results.get(Capability.PFZ).data
               if results.get(Capability.PFZ) else {}) or {}
        for zone in pfz.get("active", [])[:5]:
            viz.markers.append({
                "id": zone["advisory_id"], "kind": "pfz",
                "lat": zone["centroid"]["lat"], "lon": zone["centroid"]["lon"],
                "label": f"PFZ {zone['distance_km']} km {zone['compass']}",
                "valid_to": zone["valid_to"]})
            if zone.get("geometry"):
                viz.layers.append(MapLayerOut(
                    layer_id=zone["advisory_id"], name="Potential fishing zone",
                    kind="polygon",
                    geojson={"type": "Feature", "geometry": zone["geometry"],
                             "properties": {"valid_to": zone["valid_to"],
                                            "basis": zone["basis"],
                                            "source": zone["source"]}},
                    style_hint="pfz", source=zone.get("dataset")))

        route = (results.get(Capability.ROUTE).data
                 if results.get(Capability.ROUTE) else {}) or {}
        if route.get("geojson"):
            viz.layers.append(MapLayerOut(
                layer_id="route", name="Passage corridor", kind="line",
                geojson=route["geojson"], style_hint="route", source="ORCA"))

        if risk is not None:
            viz.charts.append({
                "id": "risk_factors", "kind": "bar",
                "title": "Risk factor contributions",
                "series": [{"label": f.label, "value": f.contribution,
                            "level": f.level.value, "measured": f.value,
                            "unit": f.unit, "threshold": f.threshold}
                           for f in risk.factors]})

        evidence_rows = [e for r in results.values() for e in r.evidence]
        viz.timeline = sorted(
            [{"evidence_id": e.evidence_id, "source": e.source.value,
              "variable": e.variable, "value": e.value, "unit": e.unit,
              "issued_at": e.issued_at.isoformat() if e.issued_at else None,
              "valid_time": (e.forecast_time or e.observation_time).isoformat()
              if (e.forecast_time or e.observation_time) else None,
              "retrieved_at": e.retrieved_at.isoformat(),
              "freshness": e.freshness.value}
             for e in evidence_rows],
            key=lambda r: r["retrieved_at"])

        sources_map: dict[str, SourceReport] = {}
        for response in results.values():
            for raw in (response.data or {}).get("sources", []) or []:
                report = SourceReport.model_validate(raw)
                sources_map[f"{report.source.value}:{report.provider}"] = report
        viz.cards = self._cards(ctx, risk, sources_map)
        return viz


def _zone_geometry(zone: dict) -> dict:
    geometry = zone.get("geometry")
    if isinstance(geometry, dict):
        return geometry
    return {"type": "Point", "coordinates": [0, 0]}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
