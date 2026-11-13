"""Where Next planning endpoints (PRODUCT_AMENDMENTS.md v2).

``POST /plans`` is stateless: the same request always gives the same plan, so
what-if toggles and reactions are just a new request with one field changed.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from jst_api.api.deps import AnalysisRateLimitDep, RegistryDep, SessionDep
from jst_api.core.errors import NotFoundError
from jst_api.db.models import Hub, PlanRecord
from jst_api.domain.enums import Interest, Pace
from jst_api.planner.model import MAX_INTERESTS, ReactionKind, Transport
from jst_api.planner.preferences import SCENE_CARD_BY_SLUG, SCENE_CARDS
from jst_api.planner.results import PlanResult
from jst_api.services.plan_service import PlanInput, build_plan

router = APIRouter(prefix="/plans", tags=["plans"])

DEFAULT_VISITED = ["Tokyo", "Kyoto", "Osaka"]


class ReactionIn(BaseModel):
    kind: ReactionKind
    stops: list[str] = Field(min_length=1, max_length=3)


class PlanRequest(BaseModel):
    """One screen of input. Every required field accepts null for "Not decided yet"."""

    month: int | None = Field(default=None, ge=1, le=12)
    start_date: date | None = None
    regional_nights: int | None = Field(default=None, ge=1, le=21)
    arrival_city: str | None = Field(default=None, max_length=40)
    departure_city: str | None = Field(default=None, max_length=40)
    interests: list[Interest] = Field(default_factory=list, max_length=MAX_INTERESTS)
    visited: list[str] = Field(default_factory=lambda: list(DEFAULT_VISITED), max_length=50)
    transport: Transport = Transport.NO_CAR
    pace: Pace = Pace.BALANCED
    big_luggage: bool = False
    kids: bool = False
    limited_walking: bool = False
    must_include: list[str] = Field(default_factory=list, max_length=4)
    scene_cards: list[str] = Field(default_factory=list, max_length=len(SCENE_CARDS))
    past_trip_best: str | None = Field(default=None, max_length=500)
    past_trip_tired: str | None = Field(default=None, max_length=500)
    free_text: str | None = Field(default=None, max_length=500)
    reactions: list[ReactionIn] = Field(default_factory=list, max_length=12)
    save: bool = True

    @model_validator(mode="after")
    def _check(self) -> PlanRequest:
        unknown = [c for c in self.scene_cards if c not in SCENE_CARD_BY_SLUG]
        if unknown:
            raise ValueError(f"unknown scene card(s): {', '.join(unknown)}")
        if self.month is None and self.start_date is not None:
            self.month = self.start_date.month
        return self


class PreferencesOut(BaseModel):
    interests: list[str]
    avoid: list[str]
    source: str


class PlanResponse(BaseModel):
    plan_id: str | None = None
    request: PlanRequest
    plan: PlanResult
    preferences: PreferencesOut
    demo_mode: bool
    latency_ms: int


class SceneCardOut(BaseModel):
    slug: str
    title: str
    themes: list[str]


class HubOut(BaseModel):
    slug: str
    name: str
    area: str
    is_international_gateway: bool


@router.get("/scene-cards", response_model=list[SceneCardOut])
async def list_scene_cards() -> list[SceneCardOut]:
    return [SceneCardOut(slug=c.slug, title=c.title, themes=list(c.themes)) for c in SCENE_CARDS]


@router.get("/cities", response_model=list[HubOut])
async def list_cities(session: SessionDep) -> list[HubOut]:
    hubs = (
        await session.scalars(select(Hub).order_by(Hub.is_international_gateway.desc(), Hub.name))
    ).all()
    return [
        HubOut(
            slug=h.slug,
            name=h.name,
            area=h.area,
            is_international_gateway=h.is_international_gateway,
        )
        for h in hubs
    ]


async def _respond(
    payload: PlanRequest, session: SessionDep, registry: RegistryDep, plan_id: str | None
) -> PlanResponse:
    data = PlanInput(
        month=payload.month,
        regional_nights=payload.regional_nights,
        arrival_city=payload.arrival_city,
        departure_city=payload.departure_city,
        interests=tuple(i.value for i in payload.interests),
        visited=tuple(payload.visited),
        transport=payload.transport,
        pace=payload.pace,
        big_luggage=payload.big_luggage,
        kids=payload.kids,
        limited_walking=payload.limited_walking,
        must_include=tuple(payload.must_include),
        scene_cards=tuple(payload.scene_cards),
        past_trip_best=payload.past_trip_best,
        past_trip_tired=payload.past_trip_tired,
        wish=payload.free_text,
        reactions=tuple((r.kind.value, tuple(r.stops)) for r in payload.reactions),
    )
    plan, inferred, latency = await build_plan(session, registry, data)
    demo_llm: Any = registry.demo_flags.get("llm", True)
    return PlanResponse(
        plan_id=plan_id,
        request=payload,
        plan=plan,
        preferences=PreferencesOut(
            interests=plan.interests,
            avoid=[a.value for a in inferred.preferences.avoid],
            source=inferred.source,
        ),
        demo_mode=bool(plan.is_demo or demo_llm),
        latency_ms=int(latency),
    )


@router.post("", response_model=PlanResponse)
async def create_plan(
    payload: PlanRequest,
    session: SessionDep,
    registry: RegistryDep,
    _rate: AnalysisRateLimitDep,
) -> PlanResponse:
    """Plan from conditions. ``save`` stores the conditions so ``/plan/[id]`` can re-open it;
    what-if toggles on Compare pass ``save: false`` and just recompute."""
    plan_id = None
    if payload.save:
        record = PlanRecord(request=payload.model_dump(mode="json"))
        session.add(record)
        await session.flush()
        plan_id = record.id
    return await _respond(payload, session, registry, plan_id)


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: str, session: SessionDep, registry: RegistryDep) -> PlanResponse:
    """Re-run a saved plan. Deterministic, so the same conditions give the same plan
    (with any facts a reviewer has since resolved)."""
    record = await session.get(PlanRecord, plan_id)
    if record is None:
        raise NotFoundError("That plan does not exist.", details={"plan_id": plan_id})
    payload = PlanRequest.model_validate(record.request)
    return await _respond(payload, session, registry, plan_id)
