"""C. Agent contracts - every agent is typed, bounded and self-describing."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.base import BaseAgent
from app.observability.trace import Trace
from app.schemas.agent import AgentRequest, AgentResponse, QueryContext, TimeSpec
from app.schemas.common import AgentStatus, Capability, Intent
from app.services.container import AGENT_CLASSES


def test_every_agent_declares_its_contract():
    for cls in AGENT_CLASSES:
        described = cls.describe()
        assert described["name"] and described["name"] != "abstract"
        assert described["responsibility"], f"{cls.__name__} has no responsibility"
        assert described["produces"], f"{cls.__name__} declares no outputs"
        assert described["failure_behaviour"], f"{cls.__name__} has no failure behaviour"


def test_capabilities_are_unique_across_agents():
    caps = [cls.capability for cls in AGENT_CLASSES]
    assert len(caps) == len(set(caps))


def test_every_planner_capability_has_an_agent(container):
    from app.agents.planner.routing import ROUTES
    registered = set(container.agents)
    for steps in ROUTES.values():
        for step in steps:
            assert step.capability in registered


def _ctx(**kw):
    from app.core.clock import utcnow
    from datetime import timedelta
    now = utcnow()
    return QueryContext(
        query_id="q", raw_query="test", intent=kw.pop("intent", Intent.MARINE_SAFETY),
        time=TimeSpec(target=now, window_start=now - timedelta(minutes=30),
                      window_end=now + timedelta(hours=3)), **kw)


async def test_agent_without_a_location_skips_rather_than_crashes(container):
    trace = Trace("q")
    agent = container.agents[Capability.WEATHER]
    response = await agent.execute(
        AgentRequest(request_id="r", capability=Capability.WEATHER, context=_ctx()),
        trace)
    assert response.status is AgentStatus.SKIPPED
    assert response.warnings


async def test_geospatial_agent_fails_cleanly_with_no_location(container):
    trace = Trace("q")
    agent = container.agents[Capability.GEOSPATIAL]
    response = await agent.execute(
        AgentRequest(request_id="r", capability=Capability.GEOSPATIAL, context=_ctx()),
        trace)
    assert response.status is AgentStatus.FAILED
    assert response.error == "location_not_found"


async def test_agent_deadline_is_enforced_by_the_base_class(container):
    class SlowAgent(BaseAgent):
        name = "slow_agent"
        capability = Capability.WEATHER

        async def run(self, request, trace):
            await asyncio.sleep(2)
            return AgentResponse(agent=self.name, capability=self.capability)

    trace = Trace("q")
    response = await SlowAgent(container.deps).execute(
        AgentRequest(request_id="r", capability=Capability.WEATHER, context=_ctx(),
                     deadline_ms=50), trace)
    assert response.status is AgentStatus.TIMEOUT
    assert response.processing_time_ms < 500


async def test_agent_exception_becomes_a_typed_failure(container):
    class BrokenAgent(BaseAgent):
        name = "broken_agent"
        capability = Capability.OCEAN

        async def run(self, request, trace):
            raise ValueError("kaboom")

    trace = Trace("q")
    response = await BrokenAgent(container.deps).execute(
        AgentRequest(request_id="r", capability=Capability.OCEAN, context=_ctx()), trace)
    assert response.status is AgentStatus.FAILED
    assert "kaboom" in response.error


async def test_geospatial_agent_produces_computed_evidence(container):
    from app.geo.gazetteer import get_gazetteer
    gz = get_gazetteer()
    ctx = _ctx(location=gz.to_resolved(gz.find("Kochi"), "Kochi"))
    trace = Trace("q")
    response = await container.agents[Capability.GEOSPATIAL].execute(
        AgentRequest(request_id="r", capability=Capability.GEOSPATIAL, context=ctx,
                     point=ctx.location.point), trace)
    assert response.status is AgentStatus.OK
    variables = {e.variable for e in response.evidence}
    assert {"distance_to_coast_km", "maritime_band"} <= variables
    for e in response.evidence:
        assert e.origin.value == "COMPUTED"
        assert e.transformation, "a computed value must say how it was computed"


async def test_satellite_agent_never_hard_fails(container):
    """An optional agent must degrade to SKIPPED, never FAILED."""
    from app.providers.demo_controls import DemoControls, set_demo_controls
    from app.geo.gazetteer import get_gazetteer
    set_demo_controls(DemoControls(fail_sources={"MOSDAC"}))
    gz = get_gazetteer()
    ctx = _ctx(location=gz.to_resolved(gz.find("Kochi"), "Kochi"))
    trace = Trace("q")
    response = await container.agents[Capability.SATELLITE].execute(
        AgentRequest(request_id="r", capability=Capability.SATELLITE, context=ctx,
                     point=ctx.location.point), trace)
    assert response.status is not AgentStatus.FAILED


async def test_every_agent_emits_a_trace_span(container):
    from app.geo.gazetteer import get_gazetteer
    gz = get_gazetteer()
    ctx = _ctx(location=gz.to_resolved(gz.find("Kochi"), "Kochi"))
    trace = Trace("q")
    await container.agents[Capability.OCEAN].execute(
        AgentRequest(request_id="r", capability=Capability.OCEAN, context=ctx,
                     point=ctx.location.point), trace)
    names = [s.name for s in trace.spans if s.kind == "agent"]
    assert "ocean_agent" in names
