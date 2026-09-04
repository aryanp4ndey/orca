"""Prove — or disprove — a live INCOIS ERDDAP data path, end to end.

    python -m app.tools.verify_incois_live                  # discover + probe near Kochi
    python -m app.tools.verify_incois_live --write          # also write the dataset mapping
    python -m app.tools.verify_incois_live --check-orca     # + push it through ORCA's pipeline
    python -m app.tools.verify_incois_live --lat 9.93 --lon 76.21

This tool exists because HTTP 200 is not evidence. It answers, for each candidate
dataset on the INCOIS ERDDAP server:

    exact dataset id · protocol · title · variables · units · lat/lon/time
    dimension names AND THEIR ORDER · spatial resolution · temporal resolution
    latest available timestamp · whether it covers Indian coastal waters
    whether it is observation / analysis / forecast · the exact request URL

and then makes a real subset request at a real coordinate and checks that what
comes back is a finite number with a parseable timestamp.

Nothing here is synthesised. If the server cannot be reached, or returns no
numeric value, the tool says FAIL and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config.settings import get_settings
from app.core.clock import utcnow

# Kochi, off the Kerala coast — the flagship demo location.
DEFAULT_LAT, DEFAULT_LON = 9.9312, 76.2125

# Indian coastal waters, generously bounded. Used only to report coverage.
INDIA_BBOX = (5.0, 25.0, 65.0, 95.0)   # lat_min, lat_max, lon_min, lon_max

# ---------------------------------------------------------------------------
# CF standard names -> ORCA canonical variables.
# Matching on `standard_name` is authoritative (CF is a published convention).
# Name-substring matching is a fallback and is ALWAYS reported as such, so a
# human can audit every mapping before it is trusted.
# ---------------------------------------------------------------------------
CF_STANDARD = {
    "sea_surface_wave_significant_height": "wave_height_significant",
    "significant_height_of_wind_and_swell_waves": "wave_height_significant",
    "sea_surface_wind_wave_significant_height": "wave_height_significant",
    "sea_surface_swell_wave_significant_height": "swell_height",
    "significant_height_of_swell_waves": "swell_height",
    "sea_surface_wave_mean_period": "wave_period",
    "sea_surface_wave_zero_upcrossing_period": "wave_period",
    "sea_surface_wave_period_at_variance_spectral_density_maximum": "wave_period",
    "sea_surface_swell_wave_period": "swell_period",
    "sea_surface_swell_wave_mean_period": "swell_period",
    "sea_surface_wave_from_direction": "wave_direction",
    "sea_surface_wave_to_direction": "wave_direction",
    "sea_surface_swell_wave_from_direction": "swell_direction",
    "sea_surface_temperature": "sea_surface_temperature",
    "sea_water_temperature": "sea_surface_temperature",
    "sea_water_potential_temperature": "sea_surface_temperature",
    "sea_water_speed": "current_speed",
    "direction_of_sea_water_velocity": "current_direction",
    "wind_speed": "wind_speed_10m",
    "eastward_wind": "wind_u",
    "northward_wind": "wind_v",
    "eastward_sea_water_velocity": "current_u",
    "surface_eastward_sea_water_velocity": "current_u",
    "northward_sea_water_velocity": "current_v",
    "surface_northward_sea_water_velocity": "current_v",
}

# Fallback substring rules. Deliberately conservative and always flagged.
NAME_HINTS = [
    (("swell", "height"), "swell_height"),
    (("swell", "period"), "swell_period"),
    (("swell", "dir"), "swell_direction"),
    (("hs",), "wave_height_significant"),
    (("swh",), "wave_height_significant"),
    (("sig", "wave", "height"), "wave_height_significant"),
    (("wave", "height"), "wave_height_significant"),
    (("wave", "period"), "wave_period"),
    (("wave", "dir"), "wave_direction"),
    (("sst",), "sea_surface_temperature"),
    (("sea_surface_temp",), "sea_surface_temperature"),
    (("current", "speed"), "current_speed"),
    (("current", "dir"), "current_direction"),
]

PRIORITY = ["wave_height_significant", "swell_height", "wave_period", "swell_period",
            "current_speed", "current_direction", "sea_surface_temperature",
            "wind_speed_10m"]

DIM_NAMES = {
    "lat": {"latitude", "lat", "y", "nav_lat"},
    "lon": {"longitude", "lon", "long", "x", "nav_lon"},
    "time": {"time", "t"},
}

C = {
    "ok": "\033[92m", "bad": "\033[91m", "warn": "\033[93m",
    "dim": "\033[2m", "b": "\033[1m", "off": "\033[0m",
}
if not sys.stdout.isatty():
    C = {k: "" for k in C}


def say(msg=""):
    print(msg, flush=True)


def rule(ch="─", n=78):
    say(C["dim"] + ch * n + C["off"])


# ---------------------------------------------------------------------------
# ERDDAP access
# ---------------------------------------------------------------------------
class Erddap:
    def __init__(self, base: str, client: httpx.AsyncClient) -> None:
        self.base = base.rstrip("/")
        self.client = client
        self.calls: list[tuple[str, float, int]] = []

    async def get_json(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        t0 = time.perf_counter()
        r = await self.client.get(url, params=params)
        ms = (time.perf_counter() - t0) * 1000
        self.calls.append((str(r.request.url), ms, r.status_code))
        r.raise_for_status()
        return r.json()

    async def get_json_url(self, url: str) -> tuple[dict, float]:
        t0 = time.perf_counter()
        r = await self.client.get(url)
        ms = (time.perf_counter() - t0) * 1000
        self.calls.append((url, ms, r.status_code))
        r.raise_for_status()
        return r.json(), ms

    async def search(self, term: str, limit: int) -> list[dict]:
        data = await self.get_json("/search/index.json",
                                   {"searchFor": term, "page": 1, "itemsPerPage": limit})
        return _rows(data)

    async def info(self, dataset_id: str) -> list[dict]:
        return _rows(await self.get_json(f"/info/{dataset_id}/index.json"))


def _rows(payload: dict) -> list[dict]:
    table = payload.get("table", {})
    cols = table.get("columnNames", [])
    return [dict(zip(cols, row)) for row in table.get("rows", [])]


# ---------------------------------------------------------------------------
# Metadata interpretation
# ---------------------------------------------------------------------------
class Dataset:
    """Everything the integration needs to know, read from the server itself."""

    def __init__(self, dataset_id: str, title: str, protocol: str) -> None:
        self.id = dataset_id
        self.title = title
        self.protocol = protocol            # griddap | tabledap
        self.dim_order: list[str] = []      # AXIS order as ERDDAP declares it
        self.axes: dict[str, dict] = {}     # role -> {name, min, max, n, spacing}
        self.variables: dict[str, dict] = {}  # var name -> {units, standard_name, long_name}
        self.mapping: dict[str, dict] = {}  # canonical -> {var, units, how}
        self.global_attrs: dict[str, str] = {}

    # -- classification ----------------------------------------------------
    @property
    def product_kind(self) -> str:
        """OBSERVATION / ANALYSIS / FORECAST, from the dataset's own metadata."""
        hay = " ".join([
            self.title.lower(),
            self.global_attrs.get("summary", "").lower(),
            self.global_attrs.get("cdm_data_type", "").lower(),
            self.global_attrs.get("title", "").lower(),
        ])
        latest = self.latest_time
        future = bool(latest and latest > utcnow() + timedelta(hours=1))
        if "forecast" in hay or future:
            return "FORECAST" if future else "FORECAST (claimed in metadata)"
        if "analysis" in hay or "reanalysis" in hay or "model" in hay:
            return "ANALYSIS"
        if "observ" in hay or "satellite" in hay or "buoy" in hay or "in situ" in hay:
            return "OBSERVATION"
        return "UNCLASSIFIED"

    @property
    def latest_time(self) -> datetime | None:
        t = self.axes.get("time", {})
        return _parse_time(t.get("max"))

    @property
    def covers_india(self) -> bool | None:
        la, lo = self.axes.get("lat"), self.axes.get("lon")
        if not la or not lo:
            return None
        try:
            lat_ok = float(la["min"]) <= INDIA_BBOX[1] and float(la["max"]) >= INDIA_BBOX[0]
            lon_ok = float(lo["min"]) <= INDIA_BBOX[3] and float(lo["max"]) >= INDIA_BBOX[2]
            return lat_ok and lon_ok
        except (TypeError, ValueError, KeyError):
            return None

    def contains(self, lat: float, lon: float) -> bool | None:
        la, lo = self.axes.get("lat"), self.axes.get("lon")
        if not la or not lo:
            return None
        try:
            return (float(la["min"]) <= lat <= float(la["max"])
                    and float(lo["min"]) <= lon <= float(lo["max"]))
        except (TypeError, ValueError, KeyError):
            return None

    def selector(self, lat: float, lon: float, when: str | None) -> str:
        """Build the ERDDAP index selector in the dataset's OWN axis order.

        Hard-coding [time][lat][lon] breaks on any dataset carrying a depth or
        ensemble axis, so the order comes from the server's metadata.
        """
        parts = []
        for axis in self.dim_order:
            role = _axis_role(axis)
            if role == "time":
                parts.append(f"[({when})]" if when else "[last]")
            elif role == "lat":
                parts.append(f"[({lat})]")
            elif role == "lon":
                parts.append(f"[({lon})]")
            else:
                parts.append("[0]")     # depth / ensemble: take the first level
        return "".join(parts)

    def data_url(self, base: str, canonical: list[str], lat: float, lon: float,
                 when: str | None, fmt: str = "json") -> str:
        sel = self.selector(lat, lon, when)
        varnames = [self.mapping[c]["var"] for c in canonical if c in self.mapping]
        expr = ",".join(f"{v}{sel}" for v in varnames)
        return f"{base.rstrip('/')}/{self.protocol}/{self.id}.{fmt}?{expr}"

    def box_url(self, base: str, canonical: str, lat: float, lon: float,
                half: float, when: str | None, stride: int = 1) -> str:
        """A small bounding box for the map layer — never the whole grid."""
        parts = []
        for axis in self.dim_order:
            role = _axis_role(axis)
            if role == "time":
                parts.append(f"[({when})]" if when else "[last]")
            elif role == "lat":
                parts.append(f"[({lat - half}):{stride}:({lat + half})]")
            elif role == "lon":
                parts.append(f"[({lon - half}):{stride}:({lon + half})]")
            else:
                parts.append("[0]")
        v = self.mapping[canonical]["var"]
        return f"{base.rstrip('/')}/{self.protocol}/{self.id}.json?{v}{''.join(parts)}"


def _axis_role(axis_name: str) -> str:
    a = axis_name.lower()
    for role, names in DIM_NAMES.items():
        if a in names:
            return role
    if a.startswith("lat"):
        return "lat"
    if a.startswith("lon"):
        return "lon"
    return "other"


def _parse_time(raw) -> datetime | None:
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_info(ds: Dataset, rows: list[dict]) -> None:
    """Turn ERDDAP's flat info table into axes, variables and attributes."""
    attr_by_var: dict[str, dict] = {}
    for r in rows:
        rtype = (r.get("Row Type") or "").strip()
        vname = (r.get("Variable Name") or "").strip()
        aname = (r.get("Attribute Name") or "").strip()
        value = r.get("Value")

        if rtype == "attribute" and vname == "NC_GLOBAL":
            ds.global_attrs[aname] = str(value) if value is not None else ""
        elif rtype == "attribute":
            attr_by_var.setdefault(vname, {})[aname] = value
        elif rtype == "dimension":
            ds.dim_order.append(vname)
            spec = {"name": vname}
            # ERDDAP writes e.g. "nValues=1401, evenlySpaced=true, averageSpacing=0.25"
            for piece in str(value or "").split(","):
                if "=" in piece:
                    k, v = piece.split("=", 1)
                    spec[k.strip()] = v.strip()
            ds.axes[_axis_role(vname)] = spec
        elif rtype in ("variable", "axisVariable"):
            ds.variables[vname] = {"data_type": r.get("Data Type")}

    # Fold attributes into axes and variables.
    for vname, attrs in attr_by_var.items():
        role = _axis_role(vname)
        if role in ds.axes and ds.axes[role].get("name") == vname:
            ds.axes[role]["min"] = attrs.get("actual_range", "").split(",")[0].strip() \
                if isinstance(attrs.get("actual_range"), str) else None
            ar = attrs.get("actual_range")
            if isinstance(ar, str) and "," in ar:
                lo, hi = ar.split(",", 1)
                ds.axes[role]["min"] = lo.strip()
                ds.axes[role]["max"] = hi.strip()
            ds.axes[role]["units"] = attrs.get("units")
        if vname in ds.variables:
            ds.variables[vname].update({
                "units": attrs.get("units"),
                "standard_name": attrs.get("standard_name"),
                "long_name": attrs.get("long_name"),
            })

    # Drop axis variables from the measurable-variable list.
    for role, spec in ds.axes.items():
        ds.variables.pop(spec.get("name", ""), None)

    _map_variables(ds)


def _map_variables(ds: Dataset) -> None:
    for vname, meta in ds.variables.items():
        std = (meta.get("standard_name") or "").strip()
        canonical, how = None, ""
        if std in CF_STANDARD:
            canonical, how = CF_STANDARD[std], f"CF standard_name={std}"
        else:
            hay = f"{vname} {meta.get('long_name') or ''}".lower()
            for needles, target in NAME_HINTS:
                if all(n in hay for n in needles):
                    canonical, how = target, f"name heuristic {'+'.join(needles)} (UNVERIFIED)"
                    break
        if canonical and canonical not in ds.mapping:
            ds.mapping[canonical] = {"var": vname, "units": meta.get("units"), "how": how}


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------
async def probe(erd: Erddap, ds: Dataset, lat: float, lon: float,
                canonical: list[str]) -> dict:
    """One real subset request. Returns the parsed values, or an error."""
    url = ds.data_url(erd.base, canonical, lat, lon, None)
    try:
        payload, ms = await erd.get_json_url(url)
    except httpx.HTTPStatusError as e:
        return {"ok": False, "url": url, "error": f"HTTP {e.response.status_code}",
                "body": e.response.text[:240]}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "url": url, "error": f"{type(e).__name__}: {e}"}

    table = payload.get("table", {})
    cols = table.get("columnNames", [])
    units = table.get("columnUnits", [])
    rows = table.get("rows", [])
    if not rows:
        return {"ok": False, "url": url, "error": "empty grid response (no rows)"}

    row = rows[-1]
    out, when = {}, None
    for i, cname in enumerate(cols):
        role = _axis_role(cname)
        if role == "time":
            when = _parse_time(row[i])
            continue
        if role in ("lat", "lon"):
            out[role] = row[i]
            continue
        v = row[i]
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f):
            continue
        out[cname] = {"value": f, "unit": units[i] if i < len(units) else None}

    numeric = {k: v for k, v in out.items() if isinstance(v, dict)}
    if not numeric:
        return {"ok": False, "url": url, "latency_ms": ms,
                "error": "response parsed but contained no finite numeric value "
                         "(land mask, or outside coverage)"}
    return {"ok": True, "url": url, "latency_ms": ms, "values": numeric,
            "time": when, "lat": out.get("lat"), "lon": out.get("lon")}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def describe_dataset(ds: Dataset, lat: float, lon: float) -> None:
    say(f"{C['b']}{ds.id}{C['off']}   {C['dim']}{ds.protocol}{C['off']}")
    say(f"    title            : {ds.title[:96]}")
    say(f"    axis order       : {' × '.join(ds.dim_order) or '(none reported)'}")
    for role in ("time", "lat", "lon"):
        a = ds.axes.get(role)
        if not a:
            continue
        span = f"{a.get('min')} .. {a.get('max')}"
        extra = []
        if a.get("nValues"):
            extra.append(f"n={a['nValues']}")
        if a.get("averageSpacing"):
            extra.append(f"spacing={a['averageSpacing']}")
        say(f"    {role:<16} : {a.get('name')}  [{span}]  {' '.join(extra)}")
    say(f"    product kind     : {ds.product_kind}")
    lt = ds.latest_time
    if lt:
        age = (utcnow() - lt).total_seconds() / 3600
        tense = "in the future" if age < 0 else f"{age:.1f} h old"
        say(f"    latest timestamp : {lt.isoformat()}  ({tense})")
    cov = ds.covers_india
    say(f"    covers India     : {'yes' if cov else 'no' if cov is False else 'unknown'}")
    inside = ds.contains(lat, lon)
    say(f"    contains target  : {'yes' if inside else 'no' if inside is False else 'unknown'}")
    if ds.mapping:
        say("    variable mapping :")
        for canon, m in sorted(ds.mapping.items()):
            flag = C["warn"] + " ← heuristic, verify" + C["off"] \
                if "UNVERIFIED" in m["how"] else ""
            say(f"        {canon:<26} -> {m['var']:<18} "
                f"[{m['units'] or 'no unit'}]  {C['dim']}{m['how']}{C['off']}{flag}")
    else:
        say(f"    variable mapping : {C['warn']}none of ORCA's variables matched{C['off']}")
    say()


def report_block(ds: Dataset, res: dict, canonical_for: dict) -> None:
    rule("═")
    say(f"{C['b']}INCOIS CONNECTION{C['off']}: "
        + (C["ok"] + "SUCCESS" + C["off"] if res["ok"] else C["bad"] + "FAIL" + C["off"]))
    say(f"DATASET          : {ds.id}")
    if not res["ok"]:
        say(f"ERROR            : {res.get('error')}")
        say(f"URL              : {res['url']}")
        rule("═")
        return
    for varname, v in res["values"].items():
        canon = canonical_for.get(varname, "(unmapped)")
        say(f"VARIABLE         : {varname}   → ORCA `{canon}`")
        say(f"VALUE            : {v['value']}")
        say(f"UNIT             : {v['unit'] or '(none declared)'}")
    say(f"LAT              : {res.get('lat')}")
    say(f"LON              : {res.get('lon')}")
    say(f"TIME             : {res['time'].isoformat() if res.get('time') else '(none)'}")
    say(f"PRODUCT KIND     : {ds.product_kind}")
    say(f"ORIGIN           : LIVE")
    say(f"SYNTHETIC FALLBACK: NO")
    say(f"LATENCY          : {res['latency_ms']:.0f} ms (cold)")
    say(f"URL              : {res['url']}")
    rule("═")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
async def run(args) -> int:
    settings = get_settings()
    base = args.base or settings.incois_erddap_base

    say()
    rule("═")
    say(f"{C['b']}ORCA · live INCOIS verification{C['off']}")
    say(f"server : {base}")
    say(f"target : {args.lat}, {args.lon}")
    say(f"time   : {utcnow().isoformat()}")
    rule("═")
    say()

    verify: object = True
    if args.insecure:
        verify = False
        say(f"{C['warn']}!! TLS verification DISABLED (--insecure). Values obtained this "
            f"way are NOT trustworthy for an operational deployment.{C['off']}\n")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=args.timeout, write=10.0, pool=10.0),
        headers={"User-Agent": f"ORCA/{settings.version} (SIH26176 marine decision support)"},
        follow_redirects=True, verify=verify)
    erd = Erddap(base, client)

    # ---- 1. discovery ----------------------------------------------------
    say(f"{C['b']}[1/5] Discovering datasets{C['off']}")
    found: dict[str, Dataset] = {}
    try:
        for term in args.search:
            try:
                for row in await erd.search(term, args.limit):
                    did = row.get("Dataset ID")
                    if not did or did in found or did == "allDatasets":
                        continue
                    proto = "griddap" if row.get("griddap") else "tabledap"
                    found[did] = Dataset(did, row.get("Title", ""), proto)
                say(f"    '{term}' → {len(found)} unique dataset(s) so far")
            except httpx.HTTPStatusError as e:
                say(f"    '{term}' → HTTP {e.response.status_code}")
    except ssl.SSLCertVerificationError as e:
        return await _tls_help(client, e)
    except httpx.ConnectError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            return await _tls_help(client, e)
        say(f"\n{C['bad']}Cannot reach {base}{C['off']}\n    {type(e).__name__}: {e}")
        await client.aclose()
        return 2
    except Exception as e:                                   # noqa: BLE001
        say(f"\n{C['bad']}Discovery failed:{C['off']} {type(e).__name__}: {e}")
        await client.aclose()
        return 2

    if not found:
        say(f"\n{C['bad']}No datasets matched.{C['off']} Try --search with other terms.")
        await client.aclose()
        return 2
    say()

    # ---- 2. metadata -----------------------------------------------------
    say(f"{C['b']}[2/5] Reading metadata for {len(found)} dataset(s){C['off']}\n")
    usable: list[Dataset] = []
    for ds in found.values():
        try:
            parse_info(ds, await erd.info(ds.id))
        except Exception as e:                               # noqa: BLE001
            say(f"{ds.id}: could not describe ({type(e).__name__}: {e})\n")
            continue
        describe_dataset(ds, args.lat, args.lon)
        if ds.mapping and ds.protocol == "griddap" and ds.contains(args.lat, args.lon):
            usable.append(ds)

    if not usable:
        say(f"{C['bad']}No griddap dataset both maps to an ORCA variable and covers "
            f"{args.lat},{args.lon}.{C['off']}")
        say("Nothing written. ORCA will continue to report INCOIS as NOT_CONFIGURED.")
        await client.aclose()
        return 2

    usable.sort(key=lambda d: (
        -len([c for c in PRIORITY if c in d.mapping]),
        PRIORITY.index(next(c for c in PRIORITY if c in d.mapping))
        if any(c in d.mapping for c in PRIORITY) else 99))

    # ---- 3. real query ---------------------------------------------------
    say(f"{C['b']}[3/5] Real subset request at {args.lat}, {args.lon}{C['off']}\n")
    verified: list[tuple[Dataset, dict]] = []
    for ds in usable[:args.max_probe]:
        canon = [c for c in PRIORITY if c in ds.mapping][:4]
        res = await probe(erd, ds, args.lat, args.lon, canon)
        canonical_for = {ds.mapping[c]["var"]: c for c in canon}
        report_block(ds, res, canonical_for)
        say()
        if res["ok"]:
            verified.append((ds, res))

    if not verified:
        say(f"{C['bad']}No dataset returned a usable numeric value at this location."
            f"{C['off']}")
        say("This is a real negative result: the point may be land-masked, or outside")
        say("the model grid. Try a point further offshore with --lat/--lon.")
        await client.aclose()
        return 2

    # ---- 4. warm-cache timing -------------------------------------------
    say(f"{C['b']}[4/5] Repeat request (warm path){C['off']}")
    ds0, res0 = verified[0]
    canon0 = [c for c in PRIORITY if c in ds0.mapping][:4]
    res1 = await probe(erd, ds0, args.lat, args.lon, canon0)
    if res1["ok"]:
        say(f"    cold : {res0['latency_ms']:.0f} ms")
        say(f"    warm : {res1['latency_ms']:.0f} ms   "
            f"{C['dim']}(server/network only — ORCA's own cache is measured "
            f"by --check-orca){C['off']}")
    say()

    # ---- 5. write the mapping -------------------------------------------
    say(f"{C['b']}[5/5] Dataset mapping{C['off']}")
    mapping = {}
    for ds, _ in verified:
        mapping[ds.id] = {
            "kind": ds.protocol,
            "title": ds.title,
            "axis_order": ds.dim_order,
            "product_kind": ds.product_kind,
            "verified_at": utcnow().isoformat(),
            "verified_at_point": [args.lat, args.lon],
            "variables": {c: m["var"] for c, m in ds.mapping.items()},
            "units": {c: m["units"] for c, m in ds.mapping.items()},
            "mapping_basis": {c: m["how"] for c, m in ds.mapping.items()},
        }
    target = os.path.join(settings.data_dir, "providers",
                          "incois_datasets.json" if args.write
                          else "incois_datasets.discovered.json")
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2)
    say(f"    wrote {target}")
    if not args.write:
        say(f"    {C['dim']}re-run with --write to install it as the live mapping{C['off']}")
    heuristics = [f"{d.id}:{c}" for d, _ in verified
                  for c, m in d.mapping.items() if "UNVERIFIED" in m["how"]]
    if heuristics:
        say(f"    {C['warn']}{len(heuristics)} mapping(s) came from a name heuristic, "
            f"not a CF standard_name — check these before trusting them:{C['off']}")
        for h in heuristics:
            say(f"        {h}")
    say()

    await client.aclose()

    # ---- optional: push it through ORCA ---------------------------------
    if args.check_orca:
        return await check_orca(args, verified)

    rule("═")
    say(f"{C['ok']}{C['b']}PASS{C['off']} — {len(verified)} INCOIS dataset(s) returned real "
        f"numeric values at {args.lat}, {args.lon}.")
    say(f"Next: {C['b']}python -m app.tools.verify_incois_live --write --check-orca{C['off']}")
    rule("═")
    return 0


async def _tls_help(client, exc) -> int:
    say(f"\n{C['bad']}TLS certificate verification failed.{C['off']}")
    say(f"    {exc}")
    say()
    say("This is a server-side problem: the INCOIS ERDDAP host does not send a")
    say("complete certificate chain (the intermediate is missing), so a strict")
    say("client cannot build a path to a trusted root.")
    say()
    say("Fixes, best first:")
    say("    1. pip install --upgrade certifi   (then re-run)")
    say("    2. SSL_CERT_FILE=$(python -m certifi) python -m app.tools.verify_incois_live")
    say("    3. Supply the missing intermediate explicitly via SSL_CERT_FILE")
    say(f"    4. {C['warn']}--insecure{C['off']} to inspect the data anyway. Diagnostic only:")
    say("       ORCA will not treat values fetched without verification as trusted.")
    await client.aclose()
    return 3


async def check_orca(args, verified) -> int:
    """Phase 12 items 8 and 9: does ORCA itself receive and surface the values?"""
    from app.providers.incois.live import INCOISLiveProvider
    from app.schemas.marine import GeoPoint, ProviderQuery

    say(f"{C['b']}[+] Pushing the verified dataset through ORCA{C['off']}\n")
    os.environ["ORCA_DEMO_MODE"] = "false"
    os.environ["ORCA_INCOIS_ENABLED"] = "true"
    from app.config.settings import reset_settings_cache
    reset_settings_cache()

    provider = INCOISLiveProvider()
    point = GeoPoint(lat=args.lat, lon=args.lon)
    q = ProviderQuery(point=point, valid_time=utcnow(), variables=())

    t0 = time.perf_counter()
    result = await provider.fetch(q)
    cold = (time.perf_counter() - t0) * 1000

    say(f"    provider status  : {result.status.value}")
    say(f"    provider origin  : {result.origin.value}")
    say(f"    measurements     : {len(result.measurements)}")
    for m in result.measurements:
        say(f"        {m.variable:<26} {m.value} {m.unit}   "
            f"valid={m.valid_time.isoformat() if m.valid_time else '—'}  "
            f"dataset={m.dataset}")
    say(f"    cold fetch       : {cold:.0f} ms")
    if result.error:
        say(f"    error            : {result.error}")
    say()

    ok = (result.status.value in ("OK", "DEGRADED")
          and result.origin.value == "LIVE"
          and result.measurements)
    rule("═")
    if ok:
        say(f"{C['ok']}{C['b']}PASS{C['off']} — ORCA's INCOIS provider returned "
            f"{len(result.measurements)} LIVE measurement(s).")
    else:
        say(f"{C['bad']}{C['b']}FAIL{C['off']} — ORCA did not receive live INCOIS values.")
    rule("═")
    return 0 if ok else 1


async def verify_oceansat(args) -> int:
    """Validate the OceanSat-2 OCM layer contract, end to end.

    dataset · variable · lat · lon · time · numeric values · units · metadata ·
    no synthetic fallback · ORCA receives it · the API payload carries it.
    """
    os.environ["ORCA_DEMO_MODE"] = "false"
    os.environ["ORCA_INCOIS_ENABLED"] = "true"
    from app.config.settings import reset_settings_cache
    reset_settings_cache()

    from app.cache.memory import MemoryCache
    from app.config.settings import get_settings as _gs
    from app.providers.incois.oceansat import DATASET_ID, VARIABLES
    from app.schemas.grid import LayerOrigin
    from app.services.ocean_layer import OceanLayerService

    say()
    rule("═")
    say(f"{C['b']}ORCA · OceanSat-2 OCM layer verification{C['off']}")
    say(f"dataset : {DATASET_ID}")
    say(f"target  : {args.lat}, {args.lon}")
    rule("═")
    say()

    service = OceanLayerService(_gs(), MemoryCache())
    checks: list[tuple[str, bool, str]] = []
    live_ok = False

    for variable in VARIABLES:
        t0 = time.perf_counter()
        field = await service.field(variable, args.lat, args.lon)
        ms = (time.perf_counter() - t0) * 1000

        say(f"{C['b']}{variable}{C['off']}  ({VARIABLES[variable]['long_name']})")
        say(f"    origin        : {field.origin.value}")
        say(f"    status        : {field.status.value}")
        say(f"    cells         : {len(field.cells)}")
        say(f"    url           : {field.request_url}")
        if field.cells:
            c = field.cells[0]
            say(f"    sample        : {c.value} {c.unit}  @ {c.lat}, {c.lon}")
            say(f"    range         : {field.value_min} .. {field.value_max} {field.unit}")
            say(f"    observed      : {field.observation_time}")
            say(f"    retrieved     : {field.retrieved_at}")
            say(f"    freshness     : {field.freshness.value}")
            say(f"    product kind  : {field.product_kind}")
        if field.error:
            say(f"    error         : {field.error}")
        say(f"    latency       : {ms:.0f} ms")
        say()

        if field.origin is LayerOrigin.INCOIS_DATA:
            live_ok = True
            checks.append((f"{variable}: live INCOIS values", True, ""))
            checks.append((f"{variable}: values numeric",
                           all(isinstance(c.value, float) and math.isfinite(c.value)
                               for c in field.cells), ""))
            checks.append((f"{variable}: unit declared", bool(field.unit), ""))
            checks.append((f"{variable}: timestamp present",
                           field.observation_time is not None, ""))
            checks.append((f"{variable}: dataset recorded",
                           field.dataset == DATASET_ID, ""))
            checks.append((f"{variable}: not labelled forecast",
                           field.product_kind == "OBSERVATION", ""))
        else:
            checks.append((f"{variable}: reached INCOIS", False,
                           field.error or "no values"))
        # No synthetic fallback, ever — this must hold in both outcomes.
        checks.append((f"{variable}: no synthetic fallback",
                       field.origin is not LayerOrigin.DEMO,
                       "demo values leaked into live mode" if
                       field.origin is LayerOrigin.DEMO else ""))

    rule("─")
    for name, ok, note in checks:
        mark = (C["ok"] + "PASS" + C["off"]) if ok else (C["bad"] + "FAIL" + C["off"])
        say(f"  {mark}  {name}" + (f"  {C['dim']}{note}{C['off']}" if note else ""))
    rule("═")

    if live_ok:
        say(f"{C['ok']}{C['b']}LIVE INCOIS DATA RECEIVED{C['off']} — the map layer "
            f"will render real values.")
        rc = 0
    else:
        say(f"{C['bad']}{C['b']}NO LIVE INCOIS RESPONSE{C['off']} — this host cannot "
            f"reach the INCOIS server.")
        say("The layer will render INCOIS DATA UNAVAILABLE. No values are shown, and")
        say("nothing synthetic is substituted under the INCOIS label. That is correct")
        say("behaviour, not a silent failure.")
        rc = 2
    rule("═")
    return rc


def main() -> int:
    p = argparse.ArgumentParser(
        description="Prove a live INCOIS ERDDAP data path for ORCA.")
    p.add_argument("--base", default=None, help="ERDDAP base URL")
    p.add_argument("--lat", type=float, default=DEFAULT_LAT)
    p.add_argument("--lon", type=float, default=DEFAULT_LON)
    p.add_argument("--search", nargs="+",
                   default=["wave", "swell", "current", "sst", "temperature"])
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--max-probe", type=int, default=4)
    p.add_argument("--timeout", type=float, default=45.0)
    p.add_argument("--write", action="store_true",
                   help="install the result as incois_datasets.json")
    p.add_argument("--check-orca", action="store_true",
                   help="also run ORCA's own provider against the verified dataset")
    p.add_argument("--insecure", action="store_true",
                   help="skip TLS verification (diagnostic only)")
    p.add_argument("--oceansat", action="store_true",
                   help="verify the OceanSat-2 OCM map layer (CHL/KD490/TSM)")
    args = p.parse_args()
    try:
        if args.oceansat:
            return asyncio.run(verify_oceansat(args))
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
