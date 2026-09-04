"""Weather Intelligence Agent."""

from __future__ import annotations

from app.agents.data_agent import WEATHER_VARIABLES, DataRetrievalAgent
from app.schemas.common import Capability


class WeatherAgent(DataRetrievalAgent):
    name = "weather_agent"
    capability = Capability.WEATHER
    responsibility = (
        "Atmospheric conditions over the marine point: wind and gusts, rainfall, "
        "visibility, cloud, temperature and convective/lightning potential")
    consumes = ("resolved marine point", "valid time")
    produces = WEATHER_VARIABLES
    sources = ("IMD (authority)", "Open-Meteo (secondary)")
    allowed_sources = ("IMD", "OPEN_METEO", "OPEN_WEATHER_MAP", "INCOIS")
    variables = WEATHER_VARIABLES
    failure_behaviour = (
        "Returns PARTIAL with the sources that answered; if no atmospheric source "
        "answers the risk engine loses a required variable and withholds the advisory")
