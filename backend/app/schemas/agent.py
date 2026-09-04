"""Agent-to-agent contract.

Agents never exchange free-form prose.  They exchange these two models, which
means every hand-off is validated by Pydantic and every failure is typed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import (
    Activity,
    AgentStatus,
    Capability,
    Intent,
    Language,
    VesselClass,
)
from app.schemas.evidence import Evidence
from app.schemas.geo import GeoPoint, ResolvedLocation


class TimeSpec(BaseModel):
    """A resolved time reference, always UTC, always explicit about its origin."""

    target: datetime                       # the instant the user asked about
    window_start: datetime
    window_end: datetime
    is_explicit: bool = True               # did the user actually state a time?
    raw: str | None = None                 # the phrase we parsed
    horizon_hours: float = 0.0             # hours from now to target
    resolver: str = "rules"                # rules | llm | session_context | default


class QueryContext(BaseModel):
    """Everything ORCA knows about *this* question, language-independent."""

    query_id: str
    session_id: str | None = None
    raw_query: str
    language: Language = Language.EN
    intent: Intent = Intent.UNKNOWN
    intent_confidence: float = 0.0
    activity: Activity = Activity.GENERIC
    vessel: VesselClass = VesselClass.NONE
    location: ResolvedLocation | None = None
    destination: ResolvedLocation | None = None
    time: TimeSpec | None = None
    analysis_windows: list[TimeSpec] = Field(default_factory=list)
    inherited_fields: list[str] = Field(default_factory=list)  # from previous turn
    constraints: dict[str, Any] = Field(default_factory=dict)
    nlu_resolver: str = "rules"
    created_at: datetime | None = None


class AgentRequest(BaseModel):
    """Typed input to a specialist agent."""

    request_id: str
    capability: Capability
    context: QueryContext
    point: GeoPoint | None = None
    deadline_ms: int = 2000
    depends_on: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    """Typed output from a specialist agent."""

    agent: str
    capability: Capability
    status: AgentStatus = AgentStatus.OK
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source_status: dict[str, str] = Field(default_factory=dict)
    processing_time_ms: float = 0.0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in (AgentStatus.OK, AgentStatus.PARTIAL)


class PlanStep(BaseModel):
    capability: Capability
    required: bool = True
    depends_on: list[Capability] = Field(default_factory=list)
    reason: str = ""
    deadline_ms: int = 2000
    options: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    """The planner's decision, inspectable by a judge."""

    query_id: str
    intent: Intent
    steps: list[PlanStep]
    skipped: dict[str, str] = Field(default_factory=dict)   # capability -> why not
    strategy: str = "intent_routing"
    planner: str = "rules"
    total_budget_ms: int = 3000

    def capabilities(self) -> list[Capability]:
        return [s.capability for s in self.steps]

    def waves(self) -> list[list[PlanStep]]:
        """Group steps into dependency waves; each wave runs concurrently."""
        remaining = list(self.steps)
        done: set = set()
        out: list[list[PlanStep]] = []
        guard = 0
        while remaining and guard < 20:
            guard += 1
            wave = [s for s in remaining if all(d in done for d in s.depends_on)]
            if not wave:      # cycle - fail safe by running the rest serially
                wave = [remaining[0]]
            out.append(wave)
            for s in wave:
                done.add(s.capability)
            remaining = [s for s in remaining if s not in wave]
        return out
