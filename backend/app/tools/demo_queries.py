"""Canonical demo queries.

One list, used by the demo script, the benchmark, the test suite and the
``/api/v1/demo/scenarios`` endpoint - so a rehearsed demo and a passing test are
literally the same thing.
"""

from __future__ import annotations

DEMO_QUERIES: list[dict] = [
    {"id": "d1", "title": "Fishing safety (flagship)",
     "query": "Is it safe to go fishing from Kochi tomorrow at 7 AM?",
     "expect_intent": "marine_safety",
     "shows": ["intent extraction", "parallel retrieval", "risk engine",
               "evidence chain", "warnings", "latency"]},
    {"id": "d2", "title": "Multi-turn follow-up", "query": "What about 5 PM?",
     "expect_intent": "marine_safety", "requires_session": True,
     "shows": ["conversation context: location, activity and intent inherited"]},
    {"id": "d3", "title": "Sea condition",
     "query": "What is the sea condition near Kochi?",
     "expect_intent": "sea_condition", "shows": ["ocean agent", "fast path"]},
    {"id": "d4", "title": "Potential Fishing Zone",
     "query": "Where is the nearest Potential Fishing Zone today?",
     "expect_intent": "pfz_lookup", "needs_location": True,
     "shows": ["PFZ agent", "bearing and distance", "validity window"]},
    {"id": "d5", "title": "Hazard check",
     "query": "Are there any cyclone or lightning warnings near my location?",
     "expect_intent": "hazard_check", "needs_location": True,
     "shows": ["hazard agent", "authority advisories quoted, not re-scored"]},
    {"id": "d6", "title": "Analytical",
     "query": "Why is fishing potential lower here between 5 PM and 10 PM?",
     "expect_intent": "analytical", "needs_location": True,
     "shows": ["two comparison windows", "refusal to claim causality"]},
    {"id": "d7", "title": "Areas to avoid", "query": "What areas should I avoid?",
     "expect_intent": "avoid_areas", "needs_location": True,
     "shows": ["geofencing", "non-authoritative layer labelling"]},
    {"id": "d8", "title": "Route risk",
     "query": "Show the safest route from Kochi to Mangaluru",
     "expect_intent": "route_risk",
     "shows": ["corridor sampling", "per-segment risk", "scope disclaimer"]},
    {"id": "d9", "title": "Hindi (romanised)",
     "query": "Kal subah 7 baje Kochi se fishing ke liye jaana safe hai?",
     "expect_intent": "marine_safety", "expect_language": "hi",
     "shows": ["language-independent internal representation"]},
    {"id": "d10", "title": "Malayalam",
     "query": "നാളെ രാവിലെ 7 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻപിടിക്കാൻ പോകുന്നത് സുരക്ഷിതമാണോ?",
     "expect_intent": "marine_safety", "expect_language": "ml",
     "shows": ["Indic script and case-suffix handling"]},
    {"id": "d11", "title": "Tamil",
     "query": "நாளை காலை 7 மணிக்கு சென்னையிலிருந்து மீன்பிடிக்கச் செல்வது பாதுகாப்பானதா?",
     "expect_intent": "marine_safety", "expect_language": "ta",
     "shows": ["Tamil intent and place extraction"]},
]

FAILURE_SWITCHES: list[dict] = [
    {"env": "ORCA_DEMO_SCENARIO=rough", "shows": "risk escalates to HIGH/CRITICAL"},
    {"env": "ORCA_DEMO_SCENARIO=pre_cyclone", "shows": "cyclone advisory forces CRITICAL"},
    {"env": "ORCA_DEMO_FAIL_SOURCES=INCOIS",
     "shows": "wave height is missing, so the advisory is WITHHELD, not guessed"},
    {"env": "ORCA_DEMO_FAIL_SOURCES=MOSDAC",
     "shows": "optional source down; answer proceeds and says so"},
    {"env": "ORCA_DEMO_STALE_SOURCES=IMD",
     "shows": "stale evidence downgrades confidence and degrades the advisory"},
    {"env": "ORCA_DEMO_SLOW_SOURCES=INCOIS:4000",
     "shows": "provider timeout, partial answer, no fabrication"},
    {"env": "ORCA_DEMO_CONFLICT=true",
     "shows": "two sources disagree on wind; IMD wins by policy, confidence drops"},
]

DEFAULT_DEMO_POINT = {"lat": 9.9312, "lon": 76.2125, "name": "off Kochi"}
