"""Risk contracts.

The risk engine is deterministic: given the same evidence it must always give
the same answer.  These models are what it produces, and they are what the UI
and the explanation agent are allowed to talk about.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import DecisionStatus, Freshness, RiskLevel


class RiskFactor(BaseModel):
    """One rule that fired, with the exact number that made it fire."""

    factor_id: str
    variable: str
    label: str
    value: float | None
    unit: str | None
    threshold: float | None = None
    comparator: str | None = None       # ">=", "<=", "=="
    level: RiskLevel = RiskLevel.LOW
    weight: float = 0.0
    contribution: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class RiskAssessment(BaseModel):
    risk_level: RiskLevel
    risk_score: float = Field(0.0, ge=0.0, le=100.0)
    decision_status: DecisionStatus
    factors: list[RiskFactor] = Field(default_factory=list)
    dominant_factor: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    confidence_drivers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_variables: list[str] = Field(default_factory=list)
    stale_variables: list[str] = Field(default_factory=list)
    evidence_freshness: Freshness = Freshness.UNAVAILABLE
    ruleset_id: str = "orca-marine-v1"
    ruleset_version: str = "1.0.0"
    activity: str = "generic"
    gate_reason: str | None = None
    disclaimer: str = ""
