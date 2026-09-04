"""List real datasets on the INCOIS ERDDAP server.

    python -m app.tools.discover_incois
    python -m app.tools.discover_incois --search wave --write

ERDDAP exposes a documented search endpoint, so dataset discovery is a real
operation rather than a guess. Use this on a networked machine to find the
dataset ids and variable names, then write them into
``app/data/providers/incois_datasets.json``. Until that file exists the INCOIS
live provider reports NOT_CONFIGURED - by design.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from app.config.settings import get_settings
from app.providers.http import close_http_client, get_http_client


async def search(base: str, term: str, limit: int) -> list[dict]:
    url = f"{base.rstrip('/')}/search/index.json"
    params = {"searchFor": term, "page": 1, "itemsPerPage": limit}
    response = await get_http_client().get(url, params=params)
    response.raise_for_status()
    table = response.json()["table"]
    columns = table["columnNames"]
    return [dict(zip(columns, row)) for row in table["rows"]]


async def describe(base: str, dataset_id: str) -> list[dict]:
    url = f"{base.rstrip('/')}/info/{dataset_id}/index.json"
    response = await get_http_client().get(url)
    response.raise_for_status()
    table = response.json()["table"]
    columns = table["columnNames"]
    rows = [dict(zip(columns, row)) for row in table["rows"]]
    return [r for r in rows
            if r.get("Row Type") == "variable" and r.get("Variable Name") != "time"]


async def main_async(args) -> int:
    base = args.base or get_settings().incois_erddap_base
    print(f"\nQuerying ERDDAP at {base} for {args.search!r} ...\n")
    try:
        datasets = await search(base, args.search, args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not reach the ERDDAP server: {type(exc).__name__}: {exc}")
        print("This host may not have outbound access. Nothing has been written.\n")
        await close_http_client()
        return 1

    mapping: dict[str, dict] = {}
    for row in datasets:
        dataset_id = row.get("Dataset ID")
        title = row.get("Title", "")
        print(f"  {dataset_id}\n      {title}")
        if args.describe or args.write:
            try:
                variables = await describe(base, dataset_id)
                names = sorted({v.get("Variable Name") for v in variables
                                if v.get("Variable Name")})
                print(f"      variables: {', '.join(names[:12])}"
                      + (" ..." if len(names) > 12 else ""))
                mapping[dataset_id] = {"kind": "griddap",
                                       "title": title,
                                       "available_variables": names,
                                       "variables": {}}
            except Exception as exc:  # noqa: BLE001
                print(f"      (could not describe: {exc})")
        print()

    if args.write and mapping:
        path = os.path.join(get_settings().data_dir, "providers",
                            "incois_datasets.discovered.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, indent=2)
        print(f"Wrote {path}.")
        print("Map the canonical variables you need into each dataset's "
              "\"variables\" block, then rename the file to incois_datasets.json.\n")

    await close_http_client()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover INCOIS ERDDAP datasets")
    parser.add_argument("--base", default=None)
    parser.add_argument("--search", default="wave")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--write", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
