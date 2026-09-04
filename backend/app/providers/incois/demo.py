"""Demo INCOIS provider - ocean state and PFZ.

Role: INCOIS is our *ocean* authority - significant wave height, swell, period,
currents, sea surface temperature - and the source of Potential Fishing Zone
advisories.  Waves are what capsize a country craft, so this is the source the
risk engine leans on hardest for small-boat activity.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.core.clock import utcnow
from app.geo.geodesy import destination_point, distance_km, initial_bearing_deg
from app.geo.gazetteer import get_gazetteer
from app.providers.base import MarineDataProvider, ProviderCapability
from app.providers.demo_controls import get_demo_controls
from app.providers.demo_synth import _smooth_noise, synth
from app.providers.schedules import INCOIS_OSF_HOURS, INCOIS_PFZ_HOURS, last_issue
from app.schemas.common import (
    DataOrigin,
    QualityFlag,
    Source,
    SourceStatus,
    VariableKind,
)
from app.schemas.geo import GeoJSONGeometry
from app.schemas.marine import (
    Advisory,
    Measurement,
    PFZAdvisory,
    ProviderQuery,
    ProviderResult,
)

INCOIS_VARIABLES = (
    "wave_height_significant", "wave_period", "wave_direction",
    "swell_height", "swell_period", "swell_direction",
    "sea_surface_temperature", "current_speed", "current_direction",
    "wind_speed_10m",
)


class DemoINCOISProvider(MarineDataProvider):
    provider_id = "incois_demo"
    source = Source.INCOIS
    origin = DataOrigin.DEMO
    role = "Ocean state forecast, sea surface temperature, currents, PFZ advisories"
    attribution = "DEMO FIXTURE modelled on INCOIS ocean information product types"
    access_mechanism = "local deterministic fixture (no network)"
    verified_access = True
    verification_note = "Demo provider. Produces synthetic values labelled DEMO end to end."

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=INCOIS_VARIABLES,
            datasets=("incois_demo_ocean_state_forecast", "incois_demo_pfz"),
            update_frequency_seconds=12 * 3600,
            max_acceptable_age_seconds=24 * 3600,
            cache_ttl_seconds=900,
            supports_advisories=True,
            supports_pfz=True,
            spatial_coverage="Indian Ocean region",
            temporal_coverage="now to +5 days",
            notes="Mirrors INCOIS ocean-state and PFZ product types; values are synthetic.",
        ))

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        controls = get_demo_controls()
        if "INCOIS" in controls.fail_sources:
            return self.empty_result(SourceStatus.UNAVAILABLE,
                                     error="DEMO: INCOIS source injected as unavailable")
        if delay := controls.slow_sources.get("INCOIS"):
            await asyncio.sleep(delay / 1000.0)

        now = utcnow()
        valid = query.valid_time or now
        issued = last_issue(now, INCOIS_OSF_HOURS)
        if "INCOIS" in controls.stale_sources:
            issued = issued - timedelta(hours=30)

        s = synth(query.point.lat, query.point.lon, valid, controls.scenario)
        values = {
            "wave_height_significant": (s.wave_height_m, "m"),
            "wave_period": (s.wave_period_s, "s"),
            "wave_direction": (s.wave_direction_deg, "deg"),
            "swell_height": (s.swell_height_m, "m"),
            "swell_period": (s.swell_period_s, "s"),
            "swell_direction": (s.swell_direction_deg, "deg"),
            "sea_surface_temperature": (s.sst_c, "degC"),
            "current_speed": (s.current_speed_kmh, "km/h"),
            "current_direction": (s.current_direction_deg, "deg"),
            "wind_speed_10m": (s.wind_speed_kmh, "km/h"),
        }
        wanted = query.variables or list(INCOIS_VARIABLES)
        measurements = [
            Measurement(
                variable=v, value=round(val, 2), unit=unit,
                kind=VariableKind.FORECAST if valid > now else VariableKind.ANALYSIS,
                valid_time=valid, issued_at=issued, location=query.point,
                quality=QualityFlag.GOOD, dataset="incois_demo_ocean_state_forecast",
                transformation="demo synthesis (deterministic)",
            )
            for v, (val, unit) in values.items() if v in wanted
        ]

        advisories: list[Advisory] = []
        if s.wave_height_m >= 3.0:
            advisories.append(Advisory(
                advisory_id=f"incois-demo-hw-{int(valid.timestamp())}",
                category="high_wave", severity="warning" if s.wave_height_m < 4.5 else "severe",
                headline="High wave alert for the coastal belt",
                detail=(f"DEMO: significant wave height {s.wave_height_m:.1f} m, "
                        f"swell {s.swell_height_m:.1f} m at period {s.swell_period_s:.0f} s."),
                issued_at=issued, valid_from=issued,
                valid_to=issued + timedelta(hours=12),
                areas=[s.basin], dataset="incois_demo_ocean_state_forecast"))
        if s.swell_height_m >= 2.2 and s.swell_period_s >= 13.0:
            advisories.append(Advisory(
                advisory_id=f"incois-demo-swell-{int(valid.timestamp())}",
                category="swell_surge", severity="advisory",
                headline="Swell surge (kallakkadal) conditions possible along the coast",
                detail=f"DEMO: long-period swell {s.swell_height_m:.1f} m / {s.swell_period_s:.0f} s.",
                issued_at=issued, valid_from=issued,
                valid_to=issued + timedelta(hours=18),
                areas=[s.basin], dataset="incois_demo_ocean_state_forecast"))

        pfz = self._pfz(query, now) if query.extras.get("want_pfz") else []

        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset="incois_demo_ocean_state_forecast", status=SourceStatus.OK,
            measurements=measurements, advisories=advisories, pfz=pfz,
            retrieved_at=now,
            extras={"issued_at": issued.isoformat(), "scenario": controls.scenario},
        )

    # ---- PFZ ------------------------------------------------------------
    def _pfz(self, query: ProviderQuery, now) -> list[PFZAdvisory]:
        """Synthesise PFZ candidates seaward of the nearest landing centre.

        Real INCOIS PFZ advisories are derived from satellite SST fronts and
        chlorophyll gradients and are issued per landing centre as a bearing and
        distance.  We reproduce that *shape* so the PFZ agent, the distance
        maths and the map output are all real - the coordinates are synthetic.
        """
        issued = last_issue(now, INCOIS_PFZ_HOURS)
        valid_from = issued
        valid_to = issued + timedelta(hours=24)
        gz = get_gazetteer()
        nearest = gz.nearest(query.point, limit=1)[0][0]
        out: list[PFZAdvisory] = []
        for i in range(3):
            n = _smooth_noise(query.point.lat + i, query.point.lon - i, "pfz", 0.7)
            bearing = (nearest.seaward_bearing + (n - 0.5) * 70.0) % 360.0
            dist = 18.0 + 55.0 * n + 14.0 * i
            centre = destination_point(nearest.point, bearing, dist)
            half = 6.0
            ring = [
                [centre.lon - half / 100.0, centre.lat - half / 110.0],
                [centre.lon + half / 100.0, centre.lat - half / 110.0],
                [centre.lon + half / 100.0, centre.lat + half / 110.0],
                [centre.lon - half / 100.0, centre.lat + half / 110.0],
                [centre.lon - half / 100.0, centre.lat - half / 110.0],
            ]
            out.append(PFZAdvisory(
                advisory_id=f"pfz-demo-{nearest.id}-{i}-{issued.date()}",
                issued_at=issued, valid_from=valid_from, valid_to=valid_to,
                region=f"{nearest.state} coast",
                centroid=centre,
                geometry=GeoJSONGeometry(type="Polygon", coordinates=[ring]),
                depth_m=round(25.0 + 90.0 * n, 0),
                bearing_from_landing_deg=round(bearing, 0),
                distance_from_landing_km=round(dist, 1),
                landing_centre=nearest.name,
                basis=["SST front (demo)", "chlorophyll gradient (demo)"],
                dataset="incois_demo_pfz",
            ))
        out.sort(key=lambda a: distance_km(query.point, a.centroid))
        return out
