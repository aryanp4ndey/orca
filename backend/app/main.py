"""ORCA application factory.

    uvicorn app.main:app --reload        (from backend/)
    python -m app.main                   (equivalent, reads ORCA_HOST/ORCA_PORT)
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as v1_router
from app.config.settings import ConfigurationError, get_settings
from app.core.errors import OrcaError
from app.observability.logging import configure_logging, get_logger, request_id_var
from app.providers.http import close_http_client
from app.services.container import Container, warmup
from app.services.ledger import QueryLedger
from app.services.marine_service import MarineService
from app.services.ocean_layer import OceanLayerService
from app.services.query_service import QueryService

log = get_logger("orca.main")

DESCRIPTION = """
**ORCA - Marine EcOsystem Reasoning with Collaborative Agents**

A conversational multi-agent marine intelligence and decision-support platform.
Built for Smart India Hackathon 2026, problem statement **SIH26176** (ISRO).

How an answer is produced:

`natural language -> intent + context -> task plan -> agent routing ->
parallel multi-source retrieval -> spatial/temporal reasoning -> evidence
validation -> deterministic risk logic -> explainable response`

Two rules the whole system is built around:

* **The AI decides what data to ask for. Authoritative sources decide what the
  data says.** A language model never produces a marine measurement, never
  computes geometry and never chooses a risk level.
* **Provenance is not optional.** Every number in an answer has an `Evidence`
  row with a source, dataset, timestamp and freshness verdict. Pull the whole
  chain for any answer from `/api/v1/evidence/{query_id}`.

ORCA is a decision-support prototype. It is **not** a certified navigation or
maritime-safety system.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging("INFO", json_output=settings.environment != "dev")
    started = time.perf_counter()
    try:
        container = Container.build(settings)
    except ConfigurationError as exc:
        log.error("startup configuration error: %s", exc)
        raise
    warm = warmup()
    app.state.container = container
    app.state.query_service = QueryService(container)
    app.state.marine_service = MarineService(container)
    app.state.ocean_layer = OceanLayerService(container.settings, container.cache)
    app.state.ledger = QueryLedger()
    for warning in container.config_warnings:
        log.warning("configuration warning: %s", warning)
    log.info("ORCA ready in %.1f ms (demo_mode=%s, providers=%d, %s)",
             (time.perf_counter() - started) * 1000, settings.demo_mode,
             len(container.registry.providers), warm)
    try:
        yield
    finally:
        await close_http_client()
        log.info("ORCA shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} - {settings.app_long_name}",
        description=DESCRIPTION, version=settings.version, lifespan=lifespan,
        docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
        contact={"name": "Team DRISHTI - SIH26176"},
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                       allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
    # Compression matters here: the evidence chain is the biggest part of a
    # response and it compresses ~8x, which is the difference between usable and
    # unusable on a 2G coastal link.
    app.add_middleware(GZipMiddleware, minimum_size=800)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter()
        rid = request.headers.get("x-request-id") or f"r_{int(started * 1000) % 10**10}"
        request_id_var.set(rid)
        response = await call_next(request)
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = rid
        response.headers["x-response-time-ms"] = f"{elapsed:.1f}"
        return response

    @app.exception_handler(OrcaError)
    async def orca_error_handler(request: Request, exc: OrcaError):
        return JSONResponse(status_code=422,
                            content={"error": exc.to_dict(),
                                     "user_message": exc.user_message})

    app.include_router(v1_router, prefix="/api/v1")
    _mount_frontend(app)

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        """Send the bare host to the app, not to JSON.

        Someone opening `localhost:8000` during a demo wants ORCA, not a service
        banner and not the Swagger console. The banner still exists at `/api` for
        anything that needs to probe the service.
        """
        return RedirectResponse(url="/app/", status_code=307)

    @app.get("/api", tags=["system"], summary="Service banner")
    async def banner():
        return {
            "name": settings.app_name, "long_name": settings.app_long_name,
            "problem_statement": "SIH26176", "organisation": "ISRO",
            "version": settings.version, "demo_mode": settings.demo_mode,
            "app": "/app/", "docs": "/docs", "health": "/api/v1/health",
            "query": "POST /api/v1/query",
            "disclaimer": ("Decision-support prototype. Not a certified navigation or "
                           "maritime-safety system."),
        }

    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the web client from the API process.

    One command starts everything. That is a demo requirement, not a
    convenience: the mock drill showed the demo has to survive a presenter who
    did not set it up. It also removes CORS from the demo path entirely, since
    the client is same-origin.

    The client is deliberately build-free - native ES modules, no bundler - so
    there is nothing to compile before this works.
    """
    web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "..", "frontend")
    web_dir = os.path.normpath(web_dir)
    if not os.path.isdir(web_dir):
        log.warning("frontend directory not found at %s; API-only mode", web_dir)
        return

    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    async def _app_index():
        return FileResponse(os.path.join(web_dir, "index.html"))

    # The service worker must be served from the root scope to be allowed to
    # control the whole origin.
    @app.get("/sw.js", include_in_schema=False)
    async def _service_worker():
        return FileResponse(os.path.join(web_dir, "sw.js"),
                            media_type="application/javascript",
                            headers={"Cache-Control": "no-cache",
                                     "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def _manifest():
        return FileResponse(os.path.join(web_dir, "manifest.webmanifest"),
                            media_type="application/manifest+json")

    app.mount("/app", StaticFiles(directory=web_dir, html=True), name="frontend")
    log.info("frontend mounted from %s at /app", web_dir)


app = create_app()


if __name__ == "__main__":
    import uvicorn
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False)
