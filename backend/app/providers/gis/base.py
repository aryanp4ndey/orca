"""GIS provider interface.

GIS is a first-class source in ORCA, not a utility function, because spatial
answers need provenance exactly like marine values do: which gazetteer, which
boundary layer, which version, and whether it is authoritative.
"""

from __future__ import annotations

import abc

from app.schemas.geo import BoundaryLayer, GeoPoint, ResolvedLocation, SpatialRelation


class GISProvider(abc.ABC):
    provider_id: str = "gis_abstract"
    attribution: str = ""
    access_mechanism: str = ""
    verified_access: bool = False

    @abc.abstractmethod
    async def resolve(self, text: str) -> ResolvedLocation | None: ...

    @abc.abstractmethod
    async def reverse(self, point: GeoPoint) -> ResolvedLocation | None: ...

    @abc.abstractmethod
    async def zones_for(self, point: GeoPoint,
                        radius_km: float = 60.0) -> list[SpatialRelation]: ...

    @abc.abstractmethod
    def layers(self) -> list[BoundaryLayer]: ...
