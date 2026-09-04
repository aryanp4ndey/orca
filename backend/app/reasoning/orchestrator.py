"""Dependency-aware agent orchestration.

The plan is a DAG, not a script.  The orchestrator groups steps into waves -
every step whose dependencies are already satisfied - and runs each wave with
``asyncio.gather``.  For the flagship query that means weather, ocean, hazard
and satellite all start at the same instant, so the answer costs one provider
round-trip, not four.

It also owns the total time budget.  When the budget is nearly spent, optional
steps are dropped (and recorded as dropped) rather than allowed to push the
answer past the point where a user on a boat has given up waiting.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.agents.base import AgentDeps, BaseAgent
from app.observability.logging import get_logger
from app.observability.trace import Trace
from app.schemas.agent import AgentRequest, AgentResponse, ExecutionPlan, QueryContext
from app.schemas.common import AgentStatus, Capability

log = get_logger("orca.orchestrator")


class Orchestrator:
    def __init__(self, deps: AgentDeps, agents: dict[Capability, BaseAgent],
                 serial_mode: bool = False) -> None:
        self.deps = deps
        self.agents = agents
        #: Benchmark-only switch. When true, steps inside a wave run one after
        #: another instead of concurrently, so `app/tools/benchmark.py` can
        #: measure what the fan-out is actually worth instead of asserting it.
        self.serial_mode = serial_mode

    async def execute(self, ctx: QueryContext, plan: ExecutionPlan,
                      trace: Trace) -> dict[Capability, AgentResponse]:
        results: dict[Capability, AgentResponse] = {}
        started = time.perf_counter()
        budget_ms = plan.total_budget_ms

        for wave_index, wave in enumerate(plan.waves()):
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            remaining_ms = budget_ms - elapsed_ms

            runnable = []
            for step in wave:
                agent = self.agents.get(step.capability)
                if agent is None:
                    results[step.capability] = AgentResponse(
                        agent="missing", capability=step.capability,
                        status=AgentStatus.SKIPPED,
                        warnings=[f"no agent registered for {step.capability.value}"])
                    continue
                if not step.required and remaining_ms < step.deadline_ms * 0.6:
                    results[step.capability] = AgentResponse(
                        agent=agent.name, capability=step.capability,
                        status=AgentStatus.SKIPPED, confidence=0.0,
                        warnings=[(f"{agent.name} skipped: only {remaining_ms:.0f} ms of the "
                                   f"{budget_ms} ms budget remained")])
                    trace.note(f"dropped optional {step.capability.value} to protect latency")
                    continue
                if any(results.get(dep) is not None
                       and results[dep].status in (AgentStatus.FAILED, AgentStatus.TIMEOUT)
                       and dep in (Capability.GEOSPATIAL,)
                       for dep in step.depends_on):
                    results[step.capability] = AgentResponse(
                        agent=agent.name, capability=step.capability,
                        status=AgentStatus.SKIPPED, confidence=0.0,
                        warnings=[f"{agent.name} skipped: a required upstream step failed"])
                    continue
                runnable.append((step, agent))

            if not runnable:
                continue

            def build(step, agent):
                return agent.execute(
                    AgentRequest(
                        request_id=f"{ctx.query_id}:{step.capability.value}",
                        capability=step.capability, context=ctx,
                        point=ctx.location.point if ctx.location else None,
                        deadline_ms=int(min(step.deadline_ms, max(120, remaining_ms))),
                        depends_on=self._dependency_payload(step.depends_on, results),
                        options=step.options),
                    trace)

            with trace.span(f"wave_{wave_index}", "wave",
                            capabilities=[s.capability.value for s, _ in runnable],
                            serial=self.serial_mode):
                if self.serial_mode:
                    responses = []
                    for step, agent in runnable:
                        try:
                            responses.append(await build(step, agent))
                        except BaseException as exc:  # noqa: BLE001
                            responses.append(exc)
                else:
                    responses = await asyncio.gather(
                        *[build(step, agent) for step, agent in runnable],
                        return_exceptions=True)

            for (step, agent), response in zip(runnable, responses):
                if isinstance(response, BaseException):
                    response = AgentResponse(
                        agent=agent.name, capability=step.capability,
                        status=AgentStatus.FAILED, confidence=0.0,
                        warnings=[f"{agent.name} raised {type(response).__name__}"],
                        error=str(response))
                results[step.capability] = response
                if step.required and not response.succeeded:
                    trace.note(f"required capability {step.capability.value} "
                               f"returned {response.status.value}")

        return results

    @staticmethod
    def _dependency_payload(depends_on: list[Capability],
                            results: dict[Capability, AgentResponse]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for cap in depends_on:
            response = results.get(cap)
            if response is not None and response.succeeded:
                payload[cap.value] = response.data
        # The risk and response agents need the full set, not just their edges.
        # `_responses` carries the live AgentResponse objects (including their
        # evidence rows) rather than a serialised copy - the risk engine has to
        # reference evidence ids, and round-tripping them through JSON here would
        # cost latency for nothing.
        payload["_all"] = {c.value: r.data for c, r in results.items() if r.succeeded}
        payload["_status"] = {c.value: r.status.value for c, r in results.items()}
        payload["_responses"] = dict(results)
        return payload
