"""Open-Meteo live providers (weather + marine).

Why Open-Meteo is in an India-first system: it is the only source in our mix
with a documented, key-free, immediately verifiable HTTP contract, which makes
it the reference implementation for the live path and a genuine fallback when
IMD/INCOIS access is not available on a given host.  It is a *secondary*
source - IMD and INCOIS remain the authorities for Indian waters, and the
conflict layer ranks them above Open-Meteo.

Contract verified against the official documentation on 2026-09-02:
  forecast : https://api.open-meteo.com/v1/forecast    (lat, lon, hourly=...)
  marine   : https://marine-api.open-meteo.com/v1/marine
  response : {"hourly": {"time": [...], "<var>": [...]}, "hourly_units": {...}}
  no API key for non-commercial use; attribution to Open-Meteo and DWD required.

NOTE: written and unit-tested against recorded payloads, but not executed
against the live host from the build container, which has no outbound network.
Run ``python -m app.tools.verify_live`` on a networked machine before a demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config.settings import get_settings
from app.core.clock import ensure_utc, utcnow
from app.core.errors import ProviderPayloadError
from app.core.units import to_canonical
from app.providers.base import MarineDataProvider, ProviderCapability
from app.providers.http import get_http_client
from app.schemas.common import (
    DataOrigin,
    QualityFlag,
    Source,
    SourceStatus,
    VariableKind,
)
from app.schemas.marine import Measurement, ProviderQuery, ProviderResult

# canonical variable  ->  Open-Meteo hourly variable
FORECAST_MAP = {
    "wind_speed_10m": "wind_speed_10m",
    "wind_gust_10m": "wind_gusts_10m",
    "wind_direction_10m": "wind_direction_10m",
    "precipitation": "precipitation",
    "visibility": "visibility",
    "cloud_cover": "cloud_cover",
    "temperature_2m": "temperature_2m",
    "cape": "cape",
}
MARINE_MAP = {
    "wave_height_significant": "wave_height",
    "wave_period": "wave_period",
    "wave_direction": "wave_direction",
    "swell_height": "swell_wave_height",
    "swell_period": "swell_wave_period",
    "swell_direction": "swell_wave_direction",
    "sea_surface_temperature": "sea_surface_temperature",
    "current_speed": "ocean_current_velocity",
    "current_direction": "ocean_current_direction",
}


def _pick_hour(times: list[str], target: datetime) -> int:
    """Index of the hourly step nearest the requested instant."""
    best_i, best_d = 0, None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        d = abs((dt - target).total_seconds())
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i


class _OpenMeteoBase(MarineDataProvider):
    source = Source.OPEN_METEO
    origin = DataOrigin.LIVE
    attribution = "Weather data by Open-Meteo.com (source models incl. DWD, ECMWF, NCEP)"
    access_mechanism = "public HTTPS JSON API, no key required for non-commercial use"
    verified_access = True
    verification_note = (
        "Endpoint, parameters and response shape verified against the official "
        "Open-Meteo documentation. Not executed from the build container "
        "(no outbound network); verify with `python -m app.tools.verify_live`.")
    var_map: dict[str, str] = {}
    base_url_attr = "openmeteo_forecast_base"
    dataset_name = "open_meteo"

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        settings = get_settings()
        wanted = [v for v in (query.variables or list(self.var_map)) if v in self.var_map]
        if not wanted:
            return self.empty_result(SourceStatus.OK, dataset=self.dataset_name)

        target = ensure_utc(query.valid_time or utcnow())
        now = utcnow()
        days = max(1, min(8, int((target - now).total_seconds() // 86400) + 2))
        params = {
            "latitude": round(query.point.lat, 4),
            "longitude": round(query.point.lon, 4),
            "hourly": ",".join(self.var_map[v] for v in wanted),
            "forecast_days": days,
            "timezone": "UTC",
        }
        if target < now - timedelta(hours=1):
            params["past_days"] = 2

        url = getattr(settings, self.base_url_attr)
        resp = await get_http_client().get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

        hourly = payload.get("hourly")
        units = payload.get("hourly_units", {})
        if not isinstance(hourly, dict) or "time" not in hourly:
            raise ProviderPayloadError(
                f"{self.provider_id}: response has no 'hourly.time' array")

        idx = _pick_hour(hourly["time"], target)
        valid_raw = hourly["time"][idx]
        valid = datetime.fromisoformat(valid_raw)
        if valid.tzinfo is None:
            valid = valid.replace(tzinfo=timezone.utc)

        measurements: list[Measurement] = []
        for canonical in wanted:
            api_name = self.var_map[canonical]
            series = hourly.get(api_name)
            if not isinstance(series, list) or idx >= len(series):
                continue
            raw = series[idx]
            if raw is None:
                measurements.append(Measurement(
                    variable=canonical, value=None, unit=units.get(api_name, ""),
                    kind=VariableKind.FORECAST, valid_time=valid, issued_at=None,
                    location=query.point, quality=QualityFlag.MISSING,
                    dataset=self.dataset_name,
                    transformation="source returned null for this hour"))
                continue
            src_unit = units.get(api_name, "")
            try:
                value, unit = to_canonical(canonical, float(raw), src_unit or "")
                transform = (f"{src_unit} -> {unit}" if src_unit and src_unit != unit
                             else "nearest-hour selection")
            except Exception:  # unknown unit: keep the source value and say so
                value, unit = float(raw), src_unit
                transform = "unit not recognised; value passed through unconverted"
            measurements.append(Measurement(
                variable=canonical, value=round(value, 3), unit=unit,
                kind=VariableKind.FORECAST if valid >= now else VariableKind.OBSERVED,
                valid_time=valid, issued_at=None, location=query.point,
                quality=QualityFlag.GOOD, dataset=self.dataset_name,
                transformation=transform))

        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset=self.dataset_name, status=SourceStatus.OK,
            measurements=measurements, retrieved_at=utcnow(),
            extras={"generationtime_ms": payload.get("generationtime_ms"),
                    "model_grid_lat": payload.get("latitude"),
                    "model_grid_lon": payload.get("longitude")},
        )


class OpenMeteoWeatherProvider(_OpenMeteoBase):
    provider_id = "open_meteo_forecast"
    role = "Secondary atmospheric forecast (wind, rain, visibility, CAPE)"
    var_map = FORECAST_MAP
    base_url_attr = "openmeteo_forecast_base"
    dataset_name = "open_meteo_forecast"

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=tuple(FORECAST_MAP),
            datasets=("open_meteo_forecast",),
            update_frequency_seconds=3600,
            max_acceptable_age_seconds=3 * 3600,
            cache_ttl_seconds=900,
            spatial_coverage="global", temporal_coverage="-2 to +8 days hourly",
        ))


class OpenMeteoMarineProvider(_OpenMeteoBase):
    provider_id = "open_meteo_marine"
    role = "Secondary ocean-state forecast (waves, swell, SST, currents)"
    var_map = MARINE_MAP
    base_url_attr = "openmeteo_marine_base"
    dataset_name = "open_meteo_marine"

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=tuple(MARINE_MAP),
            datasets=("open_meteo_marine",),
            update_frequency_seconds=3 * 3600,
            max_acceptable_age_seconds=12 * 3600,
            cache_ttl_seconds=1800,
            spatial_coverage="global ocean", temporal_coverage="-2 to +8 days hourly",
        ))
