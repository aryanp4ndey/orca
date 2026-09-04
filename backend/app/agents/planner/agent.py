"""Planner / Orchestrator agent.

Responsibilities:
  1. understand the query (deterministic first, LLM only as a fallback);
  2. resolve the location and the time into unambiguous, typed values;
  3. merge in conversation context for follow-up turns;
  4. decide which specialist capabilities are actually needed, and say why the
     others were skipped;
  5. hand the orchestrator a dependency graph, not a script.

It never touches marine data.  It decides *what to ask*, which is exactly the
job an LLM is good at - and exactly the job that does not require one when the
question is one of a dozen well-understood marine shapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.agents.planner import routing
from app.core.clock import utcnow
from app.geo.gazetteer import get_gazetteer
from app.geo.layers import maritime_band
from app.llm.base import LLMClient, LLMUnavailable
from app.observability.logging import get_logger
from app.observability.trace import Trace
from app.reasoning import nlu
from app.reasoning.context import Session, apply_context
from app.schemas.agent import ExecutionPlan, PlanStep, QueryContext, TimeSpec
from app.schemas.api import QueryRequest
from app.schemas.common import Activity, Capability, Intent, Language, VesselClass
from app.schemas.geo import GeoPoint, ResolvedLocation

log = get_logger("orca.planner")

LLM_NLU_SYSTEM = """You are the intent parser for ORCA, a marine decision-support system.
Return ONLY a JSON object with these keys and no prose:
  intent: one of marine_safety, sea_condition, weather_info, pfz_lookup, hazard_check,
          avoid_areas, route_risk, analytical, location_info, small_talk, unknown
  activity: one of fishing_small_boat, fishing_mechanised, swimming, diving,
            cargo_transit, patrol, tourism, research, generic
  vessel: one of none, canoe, small_motorised, mechanised, large
  location: the place name the user mentioned, or null
  destination: the destination place name for a route question, or null
  language: ISO-639-1 code of the user's message
  confidence: 0.0-1.0
You must NOT invent weather, wave, or any other measurement. You are only
classifying the request. If unsure, use "unknown" and a low confidence."""


class PlannerAgent:
    name = "planner"
    capability = Capability.GEOSPATIAL   # planning precedes capability execution
    responsibility = (
        "Understand the query, resolve location and time, merge conversation "
        "context, and decide which specialist agents to run")

    def __init__(self, llm: LLMClient, settings) -> None:
        self.llm = llm
        self.settings = settings

    # ------------------------------------------------------------------
    async def plan(self, request: QueryRequest, session: Session, trace: Trace,
                   now: datetime | None = None) -> tuple[QueryContext, ExecutionPlan]:
        now = now or utcnow()
        query_id = trace.query_id

        with trace.span("nlu", "reasoning") as span:
            result = nlu.understand(
                request.query, now=now,
                language_override=Language(request.language) if request.language else None)
            span.attributes.update(intent=result.intent.value,
                                   confidence=result.intent_confidence,
                                   language=result.language.value,
                                   resolver="rules")

        resolver = "rules"
        if result.needs_llm and self.settings.llm_enable_for_nlu_fallback and self.llm.available:
            with trace.span("nlu_llm_fallback", "llm") as span:
                try:
                    patched = await self._llm_fallback(request.query, result)
                    if patched is not None:
                        result = patched
                        resolver = "llm_fallback"
                        span.attributes["intent"] = result.intent.value
                except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
                    span.status = "ERROR"
                    span.attributes["error"] = str(exc)
                    trace.note("LLM fallback failed; continuing with rule-based intent")

        location, destination = self._resolve_locations(request, result)
        time_spec = result.time or self._default_time(result.intent, now)

        ctx = QueryContext(
            query_id=query_id, session_id=request.session_id,
            raw_query=request.query, language=result.language,
            intent=result.intent, intent_confidence=result.intent_confidence,
            activity=self._activity(request, result), vessel=self._vessel(request, result),
            location=location, destination=destination, time=time_spec,
            analysis_windows=result.analysis_windows,
            constraints={"low_bandwidth": request.low_bandwidth,
                         "intent_scores": result.intent_scores,
                         "nlu_reasons": result.reasons},
            nlu_resolver=resolver, created_at=now,
        )
        ctx = apply_context(ctx, session)
        # Precedence for an unstated location: what the user just said, then what
        # the conversation was about, then the device fix. A follow-up like
        # "what about 5 PM?" means the place we were already discussing - falling
        # straight to GPS would silently change the subject.
        if ctx.location is None:
            ctx.location = self._device_location(request)
        if ctx.time is None:
            ctx.time = self._default_time(ctx.intent, now)

        plan = self._build_plan(ctx)
        trace.plan = {
            "intent": ctx.intent.value,
            "intent_confidence": ctx.intent_confidence,
            "nlu_resolver": resolver,
            "language": ctx.language.value,
            "activity": ctx.activity.value,
            "inherited_from_context": ctx.inherited_fields,
            "steps": [{"capability": s.capability.value, "required": s.required,
                       "depends_on": [d.value for d in s.depends_on],
                       "reason": s.reason, "deadline_ms": s.deadline_ms}
                      for s in plan.steps],
            "skipped": plan.skipped,
            "waves": [[s.capability.value for s in wave] for wave in plan.waves()],
        }
        return ctx, plan

    # ------------------------------------------------------------------
    async def _llm_fallback(self, query: str, result: nlu.NLUResult) -> nlu.NLUResult | None:
        data = await self.llm.complete_json(
            LLM_NLU_SYSTEM, query, self.settings.llm_timeout_ms)
        try:
            intent = Intent(data.get("intent", "unknown"))
        except ValueError:
            intent = Intent.UNKNOWN
        if intent is Intent.UNKNOWN:
            return None
        try:
            activity = Activity(data.get("activity", "generic"))
        except ValueError:
            activity = result.activity
        try:
            vessel = VesselClass(data.get("vessel", "none"))
        except ValueError:
            vessel = result.vessel

        places = result.places
        if not places and data.get("location"):
            found = get_gazetteer().find(str(data["location"]))
            places = [found] if found else []
        if data.get("destination"):
            dest = get_gazetteer().find(str(data["destination"]))
            if dest and dest not in places:
                places = places + [dest]

        return nlu.NLUResult(
            language=result.language, intent=intent,
            intent_confidence=float(data.get("confidence", 0.7)),
            intent_scores=result.intent_scores, activity=activity,
            activity_confidence=result.activity_confidence, vessel=vessel,
            places=places, time=result.time, analysis_windows=result.analysis_windows,
            resolver="llm_fallback", needs_llm=False,
            reasons=result.reasons + ["intent supplied by LLM fallback"],
        )

    # ------------------------------------------------------------------
    def _resolve_locations(self, request: QueryRequest, result: nlu.NLUResult
                           ) -> tuple[ResolvedLocation | None, ResolvedLocation | None]:
        """A place stated in the query wins over everything else."""
        gz = get_gazetteer()
        primary = destination = None

        if result.places:
            primary = gz.to_resolved(result.places[0], request.query)
            if len(result.places) > 1 and result.intent is Intent.ROUTE_RISK:
                destination = gz.to_resolved(result.places[1], request.query)
        return primary, destination

    @staticmethod
    def _device_location(request: QueryRequest) -> ResolvedLocation | None:
        """The device fix, used only when nothing else supplied a location."""
        if request.lat is None or request.lon is None:
            return None
        gz = get_gazetteer()
        point = GeoPoint(lat=request.lat, lon=request.lon)
        nearest = gz.nearest(point, limit=1)
        _band_id, _band_label, coast_km = maritime_band(point)
        name = (f"your position ({point.lat:.3f}, {point.lon:.3f})"
                if not nearest else
                f"your position, {nearest[0][1]:.0f} km from {nearest[0][0].name}")
        return ResolvedLocation(
            query="device location", name=name, point=point,
            kind="device_position",
            state=nearest[0][0].state if nearest else None,
            is_marine_point=coast_km > 0.5,
            distance_to_coast_km=round(coast_km, 2),
            resolver="device_gps", confidence=1.0,
            source_dataset="client-supplied coordinates")

    @staticmethod
    def _activity(request: QueryRequest, result: nlu.NLUResult) -> Activity:
        if request.activity:
            try:
                return Activity(request.activity)
            except ValueError:
                pass
        return result.activity

    @staticmethod
    def _vessel(request: QueryRequest, result: nlu.NLUResult) -> VesselClass:
        if request.vessel:
            try:
                return VesselClass(request.vessel)
            except ValueError:
                pass
        return result.vessel

    @staticmethod
    def _default_time(intent: Intent, now: datetime) -> TimeSpec | None:
        if intent is Intent.SMALL_TALK:
            return None
        from datetime import timedelta
        return TimeSpec(target=now, window_start=now - timedelta(minutes=30),
                        window_end=now + timedelta(hours=3), is_explicit=False,
                        raw=None, horizon_hours=0.0, resolver="default")

    # ------------------------------------------------------------------
    def _build_plan(self, ctx: QueryContext) -> ExecutionPlan:
        steps: list[PlanStep] = []
        for s in routing.steps_for(ctx.intent):
            if s.capability is Capability.ROUTE and ctx.destination is None:
                continue
            steps.append(PlanStep(
                capability=s.capability, required=s.required,
                depends_on=list(s.depends_on), reason=s.reason,
                deadline_ms=min(s.deadline_ms, self.settings.budget_agent_ms),
                options=dict(s.options)))
        skipped = routing.skipped_for(ctx.intent)
        if ctx.intent is Intent.ROUTE_RISK and ctx.destination is None:
            skipped[Capability.ROUTE.value] = (
                "route scoring needs a destination; none was found in the query")
        return ExecutionPlan(
            query_id=ctx.query_id, intent=ctx.intent, steps=steps, skipped=skipped,
            planner=ctx.nlu_resolver, total_budget_ms=self.settings.budget_total_ms)


def new_query_id() -> str:
    return "q_" + uuid.uuid4().hex[:12]
