"""Evidence and provenance.

The rule ORCA is built around: *every* number that reaches a user must be
traceable to a provider, a dataset, a variable, a timestamp and a freshness
verdict.  Nothing in the response is allowed to exist without a matching
:class:`Evidence` row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.clock import iso
from app.schemas.common import (
    DataOrigin,
    Freshness,
    QualityFlag,
    Source,
    VariableKind,
)
from app.schemas.geo import GeoPoint


class Evidence(BaseModel):
    """One traceable fact used by ORCA."""

    evidence_id: str
    source: Source
    provider: str                       # concrete implementation that produced it
    dataset: str                        # dataset / endpoint / bulletin identifier
    variable: str                       # canonical variable name
    value: float | str | None
    unit: str | None
    kind: VariableKind
    origin: DataOrigin
    location: GeoPoint | None = None
    observation_time: datetime | None = None   # when it was measured
    forecast_time: datetime | None = None      # what time it describes
    issued_at: datetime | None = None          # when the source published it
    retrieved_at: datetime
    age_seconds: float
    freshness: Freshness
    quality: QualityFlag = QualityFlag.GOOD
    transformation: str | None = None   # e.g. "m/s -> km/h", "nearest-hour pick"
    agent: str | None = None
    cache_hit: bool = False
    notes: str | None = None

    def summary(self) -> str:
        v = f"{self.value}{(' ' + self.unit) if self.unit else ''}"
        t = iso(self.forecast_time or self.observation_time)
        return f"{self.source.value} {self.variable}={v} @ {t} [{self.freshness.value}]"


class SourceReport(BaseModel):
    """Per-source status shown to the user and to the trace panel."""

    source: Source
    provider: str
    origin: DataOrigin
    status: str
    latency_ms: float | None = None
    retrieved_at: datetime | None = None
    freshness: Freshness = Freshness.UNAVAILABLE
    dataset: str | None = None
    error: str | None = None
    cache_hit: bool = False
    attribution: str | None = None


class Conflict(BaseModel):
    """Two sources disagreeing about the same variable at the same time."""

    variable: str
    severity: str
    unit: str
    claims: list[dict[str, Any]]
    spread: float
    tolerance: float
    resolution: str                 # which source won and under which rule
    winning_source: Source | None = None
    confidence_penalty: float = 0.0
    explanation: str = ""


class EvidenceLedger(BaseModel):
    """Append-only record for one query. Handed to the API as-is."""

    query_id: str
    items: list[Evidence] = Field(default_factory=list)

    def add(self, e: Evidence) -> Evidence:
        self.items.append(e)
        return e

    def by_variable(self, variable: str) -> list[Evidence]:
        return [e for e in self.items if e.variable == variable]

    def variables(self) -> list[str]:
        seen: list[str] = []
        for e in self.items:
            if e.variable not in seen:
                seen.append(e.variable)
        return seen

    def worst_freshness(self) -> Freshness:
        order = [Freshness.FRESH, Freshness.AGING, Freshness.STALE, Freshness.UNAVAILABLE]
        worst = Freshness.FRESH
        for e in self.items:
            if order.index(e.freshness) > order.index(worst):
                worst = e.freshness
        return worst
