"""Risk Assessment Agent.

A thin, deliberately boring wrapper around the deterministic engine in
``app/safety/risk_engine.py``.  Its only jobs are to gather the evidence the
upstream agents produced, re-fuse it into one value per variable, tell the
engine which sources went missing, and hand back the assessment untouched.

There is no model call here and no judgement call here.  That is the point.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.observability.trace import Trace
from app.reasoning.fusion import fuse
from app.reasoning.freshness import worst as worst_freshness
from app.safety.risk_engine import RiskInputs, assess
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability, Freshness


class RiskAgent(BaseAgent):
    name = "risk_agent"
    capability = Capability.RISK
    responsibility = (
        "Score the retrieved evidence against a transparent, versioned ruleset "
        "for the user's activity and vessel, and decide whether an advisory can "
        "responsibly be issued at all")
    consumes = ("weather values", "ocean values", "hazard advisories", "evidence")
    produces = ("risk_level", "risk_score", "factors", "confidence", "decision_status")
    sources = ("deterministic ruleset app/safety/rules.yaml",)
    failure_behaviour = (
        "Missing required evidence yields INSUFFICIENT_DATA with the advisory "
        "explicitly withheld - never a default of 'safe'")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        responses = request.depends_on.get("_responses", {})

        evidence = []
        conflicts = []
        unavailable: list[str] = []
        freshnesses: list[Freshness] = []
        for response in responses.values():
            if not getattr(response, "succeeded", False):
                continue
            evidence.extend(response.evidence)
            data = response.data or {}
            unavailable.extend(data.get("unavailable", []))
            for c in data.get("conflicts", []):
                conflicts.append(c)
        # Rows with no value are UNAVAILABLE by construction (a cloud-blocked
        # chlorophyll retrieval, say). Judging the assessment's freshness by those
        # would report a current answer as UNAVAILABLE, so only rows that actually
        # carry a value count.
        freshnesses = [e.freshness for e in evidence if e.value is not None] \
            or [Freshness.UNAVAILABLE]

        hazard = (request.depends_on.get("hazard")
                  or request.depends_on.get("_all", {}).get("hazard") or {})
        severity = hazard.get("max_severity", "none")
        headlines = hazard.get("headlines", [])

        with trace.span("risk_fuse", "compute"):
            fused, fresh_conflicts = fuse(evidence)

        from app.schemas.evidence import Conflict
        conflict_models = [Conflict.model_validate(c) if isinstance(c, dict) else c
                           for c in conflicts] or fresh_conflicts

        with trace.span("risk_engine", "compute",
                        activity=ctx.activity.value, vessel=ctx.vessel.value):
            assessment = assess(RiskInputs(
                activity=ctx.activity.value, vessel=ctx.vessel.value,
                values=fused, evidence=evidence,
                advisory_severity=severity, advisory_headlines=list(headlines),
                conflicts=conflict_models,
                unavailable_sources=sorted(set(unavailable)),
                worst_freshness=worst_freshness(freshnesses),
            ))

        return AgentResponse(
            agent=self.name, capability=self.capability, status=AgentStatus.OK,
            data={"assessment": assessment.model_dump(mode="json"),
                  "fused_values": {k: {"value": v.value, "unit": v.unit,
                                       "source": v.source.value}
                                   for k, v in fused.items()}},
            evidence=[], warnings=assessment.warnings,
            confidence=assessment.confidence,
            source_status={"RISK_ENGINE": "OK"})
