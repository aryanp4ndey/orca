"""Offline GIS provider: ORCA gazetteer + local boundary layers.

This is the default because it is instant, works with no connectivity, and is
the only geocoder that can be trusted to still answer at 05:30 on a boat.
"""

from __future__ import annotations

from app.core.clock import utcnow
from app.geo.gazetteer import get_gazetteer
from app.geo.layers import layer_catalogue, maritime_band, zones_near
from app.providers.gis.base import GISProvider
from app.schemas.geo import BoundaryLayer, GeoPoint, ResolvedLocation, SpatialRelation


class LocalGISProvider(GISProvider):
    provider_id = "gis_local"
    attribution = "ORCA offline gazetteer and boundary layers (approximate, non-authoritative)"
    access_mechanism = "bundled dataset (no network)"
    verified_access = True

    async def resolve(self, text: str) -> ResolvedLocation | None:
        gz = get_gazetteer()
        place = gz.find(text)
        if place is None:
            hits = gz.search_in_text(text)
            place = hits[0] if hits else None
        return gz.to_resolved(place, text) if place else None

    async def reverse(self, point: GeoPoint) -> ResolvedLocation | None:
        gz = get_gazetteer()
        nearest = gz.nearest(point, limit=1)
        if not nearest:
            return None
        place, dist = nearest[0]
        _, band_label, coast_km = maritime_band(point)
        return ResolvedLocation(
            query=f"{point.lat:.4f},{point.lon:.4f}",
            name=(f"{dist:.0f} km from {place.name}" if dist > 2 else place.name),
            local_names=place.names_dict(), point=point, kind="offshore_point",
            state=place.state, is_marine_point=True,
            distance_to_coast_km=round(coast_km, 2),
            resolver="coordinates", confidence=0.9,
            source_dataset=f"{gz.dataset_id}@{gz.version}",
        )

    async def zones_for(self, point: GeoPoint,
                        radius_km: float = 60.0) -> list[SpatialRelation]:
        return zones_near(point, radius_km)

    def layers(self) -> list[BoundaryLayer]:
        return layer_catalogue()

    def source_note(self) -> dict:
        return {"generated_at": utcnow().isoformat(), "authoritative": False}
