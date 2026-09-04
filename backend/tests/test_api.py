"""O. API schema and endpoint contracts - the frontend team's guarantee."""

from __future__ import annotations

import pytest

FLAGSHIP = "Is it safe to go fishing from Kochi tomorrow at 7 AM?"


def test_health_reports_mode_providers_and_agents(api_client):
    body = api_client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True
    assert body["data_origin"] == "DEMO"
    assert len(body["providers"]) >= 4          # IMD, INCOIS, MOSDAC, GIS
    assert "risk_agent" in body["agents"]
    assert "llm" in body and body["llm"]["available"] is False


def test_root_sends_a_browser_to_the_app(api_client):
    """Opening the bare host during a demo must land on ORCA, not on JSON."""
    response = api_client.get("/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/app/"


def test_banner_carries_the_disclaimer(api_client):
    body = api_client.get("/api").json()
    assert body["problem_statement"] == "SIH26176"
    assert "not a certified" in body["disclaimer"].lower()


def test_query_response_has_every_documented_field(api_client):
    body = api_client.post("/api/v1/query", json={"query": FLAGSHIP}).json()
    required = {"query_id", "session_id", "answer", "answer_language", "data_origin",
                "demo_mode", "intent", "location", "time", "activity", "risk",
                "factors", "evidence", "sources", "conflicts", "warnings",
                "confidence", "freshness", "visualizations", "latency",
                "disclaimer", "generated_at", "follow_up_suggestions"}
    assert required <= set(body)


def test_query_rejects_an_empty_query(api_client):
    assert api_client.post("/api/v1/query", json={"query": ""}).status_code == 422


def test_query_rejects_an_out_of_range_coordinate(api_client):
    response = api_client.post("/api/v1/query",
                               json={"query": FLAGSHIP, "lat": 120, "lon": 0})
    assert response.status_code == 422


def test_evidence_endpoint_returns_the_full_chain(api_client):
    query = api_client.post("/api/v1/query", json={"query": FLAGSHIP}).json()
    body = api_client.get(f"/api/v1/evidence/{query['query_id']}").json()
    assert len(body["evidence"]) == len(query["evidence"]) >= 10
    assert body["trace"]["spans"]
    assert body["risk"]["ruleset_id"]


def test_evidence_endpoint_404s_for_an_unknown_id(api_client):
    assert api_client.get("/api/v1/evidence/q_nope").status_code == 404


def test_sources_endpoint_exposes_verification_status(api_client):
    body = api_client.get("/api/v1/sources").json()
    for provider in body["providers"]:
        assert "verified_access" in provider
        assert "access_mechanism" in provider
        assert "role" in provider
    assert body["source_priority"]["ocean"][0] == "INCOIS"
    assert body["source_priority"]["atmosphere"][0] == "IMD"


def test_agents_endpoint_documents_routing(api_client):
    body = api_client.get("/api/v1/agents").json()
    assert len(body["agents"]) == 9
    assert "marine_safety" in body["routing"]
    for step in body["routing"]["marine_safety"]:
        assert step["reason"], "every routing decision must carry a reason"


def test_map_layers_are_labelled_non_authoritative(api_client):
    body = api_client.get("/api/v1/map-layers").json()
    assert all(layer["authoritative"] is False for layer in body["layers"])
    assert "must not be used for navigation" in body["note"]


def test_marine_status_requires_a_location(api_client):
    assert api_client.get("/api/v1/marine-status").status_code == 400
    assert api_client.get("/api/v1/marine-status?place=Kochi").status_code == 200


def test_marine_status_returns_values_risk_and_sources(api_client):
    body = api_client.get("/api/v1/marine-status?place=Kochi").json()
    assert body["ocean"] and body["weather"]
    assert body["risk"]["risk_level"]
    assert body["sources"]


def test_pfz_endpoint(api_client):
    body = api_client.get("/api/v1/pfz?place=Kochi").json()
    assert "zones" in body and "answer" in body


def test_alerts_endpoint(api_client):
    body = api_client.get("/api/v1/alerts?place=Chennai").json()
    assert "answer" in body and "sources" in body


def test_route_risk_endpoint(api_client):
    body = api_client.post("/api/v1/route-risk", json={
        "start": {"lat": 9.93, "lon": 76.21},
        "end": {"lat": 12.91, "lon": 74.80}, "samples": 5}).json()
    assert body["total_distance_km"] > 300
    assert len(body["segments"]) == 4
    assert "not a navigational route" in body["disclaimer"].lower()


def test_low_bandwidth_mode_drops_geometry(api_client):
    full = api_client.post("/api/v1/query", json={"query": FLAGSHIP}).json()
    lite = api_client.post("/api/v1/query",
                           json={"query": FLAGSHIP, "low_bandwidth": True}).json()
    assert lite["visualizations"]["layers"] == []
    assert lite["visualizations"]["cards"]          # cards survive
    assert len(str(lite)) < len(str(full))
    assert lite["answer"] == full["answer"]         # the answer itself is unchanged


def test_trace_can_be_suppressed(api_client):
    body = api_client.post("/api/v1/query",
                           json={"query": FLAGSHIP, "include_trace": False}).json()
    assert body["trace"] is None


def test_openapi_document_is_valid_and_lists_only_real_endpoints(api_client):
    spec = api_client.get("/openapi.json").json()
    paths = set(spec["paths"])
    assert "/api/v1/query" in paths and "/api/v1/health" in paths
    for path in paths:
        assert not path.endswith("TODO")
    assert spec["info"]["title"].startswith("ORCA")


def test_response_carries_timing_headers(api_client):
    response = api_client.post("/api/v1/query", json={"query": FLAGSHIP})
    assert response.headers["x-request-id"]
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_demo_scenarios_endpoint_lists_the_rehearsed_queries(api_client):
    body = api_client.get("/api/v1/demo/scenarios").json()
    assert len(body["queries"]) >= 8
    assert any("Kochi" in q["query"] for q in body["queries"])
    assert body["failure_switches"]
