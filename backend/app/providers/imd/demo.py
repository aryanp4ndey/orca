"""Demo IMD provider - atmospheric conditions and marine warnings.

Role split (this matters and judges ask about it): IMD is our *atmospheric and
warning* authority - wind, rainfall, visibility, thunderstorm potential, port
and sea-area warnings, cyclone bulletins.  It is not our wave authority; that is
INCOIS.  The two are not interchangeable and ORCA never treats them as such.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.core.clock import utcnow
from app.providers.base import MarineDataProvider, ProviderCapability
from app.providers.demo_controls import get_demo_controls
from app.providers.demo_synth import synth
from app.providers.schedules import IMD_BULLETIN_HOURS, IMD_NOWCAST_HOURS, last_issue
from app.schemas.common import (
    DataOrigin,
    QualityFlag,
    Source,
    SourceStatus,
    VariableKind,
)
from app.schemas.marine import Advisory, Measurement, ProviderQuery, ProviderResult

IMD_VARIABLES = (
    "wind_speed_10m", "wind_gust_10m", "wind_direction_10m", "precipitation",
    "visibility", "cloud_cover", "temperature_2m", "cape", "thunderstorm_probability",
)


class DemoIMDProvider(MarineDataProvider):
    provider_id = "imd_demo"
    source = Source.IMD
    origin = DataOrigin.DEMO
    role = "Atmospheric conditions, marine/coastal warnings, cyclone bulletins"
    attribution = "DEMO FIXTURE modelled on India Meteorological Department product types"
    access_mechanism = "local deterministic fixture (no network)"
    verified_access = True
    verification_note = "Demo provider. Produces synthetic values labelled DEMO end to end."

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=IMD_VARIABLES,
            datasets=("imd_demo_marine_bulletin", "imd_demo_nowcast"),
            update_frequency_seconds=3 * 3600,      # nowcast cadence
            # A marine bulletin remains the operative advisory until superseded,
            # so the acceptable age spans a full issue cycle rather than the
            # nowcast interval. Getting this wrong made every demo answer read
            # STALE for a third of each day.
            max_acceptable_age_seconds=12 * 3600,
            cache_ttl_seconds=600,
            supports_advisories=True,
            spatial_coverage="India and surrounding seas",
            temporal_coverage="now to +5 days",
            notes="Mirrors the product mix of IMD marine bulletins; values are synthetic.",
        ))

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        controls = get_demo_controls()
        if "IMD" in controls.fail_sources:
            return self.empty_result(SourceStatus.UNAVAILABLE,
                                     error="DEMO: IMD source injected as unavailable")
        if delay := controls.slow_sources.get("IMD"):
            await asyncio.sleep(delay / 1000.0)

        now = utcnow()
        valid = query.valid_time or now
        # Two different products, two different cadences: gridded/nowcast values
        # refresh 3-hourly, the marine bulletin twice a day.
        issued = last_issue(now, IMD_NOWCAST_HOURS)
        bulletin_issued = last_issue(now, IMD_BULLETIN_HOURS)
        if "IMD" in controls.stale_sources:
            issued = issued - timedelta(hours=20)
            bulletin_issued = bulletin_issued - timedelta(hours=20)

        s = synth(query.point.lat, query.point.lon, valid, controls.scenario)
        # Conflict injection perturbs only wind, so the conflict layer has a
        # single, checkable disagreement to resolve.
        wind = s.wind_speed_kmh * (1.55 if controls.inject_conflict else 1.0)

        values = {
            "wind_speed_10m": (wind, "km/h"),
            "wind_gust_10m": (s.wind_gust_kmh, "km/h"),
            "wind_direction_10m": (s.wind_direction_deg, "deg"),
            "precipitation": (s.precipitation_mm, "mm"),
            "visibility": (s.visibility_m, "m"),
            "cloud_cover": (s.cloud_cover_pct, "%"),
            "temperature_2m": (s.temperature_c, "degC"),
            "cape": (s.cape_jkg, "J/kg"),
            "thunderstorm_probability": (s.thunderstorm_prob_pct, "%"),
        }
        wanted = query.variables or list(IMD_VARIABLES)
        measurements = [
            Measurement(
                variable=v, value=round(val, 2), unit=unit,
                kind=VariableKind.FORECAST if valid > now else VariableKind.OBSERVED,
                valid_time=valid, issued_at=issued, location=query.point,
                quality=QualityFlag.GOOD, dataset="imd_demo_marine_bulletin",
                transformation="demo synthesis (deterministic)",
            )
            for v, (val, unit) in values.items() if v in wanted
        ]

        advisories = self._advisories(s, wind, bulletin_issued, valid, query)

        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset="imd_demo_marine_bulletin", status=SourceStatus.OK,
            measurements=measurements, advisories=advisories,
            retrieved_at=now,
            extras={"issued_at": issued.isoformat(), "scenario": controls.scenario},
        )

    def _advisories(self, s, wind: float, issued, valid, query) -> list[Advisory]:
        out: list[Advisory] = []
        if wind >= 62.0 or s.wave_height_m >= 6.0:
            sev, head = "severe", "Cyclonic conditions likely; fishermen advised not to venture out"
            cat = "cyclone"
        elif wind >= 45.0:
            sev, head = "warning", "Squally weather; fishermen advised not to venture into the sea"
            cat = "fishermen_warning"
        elif wind >= 34.0:
            sev, head = "advisory", "Strong winds likely over the coastal waters"
            cat = "wind"
        else:
            sev, head, cat = "none", "No marine wind warning in force", "wind"
        if sev != "none":
            out.append(Advisory(
                advisory_id=f"imd-demo-wind-{int(valid.timestamp())}",
                category=cat, severity=sev, headline=head,
                detail=(f"DEMO advisory derived from synthetic wind of {wind:.0f} km/h "
                        f"at {query.point}."),
                issued_at=issued, valid_from=issued,
                valid_to=issued + timedelta(hours=12),
                areas=[s.basin], dataset="imd_demo_marine_bulletin"))
        if s.thunderstorm_prob_pct >= 55.0:
            out.append(Advisory(
                advisory_id=f"imd-demo-tstorm-{int(valid.timestamp())}",
                category="thunderstorm", severity="warning",
                headline="Thunderstorm with lightning likely over coastal waters",
                detail=f"DEMO: CAPE {s.cape_jkg:.0f} J/kg, probability {s.thunderstorm_prob_pct:.0f}%.",
                issued_at=issued, valid_from=issued,
                valid_to=issued + timedelta(hours=6),
                areas=[s.basin], dataset="imd_demo_nowcast"))
        return out
