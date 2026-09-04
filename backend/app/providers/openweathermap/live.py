"""OpenWeatherMap live provider — the practical free stand-in for IMD.

Why this source is in ORCA at all: IMD is the authority for Indian coastal
waters, but its API requires an IP whitelist we may not have on demo day. This
is the most generous free atmospheric source we could verify — **60 calls/minute
and 1,000,000 calls/month, with no credit card**, on the classic endpoints.
That is enough to run a real demo on live data.

It is a *secondary* source. The conflict resolver ranks IMD above it, so the
moment an IMD whitelist arrives this drops back to a cross-check without any
other change.

Contract verified against OpenWeatherMap's published documentation:
  current  : GET {base}/weather?lat=&lon=&appid=&units=metric
  forecast : GET {base}/forecast?lat=&lon=&appid=&units=metric   (5 day / 3 h)
  units=metric ⇒ wind in m/s, temperature in °C, visibility in metres,
  rain reported as a 3-hour accumulation in mm.

NOTE: written against the documented contract but not executed from the build
container, which has no outbound network. Run
``python -m app.tools.verify_live --source openweathermap`` on a networked
machine before relying on it.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
from app.schemas.marine import Advisory, Measurement, ProviderQuery, ProviderResult

VARIABLES = (
    "wind_speed_10m", "wind_gust_10m", "wind_direction_10m",
    "precipitation", "visibility", "cloud_cover", "temperature_2m",
)

#: Weather condition codes that matter to a small boat. OpenWeatherMap's 2xx
#: group is thunderstorms; we surface those as an advisory rather than silently
#: folding them into a number.
THUNDERSTORM_GROUP = range(200, 300)
SQUALL_CODES = {771, 781}          # squalls, tornado


class OpenWeatherMapProvider(MarineDataProvider):
    provider_id = "openweathermap"
    source = Source.OPEN_WEATHER_MAP
    origin = DataOrigin.LIVE
    role = "Free live atmospheric conditions (wind, rain, visibility, cloud)"
    attribution = "Weather data from OpenWeather (openweathermap.org)"
    access_mechanism = (
        "public HTTPS JSON API, free API key, no credit card; "
        "60 calls/min and 1,000,000 calls/month on /data/2.5/*")
    verified_access = True
    verification_note = (
        "Endpoints, parameters and units verified against OpenWeatherMap's "
        "published documentation. Not executed from the build container "
        "(no outbound network); verify with "
        "`python -m app.tools.verify_live --source openweathermap`.")

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=VARIABLES,
            datasets=("owm_current", "owm_forecast_3h"),
            update_frequency_seconds=1800,          # OWM refreshes ~every 10-30 min
            max_acceptable_age_seconds=3 * 3600,
            cache_ttl_seconds=900,                  # respect the quota
            supports_advisories=True,
            spatial_coverage="global",
            temporal_coverage="now, plus 5 days at 3-hourly steps",
            notes=("Free tier. Secondary to IMD for Indian waters; used as the "
                   "primary atmospheric source only when IMD is unavailable."),
        ))

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        settings = get_settings()
        key = settings.openweathermap_api_key
        if not key:
            return self.empty_result(
                SourceStatus.NOT_CONFIGURED,
                error=("OpenWeatherMap API key not set. Get a free one (no card) at "
                       "https://home.openweathermap.org/users/sign_up and set "
                       "ORCA_OPENWEATHERMAP_API_KEY."))

        now = utcnow()
        target = ensure_utc(query.valid_time or now)
        # Anything within the next hour is "now"; beyond that we need the
        # 3-hourly forecast and must pick the nearest step.
        use_forecast = (target - now).total_seconds() > 3600

        base = settings.openweathermap_base.rstrip("/")
        params = {"lat": round(query.point.lat, 4), "lon": round(query.point.lon, 4),
                  "appid": key, "units": "metric"}
        path = "/forecast" if use_forecast else "/weather"

        response = await get_http_client().get(f"{base}{path}", params=params)
        if response.status_code == 401:
            return self.empty_result(
                SourceStatus.NOT_CONFIGURED,
                error=("OpenWeatherMap rejected the API key (401). A new key can take "
                       "up to a couple of hours to activate."))
        if response.status_code == 429:
            return self.empty_result(
                SourceStatus.UNAVAILABLE,
                error="OpenWeatherMap rate limit reached (429). ORCA will not guess a value.")
        response.raise_for_status()
        payload = response.json()

        block, valid = (self._pick_forecast_step(payload, target) if use_forecast
                        else (payload, _epoch(payload.get("dt")) or now))
        if block is None:
            raise ProviderPayloadError(
                "OpenWeatherMap forecast contained no usable time step")

        dataset = "owm_forecast_3h" if use_forecast else "owm_current"
        kind = VariableKind.FORECAST if use_forecast else VariableKind.OBSERVED

        measurements = self._measurements(block, query, valid, dataset, kind)
        advisories = self._advisories(block, valid, dataset)

        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset=dataset, status=SourceStatus.OK,
            measurements=measurements, advisories=advisories, retrieved_at=utcnow(),
            extras={"owm_station": payload.get("name"),
                    "grid_lat": (payload.get("coord") or {}).get("lat"),
                    "grid_lon": (payload.get("coord") or {}).get("lon")},
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_forecast_step(payload: dict, target: datetime):
        """Nearest 3-hourly step to the requested instant."""
        steps = payload.get("list")
        if not isinstance(steps, list) or not steps:
            return None, target
        best, best_time, best_delta = None, target, None
        for step in steps:
            when = _epoch(step.get("dt"))
            if when is None:
                continue
            delta = abs((when - target).total_seconds())
            if best_delta is None or delta < best_delta:
                best, best_time, best_delta = step, when, delta
        return best, best_time

    def _measurements(self, block: dict, query: ProviderQuery, valid: datetime,
                      dataset: str, kind: VariableKind) -> list[Measurement]:
        wind = block.get("wind") or {}
        main = block.get("main") or {}
        clouds = block.get("clouds") or {}
        # OWM reports rain as an accumulation over the step ("1h" or "3h").
        rain = block.get("rain") or {}
        rain_mm = rain.get("1h", rain.get("3h"))

        raw = [
            ("wind_speed_10m", wind.get("speed"), "m/s"),
            ("wind_gust_10m", wind.get("gust"), "m/s"),
            ("wind_direction_10m", wind.get("deg"), "deg"),
            ("temperature_2m", main.get("temp"), "degC"),
            ("cloud_cover", clouds.get("all"), "%"),
            ("visibility", block.get("visibility"), "m"),
            ("precipitation", rain_mm, "mm"),
        ]

        wanted = set(query.variables or VARIABLES)
        out: list[Measurement] = []
        for variable, value, unit in raw:
            if variable not in wanted:
                continue
            if value is None:
                # Absent is absent. OWM omits `gust` in calm conditions and
                # `rain` when it is not raining - reporting those as 0 would be
                # inventing an observation, so they are simply not emitted.
                continue
            try:
                converted, canonical_unit = to_canonical(variable, float(value), unit)
            except Exception:  # noqa: BLE001
                continue
            out.append(Measurement(
                variable=variable, value=round(converted, 3), unit=canonical_unit,
                kind=kind, valid_time=valid, issued_at=None, location=query.point,
                quality=QualityFlag.GOOD, dataset=dataset,
                transformation=(f"{unit} -> {canonical_unit}"
                                if unit != canonical_unit else "as reported")))
        return out

    @staticmethod
    def _advisories(block: dict, valid: datetime, dataset: str) -> list[Advisory]:
        """Surface OWM condition codes that a small boat should know about."""
        out: list[Advisory] = []
        for condition in block.get("weather") or []:
            code = condition.get("id")
            if not isinstance(code, int):
                continue
            if code in THUNDERSTORM_GROUP:
                out.append(Advisory(
                    advisory_id=f"owm-tstorm-{int(valid.timestamp())}",
                    category="thunderstorm", severity="warning",
                    headline="Thunderstorm reported in the forecast for this area",
                    detail=str(condition.get("description", "")).capitalize(),
                    issued_at=None, valid_from=valid, dataset=dataset))
            elif code in SQUALL_CODES:
                out.append(Advisory(
                    advisory_id=f"owm-squall-{int(valid.timestamp())}",
                    category="wind", severity="warning",
                    headline="Squall reported in the forecast for this area",
                    detail=str(condition.get("description", "")).capitalize(),
                    issued_at=None, valid_from=valid, dataset=dataset))
        return out


def _epoch(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
