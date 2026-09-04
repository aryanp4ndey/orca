"""Boundary layers with mandatory provenance.

Two kinds of layer live here:

**Derived bands** - territorial sea / contiguous zone / EEZ distance bands
computed from ORCA's coarse coastal baseline.  These are *calculations*, not
claims about notified limits, and they are flagged ``authoritative=False`` with
an explicit disclaimer everywhere they surface.

**Illustrative zones** - rectangles that exist so the geofencing, alerting and
route-avoidance code paths are real and testable.  Also flagged non-authoritative.

Nothing here invents an official boundary.  ``docs/providers.md`` documents how
to drop authoritative polygons (Marine Regions EEZ, notified restricted areas)
into ``app/data/boundaries/`` and have them take over.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache

from app.geo.geodesy import NM_IN_KM, densify, distance_km, point_to_segment_km
from app.geo.polygons import distance_to_geometry_km, geometry_centroid, point_in_geometry
from app.schemas.geo import BoundaryLayer, GeoJSONGeometry, GeoPoint, MarineZone, SpatialRelation

# UNCLOS distance bands, measured from the baseline.  The *numbers* are the
# treaty definitions; the *baseline* we measure from is our approximation.
MARITIME_BANDS = [
    ("territorial_waters", "Territorial waters (within ~12 NM of the coast)", 12.0),
    ("contiguous_zone", "Contiguous zone (~12-24 NM)", 24.0),
    ("eez", "Exclusive Economic Zone (~24-200 NM)", 200.0),
]


@dataclass
class CoastalBaseline:
    dataset_id: str
    version: str
    authoritative: bool
    description: str
    polylines: list[list[GeoPoint]]

    def distance_to_coast_km(self, p: GeoPoint) -> float:
        best = float("inf")
        for line in self.polylines:
            for i in range(len(line) - 1):
                best = min(best, point_to_segment_km(p, line[i], line[i + 1]))
        return best

    def nearest_coast_point(self, p: GeoPoint) -> GeoPoint:
        best, best_pt = float("inf"), None
        for line in self.polylines:
            for i in range(len(line) - 1):
                for cand in densify(line[i], line[i + 1], 6):
                    d = distance_km(p, cand)
                    if d < best:
                        best, best_pt = d, cand
        assert best_pt is not None
        return best_pt


@lru_cache(maxsize=1)
def get_baseline() -> CoastalBaseline:
    from app.config.settings import get_settings
    from app.geo.gazetteer import get_gazetteer

    path = os.path.join(get_settings().data_dir, "boundaries", "coastline.json")
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    gz = get_gazetteer()
    polylines: list[list[GeoPoint]] = []
    for seg in raw["segments"]:
        pts = [gz.get(pid).point for pid in seg["place_ids"] if gz.get(pid)]
        if len(pts) >= 2:
            # densify so distance-to-coast is smooth rather than vertex-biased
            dense: list[GeoPoint] = []
            for i in range(len(pts) - 1):
                dense.extend(densify(pts[i], pts[i + 1], 5)[:-1])
            dense.append(pts[-1])
            polylines.append(dense)
    return CoastalBaseline(
        dataset_id=raw["dataset_id"], version=raw["version"],
        authoritative=raw.get("authoritative", False),
        description=raw["description"], polylines=polylines,
    )


@dataclass
class ZoneLayer:
    meta: BoundaryLayer
    zones: list[MarineZone]


def _bbox_polygon(bbox: list[float]) -> GeoJSONGeometry:
    min_lat, min_lon, max_lat, max_lon = bbox
    ring = [[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat],
            [min_lon, max_lat], [min_lon, min_lat]]
    return GeoJSONGeometry(type="Polygon", coordinates=[ring])


@lru_cache(maxsize=1)
def get_zone_layers() -> list[ZoneLayer]:
    from app.config.settings import get_settings

    path = os.path.join(get_settings().data_dir, "boundaries", "zones.json")
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    out: list[ZoneLayer] = []
    for layer in raw["layers"]:
        zones = [
            MarineZone(
                zone_id=z["zone_id"], name=z["name"], category=layer["category"],
                geometry=_bbox_polygon(z["bbox"]), layer_id=layer["layer_id"],
                attributes=z.get("attributes", {}),
            )
            for z in layer["zones"]
        ]
        out.append(ZoneLayer(
            meta=BoundaryLayer(
                layer_id=layer["layer_id"], name=layer["name"],
                category=layer["category"], source=layer["source"],
                source_url=layer.get("source_url"), version=raw["version"],
                authoritative=layer.get("authoritative", False),
                notes=layer.get("notes"), zone_count=len(zones),
            ),
            zones=zones,
        ))
    return out


def maritime_band(p: GeoPoint) -> tuple[str, str, float]:
    """Which derived maritime band a point falls in, plus distance to coast."""
    d_km = get_baseline().distance_to_coast_km(p)
    d_nm = d_km / NM_IN_KM
    for zone_id, label, limit_nm in MARITIME_BANDS:
        if d_nm <= limit_nm:
            return zone_id, label, d_km
    return "high_seas", "Beyond ~200 NM of the coast", d_km


def zones_containing(p: GeoPoint) -> list[SpatialRelation]:
    rels: list[SpatialRelation] = []
    for layer in get_zone_layers():
        for z in layer.zones:
            geom = z.geometry.model_dump()
            inside = point_in_geometry(p, geom)
            if inside:
                rels.append(SpatialRelation(
                    zone_id=z.zone_id, zone_name=z.name, layer_id=z.layer_id,
                    category=z.category, relation="inside", distance_km=0.0,
                    authoritative=layer.meta.authoritative, geometry=z.geometry))
    return rels


def zones_near(p: GeoPoint, radius_km: float = 60.0) -> list[SpatialRelation]:
    rels: list[SpatialRelation] = []
    for layer in get_zone_layers():
        for z in layer.zones:
            geom = z.geometry.model_dump()
            d = distance_to_geometry_km(p, geom)
            if d <= radius_km:
                rels.append(SpatialRelation(
                    zone_id=z.zone_id, zone_name=z.name, layer_id=z.layer_id,
                    category=z.category,
                    relation="inside" if d == 0.0 else "outside",
                    distance_km=round(d, 2),
                    authoritative=layer.meta.authoritative, geometry=z.geometry))
    rels.sort(key=lambda r: (r.distance_km if r.distance_km is not None else 1e9))
    return rels


def zone_centroid(zone: MarineZone) -> GeoPoint:
    return geometry_centroid(zone.geometry.model_dump())


def layer_catalogue() -> list[BoundaryLayer]:
    base = get_baseline()
    layers = [
        BoundaryLayer(
            layer_id="orca_coastal_baseline", name="ORCA coastal baseline (approximate)",
            category="baseline", source="Derived from ORCA gazetteer settlement coordinates",
            version=base.version, authoritative=False, notes=base.description,
            zone_count=len(base.polylines),
        ),
        BoundaryLayer(
            layer_id="derived_maritime_bands",
            name="Derived maritime distance bands (territorial / contiguous / EEZ)",
            category="maritime_band",
            source="UNCLOS distance definitions applied to the ORCA coastal baseline",
            version=base.version, authoritative=False,
            notes=("Distance bands computed from an approximate baseline. Indicative only; "
                   "not a determination of India's notified maritime limits."),
            zone_count=len(MARITIME_BANDS),
        ),
    ]
    layers.extend(l.meta for l in get_zone_layers())
    return layers
