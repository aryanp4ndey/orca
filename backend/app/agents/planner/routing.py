"""Intent -> capability routing table.

The planner does not call every agent for every query, and this table is why.
It is data, not control flow, so a judge can read the routing policy in one
screen and we can unit-test it directly.

Each entry lists the capabilities needed, whether each is required (its failure
degrades the answer) or optional (its failure is noted and ignored), and the
dependency edges that force ordering.  Everything without an edge between it
runs concurrently.
"""

from __future__ import annotations

from app.schemas.common import Capability, Intent

GEO = Capability.GEOSPATIAL
WX = Capability.WEATHER
OCN = Capability.OCEAN
SAT = Capability.SATELLITE
PFZ = Capability.PFZ
HAZ = Capability.HAZARD
RTE = Capability.ROUTE
RISK = Capability.RISK
RESP = Capability.RESPONSE


class Step:
    __slots__ = ("capability", "required", "depends_on", "reason", "deadline_ms", "options")

    def __init__(self, capability: Capability, required: bool = True,
                 depends_on: tuple[Capability, ...] = (), reason: str = "",
                 deadline_ms: int = 2200, options: dict | None = None) -> None:
        self.capability = capability
        self.required = required
        self.depends_on = depends_on
        self.reason = reason
        self.deadline_ms = deadline_ms
        self.options = options or {}


# Shared building blocks -----------------------------------------------------
_GEO_FIRST = Step(GEO, True, (), "resolve the place to a marine point and its zones", 600)


ROUTES: dict[Intent, list[Step]] = {
    Intent.MARINE_SAFETY: [
        _GEO_FIRST,
        Step(WX, True, (GEO,), "wind, rain, visibility and thunderstorm potential drive small-boat risk"),
        Step(OCN, True, (GEO,), "significant wave height and swell are the dominant capsize factors"),
        Step(HAZ, True, (GEO,), "an active cyclone or high-wave warning overrides everything else"),
        Step(SAT, False, (GEO,), "SST and cloud add context; archive latency means it can never gate the answer", 900),
        Step(RISK, True, (WX, OCN, HAZ), "deterministic scoring over the retrieved evidence", 400),
        Step(RESP, True, (RISK,), "explain the decision in the user's language", 900),
    ],
    Intent.SEA_CONDITION: [
        _GEO_FIRST,
        Step(OCN, True, (GEO,), "the question is about the sea state itself"),
        Step(WX, True, (GEO,), "wind context is needed to interpret the sea state"),
        Step(SAT, False, (GEO,), "sea surface temperature adds context", 900),
        Step(RISK, False, (WX, OCN), "risk band gives the reading meaning for the user's activity", 400),
        Step(RESP, True, (RISK,), "explain in the user's language", 900),
    ],
    Intent.WEATHER_INFO: [
        _GEO_FIRST,
        Step(WX, True, (GEO,), "the question is about the weather"),
        Step(HAZ, False, (GEO,), "surface any warning in force for the same area"),
        Step(RESP, True, (WX,), "explain in the user's language", 900),
    ],
    Intent.PFZ_LOOKUP: [
        _GEO_FIRST,
        Step(PFZ, True, (GEO,), "the advisory itself"),
        Step(OCN, False, (GEO,), "sea state decides whether the zone is reachable safely"),
        Step(SAT, False, (GEO,), "chlorophyll and SST are the physical basis of a PFZ", 900),
        Step(RISK, False, (OCN,), "a fishing zone you cannot safely reach is not a recommendation", 400),
        Step(RESP, True, (PFZ,), "bearing, distance and validity in the user's language", 900),
    ],
    Intent.HAZARD_CHECK: [
        _GEO_FIRST,
        Step(HAZ, True, (GEO,), "the question is about warnings"),
        Step(WX, True, (GEO,), "lightning and squall potential come from the atmospheric source"),
        Step(OCN, False, (GEO,), "high-wave and swell-surge alerts come from the ocean source"),
        Step(RESP, True, (HAZ,), "explain in the user's language", 900),
    ],
    Intent.AVOID_AREAS: [
        _GEO_FIRST,
        Step(HAZ, True, (GEO,), "hazard areas are part of the answer"),
        Step(OCN, False, (GEO,), "rough-sea sectors are areas to avoid too"),
        Step(RESP, True, (HAZ, GEO), "list zones with distance and bearing", 900),
    ],
    Intent.ROUTE_RISK: [
        _GEO_FIRST,
        Step(WX, True, (GEO,), "conditions along the corridor"),
        Step(OCN, True, (GEO,), "sea state along the corridor"),
        Step(HAZ, False, (GEO,), "warnings intersecting the corridor"),
        Step(RTE, True, (GEO, WX, OCN), "sample the corridor and score each segment", 1500),
        Step(RISK, True, (RTE,), "overall passage risk", 400),
        Step(RESP, True, (RISK,), "explain the passage in the user's language", 900),
    ],
    Intent.ANALYTICAL: [
        _GEO_FIRST,
        Step(OCN, True, (GEO,), "compare the ocean variables across the requested windows"),
        Step(WX, True, (GEO,), "compare the atmospheric variables across the requested windows"),
        Step(SAT, False, (GEO,), "chlorophyll and SST are candidate explanatory variables", 900),
        Step(RESP, True, (OCN, WX), "explain what the data does and does not support", 1200),
    ],
    Intent.LOCATION_INFO: [
        _GEO_FIRST,
        Step(RESP, True, (GEO,), "distances and zones in the user's language", 700),
    ],
    Intent.SMALL_TALK: [
        Step(RESP, True, (), "no data retrieval needed", 500),
    ],
    Intent.UNKNOWN: [
        _GEO_FIRST,
        Step(WX, False, (GEO,), "best-effort conditions while we ask what they meant"),
        Step(OCN, False, (GEO,), "best-effort sea state while we ask what they meant"),
        Step(RESP, True, (), "ask a clarifying question", 700),
    ],
}

# Why a capability was *not* invoked. Shown in the trace so "why didn't the
# satellite agent run?" has an answer that is not "we forgot".
SKIP_REASONS: dict[tuple[Intent, Capability], str] = {
    (Intent.MARINE_SAFETY, PFZ): "no fishing-zone question was asked",
    (Intent.MARINE_SAFETY, RTE): "no origin/destination pair in the query",
    (Intent.SEA_CONDITION, HAZ): "no warning question asked; hazards surface via the risk band",
    (Intent.SEA_CONDITION, PFZ): "no fishing-zone question was asked",
    (Intent.WEATHER_INFO, OCN): "question is atmospheric; ocean state not requested",
    (Intent.WEATHER_INFO, SAT): "satellite EO adds nothing to a short-range weather answer and costs latency",
    (Intent.WEATHER_INFO, RISK): "no activity given, so there is nothing to assess risk against",
    (Intent.PFZ_LOOKUP, HAZ): "hazard check runs only when safety or warnings are asked about",
    (Intent.HAZARD_CHECK, SAT): "satellite archive latency exceeds the warning horizon",
    (Intent.HAZARD_CHECK, RISK): "warnings are reported as issued, not re-scored",
    (Intent.AVOID_AREAS, SAT): "not relevant to boundary and hazard geography",
    (Intent.AVOID_AREAS, WX): "avoidance is driven by zones and warnings, not by ambient weather",
    (Intent.ROUTE_RISK, SAT): "adds latency to an already multi-sample computation",
    (Intent.ROUTE_RISK, PFZ): "no fishing-zone question was asked",
    (Intent.ANALYTICAL, RISK): "the question asks for an explanation, not a safety decision",
    (Intent.ANALYTICAL, HAZ): "no warning question asked",
    (Intent.LOCATION_INFO, WX): "purely spatial question",
    (Intent.LOCATION_INFO, OCN): "purely spatial question",
    (Intent.SMALL_TALK, GEO): "no location needed",
}

ALL_CAPABILITIES = [GEO, WX, OCN, SAT, PFZ, HAZ, RTE, RISK, RESP]


def steps_for(intent: Intent) -> list[Step]:
    return ROUTES.get(intent, ROUTES[Intent.UNKNOWN])


def skipped_for(intent: Intent) -> dict[str, str]:
    used = {s.capability for s in steps_for(intent)}
    out: dict[str, str] = {}
    for cap in ALL_CAPABILITIES:
        if cap in used:
            continue
        out[cap.value] = SKIP_REASONS.get(
            (intent, cap), "not required for this intent")
    return out
