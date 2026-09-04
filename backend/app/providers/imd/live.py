"""IMD live provider.

Verified access mechanism (checked 2026-09-02):
  * IMD publishes an API catalogue at https://api.imd.gov.in/public/api_reference.html
    with a base of ``https://api.imd.gov.in/api/v1/`` and endpoints including
    ``current_wx``, ``stationnowcast``, ``districtwarning``, ``portwarning``,
    ``seabulletin``, ``coastalbulletin``, ``cyclone_track``, ``cyclone_wind``,
    ``cyclone_cou``.
  * https://mausam.imd.gov.in/responsive/apis.php states that access requires
    **IP whitelisting by IMD**, that attribution to IMD is required, and that
    clients should cache.

What we have therefore NOT verified: the JSON field names inside each response,
because we cannot call the API from a non-whitelisted host.  Rather than guess
field names and silently mis-map a wind speed, the response mapping lives in
``app/data/providers/imd_fields.json`` and is empty by default.  Until it is
filled in on a whitelisted host, this provider reports NOT_CONFIGURED and ORCA
falls back to whatever other source the planner has - it never invents a value.

That is the whole point of the provider seam: an unverified source degrades to
"absent", not to "made up".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app.config.settings import get_settings
from app.core.clock import ensure_utc, utcnow
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

IMD_ENDPOINTS = {
    "current_wx": "/current_wx",
    "station_nowcast": "/stationnowcast",
    "district_warning": "/districtwarning",
    "port_warning": "/portwarning",
    "sea_bulletin": "/seabulletin",
    "coastal_bulletin": "/coastalbulletin",
    "cyclone_track": "/cyclone_track",
    "cyclone_wind": "/cyclone_wind",
    "cyclone_cone": "/cyclone_cou",
}


def _load_field_map() -> dict:
    path = os.path.join(get_settings().data_dir, "providers", "imd_fields.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class IMDLiveProvider(MarineDataProvider):
    provider_id = "imd_live"
    source = Source.IMD
    origin = DataOrigin.LIVE
    role = "Authoritative Indian atmospheric conditions and marine warnings"
    attribution = "India Meteorological Department (IMD)"
    access_mechanism = (
        "HTTPS JSON at https://api.imd.gov.in/api/v1/ - requires IP whitelisting by IMD")
    verified_access = False
    verification_note = (
        "Endpoint catalogue verified from IMD's published API reference. Response "
        "field names NOT verified (requires a whitelisted host). Provide "
        "app/data/providers/imd_fields.json to enable.")

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=("wind_speed_10m", "wind_direction_10m", "temperature_2m",
                       "precipitation", "visibility", "cloud_cover"),
            datasets=tuple(IMD_ENDPOINTS),
            update_frequency_seconds=3 * 3600,
            max_acceptable_age_seconds=6 * 3600,
            cache_ttl_seconds=900,
            supports_advisories=True,
            spatial_coverage="India, Indian coastal waters and sea areas",
            temporal_coverage="observations plus 5-day warnings",
            notes="Attribution to IMD required; IMD asks clients to cache.",
        ))
        self._fields = _load_field_map()

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        settings = get_settings()
        if not self._fields:
            return self.empty_result(
                SourceStatus.NOT_CONFIGURED,
                error=("IMD response field mapping not supplied. Populate "
                       "app/data/providers/imd_fields.json from a whitelisted host "
                       "(see docs/providers.md). ORCA will not guess field names."))

        base = settings.imd_api_base.rstrip("/")
        client = get_http_client()
        measurements: list[Measurement] = []
        advisories: list[Advisory] = []
        now = utcnow()
        errors: list[str] = []

        for dataset, spec in self._fields.items():
            endpoint = IMD_ENDPOINTS.get(dataset)
            if endpoint is None:
                continue
            try:
                params = dict(spec.get("params", {}))
                if station := query.extras.get("imd_station_id"):
                    params.setdefault("id", station)
                resp = await client.get(f"{base}{endpoint}", params=params)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{dataset}: {type(exc).__name__}: {exc}")
                continue

            rows = payload if isinstance(payload, list) else payload.get(
                spec.get("rows_key", "data"), [])
            if isinstance(rows, dict):
                rows = [rows]
            row = rows[0] if rows else None
            if row is None:
                continue

            issued = _parse_time(row.get(spec.get("issued_field", "")))
            for canonical, field_spec in spec.get("variables", {}).items():
                raw = row.get(field_spec["field"])
                if raw in (None, "", "NA"):
                    continue
                try:
                    value, unit = to_canonical(canonical, float(raw),
                                               field_spec.get("unit", ""))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{dataset}.{canonical}: {exc}")
                    continue
                measurements.append(Measurement(
                    variable=canonical, value=round(value, 3), unit=unit,
                    kind=VariableKind[field_spec.get("kind", "OBSERVED")],
                    valid_time=_parse_time(row.get(spec.get("valid_field", ""))) or now,
                    issued_at=issued, location=query.point, quality=QualityFlag.GOOD,
                    dataset=dataset,
                    transformation=f"{field_spec.get('unit', '')} -> {unit}"))

            for adv_spec in spec.get("advisories", []):
                text = row.get(adv_spec["field"])
                if text:
                    advisories.append(Advisory(
                        advisory_id=f"imd-{dataset}-{int(now.timestamp())}",
                        category=adv_spec.get("category", "warning"),
                        severity=str(row.get(adv_spec.get("severity_field", ""), "advisory")),
                        headline=str(text), issued_at=issued, dataset=dataset))

        if not measurements and not advisories:
            return self.empty_result(
                SourceStatus.ERROR,
                error="; ".join(errors) or "IMD returned no usable rows")

        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset="imd_api_v1",
            status=SourceStatus.DEGRADED if errors else SourceStatus.OK,
            measurements=measurements, advisories=advisories, retrieved_at=now,
            error="; ".join(errors) or None,
        )


def _parse_time(raw) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%d-%m-%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return ensure_utc(datetime.fromisoformat(str(raw)))
    except ValueError:
        return None
