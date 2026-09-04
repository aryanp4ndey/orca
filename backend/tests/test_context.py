"""N. Multi-turn conversation context."""

from __future__ import annotations

import pytest

from app.core.clock import IST
from app.schemas.api import QueryRequest
from app.schemas.common import Activity, Intent


async def test_follow_up_inherits_location_activity_and_intent(query_service):
    first = await query_service.handle(QueryRequest(
        query="Is it safe to go fishing from Kochi tomorrow morning?"))
    assert first.intent["value"] == Intent.MARINE_SAFETY.value

    second = await query_service.handle(QueryRequest(
        query="What about 5 PM?", session_id=first.session_id))

    assert second.intent["value"] == Intent.MARINE_SAFETY.value
    assert second.location["name"] == "Kochi"
    assert second.activity == Activity.FISHING_SMALL_BOAT.value
    assert set(second.intent["inherited"]) >= {"location", "activity", "intent"}


async def test_the_stated_field_overrides_the_inherited_one(query_service):
    first = await query_service.handle(QueryRequest(
        query="Is it safe to go fishing from Kochi tomorrow at 7 AM?"))
    second = await query_service.handle(QueryRequest(
        query="What about 5 PM?", session_id=first.session_id))
    first_hour = __import__("datetime").datetime.fromisoformat(
        first.time["target"]).astimezone(IST).hour
    second_hour = __import__("datetime").datetime.fromisoformat(
        second.time["target"]).astimezone(IST).hour
    assert first_hour == 7 and second_hour == 17
    assert "time" not in second.intent["inherited"]


async def test_a_new_place_replaces_the_inherited_one(query_service):
    first = await query_service.handle(QueryRequest(
        query="Is it safe to fish from Kochi tomorrow at 7 AM?"))
    second = await query_service.handle(QueryRequest(
        query="What about Chennai?", session_id=first.session_id))
    assert second.location["name"] == "Chennai"
    assert "location" not in second.intent["inherited"]


async def test_sessions_are_isolated_from_each_other(query_service):
    a = await query_service.handle(QueryRequest(
        query="Is it safe to fish from Kochi tomorrow at 7 AM?"))
    b = await query_service.handle(QueryRequest(query="What about 5 PM?"))
    assert b.session_id != a.session_id
    # With no history of its own, the second session has nothing to inherit.
    assert b.location is None or b.location["name"] != "Kochi" or not b.intent["inherited"]


def test_inheritance_is_recorded_field_by_field():
    from app.reasoning.context import Session, Turn, apply_context
    from app.schemas.agent import QueryContext
    from app.schemas.common import Language, VesselClass
    from app.geo.gazetteer import get_gazetteer

    gz = get_gazetteer()
    location = gz.to_resolved(gz.find("Kochi"), "Kochi")
    session = Session(session_id="s")
    session.turns.append(Turn(
        query_id="q1", raw_query="", intent=Intent.MARINE_SAFETY, location=location,
        destination=None, activity=Activity.FISHING_SMALL_BOAT,
        vessel=VesselClass.SMALL_MOTORISED, language=Language.EN, time=None))

    ctx = QueryContext(query_id="q2", raw_query="what about 5 pm")
    ctx = apply_context(ctx, session)
    assert ctx.location is location
    assert ctx.activity is Activity.FISHING_SMALL_BOAT
    assert ctx.vessel is VesselClass.SMALL_MOTORISED
    assert sorted(ctx.inherited_fields) == ["activity", "intent", "location", "vessel"]


def test_session_store_evicts_by_ttl():
    import time
    from app.reasoning.context import Session, SessionStore, Turn
    store = SessionStore(ttl_seconds=0)
    store.get("s1")
    time.sleep(0.01)
    store.get("s2")
    assert "s1" not in store._sessions


def test_session_history_is_bounded():
    from app.reasoning.context import SessionStore, Turn
    from app.schemas.common import Language, VesselClass
    store = SessionStore()
    store.max_turns = 3
    for i in range(6):
        store.append("s", Turn(query_id=f"q{i}", raw_query="x", intent=Intent.UNKNOWN,
                               location=None, destination=None,
                               activity=Activity.GENERIC, vessel=VesselClass.NONE,
                               language=Language.EN, time=None))
    assert len(store.get("s").turns) == 3
