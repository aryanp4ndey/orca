"""INCOIS live provider, via the INCOIS ERDDAP server.

Verified access mechanism (checked 2026-09-02): INCOIS runs an ERDDAP instance
at ``https://erddap.incois.gov.in/erddap`` which exposes the standard ERDDAP
RESTful interface - ``/search/index.json`` for discovery, ``/griddap/{id}.json``
and ``/tabledap/{id}.json`` for data, no authentication for public datasets.
ERDDAP's URL grammar is stable across installations, which is what makes this
implementable without guessing.

What is deployment-specific is the *dataset id* and its variable names, so those
live in ``app/data/providers/incois_datasets.json`` rather than being hard-coded.
Run ``python -m app.tools.discover_incois`` on a networked machine to list the
real datasets and fill that file in.  Until then this provider reports
NOT_CONFIGURED.
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
from app.schemas.marine import Measurement, ProviderQuery, ProviderResult


def _load_datasets() -> dict:
    path = os.path.join(get_settings().data_dir, "providers", "incois_datasets.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class INCOISLiveProvider(MarineDataProvider):
    provider_id = "incois_live"
    source = Source.INCOIS
    origin = DataOrigin.LIVE
    role = "Authoritative Indian ocean-state information (waves, currents, SST)"
    attribution = "Indian National Centre for Ocean Information Services (INCOIS)"
    access_mechanism = "ERDDAP RESTful API at https://erddap.incois.gov.in/erddap (public datasets)"
    verified_access = False
    verification_note = (
        "ERDDAP server and URL grammar verified. Dataset ids and variable names "
        "NOT verified from this host; run `python -m app.tools.discover_incois` "
        "and populate app/data/providers/incois_datasets.json.")

    def __init__(self) -> None:
        super().__init__(ProviderCapability(
            variables=("wave_height_significant", "wave_period", "wave_direction",
                       "swell_height", "swell_period", "sea_surface_temperature",
                       "current_speed", "current_direction"),
            datasets=("incois_erddap",),
            update_frequency_seconds=12 * 3600,
            max_acceptable_age_seconds=24 * 3600,
            cache_ttl_seconds=1800,
            spatial_coverage="Indian Ocean region",
            temporal_coverage="dataset dependent",
        ))
        self._datasets = _load_datasets()

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        if not self._datasets:
            return self.empty_result(
                SourceStatus.NOT_CONFIGURED,
                error=("INCOIS ERDDAP dataset mapping not supplied. Run "
                       "`python -m app.tools.discover_incois` on a networked host and "
                       "populate app/data/providers/incois_datasets.json."))

        base = get_settings().incois_erddap_base.rstrip("/")
        client = get_http_client()
        target = ensure_utc(query.valid_time or utcnow())
        now = utcnow()
        measurements: list[Measurement] = []
        errors: list[str] = []

        for ds_id, spec in self._datasets.items():
            wanted = {c: v for c, v in spec.get("variables", {}).items()
                      if not query.variables or c in query.variables}
            if not wanted:
                continue
            t = target.strftime("%Y-%m-%dT%H:%M:%SZ")
            selector = "".join(
                f"[({t})][({query.point.lat})][({query.point.lon})]"
                for _ in [0])
            expr = ",".join(f"{v}{selector}" for v in wanted.values())
            url = f"{base}/griddap/{ds_id}.json?{expr}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{ds_id}: {type(exc).__name__}: {exc}")
                continue

            table = payload.get("table", {})
            col_names = table.get("columnNames", [])
            units = table.get("columnUnits", [])
            rows = table.get("rows", [])
            if not rows:
                errors.append(f"{ds_id}: empty grid response")
                continue
            row = rows[-1]
            tcol = col_names.index("time") if "time" in col_names else 0
            valid = _parse_erddap_time(row[tcol]) or target

            for canonical, api_var in wanted.items():
                if api_var not in col_names:
                    continue
                i = col_names.index(api_var)
                raw = row[i]
                if raw is None:
                    continue
                src_unit = units[i] if i < len(units) and units[i] else ""
                try:
                    value, unit = to_canonical(canonical, float(raw), src_unit)
                    transform = f"{src_unit} -> {unit}" if src_unit else "as reported"
                except Exception:
                    value, unit, transform = float(raw), src_unit, "unit not recognised"
                measurements.append(Measurement(
                    variable=canonical, value=round(value, 3), unit=unit,
                    kind=VariableKind.FORECAST if valid > now else VariableKind.ANALYSIS,
                    valid_time=valid, issued_at=None, location=query.point,
                    quality=QualityFlag.GOOD, dataset=ds_id,
                    transformation=transform))

        if not measurements:
            return self.empty_result(SourceStatus.ERROR,
                                     error="; ".join(errors) or "no INCOIS rows returned")
        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset="incois_erddap",
            status=SourceStatus.DEGRADED if errors else SourceStatus.OK,
            measurements=measurements, retrieved_at=now,
            error="; ".join(errors) or None)


def _parse_erddap_time(raw) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        try:
            return ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except ValueError:
            return None
