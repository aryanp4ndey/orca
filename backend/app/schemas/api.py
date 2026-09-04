"""Public API contracts - the frontend team's source of truth."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import DataOrigin, Freshness, Intent, Language
from app.schemas.evidence import Conflict, Evidence, SourceReport
from app.schemas.geo import GeoPoint
from app.schemas.risk import RiskAssessment


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000,
                       examples=["Is it safe to go fishing from Kochi tomorrow at 7 AM?"])
    session_id: str | None = Field(None, description="Carry this back to keep multi-turn context.")
    language: Language | None = Field(None, description="Override auto-detection.")
    lat: float | None = Field(None, ge=-90, le=90, description="Device location, if shared.")
    lon: float | None = Field(None, ge=-180, le=180)
    activity: str | None = None
    vessel: str | None = None
    low_bandwidth: bool = Field(False, description="Drop map geometry and trim payload.")
    include_trace: bool | None = None


class LatencyBreakdown(BaseModel):
    total_ms: float = 0.0
    nlu_ms: float = 0.0
    planning_ms: float = 0.0
    agents_ms: float = 0.0
    providers_ms: float = 0.0
    risk_ms: float = 0.0
    response_ms: float = 0.0
    per_agent_ms: dict[str, float] = Field(default_factory=dict)
    per_provider_ms: dict[str, float] = Field(default_factory=dict)
    parallel_saving_ms: float = 0.0
    llm_ms: float = 0.0


class FreshnessSummary(BaseModel):
    overall: Freshness = Freshness.UNAVAILABLE
    oldest_evidence_age_seconds: float | None = None
    per_source: dict[str, str] = Field(default_factory=dict)
    stale_sources: list[str] = Field(default_factory=list)


class MapLayerOut(BaseModel):
    layer_id: str
    name: str
    kind: str            # marker | polygon | line | heat
    geojson: dict[str, Any]
    style_hint: str | None = None
    source: str | None = None


class Visualizations(BaseModel):
    markers: list[dict[str, Any]] = Field(default_factory=list)
    layers: list[MapLayerOut] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)


class TraceSpan(BaseModel):
    name: str
    kind: str
    start_ms: float
    duration_ms: float
    status: str = "OK"
    attributes: dict[str, Any] = Field(default_factory=dict)


class QueryTrace(BaseModel):
    query_id: str
    plan: dict[str, Any] = Field(default_factory=dict)
    spans: list[TraceSpan] = Field(default_factory=list)
    cache: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    query_id: str
    session_id: str
    answer: str
    answer_language: Language
    data_origin: DataOrigin
    demo_mode: bool
    intent: dict[str, Any]
    location: dict[str, Any] | None = None
    time: dict[str, Any] | None = None
    activity: str
    risk: RiskAssessment | None = None
    factors: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[SourceReport] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    freshness: FreshnessSummary = Field(default_factory=FreshnessSummary)
    visualizations: Visualizations = Field(default_factory=Visualizations)
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
    trace: QueryTrace | None = None
    disclaimer: str = ""
    generated_at: datetime | None = None
    follow_up_suggestions: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    demo_mode: bool
    data_origin: DataOrigin
    uptime_seconds: float
    providers: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    llm: dict[str, Any] = Field(default_factory=dict)
    cache: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    time_utc: datetime | None = None


class MarineStatusResponse(BaseModel):
    location: dict[str, Any]
    point: GeoPoint
    valid_time: datetime
    weather: dict[str, Any] = Field(default_factory=dict)
    ocean: dict[str, Any] = Field(default_factory=dict)
    risk: RiskAssessment | None = None
    sources: list[SourceReport] = Field(default_factory=list)
    freshness: FreshnessSummary = Field(default_factory=FreshnessSummary)
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)


class RouteRiskRequest(BaseModel):
    start: GeoPoint
    end: GeoPoint
    depart_at: datetime | None = None
    speed_knots: float = Field(8.0, gt=0, le=40)
    activity: str = "fishing_small_boat"
    vessel: str = "small_motorised"
    samples: int = Field(8, ge=2, le=30)


class RouteRiskResponse(BaseModel):
    query_id: str
    start: GeoPoint
    end: GeoPoint
    total_distance_km: float
    estimated_duration_hours: float
    overall_risk: RiskAssessment
    segments: list[dict[str, Any]] = Field(default_factory=list)
    hazardous_segments: list[int] = Field(default_factory=list)
    geojson: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    sources: list[SourceReport] = Field(default_factory=list)
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
    disclaimer: str = ""
