"""The API process also serves the web client - that has to keep working.

These are contract tests for the seam between the two halves of the project.
They do not test the UI itself (that is `tools/verify_frontend.py`, which drives
a real browser); they test that the frontend is served, that every module it
imports resolves, and that the endpoints it depends on exist with the shape it
expects.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def test_frontend_directory_ships_with_the_backend():
    assert FRONTEND.is_dir(), "frontend/ is missing next to backend/"
    assert (FRONTEND / "index.html").exists()
    assert (FRONTEND / "js" / "main.js").exists()
    assert (FRONTEND / "styles" / "app.css").exists()


def test_app_shell_is_served(api_client):
    response = api_client.get("/app/")
    assert response.status_code == 200
    assert "ORCA" in response.text
    assert "/app/js/main.js" in response.text


@pytest.mark.parametrize("path", [
    "/app/styles/app.css",
    "/app/js/main.js",
    "/app/js/api.js",
    "/app/js/state.js",
    "/app/js/i18n.js",
    "/app/js/config.js",
    "/app/js/util/dom.js",
    "/app/js/util/format.js",
    "/app/js/views/ask.js",
    "/app/js/views/answer.js",
    "/app/js/views/evidence.js",
    "/app/js/views/trace.js",
    "/app/js/views/map.js",
    "/app/js/views/screens.js",
    "/app/js/views/settings.js",
    "/app/js/views/progress.js",
    "/app/js/services/net.js",
    "/app/js/services/geolocation.js",
    "/app/js/services/voice.js",
    "/app/js/services/cache.js",
    "/sw.js",
    "/manifest.webmanifest",
])
def test_every_client_asset_is_reachable(api_client, path):
    assert api_client.get(path).status_code == 200, f"{path} is not served"


def test_every_module_import_resolves():
    """A broken relative import is a blank screen, so it is worth a test."""
    js_root = FRONTEND / "js"
    pattern = re.compile(r"""from\s+['"](\.[^'"]+)['"]""")
    missing = []
    for module in js_root.rglob("*.js"):
        for target in pattern.findall(module.read_text(encoding="utf-8")):
            resolved = (module.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{module.relative_to(FRONTEND)} -> {target}")
    assert not missing, f"unresolved imports: {missing}"


def test_service_worker_never_caches_api_responses():
    """Serving a cached marine forecast transparently is the one thing the
    service worker must not do - the user would have no way to know it was old."""
    source = (FRONTEND / "sw.js").read_text(encoding="utf-8")
    assert "url.pathname.startsWith('/api/')" in source
    assert "return;" in source.split("url.pathname.startsWith('/api/')")[1][:120]


def test_manifest_is_valid_json_and_installable():
    manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] and manifest["short_name"]
    assert manifest["start_url"].startswith("/app")
    assert manifest["display"] == "standalone"
    assert len(manifest["icons"]) >= 2


def test_endpoints_the_client_calls_all_exist(api_client):
    """The client's API module names these. If one disappears, fail here rather
    than in a demo."""
    spec = api_client.get("/openapi.json").json()
    paths = set(spec["paths"])
    required = {
        "/api/v1/query", "/api/v1/health", "/api/v1/sources", "/api/v1/agents",
        "/api/v1/pfz", "/api/v1/alerts", "/api/v1/route-risk",
        "/api/v1/marine-status", "/api/v1/map-layers",
        "/api/v1/geo/basemap", "/api/v1/geo/places",
        "/api/v1/evidence/{query_id}",
    }
    assert required <= paths, f"client depends on missing endpoints: {required - paths}"


def test_basemap_gives_the_client_something_to_draw(api_client):
    body = api_client.get("/api/v1/geo/basemap").json()
    assert body["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in body["features"]}
    assert {"coastline", "zone", "place"} <= kinds
    # Every drawable outline must declare whether it is authoritative, because
    # the UI renders approximations differently from official data.
    for feature in body["features"]:
        assert "authoritative" in feature["properties"]
        assert feature["properties"]["authoritative"] is False


def test_places_endpoint_supports_manual_location_entry(api_client):
    body = api_client.get("/api/v1/geo/places?q=kochi").json()
    assert body["count"] >= 1
    place = body["places"][0]
    assert place["name"] == "Kochi"
    # The client sends the marine point, not the town centre - a forecast has no
    # value on land.
    assert place["marine_point"]["lon"] < place["lon"]


def test_query_response_carries_everything_the_client_renders(api_client):
    body = api_client.post("/api/v1/query", json={
        "query": "Is it safe to go fishing from Kochi tomorrow at 7 AM?",
    }).json()
    assert body["risk"]["risk_level"]
    assert body["factors"], "the client's factor grid needs response.factors"
    assert body["evidence"], "the evidence panel needs response.evidence"
    assert body["sources"], "the source panel needs response.sources"
    assert body["trace"]["plan"]["waves"], "the trace view needs plan.waves"
    assert body["visualizations"]["markers"], "the map needs a marker"
    assert body["follow_up_suggestions"], "the chips need suggestions"
    assert "total_ms" in body["latency"]


def test_evidence_rows_are_not_duplicated(api_client):
    """Agents share provider responses on purpose; the ledger must still carry
    each fact once."""
    body = api_client.post("/api/v1/query", json={
        "query": "Is it safe to go fishing from Kochi tomorrow at 7 AM?",
    }).json()
    ids = [row["evidence_id"] for row in body["evidence"]]
    assert len(ids) == len(set(ids)), "duplicate evidence rows reached the client"


def test_low_bandwidth_trims_the_payload_but_not_the_answer(api_client):
    full = api_client.post("/api/v1/query", json={"query": "sea condition near Kochi"}).json()
    lite = api_client.post("/api/v1/query", json={
        "query": "sea condition near Kochi", "low_bandwidth": True}).json()
    assert lite["visualizations"]["layers"] == []
    assert lite["answer"] == full["answer"]


def test_route_risk_overall_verdict_is_not_gated_by_spatial_variation(api_client):
    """Conditions differ along a 360 km corridor. That is geography, not sources
    disagreeing, and it must not withhold the passage advisory."""
    body = api_client.post("/api/v1/route-risk", json={
        "start": {"lat": 9.93, "lon": 76.21},
        "end": {"lat": 12.91, "lon": 74.80},
        "samples": 5, "activity": "fishing_small_boat", "vessel": "small_motorised",
    }).json()
    levels = {segment["risk_level"] for segment in body["segments"]}
    assert body["overall_risk"]["risk_level"] != "INSUFFICIENT_DATA" or \
        levels == {"INSUFFICIENT_DATA"}
    # The overall verdict is the worst stretch, not an average of the corridor.
    order = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    worst = max((l for l in levels if l in order), key=order.index, default=None)
    if worst:
        assert body["overall_risk"]["risk_level"] == worst
