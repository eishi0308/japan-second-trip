"""Health, readiness, pricing and provider disclosure."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from jst_api.api.deps import RegistryDep, SessionDep, SettingsDep
from jst_api.api.schemas import HealthOut, PricingPlan, ReadyOut
from jst_api.core.logging import get_logger
from jst_api.db.models import EvidenceChunk, Region
from jst_api.prompts.registry import get_prompts

router = APIRouter(tags=["system"])
log = get_logger(__name__)


@router.get("/health", response_model=HealthOut)
async def health(settings: SettingsDep) -> HealthOut:
    """Liveness. Never touches the database — a slow query must not evict the task."""
    from jst_api import __version__

    return HealthOut(status="ok", version=__version__, environment=settings.environment)


@router.get("/ready", response_model=ReadyOut)
async def ready(session: SessionDep, registry: RegistryDep, settings: SettingsDep) -> ReadyOut:
    """Readiness. Verifies the database is reachable and actually seeded."""
    checks: dict[str, bool] = {}
    chunks = 0
    regions = 0
    database = "unavailable"
    try:
        chunks = int(await session.scalar(select(func.count()).select_from(EvidenceChunk)) or 0)
        regions = int(await session.scalar(select(func.count()).select_from(Region)) or 0)
        database = "ok"
        checks["database"] = True
    except Exception as exc:  # pragma: no cover - requires a broken DB
        log.warning("ready.database_unavailable", error=str(exc))
        checks["database"] = False

    checks["seeded"] = chunks > 0 and regions > 0
    checks["prompts"] = bool(get_prompts().versions())
    checks["embeddings"] = getattr(registry.embeddings, "dim", 0) > 0

    return ReadyOut(
        status="ok" if all(checks.values()) else "degraded",
        database=database,
        evidence_chunks=chunks,
        regions=regions,
        providers=registry.describe(),
        demo_mode=registry.any_demo,
        checks=checks,
    )


@router.get("/pricing", response_model=list[PricingPlan])
async def pricing(settings: SettingsDep) -> list[PricingPlan]:
    """Pricing is configuration, not code. Values come from settings so a
    business hypothesis can change without a deploy of the reasoning layer."""
    return [
        PricingPlan(
            id="free",
            name="Where Next preview",
            price_aud=settings.price_where_next_aud,
            cadence="free",
            description="See which regions actually fit your dates, and why the others don't.",
            features=[
                "Ranked regions with the deterministic fit score",
                "The single strongest option explained",
                "Constraints that rule regions out",
            ],
            cta="Start free",
        ),
        PricingPlan(
            id="verified_route",
            name="Verified Regional Route",
            price_aud=settings.price_verified_route_aud,
            cadence="per trip",
            description="A regional leg built around real transport, with every operational claim sourced.",
            features=[
                "Full comparison across all candidate regions",
                "A concrete route with real travel times",
                "Booking lead times and language constraints",
                "Every claim carries a source and a last-verified date",
            ],
            cta="Build my route",
            highlight=True,
        ),
        PricingPlan(
            id="route_check",
            name="RouteCheck",
            price_aud=settings.price_route_check_aud,
            cadence="per itinerary",
            description="Your itinerary, stress-tested against the connections that actually exist.",
            features=[
                "Deterministic route-health analysis",
                "Critical problems, warnings and what is already working",
                "A costed alternative route",
                "Human verification when sources disagree",
            ],
            cta="Check my route",
        ),
    ]


@router.get("/providers")
async def providers(registry: RegistryDep) -> dict[str, Any]:
    """Public disclosure of what is live and what is demo data.

    Surfaced in the UI. A product whose whole claim is verification cannot be
    coy about which of its own answers came from seeded demo data.
    """
    return {"providers": registry.describe(), "demo_mode": registry.any_demo}
