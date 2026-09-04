"""Ocean Intelligence Agent."""

from __future__ import annotations

from app.agents.data_agent import OCEAN_VARIABLES, DataRetrievalAgent
from app.schemas.common import Capability


class OceanAgent(DataRetrievalAgent):
    name = "ocean_agent"
    capability = Capability.OCEAN
    responsibility = (
        "Sea state at the marine point: significant wave height, wave and swell "
        "period and direction, surface currents and sea surface temperature")
    consumes = ("resolved marine point", "valid time")
    produces = OCEAN_VARIABLES
    sources = ("INCOIS (authority)", "Open-Meteo marine (secondary)")
    allowed_sources = ("INCOIS", "OPEN_METEO", "MOSDAC")
    variables = OCEAN_VARIABLES
    failure_behaviour = (
        "Returns PARTIAL; significant wave height is a required risk variable, so "
        "losing every ocean source withholds the safety advisory rather than "
        "guessing the sea state")
