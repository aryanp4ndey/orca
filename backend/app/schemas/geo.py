"""Geospatial contracts. All coordinates are WGS84 / EPSG:4326, lat then lon."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GeoPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)

    def as_geojson(self) -> dict:
        return {"type": "Point", "coordinates": [self.lon, self.lat]}

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.lat:.4f},{self.lon:.4f}"


class BBox(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def contains(self, p: GeoPoint) -> bool:
        return (self.min_lat <= p.lat <= self.max_lat
                and self.min_lon <= p.lon <= self.max_lon)


class GeoJSONGeometry(BaseModel):
    type: Literal["Point", "LineString", "Polygon", "MultiPolygon"]
    coordinates: Any


class LocationKind(str):
    pass


class ResolvedLocation(BaseModel):
    """A user-supplied place name turned into something the system can use."""

    query: str                      # what the user actually said
    name: str                       # canonical name
    local_names: dict[str, str] = Field(default_factory=dict)
    point: GeoPoint                 # the point used for data retrieval
    kind: str = "coastal_town"      # port | coastal_town | landing_centre | offshore_point
    state: str | None = None
    country: str = "IN"
    is_marine_point: bool = True    # is the retrieval point at sea?
    distance_to_coast_km: float | None = None
    resolver: str = "gazetteer"     # gazetteer | coordinates | geocoder | session_context
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source_dataset: str | None = None


class MarineZone(BaseModel):
    """A named polygon a point can be inside or near."""

    zone_id: str
    name: str
    category: str            # eez | territorial | contiguous | fishing_ban | mpa | port_limit | imd_sea_area
    geometry: GeoJSONGeometry
    layer_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class BoundaryLayer(BaseModel):
    """Provenance wrapper around a set of zones.

    Every boundary ORCA reasons about must be able to say where it came from,
    which version, and how authoritative it is. Illustrative layers are marked
    as such and are never used to make a legal claim.
    """

    layer_id: str
    name: str
    category: str
    source: str
    source_url: str | None = None
    version: str
    authoritative: bool = False
    notes: str | None = None
    zone_count: int = 0


class SpatialRelation(BaseModel):
    zone_id: str
    zone_name: str
    layer_id: str
    category: str
    relation: Literal["inside", "outside"]
    distance_km: float | None = None      # to boundary if outside, 0 if inside
    authoritative: bool = False
    #: The zone outline. Carried through so a client can draw the zone it is
    #: being told about - without it the relation is unmappable.
    geometry: GeoJSONGeometry | None = None


class RouteSegment(BaseModel):
    index: int
    start: GeoPoint
    end: GeoPoint
    length_km: float
    midpoint: GeoPoint
    bearing_deg: float
    eta_offset_minutes: float = 0.0
