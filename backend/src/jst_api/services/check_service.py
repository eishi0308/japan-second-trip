"""RouteCheck on the v2 feasibility engine.

Three steps, matching the screen:

1. ``parse_itinerary``: pasted text becomes a stop table. A model extracts
   only the structure (names and nights), and the deterministic parser runs
   if the model is unavailable. Each row is matched against the catalogue,
   and rows that match nothing are marked so the UI can highlight them for
   the traveller to confirm.
2. ``run_check``: the confirmed table goes through the deterministic
   feasibility engine, with day-by-day analysis, issues, fixes and booking
   items.
3. ``also_consider``: with the same conditions, what Where Next would
   suggest instead.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.logging import get_logger
from jst_api.db.repositories.planner_repo import load_planner_catalogue
from jst_api.domain.results import ExtractedItinerary
from jst_api.planner.engine import Planner
from jst_api.planner.feasibility import Checker, Itinerary
from jst_api.planner.model import Catalogue, Conditions
from jst_api.planner.results import CheckResult
from jst_api.prompts.registry import get_prompts
from jst_api.providers.llm import DemoLLMProvider, TaskClass, complete_with_repair, structured_block
from jst_api.security.injection import sanitise_user_text

log = get_logger(__name__)


class ParsedRow(BaseModel):
    name: str
    nights: int
    status: str  # "known" | "city" | "unknown"
    matched_name: str | None = None
    slug: str | None = None
    area: str | None = None
    note: str | None = None


class ParsedItinerary(BaseModel):
    rows: list[ParsedRow]
    arrival_city: str | None = None
    departure_city: str | None = None
    to_confirm: list[str] = Field(default_factory=list)
    source: str


class AlsoConsider(BaseModel):
    character_label: str
    title: str
    nights_label: str
    fit_label: str


@dataclass
class CheckOutcome:
    check: CheckResult
    also_consider: list[AlsoConsider]


def match_row(checker: Checker, name: str, nights: int, note: str | None = None) -> ParsedRow:
    from jst_api.planner.feasibility import StopSpec

    stop = checker.resolve_stop(StopSpec(name, nights))
    status = {"place": "known", "city": "city", "unknown": "unknown"}[stop.kind]
    return ParsedRow(
        name=name,
        nights=nights,
        status=status,
        matched_name=stop.place.name if stop.place else None,
        slug=stop.place.slug if stop.place else None,
        area=stop.place.area if stop.place else None,
        note=note,
    )


async def parse_itinerary(session: AsyncSession, registry: Any, text: str) -> ParsedItinerary:
    cleaned, scan = sanitise_user_text(text, max_chars=4000)
    prompt = get_prompts().get("itinerary_extraction")
    user = f"{prompt.render_user(raw_text=cleaned)}\n\n" + structured_block({"raw_text": cleaned})
    source = "model"
    provider = registry.llm
    if scan.quarantine:
        provider, source = DemoLLMProvider(), "deterministic"
    try:
        extracted, _ = await complete_with_repair(
            provider,
            system=prompt.system,
            user=user,
            schema=ExtractedItinerary,
            model=registry.router.model_for(TaskClass.EXTRACTION),
            repair_model=registry.router.model_for(TaskClass.REPAIR),
        )
    except Exception as exc:
        log.warning("check.parse_fallback", error=str(exc)[:200])
        extracted, _ = await complete_with_repair(
            DemoLLMProvider(),
            system=prompt.system,
            user=user,
            schema=ExtractedItinerary,
            model=None,
        )
        source = "deterministic"
    if getattr(registry.llm, "is_demo", False):
        source = "deterministic"

    checker = Checker(await load_planner_catalogue(session))
    rows = [match_row(checker, s.name, s.nights, s.note) for s in extracted.stops]
    to_confirm = [
        f"{r.name}: not in our database. Check the name, or keep it unchecked."
        for r in rows
        if r.status == "unknown"
    ]
    to_confirm += list(extracted.ambiguities)
    if not rows:
        to_confirm.insert(
            0, "We could not find any stops in this text. Add them to the table one by one."
        )
    return ParsedItinerary(
        rows=rows,
        arrival_city=extracted.arrival_city,
        departure_city=extracted.departure_city,
        to_confirm=to_confirm,
        source=source,
    )


def also_consider(catalogue: Catalogue, checker: Checker, itin: Itinerary) -> list[AlsoConsider]:
    """With these conditions, what Where Next would suggest (PRODUCT_AMENDMENTS.md §3)."""
    stops = [checker.resolve_stop(s) for s in itin.stops]
    regional = [s for s in stops if s.kind == "place"]
    nights = sum(s.spec.nights for s in regional)
    if nights < 2:
        return []
    themes = Counter(t for s in regional for t in (s.place.themes if s.place else ()))
    conditions = Conditions(
        month=itin.month,
        regional_nights=min(nights, 10),
        arrival_hub=itin.arrival or (stops[0].place.hub_slug if stops[0].place else None),
        departure_hub=itin.departure or (stops[-1].place.hub_slug if stops[-1].place else None),
        interests=tuple(t for t, _ in themes.most_common(3)),
        visited=tuple(s.slug for s in regional if s.slug),
        transport=itin.transport,
        pace=itin.pace,
    )
    planner = Planner(catalogue, now=checker.now)
    resolved = planner.resolve(
        conditions, conditions.month or itin.month, conditions.regional_nights or nights
    )
    result = planner.option_set(resolved, explain=False, check=False)
    return [
        AlsoConsider(
            character_label=o.character_label,
            title=o.title,
            nights_label=o.nights_label,
            fit_label=o.fit.label,
        )
        for o in result.options
    ]


async def run_check(session: AsyncSession, itin: Itinerary) -> CheckOutcome:
    catalogue = await load_planner_catalogue(session)
    checker = Checker(catalogue)
    result = checker.check(itin)
    return CheckOutcome(result, also_consider(catalogue, checker, itin))


async def alternatives_for(
    session: AsyncSession, itin: Itinerary, index: int
) -> list[dict[str, Any]]:
    checker = Checker(await load_planner_catalogue(session))
    analysis = checker.analyse(itin)
    if not 0 <= index < len(analysis.stops) or analysis.stops[index].spec.pinned:
        return []
    return [
        {"slug": p.slug, "name": p.name, "area": p.area, "summary": p.summary, "is_demo": p.is_demo}
        for p in checker.alternatives(analysis, index, limit=5)
    ]
