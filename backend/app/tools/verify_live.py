"""Verify live source access from a networked machine.

    python -m app.tools.verify_live
    python -m app.tools.verify_live --source open_meteo

Run this before a live demo. It does not fake anything: for each configured
source it makes one real request and reports exactly what came back, including
which canonical variables could actually be filled. A source that fails here
will report NOT_CONFIGURED or UNAVAILABLE in ORCA - it will never be quietly
substituted with demo data.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

from app.config.settings import get_settings
from app.core.clock import utcnow
from app.providers.http import close_http_client
from app.providers.imd.live import IMDLiveProvider
from app.providers.incois.live import INCOISLiveProvider
from app.providers.mosdac.live import MOSDACLiveProvider
from app.providers.openmeteo.live import OpenMeteoMarineProvider, OpenMeteoWeatherProvider
from app.providers.openweathermap.live import OpenWeatherMapProvider
from app.schemas.geo import GeoPoint
from app.schemas.marine import ProviderQuery

PROVIDERS = {
    "open_meteo_forecast": OpenMeteoWeatherProvider,
    "open_meteo_marine": OpenMeteoMarineProvider,
    "openweathermap": OpenWeatherMapProvider,
    "imd": IMDLiveProvider,
    "incois": INCOISLiveProvider,
    "mosdac": MOSDACLiveProvider,
}
POINT = GeoPoint(lat=9.9312, lon=76.2125)      # off Kochi


async def check(name: str, provider_cls) -> dict:
    provider = provider_cls()
    descriptor = provider.describe()
    query = ProviderQuery(point=POINT, valid_time=utcnow() + timedelta(hours=6),
                          variables=list(provider.capability.variables))
    result = await provider.fetch(query)
    filled = [m.variable for m in result.measurements if m.value is not None]
    return {
        "name": name,
        "provider_id": descriptor.provider_id,
        "access_mechanism": descriptor.access_mechanism,
        "verified_before_run": descriptor.verified,
        "status": result.status.value,
        "latency_ms": result.latency_ms,
        "variables_filled": filled,
        "variables_missing": [v for v in provider.capability.variables if v not in filled],
        "advisories": len(result.advisories),
        "error": result.error,
        "attribution": descriptor.attribution,
    }


async def main_async(args) -> int:
    settings = get_settings()
    print(f"\nORCA live source verification  (demo_mode={settings.demo_mode})")
    print(f"Probe point: {POINT.lat}, {POINT.lon} (off Kochi), +6 h\n")
    if settings.demo_mode:
        print("NOTE: ORCA_DEMO_MODE is true, so the running service will still use "
              "demo providers.\n      This tool probes the LIVE implementations "
              "directly, regardless.\n")

    selected = ({args.source: PROVIDERS[args.source]} if args.source
                else PROVIDERS)
    if args.source and args.source not in PROVIDERS:
        print(f"unknown source {args.source!r}; choose from {list(PROVIDERS)}")
        return 2

    ok = 0
    for name, cls in selected.items():
        report = await check(name, cls)
        marker = "OK  " if report["status"] in ("OK", "DEGRADED") else "FAIL"
        if marker == "OK  ":
            ok += 1
        print(f"[{marker}] {name}")
        print(f"        access   : {report['access_mechanism']}")
        print(f"        status   : {report['status']}  ({report['latency_ms']} ms)")
        if report["variables_filled"]:
            print(f"        filled   : {', '.join(report['variables_filled'])}")
        if report["variables_missing"]:
            print(f"        missing  : {', '.join(report['variables_missing'])}")
        if report["error"]:
            print(f"        error    : {report['error']}")
        print(f"        credit   : {report['attribution']}")
        print()

    await close_http_client()
    print(f"{ok}/{len(selected)} source(s) answered.\n")
    if ok == 0:
        print("No live source answered. ORCA will report every source as unavailable "
              "rather than inventing values.\nRun the demo in ORCA_DEMO_MODE=true.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe ORCA's live data sources")
    parser.add_argument("--source", help=f"one of {list(PROVIDERS)}")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
