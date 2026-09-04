"""B. Planner routing - the planner must not call every agent for every query."""

from __future__ import annotations

import pytest

from app.agents.planner.routing import skipped_for, steps_for
from app.schemas.common import Capability, Intent


def caps(intent):
    return {s.capability for s in steps_for(intent)}


def test_safety_query_uses_the_full_safety_chain():
    required = {Capability.GEOSPATIAL, Capability.WEATHER, Capability.OCEAN,
                Capability.HAZARD, Capability.RISK, Capability.RESPONSE}
    assert required <= caps(Intent.MARINE_SAFETY)


def test_weather_query_does_not_pay_for_ocean_or_satellite():
    selected = caps(Intent.WEATHER_INFO)
    assert Capability.OCEAN not in selected
    assert Capability.SATELLITE not in selected
    assert Capability.WEATHER in selected


def test_pfz_query_routes_to_the_pfz_agent_not_the_hazard_agent():
    selected = caps(Intent.PFZ_LOOKUP)
    assert Capability.PFZ in selected
    assert Capability.HAZARD not in selected


def test_small_talk_touches_no_data_source():
    assert caps(Intent.SMALL_TALK) == {Capability.RESPONSE}


def test_satellite_is_optional_wherever_it_appears():
    for intent in Intent:
        for step in steps_for(intent):
            if step.capability is Capability.SATELLITE:
                assert step.required is False, f"{intent} marks satellite required"


def test_every_skipped_capability_has_a_stated_reason():
    for intent in Intent:
        for capability, reason in skipped_for(intent).items():
            assert reason and isinstance(reason, str)


def test_dependency_waves_put_independent_retrieval_in_one_wave():
    from app.schemas.agent import ExecutionPlan, PlanStep
    plan = ExecutionPlan(
        query_id="q", intent=Intent.MARINE_SAFETY,
        steps=[PlanStep(capability=s.capability, required=s.required,
                        depends_on=list(s.depends_on), reason=s.reason)
               for s in steps_for(Intent.MARINE_SAFETY)])
    waves = [[s.capability for s in wave] for wave in plan.waves()]
    assert waves[0] == [Capability.GEOSPATIAL]
    assert set(waves[1]) == {Capability.WEATHER, Capability.OCEAN,
                             Capability.HAZARD, Capability.SATELLITE}
    assert waves[-1] == [Capability.RESPONSE]


def test_planner_produces_a_plan_and_records_what_it_skipped(container, frozen_clock):
    import asyncio
    from app.observability.trace import Trace
    from app.reasoning.context import Session
    from app.schemas.api import QueryRequest

    trace = Trace(query_id="q_test")
    ctx, plan = asyncio.run(container.planner.plan(
        QueryRequest(query="Show me the marine weather near Chennai"),
        Session(session_id="s"), trace, now=frozen_clock))
    assert ctx.intent is Intent.WEATHER_INFO
    assert Capability.OCEAN.value in plan.skipped
    assert trace.plan["waves"][0] == ["geospatial"]
