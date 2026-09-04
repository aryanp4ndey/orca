"""Typed contracts for a gridded ocean field.

A *field* is different from a `Measurement`: it is many values over a small
bounding box, retrieved for visualisation. It still carries full provenance,
because a map that shows a number without saying where the number came from is
exactly the thing ORCA exists not to be.

`LayerOrigin` is deliberately a separate, explicit enum rather than something the
frontend infers from the shape of the payload:

    INCOIS_DATA  - values came from the INCOIS ERDDAP server
    DEMO         - values came from ORCA's deterministic demo model
    UNAVAILABLE  - no values; the layer must render as unavailable, never as zero
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.common import Freshness, SourceStatus


class LayerOrigin(str, Enum):
    INCOIS_DATA = "INCOIS_DATA"
    DEMO = "DEMO"
    UNAVAILABLE = "UNAVAILABLE"


class GridCell(BaseModel):
    """One source grid cell. `lat`/`lon` are the coordinates ERDDAP returned,
    never a client-side interpolation."""

    lat: float
    lon: float
    value: float
    unit: str


class OceanField(BaseModel):
    """A gridded variable over a bounding box, with its provenance."""

    origin: LayerOrigin
    status: SourceStatus
    source: str = "INCOIS"
    provider_id: str = ""
    dataset: str = ""
    variable: str = ""                 # the source variable name, e.g. "CHL"
    long_name: str = ""
    unit: str = ""
    product_kind: str = "OBSERVATION"  # never "FORECAST" unless metadata says so
    cells: list[GridCell] = Field(default_factory=list)
    bbox: list[float] = Field(default_factory=list)   # lat_min, lat_max, lon_min, lon_max
    value_min: float | None = None
    value_max: float | None = None
    observation_time: datetime | None = None
    retrieved_at: datetime | None = None
    freshness: Freshness = Freshness.UNAVAILABLE
    attribution: str = ""
    request_url: str = ""
    error: str | None = None
    latency_ms: float | None = None
    cache_hit: bool = False

    @property
    def has_data(self) -> bool:
        return bool(self.cells)
