"""Where Next planning: request in, three options out.

The only model call is the past-trip extraction, and only when the traveller
wrote past-trip answers. Everything after it is the deterministic planner. If
the model is down or returns something unusable, the keyword extractor runs
instead and the plan is still produced (PRODUCT_AMENDMENTS.md §7, "LLM down").
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.errors import ValidationFailedError
from jst_api.core.logging import get_logger
from jst_api.db.repositories.planner_repo import load_planner_catalogue
from jst_api.planner.engine import Planner
from jst_api.planner.model import Avoid, Catalogue, Conditions, Reaction, ReactionKind, Transport
from jst_api.planner.preferences import PastTripPreferences, interests_from, keyword_past_trip
from jst_api.planner.results import PlanResult
from jst_api.prompts.registry import get_prompts
from jst_api.providers.llm import TaskClass, complete_with_repair, structured_block
from jst_api.security.injection import sanitise_user_text

log = get_logger(__name__)


@dataclass(frozen=True)
class PlanInput:
    month: int | None
    regional_nights: int | None
    arrival_city: str | None
    departure_city: str | None
    interests: tuple[str, ...]
    visited: tuple[str, ...]
    transport: Transport
    pace: Any
    big_luggage: bool
    kids: bool
    limited_walking: bool
    must_include: tuple[str, ...]
    scene_cards: tuple[str, ...]
    past_trip_best: str | None
    past_trip_tired: str | None
    wish: str | None
    reactions: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class Inferred:
    preferences: PastTripPreferences
    source: str  # "model" | "deterministic" | "none"
    flagged: bool = False


def resolve_hub(catalogue: Catalogue, city: str | None) -> str | None:
    """A city name or hub slug to a hub slug. ``None`` stays "Not decided yet"."""
    if city is None or not city.strip():
        return None
    key = city.strip().lower()
    for hub in catalogue.hubs.values():
        if key in (hub.slug, hub.name.lower()):
            return hub.slug
    known = ", ".join(sorted(h.name for h in catalogue.hubs.values() if h.is_gateway))
    raise ValidationFailedError(
        f"We do not know the city '{city}'. Try one of: {known}.",
        details={"city": city},
    )


async def infer_past_trip(registry: Any, data: PlanInput) -> Inferred:
    if not (data.past_trip_best or data.past_trip_tired or data.wish):
        return Inferred(PastTripPreferences(), "none")
    best, scan_best = sanitise_user_text(data.past_trip_best or "", max_chars=500)
    tired, scan_tired = sanitise_user_text(data.past_trip_tired or "", max_chars=500)
    wish, scan_wish = sanitise_user_text(data.wish or "", max_chars=500)
    flagged = any(s.quarantine for s in (scan_best, scan_tired, scan_wish))
    fallback = keyword_past_trip(f"{best} {wish}".strip(), tired)
    if flagged:
        # Instruction-shaped text never reaches a model; keywords still work on it.
        return Inferred(fallback, "deterministic", flagged=True)
    prompt = get_prompts().get("past_trip_preferences")
    user = f"{prompt.render_user()}\n\n" + structured_block(
        {"best": best, "tired": tired, "wish": wish}
    )
    try:
        output, _ = await complete_with_repair(
            registry.llm,
            system=prompt.system,
            user=user,
            schema=PastTripPreferences,
            model=registry.router.model_for(TaskClass.EXTRACTION),
            repair_model=registry.router.model_for(TaskClass.REPAIR),
        )
    except Exception as exc:
        log.warning("plan.past_trip_fallback", error=str(exc)[:200])
        return Inferred(fallback, "deterministic")
    return Inferred(output, "model")


async def build_plan(
    session: AsyncSession, registry: Any, data: PlanInput
) -> tuple[PlanResult, Inferred, float]:
    started = time.perf_counter()
    catalogue = await load_planner_catalogue(session)
    inferred = await infer_past_trip(registry, data)
    interests = interests_from(
        data.interests, data.scene_cards, [i.value for i in inferred.preferences.liked]
    )
    conditions = Conditions(
        month=data.month,
        regional_nights=data.regional_nights,
        arrival_hub=resolve_hub(catalogue, data.arrival_city),
        departure_hub=resolve_hub(catalogue, data.departure_city),
        interests=interests,
        visited=data.visited,
        transport=data.transport,
        pace=data.pace,
        big_luggage=data.big_luggage,
        kids=data.kids,
        limited_walking=data.limited_walking,
        must_include=data.must_include,
        avoid=tuple(Avoid(a) for a in inferred.preferences.avoid),
        reactions=tuple(Reaction(ReactionKind(kind), stops) for kind, stops in data.reactions),
    )
    result = Planner(catalogue).plan(conditions)
    return result, inferred, (time.perf_counter() - started) * 1000
