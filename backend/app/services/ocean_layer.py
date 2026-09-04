"""Serves the ocean-colour map layer.

Sits between the OceanSat-2 provider and the API, and owns three things the
provider should not: the cache, in-flight request de-duplication, and the
demo/live decision.

The demo/live decision is the important one, and it is made in exactly one
place:

    demo_mode = true   -> LayerOrigin.DEMO         (deterministic model)
    demo_mode = false  -> LayerOrigin.INCOIS_DATA  (real ERDDAP response)
                          or LayerOrigin.UNAVAILABLE if the call fails

There is no fourth branch. Demo values can never be emitted carrying the
INCOIS_DATA origin, so the frontend can trust the origin field absolutely and
never has to guess from the payload's shape.
"""

from __future__ import annotations

import asyncio
import hashlib
import math

from app.cache.base import Cache
from app.config.settings import Settings
from app.core.clock import utcnow
from app.providers.incois.oceansat import (
    INCOISOceanSatProvider,
    UPDATE_FREQUENCY_SECONDS,
    VARIABLES,
)
from app.schemas.common import Freshness, SourceStatus
from app.schemas.grid import GridCell, LayerOrigin, OceanField

# Demo cell spacing in degrees. Coarser than the real product on purpose: the
# demo layer should be visibly a model, not a convincing forgery of a satellite
# swath.
DEMO_STEP = 0.15


class OceanLayerService:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self.settings = settings
        self.cache = cache
        self.provider = INCOISOceanSatProvider()
        self._inflight: dict[str, asyncio.Future] = {}

    # ---- public ----------------------------------------------------------
    def variables(self) -> list[dict]:
        """What the layer control should offer. Read from the verified contract."""
        return [
            {"id": key, "long_name": spec["long_name"], "unit": spec["unit"],
             "scale": spec["scale"]}
            for key, spec in VARIABLES.items()
        ]

    async def field(self, variable: str, lat: float, lon: float,
                    half_deg: float | None = None) -> OceanField:
        half = half_deg if half_deg is not None else self.settings.oceansat_half_degrees

        if self.settings.demo_mode:
            return _demo_field(variable, lat, lon, half)

        key = _cache_key(variable, lat, lon, half)
        cached = await self.cache.get(key)
        if cached is not None:
            field = OceanField.model_validate(cached.value)
            field.cache_hit = True
            return field

        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._inflight[key] = future
        try:
            field = await self.provider.fetch_field(variable, lat, lon, half)
            field = _decimate(field, self.settings.oceansat_max_cells)
            if field.origin is LayerOrigin.INCOIS_DATA:
                await self.cache.set(key, field.model_dump(mode="json"),
                                     self.settings.oceansat_cache_ttl_seconds)
            if not future.done():
                future.set_result(field)
            return field
        except Exception as exc:                                # noqa: BLE001
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)


def _cache_key(variable: str, lat: float, lon: float, half: float) -> str:
    # Quantised to the demo grid so two nearby users share one upstream call.
    qlat = round(lat * 4) / 4
    qlon = round(lon * 4) / 4
    raw = f"oceansat|{variable}|{qlat}|{qlon}|{half}|{utcnow():%Y%m%d%H}"
    return "ocean_layer:" + hashlib.sha1(raw.encode()).hexdigest()[:20]


def _decimate(field: OceanField, max_cells: int) -> OceanField:
    """Keep the payload small without inventing or moving any cell."""
    if len(field.cells) <= max_cells:
        return field
    step = math.ceil(len(field.cells) / max_cells)
    field.cells = field.cells[::step]
    return field


def _demo_field(variable: str, lat: float, lon: float, half: float) -> OceanField:
    """A deterministic, clearly-labelled stand-in used only in demo mode.

    Labelled ``LayerOrigin.DEMO`` end to end. It exists so the map is
    demonstrable with no network at all; it is never presented as INCOIS.
    """
    spec = VARIABLES.get(variable) or VARIABLES["CHL"]
    lo, hi = spec["typical"]
    cells: list[GridCell] = []
    steps = int((half * 2) / DEMO_STEP) + 1
    for i in range(steps):
        for j in range(steps):
            clat = round(lat - half + i * DEMO_STEP, 4)
            clon = round(lon - half + j * DEMO_STEP, 4)
            # Coastal enrichment: productivity falls off with distance offshore.
            offshore = max(0.0, lon - clon) * 3.0
            swirl = 0.5 + 0.5 * math.sin(clat * 5.1) * math.cos(clon * 4.3)
            t = max(0.0, min(1.0, 0.82 - offshore * 0.35 + swirl * 0.22))
            value = lo * ((hi / lo) ** t)
            cells.append(GridCell(lat=clat, lon=clon,
                                  value=round(value, 4), unit=spec["unit"]))
    values = [c.value for c in cells]
    now = utcnow()
    return OceanField(
        origin=LayerOrigin.DEMO,
        status=SourceStatus.OK,
        source="ORCA demo model",
        provider_id="oceansat_demo",
        dataset="orca_demo_ocean_colour",
        variable=variable,
        long_name=spec["long_name"] + " (DEMO — not INCOIS)",
        unit=spec["unit"],
        product_kind="DEMO MODEL",
        cells=cells,
        bbox=[lat - half, lat + half, lon - half, lon + half],
        value_min=min(values), value_max=max(values),
        observation_time=now, retrieved_at=now,
        freshness=Freshness.FRESH,
        attribution="ORCA deterministic demo model — NOT an INCOIS product",
        request_url="",
        error=None,
    )
