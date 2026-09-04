"""Enumerations shared by every layer of ORCA.

These are deliberately *closed* sets.  If an agent or provider wants to express
something outside them, that is a design conversation - not a free-text string.
"""

from __future__ import annotations

from enum import Enum


class Language(str, Enum):
    EN = "en"
    HI = "hi"
    ML = "ml"   # Malayalam - Kerala, our first demo coast
    TA = "ta"   # Tamil
    BN = "bn"
    TE = "te"
    MR = "mr"
    GU = "gu"
    OR = "or"


class Intent(str, Enum):
    MARINE_SAFETY = "marine_safety"          # "is it safe to go out"
    SEA_CONDITION = "sea_condition"          # "what is the sea like"
    WEATHER_INFO = "weather_info"            # "marine weather near X"
    PFZ_LOOKUP = "pfz_lookup"                # "nearest potential fishing zone"
    HAZARD_CHECK = "hazard_check"            # "cyclone / lightning warnings"
    AVOID_AREAS = "avoid_areas"              # "what areas should I avoid"
    ROUTE_RISK = "route_risk"                # "safest route between A and B"
    ANALYTICAL = "analytical"                # "why is fishing lower at 5-10pm"
    LOCATION_INFO = "location_info"          # "where am I / how far is X"
    SMALL_TALK = "small_talk"
    UNKNOWN = "unknown"


class Activity(str, Enum):
    FISHING_SMALL_BOAT = "fishing_small_boat"     # country craft / IBM
    FISHING_MECHANISED = "fishing_mechanised"     # trawler
    SWIMMING = "swimming"
    DIVING = "diving"
    CARGO_TRANSIT = "cargo_transit"
    PATROL = "patrol"
    TOURISM = "tourism"
    RESEARCH = "research"
    GENERIC = "generic"


class VesselClass(str, Enum):
    NONE = "none"
    CANOE = "canoe"                 # traditional non-motorised
    SMALL_MOTORISED = "small_motorised"   # < 12 m
    MECHANISED = "mechanised"       # 12-24 m
    LARGE = "large"                 # > 24 m


class Source(str, Enum):
    """Authoritative source families. Not the same thing as a provider."""

    IMD = "IMD"
    INCOIS = "INCOIS"
    MOSDAC = "MOSDAC"
    GIS = "GIS"
    OPEN_METEO = "OPEN_METEO"
    OPEN_WEATHER_MAP = "OPEN_WEATHER_MAP"
    ORCA_INTERNAL = "ORCA_INTERNAL"   # deterministic computation, not a source


class DataOrigin(str, Enum):
    """How a number reached the user. Never hidden, never mixed up."""

    LIVE = "LIVE"
    DEMO = "DEMO"
    CACHED_LIVE = "CACHED_LIVE"
    COMPUTED = "COMPUTED"
    MIXED = "MIXED"        # some values live, some demo - never silently blended


class Freshness(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class SourceStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"          # answered, but late / partial / stale
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class AgentStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class VariableKind(str, Enum):
    OBSERVED = "OBSERVED"
    FORECAST = "FORECAST"
    ANALYSIS = "ANALYSIS"
    ADVISORY = "ADVISORY"
    DERIVED = "DERIVED"


class QualityFlag(str, Enum):
    GOOD = "GOOD"
    ESTIMATED = "ESTIMATED"
    SUSPECT = "SUSPECT"
    MISSING = "MISSING"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

    @property
    def rank(self) -> int:
        return {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3,
                "INSUFFICIENT_DATA": -1}[self.value]


class DecisionStatus(str, Enum):
    ADVISORY_ISSUED = "ADVISORY_ISSUED"
    ADVISORY_WITHHELD = "ADVISORY_WITHHELD"      # not enough / too stale evidence
    ADVISORY_DEGRADED = "ADVISORY_DEGRADED"      # issued, but with caveats


class Capability(str, Enum):
    """What the planner can ask for. Maps 1:1 onto an agent."""

    GEOSPATIAL = "geospatial"
    WEATHER = "weather"
    OCEAN = "ocean"
    SATELLITE = "satellite"
    PFZ = "pfz"
    HAZARD = "hazard"
    ROUTE = "route"
    RISK = "risk"
    RESPONSE = "response"


class ConflictSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"       # changes the risk band
