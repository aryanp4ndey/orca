"""Response / Explanation Agent.

Turns a validated, structured result into something a person can act on, in
their own language, without knowing anything about agents or providers.

Three rules it enforces:

1. **It cannot invent a measurement.**  Every number it emits is checked against
   the evidence ledger by ``grounding.check`` before the answer is returned.
2. **It cannot upgrade a verdict.**  The risk level comes from the deterministic
   engine; this agent only phrases it.
3. **It cannot hide a caveat.**  Stale data, unavailable sources, source
   conflicts and demo mode all produce a line in the answer, not a silent
   footnote.

The LLM is optional here and off by default.  When enabled it is used only to
rephrase text whose facts are supplied verbatim - and if its output fails the
same grounding check, it is thrown away and the template answer is used.
"""

from __future__ import annotations

from datetime import datetime

from app.agents.base import BaseAgent
from app.agents.response import grounding
from app.core.clock import IST, utcnow
from app.i18n.catalog import t
from app.llm.base import LLMUnavailable
from app.observability.trace import Trace
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability, DataOrigin, Intent, RiskLevel

LLM_STYLE_SYSTEM = """You rewrite marine safety messages for fishermen and coastal users.
Rules you must obey exactly:
- Use ONLY the facts given to you. Never add a number, place, time or condition
  that is not in the facts.
- Never change a risk verdict, a value or a unit.
- Keep it under 90 words, plain and calm. No jargon, no markdown.
- Reply in the requested language only."""


def _when_phrase(target: datetime | None, language) -> str:
    if target is None:
        return ""
    local = target.astimezone(IST)
    now_local = utcnow().astimezone(IST)
    delta_days = (local.date() - now_local.date()).days
    day = {0: {"en": "today", "hi": "आज", "ml": "ഇന്ന്", "ta": "இன்று"},
           1: {"en": "tomorrow", "hi": "कल", "ml": "നാളെ", "ta": "நாளை"},
           2: {"en": "day after tomorrow", "hi": "परसों", "ml": "മറ്റന്നാൾ", "ta": "நாளை மறுநாள்"}}
    lang = language.value if hasattr(language, "value") else str(language)
    word = day.get(delta_days, {}).get(lang) or day.get(delta_days, {}).get("en")
    stamp = local.strftime("%H:%M IST")
    if word:
        return f"{word} {stamp}"
    return local.strftime("%d %b %H:%M IST")


class ResponseAgent(BaseAgent):
    name = "response_agent"
    capability = Capability.RESPONSE
    responsibility = (
        "Convert validated structured results into an explanation in the user's "
        "language, citing evidence and surfacing every caveat")
    consumes = ("risk assessment", "agent data", "evidence ledger")
    produces = ("answer text", "factor list", "follow-up suggestions", "grounding report")
    sources = ("ORCA message catalogue", "optional LLM for phrasing only")
    failure_behaviour = (
        "Falls back to the deterministic template answer if the LLM is slow, "
        "unavailable, or produces text that fails the grounding check")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        all_data = request.depends_on.get("_all", {})
        responses = request.depends_on.get("_responses", {})
        language = ctx.language

        evidence = []
        for response in responses.values():
            evidence.extend(getattr(response, "evidence", []) or [])

        risk = (all_data.get("risk") or {}).get("assessment")
        lines: list[str] = []
        factors_out: list[dict] = []

        place = ctx.location.name if ctx.location else None
        when = _when_phrase(ctx.time.target if ctx.time else None, language)

        if ctx.intent is Intent.SMALL_TALK:
            lines.append(t("answer.greeting", language))
        elif ctx.location is None:
            lines.append(t("answer.no_location", language))
        elif ctx.intent in (Intent.MARINE_SAFETY,) and risk:
            lines.append(t("answer.for", language,
                           activity=t(f"act.{ctx.activity.value}", language),
                           place=place, when=when))
            lines.append(t(f"risk.{risk['risk_level']}", language))
            factor_lines, factors_out = self._factor_lines(risk, language)
            if factor_lines:
                lines.append(t("answer.because", language))
                lines.extend(factor_lines)
            lines.extend(self._advisory_lines(all_data, language))
        elif ctx.intent is Intent.SEA_CONDITION:
            lines.append(t("answer.sea_state", language, place=place, when=when))
            lines.extend(self._value_lines(all_data.get("ocean", {}), language,
                                           ["wave_height_significant", "swell_height",
                                            "wave_period", "current_speed",
                                            "sea_surface_temperature"]))
            lines.extend(self._value_lines(all_data.get("weather", {}), language,
                                           ["wind_speed_10m"]))
            if risk:
                lines.append(t(f"risk.{risk['risk_level']}", language))
                _, factors_out = self._factor_lines(risk, language)
            lines.extend(self._advisory_lines(all_data, language))
        elif ctx.intent is Intent.WEATHER_INFO:
            lines.append(t("answer.weather", language, place=place, when=when))
            lines.extend(self._value_lines(all_data.get("weather", {}), language,
                                           ["wind_speed_10m", "wind_gust_10m",
                                            "precipitation", "visibility",
                                            "thunderstorm_probability"]))
        elif ctx.intent is Intent.PFZ_LOOKUP:
            lines.extend(self._pfz_lines(all_data, language, place, risk))
        elif ctx.intent is Intent.HAZARD_CHECK:
            lines.extend(self._hazard_lines(all_data, language))
        elif ctx.intent is Intent.AVOID_AREAS:
            lines.extend(self._avoid_lines(all_data, language, place))
        elif ctx.intent is Intent.ROUTE_RISK:
            lines.extend(self._route_lines(all_data, ctx, language))
        elif ctx.intent is Intent.ANALYTICAL:
            lines.extend(self._analytical_lines(all_data, ctx, language))
        elif ctx.intent is Intent.LOCATION_INFO:
            lines.extend(self._location_lines(all_data, language, place))
        else:
            lines.append(t("answer.clarify", language))

        provenance = self._provenance_line(responses, language)
        caveats = self._caveats(all_data, responses, risk, language)
        answer = "\n".join([l for l in lines if l]
                           + ([provenance] if provenance else []) + caveats).strip()

        allowed = self._allowed_numbers(evidence, risk, all_data, ctx)
        with trace.span("grounding_check", "validation"):
            report = grounding.check(answer, allowed)
            if not report.ok:
                trace.note(f"template answer contained ungrounded numbers: "
                           f"{report.ungrounded}")

        if (self.deps.settings.llm_enable_for_explanation and self.deps.llm.available
                and ctx.intent is not Intent.SMALL_TALK):
            answer, report = await self._llm_polish(answer, language, allowed, trace, report)

        return AgentResponse(
            agent=self.name, capability=self.capability, status=AgentStatus.OK,
            data={"answer": answer, "language": language.value,
                  "factors": factors_out,
                  "grounding": report.as_dict(),
                  "follow_up_suggestions": self._follow_ups(ctx, language),
                  "disclaimer": t("note.disclaimer", language)},
            evidence=[], warnings=[], confidence=1.0 if report.ok else 0.6,
            source_status={"RESPONSE": "OK"})

    @staticmethod
    def _advisory_lines(all_data: dict, language) -> list[str]:
        """Authority warnings are quoted, never paraphrased or re-scored."""
        hazard = all_data.get("hazard", {}) or {}
        advisories = hazard.get("advisories", [])
        if not advisories:
            return []
        lines = [t("answer.warnings_in_force", language)]
        for a in advisories[:3]:
            lines.append(f"- [{a['severity'].upper()}] {a['headline']}")
        return lines

    @staticmethod
    def _provenance_line(responses: dict, language) -> str:
        names, retrieved = [], None
        for response in responses.values():
            for raw in (getattr(response, "data", {}) or {}).get("sources", []) or []:
                if raw.get("status") in ("OK", "DEGRADED"):
                    if raw["source"] not in names:
                        names.append(raw["source"])
                    if raw.get("retrieved_at"):
                        retrieved = max(retrieved or raw["retrieved_at"], raw["retrieved_at"])
        if not names:
            return ""
        stamp = ""
        if retrieved:
            try:
                stamp = datetime.fromisoformat(retrieved).astimezone(IST).strftime("%H:%M IST")
            except ValueError:
                stamp = retrieved
        return t("note.sources", language, sources=", ".join(names), retrieved=stamp)

    # ------------------------------------------------------------------
    def _factor_lines(self, risk: dict, language) -> tuple[list[str], list[dict]]:
        lines, out = [], []
        for f in risk.get("factors", [])[:4]:
            if f["level"] == RiskLevel.LOW.value:
                continue
            label = t(f"var.{f['variable']}", language)
            if label.startswith("var."):
                label = f["label"]
            unit = f.get("unit") or ""
            lines.append(f"- {label}: {f['value']:g} {unit} ({f['level']})".rstrip())
            out.append({"label": label, "variable": f["variable"],
                        "value": f["value"], "unit": unit, "level": f["level"],
                        "rationale": f["rationale"], "evidence_ids": f["evidence_ids"]})
        if not lines:
            for f in risk.get("factors", [])[:2]:
                label = t(f"var.{f['variable']}", language)
                if label.startswith("var."):
                    label = f["label"]
                lines.append(f"- {label}: {f['value']:g} {f.get('unit') or ''}".rstrip())
                out.append({"label": label, "variable": f["variable"],
                            "value": f["value"], "unit": f.get("unit"),
                            "level": f["level"], "rationale": f["rationale"],
                            "evidence_ids": f["evidence_ids"]})
        return lines, out

    @staticmethod
    def _value_lines(agent_data: dict, language, variables: list[str]) -> list[str]:
        values = (agent_data or {}).get("values", {})
        lines = []
        for variable in variables:
            v = values.get(variable)
            if not v:
                continue
            label = t(f"var.{variable}", language)
            if label.startswith("var."):
                label = variable.replace("_", " ")
            lines.append(f"- {label}: {v['value']:g} {v['unit']} ({v['source']})")
        return lines

    def _pfz_lines(self, all_data: dict, language, place, risk) -> list[str]:
        pfz = all_data.get("pfz", {})
        nearest = pfz.get("nearest")
        if not nearest:
            return [t("answer.pfz_none", language)]
        valid_to = datetime.fromisoformat(nearest["valid_to"]).astimezone(IST)
        lines = [t("answer.pfz_nearest", language,
                   distance=f"{nearest['distance_km']:g}",
                   compass=nearest["compass"], place=place or nearest["landing_centre"],
                   valid_to=valid_to.strftime("%d %b %H:%M IST"))]
        if nearest.get("depth_m"):
            lines.append(f"- Depth about {nearest['depth_m']:g} m; "
                         f"bearing {nearest['bearing_deg']:g}° from your position.")
        others = [z for z in pfz.get("active", []) if z is not nearest][:2]
        for z in others:
            lines.append(f"- Also {z['distance_km']:g} km {z['compass']}.")
        if risk and risk["risk_level"] in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value):
            lines.append(t(f"risk.{risk['risk_level']}", language))
        return lines

    def _hazard_lines(self, all_data: dict, language) -> list[str]:
        hazard = all_data.get("hazard", {})
        advisories = hazard.get("advisories", [])
        if not advisories:
            return [t("answer.no_warnings", language)]
        lines = [t("answer.warnings_in_force", language)]
        for a in advisories[:4]:
            lines.append(f"- [{a['severity'].upper()}] {a['headline']}")
        return lines

    def _avoid_lines(self, all_data: dict, language, place) -> list[str]:
        geo = all_data.get("geospatial", {})
        hazard = all_data.get("hazard", {})
        lines = [t("answer.avoid", language, place=place)]
        zones = hazard.get("hazard_zones") or [
            z for z in geo.get("zones", [])
            if z.get("category") in ("restricted", "fishing_ban")]
        if not zones:
            lines.append("- No restricted or closure area was found near this point "
                         "in the layers ORCA carries.")
        for z in zones[:5]:
            where = ("you are inside it" if z["relation"] == "inside"
                     else f"{z['distance_km']:g} km away")
            note = "" if z.get("authoritative") else " (illustrative layer, confirm officially)"
            lines.append(f"- {z['zone_name']}: {where}{note}")
        for a in hazard.get("advisories", [])[:2]:
            lines.append(f"- [{a['severity'].upper()}] {a['headline']}")
        return lines

    def _route_lines(self, all_data: dict, ctx, language) -> list[str]:
        route = all_data.get("route", {})
        if not route:
            return [t("answer.no_location", language)]
        lines = [t("answer.route", language,
                   start=ctx.location.name, end=ctx.destination.name,
                   distance=f"{route['total_distance_km']:g}",
                   hours=f"{route['duration_hours']:.1f}", speed="8")]
        hazardous = route.get("hazardous_segments", [])
        if hazardous:
            for i in hazardous[:3]:
                seg = route["segments"][i]
                lines.append(f"- Segment {i + 1}: {seg['risk_level']}"
                             + (f", driven by {seg['dominant_factor']}"
                                if seg.get("dominant_factor") else ""))
        else:
            lines.append("- No segment scored HIGH or CRITICAL on the sampled corridor.")
        return lines

    def _analytical_lines(self, all_data: dict, ctx, language) -> list[str]:
        ocean = all_data.get("ocean", {})
        weather = all_data.get("weather", {})
        windows = ocean.get("windows") or weather.get("windows") or {}
        if len(windows) < 2:
            return ["ORCA compared the requested periods but has data for only one of "
                    "them, so it cannot attribute a difference. Ask again with two "
                    "clear time windows."]
        keys = sorted(windows)
        lines = ["Comparison of the two periods you asked about:"]
        for key in keys[:2]:
            local = datetime.fromisoformat(key).astimezone(IST).strftime("%H:%M IST")
            parts = []
            for variable in ("wave_height_significant", "wind_speed_10m",
                             "sea_surface_temperature", "current_speed"):
                v = windows[key].get(variable)
                if v:
                    label = t(f"var.{variable}", language)
                    if label.startswith("var."):
                        label = variable.replace("_", " ")
                    parts.append(f"{label} {v['value']:g} {v['unit']}")
            lines.append(f"- {local}: " + ", ".join(parts))
        lines.append(
            "ORCA reports what the retrieved variables did. It does not claim a "
            "causal explanation for fishing outcomes - that would need catch data "
            "and biological evidence it does not have.")
        return lines

    def _location_lines(self, all_data: dict, language, place) -> list[str]:
        geo = all_data.get("geospatial", {})
        if not geo:
            return [t("answer.no_location", language)]
        band = geo.get("maritime_band", {})
        nearest = geo.get("nearest_landing_centre", {})
        return [
            f"{place}: {geo['distance_to_coast_km']:g} km from the coast.",
            f"- Band: {band.get('label')} (indicative, not an official limit).",
            f"- Nearest landing centre: {nearest.get('name')}, "
            f"{nearest.get('distance_km')} km {nearest.get('compass')}.",
        ]

    # ------------------------------------------------------------------
    def _caveats(self, all_data: dict, responses: dict, risk, language) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for response in responses.values():
            for warning in getattr(response, "warnings", []) or []:
                if "unavailable" in warning.lower() and warning not in seen:
                    seen.add(warning)
                    out.append(f"! {warning}")
        if risk:
            if risk.get("stale_variables"):
                out.append("! " + t("note.stale", language))
            if risk.get("gate_reason"):
                out.append(f"! {risk['gate_reason']}")
        for agent_data in all_data.values():
            for conflict in (agent_data or {}).get("conflicts", []) or []:
                if conflict.get("severity") == "MATERIAL":
                    out.append("! " + t("note.conflict", language,
                                        variable=conflict["variable"],
                                        winner=conflict.get("winning_source", "")))
        if self.deps.settings.demo_mode:
            out.append("! " + t("note.demo", language))
        out.append(t("note.disclaimer", language))
        return out

    @staticmethod
    def _allowed_numbers(evidence, risk, all_data, ctx) -> set[float]:
        groups: list[list] = [[e.value for e in evidence
                               if isinstance(e.value, (int, float))]]
        if risk:
            groups.append([f["value"] for f in risk.get("factors", [])])
            groups.append([f.get("threshold") for f in risk.get("factors", [])])
            groups.append([risk.get("risk_score"), risk.get("confidence")])
        for agent_data in all_data.values():
            values = (agent_data or {}).get("values", {})
            groups.append([v["value"] for v in values.values()])
            for window in ((agent_data or {}).get("windows") or {}).values():
                groups.append([v["value"] for v in window.values()])
            geo_numbers = [
                (agent_data or {}).get("distance_to_coast_km"),
                ((agent_data or {}).get("nearest_landing_centre") or {}).get("distance_km"),
                (agent_data or {}).get("total_distance_km"),
                (agent_data or {}).get("duration_hours"),
            ]
            groups.append(geo_numbers)
            for z in ((agent_data or {}).get("zones") or []):
                if isinstance(z, dict):
                    groups.append([z.get("distance_km"), z.get("depth_m"),
                                   z.get("bearing_deg"), z.get("distance_from_landing_km")])
            for z in ((agent_data or {}).get("active") or []):
                groups.append([z.get("distance_km"), z.get("depth_m"),
                               z.get("bearing_deg")])
            for seg in ((agent_data or {}).get("segments") or []):
                groups.append([seg.get("index", 0) + 1, seg.get("length_km"),
                               seg.get("risk_score")])
        groups.append(grounding.numbers_in_timestamp(ctx.time.target if ctx.time else None))
        groups.append(grounding.numbers_in_timestamp(
            (ctx.time.target.astimezone(IST) if ctx.time else None)))
        # The provenance line prints the retrieval time, and evidence rows carry
        # their own issue times. Those clock components are legitimate numbers in
        # an answer, so they belong in the allowed set - otherwise the grounding
        # check fires on our own timestamps.
        now_ist = utcnow().astimezone(IST)
        groups.append(grounding.numbers_in_timestamp(now_ist))
        for e in evidence:
            for stamp in (e.issued_at, e.retrieved_at, e.forecast_time, e.observation_time):
                if stamp is not None:
                    groups.append(grounding.numbers_in_timestamp(stamp.astimezone(IST)))
        groups.append([0, 1, 2, 3, 4, 5, 8, 10, 12, 24, 100])   # ordinals and speeds
        for agent_data in all_data.values():
            for z in ((agent_data or {}).get("active") or []):
                try:
                    groups.append(grounding.numbers_in_timestamp(
                        datetime.fromisoformat(z["valid_to"]).astimezone(IST)))
                except Exception:  # noqa: BLE001
                    pass
        return grounding.collect_allowed(*groups)

    async def _llm_polish(self, answer: str, language, allowed, trace, report):
        with trace.span("llm_explanation", "llm") as span:
            try:
                facts = f"Language: {language.value}\nFacts and verdict:\n{answer}"
                polished = await self.deps.llm.complete_text(
                    LLM_STYLE_SYSTEM, facts, self.deps.settings.llm_timeout_ms)
                check = grounding.check(polished, allowed)
                if check.ok and polished.strip():
                    span.attributes["accepted"] = True
                    return polished.strip(), check
                span.attributes["accepted"] = False
                span.attributes["ungrounded"] = check.ungrounded
                trace.note("LLM phrasing rejected: it introduced numbers not in the "
                           "evidence; using the deterministic answer")
            except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
                span.status = "ERROR"
                span.attributes["error"] = str(exc)
                trace.note("LLM phrasing unavailable; using the deterministic answer")
        return answer, report

    @staticmethod
    def _follow_ups(ctx, language) -> list[str]:
        if ctx.intent is Intent.MARINE_SAFETY:
            return [t("followup.time", language), t("followup.pfz", language),
                    t("followup.warnings", language)]
        if ctx.intent is Intent.PFZ_LOOKUP:
            return [t("followup.warnings", language), t("followup.avoid", language)]
        return [t("followup.warnings", language), t("followup.pfz", language)]
