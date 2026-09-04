"""INCOIS OceanSat-2 OCM ocean-colour fields, from the INCOIS ERDDAP server.

Dataset (supplied and verified by the team against the official server):

    server    https://erddap.incois.gov.in/erddap
    protocol  griddap
    dataset   incois_oceansat2_datasets
    variables CHL    chlorophyll-a                       mg/m3
              KD490  diffuse attenuation coefficient     m^-1
              TSM    total suspended matter              mg/L

This provider fetches a **small bounding box**, never the whole grid, and returns
the latitudes and longitudes ERDDAP itself reported. It does not interpolate, it
does not fill gaps, and it has no synthetic path: if the request fails, it
returns ``LayerOrigin.UNAVAILABLE`` with the reason, and the map renders that
rather than a value.

Two properties of ocean-colour data that the code takes seriously:

* **Nulls are normal and meaningful.** Cloud, sun-glint and land are masked, and
  ERDDAP returns ``null`` for those cells. A masked cell is dropped, never
  coerced to 0.0 — a zero chlorophyll reading is a claim, and we are not making
  it.
* **This is an OBSERVATION product, not a forecast.** ``product_kind`` is fixed
  to OBSERVATION and the UI is expected to say so. Satellite ocean colour cannot
  answer "tomorrow at 7 AM" and ORCA does not pretend otherwise.

Axis order is configuration, not an assumption: ERDDAP's index selector is
positional, so ``ORCA_OCEANSAT_AXIS_ORDER`` (default ``time,latitude,longitude``,
the near-universal ERDDAP convention) controls how the selector is built. If the
server rejects it, the error is surfaced verbatim rather than retried blindly.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from app.config.settings import get_settings
from app.core.clock import utcnow
from app.providers.http import get_http_client
from app.schemas.common import Freshness, SourceStatus
from app.schemas.grid import GridCell, LayerOrigin, OceanField

PROVIDER_ID = "incois_oceansat2"
DATASET_ID = "incois_oceansat2_datasets"
ATTRIBUTION = ("Indian National Centre for Ocean Information Services (INCOIS) — "
               "OceanSat-2 OCM")

#: The verified variable contract. Units are what the dataset declares; the
#: provider still reads the unit ERDDAP returns and prefers that if present.
VARIABLES: dict[str, dict] = {
    "CHL": {
        "long_name": "Chlorophyll-a concentration",
        "unit": "mg/m3",
        "scale": "log",       # chlorophyll spans orders of magnitude
        "typical": (0.03, 10.0),
    },
    "KD490": {
        "long_name": "Diffuse attenuation coefficient at 490 nm",
        "unit": "m^-1",
        "scale": "log",
        "typical": (0.02, 2.0),
    },
    "TSM": {
        "long_name": "Total suspended matter",
        "unit": "mg/L",
        "scale": "log",
        "typical": (0.1, 50.0),
    },
}

# OceanSat-2 OCM is a daily product; treat anything beyond three days as stale.
UPDATE_FREQUENCY_SECONDS = 24 * 3600
MAX_ACCEPTABLE_AGE_SECONDS = 3 * 24 * 3600


class INCOISOceanSatProvider:
    """Gridded ocean-colour fields for the map layer.

    Not a `MarineDataProvider`: it answers with a *field*, not point
    measurements, and it feeds visualisation rather than the risk engine.
    Ocean-colour variables are not inputs to any rule in ``safety/rules.yaml``,
    and inventing a threshold for them to make the map look integrated would be
    exactly the kind of fabrication ORCA refuses.
    """

    provider_id = PROVIDER_ID
    dataset = DATASET_ID
    attribution = ATTRIBUTION
    access_mechanism = (
        "ERDDAP griddap JSON at https://erddap.incois.gov.in/erddap/griddap/"
        f"{DATASET_ID}.json (public dataset, no key)")

    def __init__(self) -> None:
        self._settings = get_settings()

    # ---- URL construction -------------------------------------------------
    def _axis_order(self) -> list[str]:
        raw = self._settings.oceansat_axis_order
        return [a.strip() for a in raw.split(",") if a.strip()]

    def selector(self, lat_min: float, lat_max: float, lon_min: float,
                 lon_max: float, when: str | None, stride: int) -> str:
        """ERDDAP's positional index selector, built in the dataset's axis order."""
        parts: list[str] = []
        for axis in self._axis_order():
            a = axis.lower()
            if a.startswith("t"):
                parts.append(f"[({when})]" if when else "[last]")
            elif a.startswith("lat") or a == "y":
                parts.append(f"[({lat_min}):{stride}:({lat_max})]")
            elif a.startswith("lon") or a == "x":
                parts.append(f"[({lon_min}):{stride}:({lon_max})]")
            else:
                parts.append("[0]")     # depth / altitude: surface level
        return "".join(parts)

    def build_url(self, variable: str, lat: float, lon: float, half_deg: float,
                  when: str | None = None, stride: int = 1) -> str:
        base = self._settings.incois_erddap_base.rstrip("/")
        sel = self.selector(lat - half_deg, lat + half_deg,
                            lon - half_deg, lon + half_deg, when, stride)
        expr = f"{variable}{sel}".replace("[", "%5B").replace("]", "%5D")
        return f"{base}/griddap/{DATASET_ID}.json?{expr}"

    # ---- fetch ------------------------------------------------------------
    async def fetch_field(self, variable: str, lat: float, lon: float,
                          half_deg: float = 0.75, when: str | None = None,
                          stride: int = 1) -> OceanField:
        spec = VARIABLES.get(variable)
        if spec is None:
            return self._unavailable(
                variable, lat, lon, half_deg, SourceStatus.NOT_CONFIGURED,
                f"{variable!r} is not one of the verified OceanSat-2 variables "
                f"({', '.join(VARIABLES)}).")

        if not self._settings.incois_enabled:
            return self._unavailable(
                variable, lat, lon, half_deg, SourceStatus.NOT_CONFIGURED,
                "INCOIS is not enabled. Set ORCA_DEMO_MODE=false and "
                "ORCA_INCOIS_ENABLED=true to call the real ERDDAP server.")

        url = self.build_url(variable, lat, lon, half_deg, when, stride)
        started = time.perf_counter()
        try:
            response = await get_http_client().get(url)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:                                # noqa: BLE001
            status = (SourceStatus.TIMEOUT
                      if "timeout" in type(exc).__name__.lower()
                      or "timed out" in str(exc).lower()
                      else SourceStatus.UNAVAILABLE)
            return self._unavailable(
                variable, lat, lon, half_deg, status,
                f"{type(exc).__name__}: {exc}", url=url,
                latency_ms=(time.perf_counter() - started) * 1000)

        latency_ms = (time.perf_counter() - started) * 1000
        return self._parse(payload, variable, spec, lat, lon, half_deg, url,
                           latency_ms)

    # ---- parsing ----------------------------------------------------------
    def _parse(self, payload: dict, variable: str, spec: dict, lat: float,
               lon: float, half_deg: float, url: str,
               latency_ms: float) -> OceanField:
        table = payload.get("table") or {}
        cols: list[str] = table.get("columnNames") or []
        units: list = table.get("columnUnits") or []
        rows: list = table.get("rows") or []

        if not cols or not rows:
            return self._unavailable(
                variable, lat, lon, half_deg, SourceStatus.UNAVAILABLE,
                "ERDDAP returned no rows for this box.", url=url,
                latency_ms=latency_ms)

        idx = {name.lower(): i for i, name in enumerate(cols)}
        i_lat = _first(idx, ("latitude", "lat", "y"))
        i_lon = _first(idx, ("longitude", "lon", "x"))
        i_time = _first(idx, ("time", "t"))
        i_val = next((i for i, c in enumerate(cols)
                      if c.upper() == variable.upper()), None)

        if i_lat is None or i_lon is None or i_val is None:
            return self._unavailable(
                variable, lat, lon, half_deg, SourceStatus.ERROR,
                f"Unexpected ERDDAP columns {cols!r}; cannot locate "
                f"latitude/longitude/{variable}.", url=url, latency_ms=latency_ms)

        declared_unit = ""
        if i_val < len(units) and units[i_val]:
            declared_unit = str(units[i_val])
        unit = declared_unit or spec["unit"]

        cells: list[GridCell] = []
        observation_time: datetime | None = None
        for row in rows:
            raw = row[i_val]
            if raw is None:                     # cloud / land / glint mask
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            try:
                clat, clon = float(row[i_lat]), float(row[i_lon])
            except (TypeError, ValueError):
                continue
            cells.append(GridCell(lat=clat, lon=clon, value=value, unit=unit))
            if observation_time is None and i_time is not None:
                observation_time = _parse_time(row[i_time])

        if not cells:
            return self._unavailable(
                variable, lat, lon, half_deg, SourceStatus.UNAVAILABLE,
                "Every cell in this box was masked (cloud, sun-glint or land). "
                "No value is available here — this is a real gap, not an error.",
                url=url, latency_ms=latency_ms,
                observation_time=observation_time)

        values = [c.value for c in cells]
        now = utcnow()
        return OceanField(
            origin=LayerOrigin.INCOIS_DATA,
            status=SourceStatus.OK,
            source="INCOIS",
            provider_id=self.provider_id,
            dataset=DATASET_ID,
            variable=variable,
            long_name=spec["long_name"],
            unit=unit,
            product_kind="OBSERVATION",
            cells=cells,
            bbox=[lat - half_deg, lat + half_deg, lon - half_deg, lon + half_deg],
            value_min=min(values),
            value_max=max(values),
            observation_time=observation_time,
            retrieved_at=now,
            freshness=_freshness(observation_time, now),
            attribution=ATTRIBUTION,
            request_url=url,
            latency_ms=round(latency_ms, 1),
        )

    # ---- failure ----------------------------------------------------------
    def _unavailable(self, variable: str, lat: float, lon: float, half_deg: float,
                     status: SourceStatus, error: str, url: str = "",
                     latency_ms: float | None = None,
                     observation_time: datetime | None = None) -> OceanField:
        spec = VARIABLES.get(variable, {})
        return OceanField(
            origin=LayerOrigin.UNAVAILABLE,
            status=status,
            source="INCOIS",
            provider_id=self.provider_id,
            dataset=DATASET_ID,
            variable=variable,
            long_name=spec.get("long_name", variable),
            unit=spec.get("unit", ""),
            product_kind="OBSERVATION",
            cells=[],
            bbox=[lat - half_deg, lat + half_deg, lon - half_deg, lon + half_deg],
            observation_time=observation_time,
            retrieved_at=utcnow(),
            freshness=Freshness.UNAVAILABLE,
            attribution=ATTRIBUTION,
            request_url=url or self.build_url(variable, lat, lon, half_deg),
            error=error,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
        )


def _first(idx: dict, names: tuple[str, ...]) -> int | None:
    for n in names:
        if n in idx:
            return idx[n]
    return None


def _parse_time(raw) -> datetime | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
            timezone.utc)
    except ValueError:
        return None


def _freshness(observed: datetime | None, now: datetime) -> Freshness:
    if observed is None:
        return Freshness.UNAVAILABLE
    age = (now - observed).total_seconds()
    if age <= UPDATE_FREQUENCY_SECONDS:
        return Freshness.FRESH
    if age <= MAX_ACCEPTABLE_AGE_SECONDS:
        return Freshness.AGING
    return Freshness.STALE
