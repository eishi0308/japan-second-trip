"""FastAPI application factory."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from jst_api import __version__
from jst_api.api.errors import install_error_handlers
from jst_api.api.v1 import admin, analyses, evidence, feedback, system, trips
from jst_api.core.config import Settings, get_settings
from jst_api.core.ids import new_id
from jst_api.core.logging import configure_logging, get_logger
from jst_api.db.base import build_engine, get_sessionmaker, reset_engine
from jst_api.observability.metrics import METRICS
from jst_api.observability.tracing import init_tracing
from jst_api.providers.registry import build_registry
from jst_api.security.ratelimit import RateLimiter
from jst_api.services.analysis_service import AnalysisService
from jst_api.services.mcp_backend import JstTravelBackend

log = get_logger(__name__)

DESCRIPTION = """\
Verified regional travel intelligence for repeat visitors to Japan.

Two capabilities:

* **Where Next** — which region actually fits *this* trip, scored by a
  deterministic rubric and explained against retrieved evidence.
* **RouteCheck** — whether an itinerary is realistic, judged by a deterministic
  rules engine over real transport data.

Operational facts come from verified records or clearly-labelled estimates.
Where the system cannot verify something, it says so rather than guessing.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level, json_output=settings.log_json)
    init_tracing(settings)

    reset_engine()
    build_engine(settings)
    session_factory = get_sessionmaker()
    registry = build_registry(session_factory, settings)

    app.state.session_factory = session_factory
    app.state.registry = registry
    app.state.backend = JstTravelBackend(session_factory, registry, settings)
    app.state.analysis_service = AnalysisService(session_factory, registry, settings)

    redis_client = None
    if settings.redis_url:
        try:  # pragma: no cover - requires Redis
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception as exc:
            log.warning("startup.redis_unavailable", error=str(exc))
    app.state.rate_limiter = RateLimiter(limit=settings.rate_limit_per_minute, redis=redis_client)

    log.info(
        "startup.complete",
        environment=settings.environment,
        demo_mode=registry.any_demo,
        providers={k: v["provider"] for k, v in registry.describe().items()},
    )
    yield
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Japan Second Trip API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or new_id("req")
        started = time.perf_counter()
        import structlog

        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            METRICS.observe_latency(f"http.{request.method}", elapsed)
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request_id
        response.headers["server-timing"] = f"app;dur={elapsed:.1f}"
        return response

    install_error_handlers(app)

    app.include_router(system.router)
    app.include_router(analyses.router, prefix=settings.api_prefix)
    app.include_router(trips.router, prefix=settings.api_prefix)
    app.include_router(evidence.router, prefix=settings.api_prefix)
    app.include_router(feedback.router, prefix=settings.api_prefix)
    app.include_router(admin.router, prefix=settings.api_prefix)
    return app


app = create_app()
