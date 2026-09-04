"""Satellite / Earth Observation Agent.

Always optional, by design.  Two facts drive that:

* MOSDAC's published access route is an order-based archive download, so
  satellite products are hours old by the time they can be used;
* ocean-colour retrievals do not exist under cloud, which is exactly when a
  monsoon safety question is most likely to be asked.

So this agent contributes context (SST, chlorophyll, cloud) and never gates a
safety decision.  When it has nothing, it says so and the answer proceeds.
"""

from __future__ import annotations

from app.agents.data_agent import SATELLITE_VARIABLES, DataRetrievalAgent
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability
from app.observability.trace import Trace


class SatelliteAgent(DataRetrievalAgent):
    name = "satellite_agent"
    capability = Capability.SATELLITE
    responsibility = (
        "Satellite-derived context: sea surface temperature, ocean colour / "
        "chlorophyll, and cloud cover from the most recent usable pass")
    consumes = ("resolved marine point",)
    produces = SATELLITE_VARIABLES
    sources = ("MOSDAC / ISRO",)
    allowed_sources = ("MOSDAC",)
    variables = SATELLITE_VARIABLES
    optional = True
    failure_behaviour = (
        "Never blocks an answer. Cloud-limited or unavailable retrievals are "
        "reported as such and the pipeline continues")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        response = await super().run(request, trace)
        # An optional agent must never surface as a hard failure.
        if response.status is AgentStatus.FAILED:
            response.status = AgentStatus.SKIPPED
            response.warnings.append(
                "Satellite EO contributed nothing to this answer (cloud cover or "
                "archive latency). This does not affect the safety assessment.")
        return response
