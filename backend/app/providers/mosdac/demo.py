"""Demo MOSDAC provider - satellite Earth Observation.

Role: MOSDAC/ISRO is our *Earth observation* source - satellite-derived sea
surface temperature, ocean colour / chlorophyll, and INSAT cloud imagery.

Two properties of real satellite EO are reproduced here because they change the
architecture, and pretending otherwise would be dishonest:

* **Ocean colour is cloud-limited.**  Under heavy monsoon cloud, an OCM
  chlorophyll retrieval simply does not exist.  The demo returns MISSING with a
  reason rather than a number, which is what exercises ORCA's "optional source
  unavailable, continue safely" path.
* **Archive access is not real-time.**  The published MOSDAC download API is an
  order-based client, so satellite products arrive with hours of latency.  The
  satellite agent is therefore always optional and never gates a safety call.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.core.clock import utcnow
from app.providers.base import MarineDataProvider, ProviderCapability
from app.providers.demo_controls import get_demo_controls
from app.providers.demo_synth import synth
from app.providers.schedules import MOSDAC_OCEANCOLOUR_HOURS, last_issue
from app.schemas.common import (
    DataOrigin,
    QualityFlag,
    Source,
    SourceStatus,
    VariableKind,
)
from app.schemas.marine import Measurement, ProviderQuery, ProviderResult

MOSDAC_VARIABLES = ("sea_surface_temperature", "chlorophyll_a", "cloud_cover")
CLOUD_BLOCK_THRESHOLD = 70.0


class DemoMOSDACProvider(MarineDataProvider):
    provider_id = "mosdac_demo"
    source = Source.MOSDAC
    origin = DataOrigin.DEMO
    role = "Satellite EO: SST, ocean colour / chlorophyll, INSAT cloud imagery"
    attribution = "DEMO FIXTURE modelled on MOSDAC/ISRO satellite product types"
    access_mechanism = "local deterministic fixture (no network)"
    verified_access = True
    verification_note = "Demo provider. Produces synthetic values labelled DEMO end to end."

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=MOSDAC_VARIABLES,
            datasets=("mosdac_demo_oceancolour", "mosdac_demo_insat_sst"),
            update_frequency_seconds=24 * 3600,
            max_acceptable_age_seconds=72 * 3600,
            cache_ttl_seconds=3600,
            spatial_coverage="INSAT/Oceansat footprint over the Indian Ocean",
            temporal_coverage="last available pass",
            notes=("Satellite retrievals are cloud-limited and archive access is "
                   "order-based, so this source is always optional."),
        ))

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        controls = get_demo_controls()
        if "MOSDAC" in controls.fail_sources:
            return self.empty_result(SourceStatus.UNAVAILABLE,
                                     error="DEMO: MOSDAC source injected as unavailable")
        if delay := controls.slow_sources.get("MOSDAC"):
            await asyncio.sleep(delay / 1000.0)

        now = utcnow()
        issued = last_issue(now, MOSDAC_OCEANCOLOUR_HOURS)
        if "MOSDAC" in controls.stale_sources:
            issued = issued - timedelta(days=3)

        # Satellite products describe the last pass, not the requested forecast
        # hour - conflating those is a classic provenance bug, so we keep the
        # valid_time at the pass time.
        s = synth(query.point.lat, query.point.lon, issued, controls.scenario)
        cloudy = s.cloud_cover_pct >= CLOUD_BLOCK_THRESHOLD

        measurements = [
            Measurement(
                variable="sea_surface_temperature", value=round(s.sst_c, 2), unit="degC",
                kind=VariableKind.ANALYSIS, valid_time=issued, issued_at=issued,
                location=query.point, quality=QualityFlag.GOOD,
                dataset="mosdac_demo_insat_sst",
                transformation="demo synthesis (deterministic); satellite pass time"),
            Measurement(
                variable="cloud_cover", value=round(s.cloud_cover_pct, 1), unit="%",
                kind=VariableKind.ANALYSIS, valid_time=issued, issued_at=issued,
                location=query.point, quality=QualityFlag.GOOD,
                dataset="mosdac_demo_insat_sst",
                transformation="demo synthesis (deterministic)"),
            Measurement(
                variable="chlorophyll_a",
                value=None if cloudy else round(s.chlorophyll, 3),
                unit="mg/m^3", kind=VariableKind.ANALYSIS, valid_time=issued,
                issued_at=issued, location=query.point,
                quality=QualityFlag.MISSING if cloudy else QualityFlag.GOOD,
                dataset="mosdac_demo_oceancolour",
                transformation=("no retrieval: cloud cover "
                                f"{s.cloud_cover_pct:.0f}% exceeds ocean-colour threshold"
                                if cloudy else "demo synthesis (deterministic)")),
        ]
        wanted = query.variables or list(MOSDAC_VARIABLES)
        measurements = [m for m in measurements if m.variable in wanted]

        status = SourceStatus.DEGRADED if cloudy else SourceStatus.OK
        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset="mosdac_demo_oceancolour", status=status,
            measurements=measurements, retrieved_at=now,
            error=("ocean-colour retrieval unavailable under cloud" if cloudy else None),
            extras={"issued_at": issued.isoformat(), "cloud_limited": cloudy,
                    "scenario": controls.scenario},
        )
