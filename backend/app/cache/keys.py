"""Deterministic cache keys.

Keys are quantised on purpose: marine forecasts are gridded, so two fishermen
2 km apart asking about the same hour should share one upstream call.  That is
where most of the request-deduplication win comes from on a coastal network.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.schemas.geo import GeoPoint

GRID_DEG = 0.25          # ~27 km - matches typical global marine model spacing
TIME_BUCKET_MINUTES = 60


def quantise_point(p: GeoPoint, grid: float = GRID_DEG) -> tuple[float, float]:
    return (round(round(p.lat / grid) * grid, 4), round(round(p.lon / grid) * grid, 4))


def quantise_time(t: datetime, minutes: int = TIME_BUCKET_MINUTES) -> str:
    epoch = int(t.timestamp())
    bucket = epoch - (epoch % (minutes * 60))
    return str(bucket)


def provider_key(provider_id: str, dataset: str, p: GeoPoint,
                 valid_time: datetime | None, variables: list[str],
                 variant: str | None = None) -> str:
    """Key for one provider call.

    ``variant`` carries anything else that changes the value. In demo mode that
    is the scenario and the failure switches: flipping ORCA_DEMO_SCENARIO while
    the process is running must produce new values, not the previous scenario's
    cached ones. A cache key that omits an input is a correctness bug, not a
    performance detail.
    """
    lat, lon = quantise_point(p)
    tpart = quantise_time(valid_time) if valid_time else "now"
    vpart = hashlib.sha1(",".join(sorted(variables)).encode()).hexdigest()[:8]
    key = f"prov:{provider_id}:{dataset}:{lat}:{lon}:{tpart}:{vpart}"
    return f"{key}:{variant}" if variant else key


def geocode_key(query: str) -> str:
    return f"geo:{query.strip().lower()}"
