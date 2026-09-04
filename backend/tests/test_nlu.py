"""A. Intent extraction, M. multilingual internal representation, time parsing."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.clock import IST
from app.reasoning.nlu import classify_intent, detect_language, parse_time, understand
from app.schemas.common import Activity, Intent, Language, VesselClass

NOW = dt.datetime(2026, 9, 2, 5, 30, tzinfo=dt.timezone.utc)   # 11:00 IST


@pytest.mark.parametrize("query,intent", [
    ("Is it safe to go fishing from Kochi tomorrow at 7 AM?", Intent.MARINE_SAFETY),
    ("What is the sea condition near Kochi?", Intent.SEA_CONDITION),
    ("Show me the marine weather near Chennai", Intent.WEATHER_INFO),
    ("Where is the nearest Potential Fishing Zone today?", Intent.PFZ_LOOKUP),
    ("Are there any cyclone or lightning warnings near my location?", Intent.HAZARD_CHECK),
    ("Why is fishing potential lower here between 5 PM and 10 PM?", Intent.ANALYTICAL),
    ("What areas should I avoid?", Intent.AVOID_AREAS),
    ("Show the safest route from Kochi to Mangaluru", Intent.ROUTE_RISK),
    ("hello", Intent.SMALL_TALK),
])
def test_intent_classification(query, intent):
    assert classify_intent(query)[0] is intent


def test_safety_beats_sea_condition_when_both_match():
    intent, confidence, scores = classify_intent(
        "Is it safe? What are the waves like near Kochi?")
    assert intent is Intent.MARINE_SAFETY
    assert scores["marine_safety"] > scores["sea_condition"]


def test_unknown_intent_is_flagged_for_the_llm_fallback():
    result = understand("What about 5 PM?", now=NOW)
    assert result.intent is Intent.UNKNOWN
    assert result.needs_llm is True
    assert result.time is not None          # the one thing stated is still parsed


@pytest.mark.parametrize("query,language", [
    ("Is it safe to go fishing from Kochi?", Language.EN),
    ("क्या कल सुबह जाना सुरक्षित है?", Language.HI),
    ("Kal subah 7 baje Kochi se jaana safe hai kya?", Language.HI),
    ("നാളെ കടൽ എങ്ങനെയുണ്ട്?", Language.ML),
    ("நாளை கடல் எப்படி இருக்கும்?", Language.TA),
])
def test_language_detection(query, language):
    assert detect_language(query) is language


def test_internal_representation_is_language_independent():
    """The core claim of the multilingual design, asserted directly."""
    queries = {
        Language.EN: "Is it safe to go fishing from Kochi tomorrow at 7 AM?",
        Language.HI: "क्या कल सुबह 7 बजे कोच्चि से मछली पकड़ने जाना सुरक्षित है?",
        Language.ML: "നാളെ രാവിലെ 7 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻപിടിക്കാൻ പോകുന്നത് സുരക്ഷിതമാണോ?",
    }
    shapes = []
    for language, text in queries.items():
        result = understand(text, now=NOW)
        assert result.language is language
        shapes.append((result.intent, result.activity,
                       tuple(p.id for p in result.places),
                       result.time.target))
    assert len(set(shapes)) == 1, f"representations diverged: {shapes}"


def test_tamil_query_resolves_chennai_and_the_same_time():
    result = understand(
        "நாளை காலை 7 மணிக்கு சென்னையிலிருந்து மீன்பிடிக்கச் செல்வது பாதுகாப்பானதா?", now=NOW)
    assert result.intent is Intent.MARINE_SAFETY
    assert [p.id for p in result.places] == ["chennai"]
    assert result.time.target.astimezone(IST).hour == 7


def test_activity_and_vessel_extraction():
    result = understand("Is it safe to take my small boat out for fishing from Kochi?",
                        now=NOW)
    assert result.activity is Activity.FISHING_SMALL_BOAT
    assert result.vessel is VesselClass.SMALL_MOTORISED
    trawler = understand("Can my trawler go out from Veraval tomorrow?", now=NOW)
    assert trawler.vessel is VesselClass.MECHANISED


# ---- time ------------------------------------------------------------------
def test_tomorrow_at_seven_am():
    spec, _ = parse_time("tomorrow at 7 AM", NOW)
    local = spec.target.astimezone(IST)
    assert (local.day, local.hour) == (3, 7)
    assert spec.is_explicit


def test_bare_five_pm_stays_today_when_still_ahead():
    spec, _ = parse_time("What about 5 PM?", NOW)
    local = spec.target.astimezone(IST)
    assert (local.day, local.hour) == (2, 17)


def test_bare_past_hour_rolls_to_tomorrow():
    spec, _ = parse_time("at 7 AM", NOW)          # 07:00 already gone at 11:00 IST
    local = spec.target.astimezone(IST)
    assert (local.day, local.hour) == (3, 7)


def test_hindi_kal_subah_seven_baje():
    spec, _ = parse_time("kal subah 7 baje", NOW)
    local = spec.target.astimezone(IST)
    assert (local.day, local.hour) == (3, 7)


def test_part_of_day_disambiguates_a_bare_hour():
    spec, _ = parse_time("shaam 5 baje", NOW)     # evening -> 17:00, not 05:00
    assert spec.target.astimezone(IST).hour == 17


def test_today_never_resolves_into_the_past():
    spec, _ = parse_time("today", NOW)
    assert spec.target >= NOW


def test_comparison_window_produces_two_windows():
    primary, windows = parse_time("between 5 PM and 10 PM", NOW)
    assert len(windows) == 2
    hours = sorted(w.target.astimezone(IST).hour for w in windows)
    assert hours == [17, 22]
    assert primary.target == windows[0].target


def test_no_time_reference_returns_none():
    assert parse_time("what is the sea like near Kochi", NOW)[0] is None


def test_nlu_is_fast_enough_to_be_on_the_critical_path():
    import time
    understand("Is it safe to go fishing from Kochi tomorrow at 7 AM?", now=NOW)
    start = time.perf_counter()
    for _ in range(50):
        understand("Is it safe to go fishing from Kochi tomorrow at 7 AM?", now=NOW)
    per_call_ms = (time.perf_counter() - start) * 1000 / 50
    assert per_call_ms < 5.0, f"NLU took {per_call_ms:.2f} ms per call"
