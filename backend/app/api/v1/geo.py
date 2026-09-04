"""Geometry the frontend needs to draw a map.

ORCA's map is drawn from ORCA's own data. There is no third-party basemap in the
default path, which means the map works with no internet at all - the right
property for a product whose users are on a weak coastal link - and it means we
are never showing a boundary we cannot account for.

Everything returned here already exists in the backend: the coastal baseline,
the boundary layers and the gazetteer. Each feature carries the `authoritative`
flag so the UI can render approximations differently from official data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.geo.gazetteer import get_gazetteer
from app.geo.layers import get_baseline, get_zone_layers, layer_catalogue

router = APIRouter()


@router.get("/geo/basemap", tags=["marine"],
            summary="Coastline, zones and places as GeoJSON for the map")
async def basemap(include_places: bool = Query(True),
                  include_zones: bool = Query(True)) -> dict[str, Any]:
    baseline = get_baseline()
    features: list[dict[str, Any]] = []

    features.append({
        "type": "Feature",
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [[[p.lon, p.lat] for p in line]
                            for line in baseline.polylines],
        },
        "properties": {
            "kind": "coastline",
            "layer_id": "orca_coastal_baseline",
            "name": "Indian coast (approximate baseline)",
            "authoritative": False,
            "dataset": f"{baseline.dataset_id}@{baseline.version}",
            "note": ("Approximate, order 10 km. Not a survey baseline and not for "
                     "navigation."),
        },
    })

    if include_zones:
        for layer in get_zone_layers():
            for zone in layer.zones:
                features.append({
                    "type": "Feature",
                    "geometry": zone.geometry.model_dump(),
                    "properties": {
                        "kind": "zone",
                        "zone_id": zone.zone_id,
                        "name": zone.name,
                        "category": zone.category,
                        "layer_id": layer.meta.layer_id,
                        "authoritative": layer.meta.authoritative,
                        "note": layer.meta.notes,
                        **zone.attributes,
                    },
                })

    if include_places:
        gz = get_gazetteer()
        for place in gz.places.values():
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [place.lon, place.lat]},
                "properties": {
                    "kind": "place",
                    "id": place.id,
                    "name": place.name,
                    "state": place.state,
                    "place_kind": place.kind,
                    "local_names": place.names_dict(),
                    "authoritative": False,
                },
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "layers": [layer.model_dump(mode="json") for layer in layer_catalogue()],
            "crs": "EPSG:4326",
            "note": ("Every layer here is an approximation built for this prototype. "
                     "Nothing in it may be used for navigation or for any legal "
                     "determination of maritime limits."),
        },
    }


@router.get("/geo/places", tags=["marine"],
            summary="Searchable coastal place list for manual location entry")
async def places(q: str | None = Query(None, description="filter by name"),
                 limit: int = Query(60, ge=1, le=200)) -> dict[str, Any]:
    gz = get_gazetteer()
    items = []
    for place in gz.places.values():
        if q:
            needle = q.strip().lower()
            haystack = " ".join([place.name, place.id, place.state,
                                 *place.aliases, *[v for _, v in place.local_names]]).lower()
            if needle not in haystack:
                continue
        items.append({
            "id": place.id, "name": place.name, "state": place.state,
            "kind": place.kind, "lat": place.lat, "lon": place.lon,
            "local_names": place.names_dict(),
            "marine_point": {"lat": place.offshore_point(6.0).lat,
                             "lon": place.offshore_point(6.0).lon},
        })
    items.sort(key=lambda p: p["name"])
    return {"count": len(items), "places": items[:limit],
            "dataset": f"{gz.dataset_id}@{gz.version}",
            "precision_note": gz.precision_note}
