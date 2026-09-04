"""ORCA v1 API.

Only endpoints that are actually implemented are exposed. Contract details and
example payloads live in ``docs/api.md``; the live schema is at ``/docs``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import (
    get_container,
    get_ledger,
    get_marine_service,
    get_ocean_layer,
    get_query_service,
)
from app.core.clock import utcnow
from app.geo.layers import layer_catalogue
from app.i18n.catalog import supported_languages
from app.providers.demo_controls import get_demo_controls
from app.schemas.api import (
    HealthResponse,
    MarineStatusResponse,
    QueryRequest,
    QueryResponse,
    RouteRiskRequest,
    RouteRiskResponse,
)
from app.schemas.common import DataOrigin
from app.services.container import Container
from app.services.ledger import QueryLedger
from app.services.marine_service import MarineService
from app.services.ocean_layer import OceanLayerService
from app.services.query_service import QueryService

router = APIRouter()

# Geometry endpoints live in their own module; same prefix.
from app.api.v1.geo import router as geo_router  # noqa: E402
router.include_router(geo_router)


# --------------------------------------------------------------- health ----
@router.get("/health", response_model=HealthResponse, tags=["system"],
            summary="Liveness, configuration and per-source status")
async def health(container: Container = Depends(get_container)) -> HealthResponse:
    providers = container.registry.describe_all()
    return HealthResponse(
        status="ok", app=container.settings.app_name, version=container.settings.version,
        environment=container.settings.environment,
        demo_mode=container.settings.demo_mode,
        data_origin=DataOrigin.DEMO if container.settings.demo_mode else DataOrigin.LIVE,
        uptime_seconds=container.uptime_seconds, providers=providers,
        agents=[a["name"] for a in container.agent_catalogue()],
        llm=container.deps.llm.info(),
        cache={**container.cache.stats(), "sessions": container.sessions.stats(),
               "circuit_breakers": container.registry.breaker_snapshot()},
        warnings=container.config_warnings, time_utc=utcnow())


# ---------------------------------------------------------------- query ----
@router.post("/query", response_model=QueryResponse, tags=["conversation"],
             summary="Ask ORCA a marine question in natural language")
async def query(request: QueryRequest,
                service: QueryService = Depends(get_query_service),
                ledger: QueryLedger = Depends(get_ledger)) -> QueryResponse:
    response = await service.handle(request)
    ledger.put(response)
    return response


# ------------------------------------------------------ direct capabilities -
@router.get("/marine-status", response_model=MarineStatusResponse, tags=["marine"],
            summary="Structured conditions and risk for a place or coordinates")
async def marine_status(
    place: str | None = Query(None, examples=["Kochi"]),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    at: datetime | None = Query(None, description="UTC instant; defaults to now"),
    activity: str = Query("fishing_small_boat"),
    vessel: str = Query("small_motorised"),
    service: MarineService = Depends(get_marine_service),
) -> MarineStatusResponse:
    result = await service.marine_status(place, lat, lon, at, activity, vessel)
    if result is None:
        raise HTTPException(400, "Provide either ?place= or both ?lat= and ?lon=")
    return result


@router.get("/pfz", tags=["marine"],
            summary="Potential Fishing Zone advisories near a point")
async def pfz(place: str | None = Query(None), lat: float | None = Query(None),
              lon: float | None = Query(None),
              service: QueryService = Depends(get_query_service),
              ledger: QueryLedger = Depends(get_ledger)) -> dict[str, Any]:
    text = (f"Where is the nearest potential fishing zone from {place}?" if place
            else "Where is the nearest potential fishing zone today?")
    response = await service.handle(QueryRequest(query=text, lat=lat, lon=lon))
    ledger.put(response)
    markers = [m for m in response.visualizations.markers if m.get("kind") == "pfz"]
    return {"query_id": response.query_id, "answer": response.answer,
            "zones": markers, "layers": [l.model_dump() for l in response.visualizations.layers
                                         if l.style_hint == "pfz"],
            "sources": [s.model_dump(mode="json") for s in response.sources],
            "warnings": response.warnings, "freshness": response.freshness.model_dump(),
            "latency": response.latency.model_dump()}


@router.get("/alerts", tags=["marine"],
            summary="Warnings and hazard zones in force near a point")
async def alerts(place: str | None = Query(None), lat: float | None = Query(None),
                 lon: float | None = Query(None),
                 service: QueryService = Depends(get_query_service),
                 ledger: QueryLedger = Depends(get_ledger)) -> dict[str, Any]:
    text = (f"Are there any cyclone or lightning warnings near {place}?" if place
            else "Are there any cyclone or lightning warnings near my location?")
    response = await service.handle(QueryRequest(query=text, lat=lat, lon=lon))
    ledger.put(response)
    return {"query_id": response.query_id, "answer": response.answer,
            "sources": [s.model_dump(mode="json") for s in response.sources],
            "warnings": response.warnings,
            "evidence": [e.model_dump(mode="json") for e in response.evidence
                         if e.variable.startswith("advisory:")],
            "layers": [l.model_dump() for l in response.visualizations.layers],
            "freshness": response.freshness.model_dump(),
            "latency": response.latency.model_dump()}


@router.post("/route-risk", response_model=RouteRiskResponse, tags=["marine"],
             summary="Risk annotation of a straight-line passage (not navigation)")
async def route_risk(request: RouteRiskRequest,
                     service: MarineService = Depends(get_marine_service)
                     ) -> RouteRiskResponse:
    return await service.route_risk(request)


# ------------------------------------------------------- introspection ------

# ---------------------------------------------------- ocean-colour layer ----
@router.get("/ocean-layer", tags=["marine"],
            summary="Gridded ocean-colour field for the map (INCOIS OceanSat-2)")
async def ocean_layer(
    lat: float = Query(..., ge=-90, le=90, description="Centre latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Centre longitude"),
    variable: str = Query("CHL", description="CHL | KD490 | TSM"),
    half_deg: float | None = Query(
        None, gt=0, le=5,
        description="Bounding-box half-width in degrees. Kept small on purpose: "
                    "the server never fetches the whole grid."),
    service: OceanLayerService = Depends(get_ocean_layer),
) -> dict:
    """One gridded variable over a small box around a point.

    `origin` is authoritative and is the only thing the client should branch on:

    * `INCOIS_DATA` - real values from the INCOIS ERDDAP server
    * `DEMO` - ORCA's deterministic demo model, never labelled INCOIS
    * `UNAVAILABLE` - no values; `error` says why. The map must render this as
      unavailable rather than as zero or as an empty ocean.
    """
    field = await service.field(variable.upper(), lat, lon, half_deg)
    payload = field.model_dump(mode="json")
    payload["variables_available"] = service.variables()
    return payload


@router.get("/evidence/{query_id}", tags=["transparency"],
            summary="Full evidence chain and trace for an earlier answer")
async def evidence(query_id: str,
                   ledger: QueryLedger = Depends(get_ledger)) -> dict[str, Any]:
    response = ledger.get(query_id)
    if response is None:
        raise HTTPException(404, f"query_id {query_id} is not in the recent ledger")
    return {
        "query_id": query_id,
        "answer": response.answer,
        "risk": response.risk.model_dump(mode="json") if response.risk else None,
        "evidence": [e.model_dump(mode="json") for e in response.evidence],
        "sources": [s.model_dump(mode="json") for s in response.sources],
        "conflicts": [c.model_dump(mode="json") for c in response.conflicts],
        "freshness": response.freshness.model_dump(),
        "latency": response.latency.model_dump(),
        "trace": response.trace.model_dump() if response.trace else None,
    }


@router.get("/sources", tags=["transparency"],
            summary="Every data source, its role, access mechanism and verification status")
async def sources(container: Container = Depends(get_container)) -> dict[str, Any]:
    return {
        "demo_mode": container.settings.demo_mode,
        "demo_controls": get_demo_controls().snapshot() if container.settings.demo_mode else None,
        "providers": container.registry.describe_all(),
        "source_priority": {
            "atmosphere": ["IMD", "OPEN_METEO"],
            "ocean": ["INCOIS", "OPEN_METEO"],
            "satellite": ["MOSDAC"],
        },
        "circuit_breakers": container.registry.breaker_snapshot(),
    }


@router.get("/agents", tags=["transparency"],
            summary="Every agent: responsibility, inputs, outputs and failure behaviour")
async def agents(container: Container = Depends(get_container)) -> dict[str, Any]:
    from app.agents.planner.routing import ROUTES
    return {
        "agents": container.agent_catalogue(),
        "routing": {intent.value: [{"capability": s.capability.value,
                                    "required": s.required,
                                    "depends_on": [d.value for d in s.depends_on],
                                    "reason": s.reason}
                                   for s in steps]
                    for intent, steps in ROUTES.items()},
    }


@router.get("/map-layers", tags=["marine"],
            summary="Boundary layers available, with provenance and authority flags")
async def map_layers() -> dict[str, Any]:
    return {"layers": [l.model_dump(mode="json") for l in layer_catalogue()],
            "note": ("Layers flagged authoritative=false are approximations built for "
                     "this prototype. They must not be used for navigation or for any "
                     "legal determination of maritime limits.")}


@router.get("/languages", tags=["system"], summary="Languages ORCA can answer in")
async def languages() -> dict[str, Any]:
    return {"supported": supported_languages(),
            "note": ("Understanding is script- and keyword-based and covers more "
                     "input languages than the answer catalogue; unsupported answer "
                     "languages fall back to English.")}


@router.get("/demo/scenarios", tags=["demo"],
            summary="Canonical demo queries and the failure switches")
async def demo_scenarios() -> dict[str, Any]:
    from app.tools.demo_queries import DEMO_QUERIES, FAILURE_SWITCHES
    return {"queries": DEMO_QUERIES, "failure_switches": FAILURE_SWITCHES}
