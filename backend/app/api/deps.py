"""Request-scoped dependencies."""

from __future__ import annotations

from fastapi import Request

from app.services.container import Container
from app.services.ledger import QueryLedger
from app.services.marine_service import MarineService
from app.services.ocean_layer import OceanLayerService
from app.services.query_service import QueryService


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


def get_marine_service(request: Request) -> MarineService:
    return request.app.state.marine_service


def get_ledger(request: Request) -> QueryLedger:
    return request.app.state.ledger


def get_ocean_layer(request: Request) -> OceanLayerService:
    return request.app.state.ocean_layer
