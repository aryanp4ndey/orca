"""Agent base class and shared dependencies.

What makes something an *agent* in ORCA rather than a function with a fancy name:

* a single declared responsibility (:class:`Capability`);
* a typed input (:class:`AgentRequest`) and a typed output (:class:`AgentResponse`)
  validated by Pydantic at the boundary;
* its own tools - concretely, its own provider selection and its own
  deterministic computations;
* its own deadline, enforced by the base class, not by the caller's goodwill;
* defined failure behaviour: it returns a status, it does not raise;
* its own observability span and its own evidence rows.

An agent that cannot say what it is responsible for, what it needs, what it
returns and what it does when its source dies is not an agent.  All seven of
ORCA's core agents satisfy the list above; the file ``docs/agents.md`` is
generated from these declarations so the documentation cannot drift from code.
"""

from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass

from app.cache.base import Cache
from app.config.settings import Settings
from app.llm.base import LLMClient
from app.observability.logging import get_logger
from app.observability.trace import Trace
from app.providers.registry import ProviderRegistry
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability

log = get_logger("orca.agent")


@dataclass
class AgentDeps:
    settings: Settings
    registry: ProviderRegistry
    cache: Cache
    llm: LLMClient


class BaseAgent(abc.ABC):
    name: str = "abstract"
    capability: Capability = Capability.RESPONSE
    responsibility: str = ""
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    optional: bool = False
    failure_behaviour: str = "returns FAILED with a warning; orchestrator continues"

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    # ---- the method subclasses implement --------------------------------
    @abc.abstractmethod
    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse: ...

    # ---- the method the orchestrator calls -------------------------------
    async def execute(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        started = time.perf_counter()
        with trace.span(self.name, "agent", capability=self.capability.value,
                        deadline_ms=request.deadline_ms) as span:
            try:
                response = await asyncio.wait_for(
                    self.run(request, trace), timeout=request.deadline_ms / 1000.0)
            except asyncio.TimeoutError:
                response = AgentResponse(
                    agent=self.name, capability=self.capability,
                    status=AgentStatus.TIMEOUT, confidence=0.0,
                    warnings=[f"{self.name} exceeded its {request.deadline_ms} ms budget"],
                    error="timeout")
            except Exception as exc:  # noqa: BLE001 - an agent fault is not a crash
                log.exception("agent %s failed", self.name)
                response = AgentResponse(
                    agent=self.name, capability=self.capability,
                    status=AgentStatus.FAILED, confidence=0.0,
                    warnings=[f"{self.name} failed: {type(exc).__name__}"],
                    error=f"{type(exc).__name__}: {exc}")
            response.processing_time_ms = round((time.perf_counter() - started) * 1000.0, 2)
            span.status = response.status.value
            span.attributes["confidence"] = response.confidence
            span.attributes["evidence"] = len(response.evidence)
            return response

    # ---- self-description used by /api/v1/agents and docs ----------------
    @classmethod
    def describe(cls) -> dict:
        return {
            "name": cls.name,
            "capability": cls.capability.value,
            "responsibility": cls.responsibility,
            "consumes": list(cls.consumes),
            "produces": list(cls.produces),
            "sources": list(cls.sources),
            "optional": cls.optional,
            "failure_behaviour": cls.failure_behaviour,
        }
