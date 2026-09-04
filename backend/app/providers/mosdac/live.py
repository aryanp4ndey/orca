"""MOSDAC live provider.

Verified access mechanism (checked 2026-09-02): MOSDAC publishes a *data
download API* whose documented client is a Python script (``mdapi.py``) driven
by a ``config.json``, authenticating with MOSDAC account credentials, searching
by ``datasetId`` with optional ``startTime``/``endTime``/``boundingBox``, capped
at 5000 files per user per day, with a one-hour lockout after three failed
logins.

Two architectural consequences we do not paper over:

1. It is an **archive ordering** interface, not a low-latency point query.  A
   request returns *files* (granules), which must then be downloaded and
   processed.  That is minutes-to-hours, not milliseconds.
2. Therefore MOSDAC is never on the critical path of a safety answer.  The
   satellite agent is optional, its results are cached aggressively, and if it
   is missing the risk engine proceeds without it and says so.

This class implements the *search* half of that workflow, gated behind
credentials.  Granule download and product decoding are deliberately out of
scope for the prototype and are marked as such rather than faked.
"""

from __future__ import annotations

from app.config.settings import get_settings
from app.core.clock import utcnow
from app.providers.base import MarineDataProvider, ProviderCapability
from app.providers.http import get_http_client
from app.schemas.common import DataOrigin, Source, SourceStatus
from app.schemas.marine import ProviderQuery, ProviderResult


class MOSDACLiveProvider(MarineDataProvider):
    provider_id = "mosdac_live"
    source = Source.MOSDAC
    origin = DataOrigin.LIVE
    role = "Satellite EO granule discovery (INSAT / Oceansat products)"
    attribution = "MOSDAC, Space Applications Centre, ISRO"
    access_mechanism = (
        "Account-authenticated data download API (documented client: mdapi.py + "
        "config.json); order-based granule retrieval, 5000 files/user/day")
    verified_access = False
    verification_note = (
        "Access model verified from MOSDAC's published user manual. Granule search "
        "requires MOSDAC account credentials, which this deployment may not hold; "
        "granule download and product decoding are NOT implemented in the prototype.")

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=("sea_surface_temperature", "chlorophyll_a", "cloud_cover"),
            datasets=("3SIMG_L1B_STD",),
            update_frequency_seconds=24 * 3600,
            max_acceptable_age_seconds=72 * 3600,
            cache_ttl_seconds=6 * 3600,
            supports_forecast=False,
            spatial_coverage="INSAT / Oceansat footprint",
            temporal_coverage="archive",
            notes="Order-based archive access; not suitable for real-time gating.",
        ))

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        s = get_settings()
        if not (s.mosdac_username and s.mosdac_password):
            return self.empty_result(
                SourceStatus.NOT_CONFIGURED,
                error=("MOSDAC credentials not configured. Set ORCA_MOSDAC_USERNAME "
                       "and ORCA_MOSDAC_PASSWORD (account from mosdac.gov.in/signup)."))
        # Granule *search* only. We intentionally stop here rather than pretend a
        # decoded geophysical value exists: see the module docstring.
        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset="mosdac_search", status=SourceStatus.DEGRADED,
            measurements=[], retrieved_at=utcnow(),
            error=("MOSDAC granule search is credential-gated and granule decoding "
                   "is not implemented in this prototype; no geophysical values "
                   "returned. Use the demo MOSDAC provider for demonstrations."),
            extras={"bounding_box": _bbox_param(query), "client": "mdapi.py workflow"},
        )


def _bbox_param(query: ProviderQuery) -> str:
    r = (query.radius_km or 50.0) / 111.0
    p = query.point
    return f"{p.lon - r:.3f},{p.lat - r:.3f},{p.lon + r:.3f},{p.lat + r:.3f}"
