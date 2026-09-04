"""P. End-to-end - every demo query, and every failure mode we claim to survive."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.clock import IST
from app.providers.demo_controls import DemoControls, set_demo_controls
from app.schemas.api import QueryRequest
from app.schemas.common import DataOrigin, DecisionStatus, Intent, RiskLevel
from app.tools.demo_queries import DEFAULT_DEMO_POINT

KOCHI_LAT, KOCHI_LON = DEFAULT_DEMO_POINT["lat"], DEFAULT_DEMO_POINT["lon"]
FLAGSHIP = "Is it safe to go fishing from Kochi tomorrow at 7 AM?"


# ---------------------------------------------------------------- demo 1 ----
async def test_flagship_fishing_safety_query(query_service):
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))

    assert response.intent["value"] == Intent.MARINE_SAFETY.value
    assert response.location["name"] == "Kochi"
    assert response.time["target"].astimezone(IST).hour == 7 \
        if hasattr(response.time["target"], "astimezone") else True
    assert response.activity == "fishing_small_boat"

    assert response.risk is not None
    assert response.risk.risk_level in (RiskLevel.LOW, RiskLevel.MODERATE,
                                        RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert response.risk.factors
    assert response.answer

    # The evidence chain, which is the whole point.
    assert len(response.evidence) >= 10
    for row in response.evidence:
        assert row.source and row.provider and row.dataset and row.variable
        assert row.retrieved_at is not None
        assert row.freshness is not None

    # Every risk factor must be traceable back to an evidence row.
    ids = {row.evidence_id for row in response.evidence}
    for factor in response.risk.factors:
        assert factor.evidence_ids
        assert set(factor.evidence_ids) <= ids

    assert response.sources
    assert response.confidence > 0
    assert response.latency.total_ms > 0
    assert response.disclaimer
    assert response.data_origin is DataOrigin.DEMO
    assert response.demo_mode is True


async def test_flagship_answer_is_fully_grounded(query_service):
    """No number in the answer may be absent from the evidence."""
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    grounding = None
    for span in response.trace.spans:
        if span.name == "grounding_check":
            grounding = span
    assert grounding is not None and grounding.status == "OK"
    assert "DEMO MODE" in response.answer      # never presented as live


async def test_flagship_runs_retrieval_in_parallel(query_service):
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    waves = response.trace.plan["waves"]
    assert waves[0] == ["geospatial"]
    assert set(waves[1]) == {"weather", "ocean", "hazard", "satellite"}


async def test_flagship_is_fast(query_service):
    """The judge's question: how does this behave on a slow coastal link?

    The part we control is server-side work. Anything above ~250 ms here would
    mean we had reintroduced a serial dependency or an LLM on the critical path.
    """
    await query_service.handle(QueryRequest(query=FLAGSHIP))   # warm
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    assert response.latency.total_ms < 250, response.latency.model_dump()
    assert response.latency.llm_ms == 0.0


# ---------------------------------------------------------------- demo 2 ----
async def test_multi_turn_follow_up(query_service):
    first = await query_service.handle(QueryRequest(query=FLAGSHIP))
    second = await query_service.handle(QueryRequest(
        query="What about 5 PM?", session_id=first.session_id))
    assert second.location["name"] == "Kochi"
    assert second.intent["value"] == Intent.MARINE_SAFETY.value
    assert second.risk is not None


# ---------------------------------------------------------------- demo 3 ----
async def test_sea_condition_query(query_service):
    response = await query_service.handle(QueryRequest(
        query="What is the sea condition near Kochi?"))
    assert response.intent["value"] == Intent.SEA_CONDITION.value
    variables = {e.variable for e in response.evidence}
    assert "wave_height_significant" in variables
    assert "wave" in response.answer.lower() or "Wave" in response.answer


# ---------------------------------------------------------------- demo 4 ----
async def test_pfz_query(query_service):
    response = await query_service.handle(QueryRequest(
        query="Where is the nearest Potential Fishing Zone today?",
        lat=KOCHI_LAT, lon=KOCHI_LON))
    assert response.intent["value"] == Intent.PFZ_LOOKUP.value
    pfz_markers = [m for m in response.visualizations.markers if m["kind"] == "pfz"]
    assert pfz_markers, "no PFZ produced"
    pfz_evidence = [e for e in response.evidence if e.variable == "pfz_advisory"]
    assert pfz_evidence
    for row in pfz_evidence:
        assert row.notes and "valid" in row.notes
    assert "km" in response.answer


# ---------------------------------------------------------------- demo 5 ----
async def test_hazard_query(query_service):
    set_demo_controls(DemoControls(scenario="rough"))
    response = await query_service.handle(QueryRequest(
        query="Are there any cyclone or lightning warnings near my location?",
        lat=KOCHI_LAT, lon=KOCHI_LON))
    assert response.intent["value"] == Intent.HAZARD_CHECK.value
    advisories = [e for e in response.evidence if e.variable.startswith("advisory:")]
    assert advisories, "rough conditions should produce advisories"
    for row in advisories:
        assert row.notes            # the headline, quoted verbatim


# ---------------------------------------------------------------- demo 6 ----
async def test_analytical_query_compares_windows_and_refuses_to_claim_causality(query_service):
    response = await query_service.handle(QueryRequest(
        query="Why is fishing potential lower here between 5 PM and 10 PM?",
        lat=KOCHI_LAT, lon=KOCHI_LON))
    assert response.intent["value"] == Intent.ANALYTICAL.value
    assert "causal" in response.answer.lower() or "does not claim" in response.answer.lower()
    assert response.evidence


# ---------------------------------------------------------------- demo 7 ----
async def test_avoid_areas_query_labels_illustrative_layers(query_service):
    response = await query_service.handle(QueryRequest(
        query="What areas should I avoid?", lat=KOCHI_LAT, lon=KOCHI_LON))
    assert response.intent["value"] == Intent.AVOID_AREAS.value
    assert "keep clear" in response.answer.lower() or "avoid" in response.answer.lower()
    if response.visualizations.layers:
        assert any("illustrative" in response.answer.lower()
                   or not layer.geojson["properties"].get("authoritative", False)
                   for layer in response.visualizations.layers)


# ---------------------------------------------------------------- demo 8 ----
async def test_route_query(query_service):
    response = await query_service.handle(QueryRequest(
        query="Show the safest route from Kochi to Mangaluru"))
    assert response.intent["value"] == Intent.ROUTE_RISK.value
    assert response.location["name"] == "Kochi"
    lines = [l for l in response.visualizations.layers if l.kind == "line"]
    assert lines, "no route geometry produced"
    assert "not a navigational route" in response.answer.lower() or \
           any("not a navigational route" in w.lower() for w in response.warnings)


# ------------------------------------------------------------- multilingual -
@pytest.mark.parametrize("query,language", [
    ("Kal subah 7 baje Kochi se fishing ke liye jaana safe hai?", "hi"),
    ("क्या कल सुबह 7 बजे कोच्चि से मछली पकड़ने जाना सुरक्षित है?", "hi"),
    ("നാളെ രാവിലെ 7 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻപിടിക്കാൻ പോകുന്നത് സുരക്ഷിതമാണോ?", "ml"),
    ("நாளை காலை 7 மணிக்கு சென்னையிலிருந்து மீன்பிடிக்கச் செல்வது பாதுகாப்பானதா?", "ta"),
])
async def test_multilingual_queries_answer_in_the_same_language(query_service, query, language):
    response = await query_service.handle(QueryRequest(query=query))
    assert response.answer_language.value == language
    assert response.intent["value"] == Intent.MARINE_SAFETY.value
    assert response.risk is not None
    assert response.answer


async def test_same_question_in_four_languages_yields_the_same_risk(query_service):
    """The multilingual claim, end to end: language changes words, not verdicts."""
    queries = [
        "Is it safe to go fishing from Kochi tomorrow at 7 AM?",
        "Kal subah 7 baje Kochi se fishing ke liye jaana safe hai?",
        "क्या कल सुबह 7 बजे कोच्चि से मछली पकड़ने जाना सुरक्षित है?",
        "നാളെ രാവിലെ 7 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻപിടിക്കാൻ പോകുന്നത് സുരക്ഷിതമാണോ?",
    ]
    verdicts = set()
    for query in queries:
        response = await query_service.handle(QueryRequest(query=query))
        verdicts.add((response.risk.risk_level, round(response.risk.risk_score, 1)))
    assert len(verdicts) == 1, f"verdicts diverged across languages: {verdicts}"


# ------------------------------------------------------- failure behaviour --
async def test_critical_source_down_withholds_the_advisory(query_service):
    """Milestone 3: survive a dead source without hallucinating."""
    set_demo_controls(DemoControls(fail_sources={"INCOIS"}))
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    assert response.risk.risk_level is RiskLevel.INSUFFICIENT_DATA
    assert response.risk.decision_status is DecisionStatus.ADVISORY_WITHHELD
    assert "wave_height_significant" in response.risk.missing_variables
    assert "unknown" in response.answer.lower()
    assert response.confidence < 0.7
    # And it must not have invented a wave height from somewhere else.
    assert not [e for e in response.evidence
                if e.variable == "wave_height_significant" and e.value is not None]


async def test_optional_source_down_still_answers(query_service):
    set_demo_controls(DemoControls(fail_sources={"MOSDAC"}))
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    assert response.risk.decision_status is not DecisionStatus.ADVISORY_WITHHELD
    assert response.risk.risk_level is not RiskLevel.INSUFFICIENT_DATA
    assert any("MOSDAC" in w for w in response.warnings)


async def test_stale_source_degrades_rather_than_lying(query_service):
    set_demo_controls(DemoControls(stale_sources={"IMD", "INCOIS"}))
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    assert response.risk.decision_status is DecisionStatus.ADVISORY_DEGRADED
    assert response.risk.stale_variables
    assert response.freshness.overall.value == "STALE"
    assert any("older" in w.lower() for w in response.warnings + [response.answer])


async def test_slow_source_times_out_without_breaking_the_answer(query_service, container):
    container.settings.budget_provider_ms = 120
    set_demo_controls(DemoControls(slow_sources={"MOSDAC": 900}))
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    assert response.answer
    statuses = {s.source.value: s.status for s in response.sources}
    assert statuses.get("MOSDAC") in ("TIMEOUT", "ERROR", "CIRCUIT_OPEN", "DEGRADED")
    assert response.risk is not None


async def test_conflicting_sources_are_surfaced_not_averaged(query_service):
    set_demo_controls(DemoControls(inject_conflict=True))
    response = await query_service.handle(QueryRequest(query=FLAGSHIP))
    wind_conflicts = [c for c in response.conflicts if c.variable == "wind_speed_10m"]
    assert wind_conflicts, "expected a wind conflict between IMD and INCOIS"
    conflict = wind_conflicts[0]
    values = sorted(c["value"] for c in conflict.claims)
    assert len(values) >= 2
    used = next(f for f in response.risk.factors if f.variable == "wind_speed_10m").value
    assert used in [round(v, 2) for v in values], "the used value must be one source's claim"
    midpoint = sum(values) / len(values)
    assert abs(used - midpoint) > 1e-6 or values[0] == values[-1], "never average"


async def test_rough_and_cyclone_scenarios_escalate_the_risk(query_service):
    levels = {}
    for scenario in ("calm", "normal", "rough", "pre_cyclone"):
        set_demo_controls(DemoControls(scenario=scenario))
        response = await query_service.handle(QueryRequest(query=FLAGSHIP))
        levels[scenario] = response.risk.risk_level
    assert levels["calm"].rank <= levels["normal"].rank <= levels["rough"].rank
    assert levels["pre_cyclone"] is RiskLevel.CRITICAL


async def test_unknown_place_asks_rather_than_guessing(query_service):
    response = await query_service.handle(QueryRequest(
        query="Is it safe to go fishing from Atlantis tomorrow at 7 AM?"))
    assert response.location is None
    assert response.risk is None or response.risk.risk_level is RiskLevel.INSUFFICIENT_DATA
    assert "which place" in response.answer.lower() or "location" in response.answer.lower()


async def test_missing_time_defaults_to_now_and_says_so(query_service):
    response = await query_service.handle(QueryRequest(
        query="What is the sea condition near Kochi?"))
    assert response.time["is_explicit"] is False
    assert response.time["resolver"] == "default"


async def test_small_talk_costs_no_provider_call(query_service):
    response = await query_service.handle(QueryRequest(query="hello"))
    assert response.evidence == []
    assert response.sources == []
    assert response.latency.providers_ms == 0.0
    assert "ORCA" in response.answer


async def test_no_llm_is_required_for_any_demo_query(query_service, container):
    """The latency answer: not one demo query needs a model round-trip."""
    from app.tools.demo_queries import DEMO_QUERIES
    assert container.deps.llm.available is False
    session_id = None
    for demo in DEMO_QUERIES:
        request = QueryRequest(
            query=demo["query"], session_id=session_id,
            lat=KOCHI_LAT if demo.get("needs_location") else None,
            lon=KOCHI_LON if demo.get("needs_location") else None)
        response = await query_service.handle(request)
        session_id = response.session_id
        assert response.answer, f"{demo['id']} produced no answer"
        assert response.latency.llm_ms == 0.0
        if "expect_intent" in demo and not demo.get("requires_session"):
            assert response.intent["value"] == demo["expect_intent"], demo["id"]
