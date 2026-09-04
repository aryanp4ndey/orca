"""Normalised marine data contracts.

Agents depend on *these* types, never on an external API's response shape.
That is what makes a provider swappable: INCOIS ERDDAP, Open-Meteo and a demo
fixture all have to produce the same :class:`Measurement` objects or they do not
get to participate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import (
    DataOrigin,
    Freshness,
    QualityFlag,
    Source,
    SourceStatus,
    VariableKind,
)
from app.schemas.geo import GeoJSONGeometry, GeoPoint


class Measurement(BaseModel):
    """A single normalised value at a single place and time."""

    variable: str
    value: float | None
    unit: str
    kind: VariableKind
    valid_time: datetime                 # the time this value describes
    issued_at: datetime | None = None    # when the source produced it
    location: GeoPoint
    quality: QualityFlag = QualityFlag.GOOD
    transformation: str | None = None
    dataset: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.value is not None and self.quality is not QualityFlag.MISSING


class Advisory(BaseModel):
    """A textual/categorical warning product (IMD bulletins, INCOIS alerts)."""

    advisory_id: str
    category: str            # cyclone | high_wave | swell_surge | thunderstorm | wind | fishermen_warning
    severity: str            # none | watch | advisory | warning | severe
    headline: str
    detail: str | None = None
    issued_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    areas: list[str] = Field(default_factory=list)
    geometry: GeoJSONGeometry | None = None
    dataset: str | None = None


class PFZAdvisory(BaseModel):
    """Potential Fishing Zone advisory - an INCOIS product."""

    advisory_id: str
    issued_at: datetime
    valid_from: datetime
    valid_to: datetime
    region: str
    centroid: GeoPoint
    geometry: GeoJSONGeometry | None = None
    depth_m: float | None = None
    bearing_from_landing_deg: float | None = None
    distance_from_landing_km: float | None = None
    landing_centre: str | None = None
    basis: list[str] = Field(default_factory=list)   # e.g. ["SST front", "chlorophyll"]
    dataset: str | None = None


class CacheInfo(BaseModel):
    hit: bool = False
    key: str | None = None
    stored_at: datetime | None = None
    ttl_seconds: int | None = None


class ProviderResult(BaseModel):
    """Uniform envelope returned by every provider call.

    A provider *never* raises into an agent; it returns one of these with a
    status.  That is what makes graceful degradation possible: the orchestrator
    can always keep going and the user can always be told what was missing.
    """

    provider_id: str
    source: Source
    origin: DataOrigin
    dataset: str
    status: SourceStatus = SourceStatus.OK
    measurements: list[Measurement] = Field(default_factory=list)
    advisories: list[Advisory] = Field(default_factory=list)
    pfz: list[PFZAdvisory] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime | None = None
    latency_ms: float = 0.0
    cache: CacheInfo = Field(default_factory=CacheInfo)
    error: str | None = None
    attribution: str | None = None
    update_frequency_seconds: int | None = None
    max_acceptable_age_seconds: int | None = None
    freshness: Freshness = Freshness.UNAVAILABLE

    @property
    def ok(self) -> bool:
        return self.status in (SourceStatus.OK, SourceStatus.DEGRADED)

    def usable_measurements(self) -> list[Measurement]:
        return [m for m in self.measurements if m.is_usable]


class ProviderQuery(BaseModel):
    """What an agent asks a provider for."""

    point: GeoPoint
    variables: list[str] = Field(default_factory=list)
    valid_time: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    radius_km: float | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
