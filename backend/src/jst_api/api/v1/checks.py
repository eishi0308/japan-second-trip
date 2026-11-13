"""RouteCheck (v2): paste, confirm the table, check day by day.

Every customisation (pin, swap, change nights, reorder, leave earlier) is the
same ``POST /checks`` with the edited table, so every change re-runs the full
check.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from jst_api.api.deps import AnalysisRateLimitDep, RegistryDep, SessionDep
from jst_api.db.repositories.planner_repo import load_planner_catalogue
from jst_api.domain.enums import Pace
from jst_api.planner.feasibility import Assumptions, Itinerary, StopSpec, parse_clock
from jst_api.planner.model import Transport
from jst_api.planner.results import CheckResult
from jst_api.services.check_service import (
    AlsoConsider,
    ParsedItinerary,
    alternatives_for,
    parse_itinerary,
    run_check,
)
from jst_api.services.plan_service import resolve_hub

router = APIRouter(prefix="/checks", tags=["checks"])

CLOCK = r"^([01]\d|2[0-3]):[0-5]\d$"


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class StopIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    nights: int = Field(ge=0, le=30)
    pinned: bool = False
    leave_at: str | None = Field(default=None, pattern=CLOCK)


class AssumptionsIn(BaseModel):
    leave_hotel: str = Field(default="09:30", pattern=CLOCK)
    day_end: str = Field(default="18:30", pattern=CLOCK)
    landing: str = Field(default="14:00", pattern=CLOCK)
    flight_cutoff: str = Field(default="15:00", pattern=CLOCK)


class CheckRequest(BaseModel):
    stops: list[StopIn] = Field(min_length=1, max_length=20)
    month: int | None = Field(default=None, ge=1, le=12)
    start_date: date | None = None
    arrival_city: str | None = Field(default=None, max_length=40)
    departure_city: str | None = Field(default=None, max_length=40)
    transport: Transport = Transport.NO_CAR
    pace: Pace = Pace.BALANCED
    big_luggage: bool = False
    mode: Literal["whole_trip", "regional"] = "whole_trip"
    assumptions: AssumptionsIn = Field(default_factory=AssumptionsIn)

    @model_validator(mode="after")
    def _month(self) -> CheckRequest:
        if self.month is None and self.start_date is not None:
            self.month = self.start_date.month
        if self.month is None:
            raise ValueError("pick a travel month or a start date")
        if not any(s.nights for s in self.stops):
            raise ValueError("at least one stop needs a night")
        return self


class AlternativesRequest(CheckRequest):
    index: int = Field(ge=0, le=19)


class CheckResponse(BaseModel):
    check: CheckResult
    also_consider: list[AlsoConsider]


class AlternativeOut(BaseModel):
    slug: str
    name: str
    area: str
    summary: str
    is_demo: bool


async def _itinerary(session: SessionDep, body: CheckRequest) -> Itinerary:
    catalogue = await load_planner_catalogue(session)
    a = body.assumptions

    def minutes(value: str) -> int:
        parsed = parse_clock(value)
        assert parsed is not None  # the pattern guarantees it
        return parsed

    return Itinerary(
        stops=tuple(
            StopSpec(
                s.name,
                s.nights,
                pinned=s.pinned,
                leave_at=parse_clock(s.leave_at) if s.leave_at else None,
            )
            for s in body.stops
        ),
        month=body.month or 1,
        arrival=resolve_hub(catalogue, body.arrival_city),
        departure=resolve_hub(catalogue, body.departure_city),
        start_date=body.start_date,
        transport=body.transport,
        pace=body.pace,
        big_luggage=body.big_luggage,
        assumptions=Assumptions(
            leave_hotel=minutes(a.leave_hotel),
            day_end=minutes(a.day_end),
            landing=minutes(a.landing),
            flight_cutoff=minutes(a.flight_cutoff),
            whole_trip=body.mode == "whole_trip",
        ),
    )


@router.post("/parse", response_model=ParsedItinerary)
async def parse(
    body: ParseRequest, session: SessionDep, registry: RegistryDep, _rate: AnalysisRateLimitDep
) -> ParsedItinerary:
    return await parse_itinerary(session, registry, body.text)


@router.post("", response_model=CheckResponse)
async def check(body: CheckRequest, session: SessionDep) -> CheckResponse:
    outcome = await run_check(session, await _itinerary(session, body))
    return CheckResponse(check=outcome.check, also_consider=outcome.also_consider)


@router.post("/alternatives", response_model=list[AlternativeOut])
async def alternatives(body: AlternativesRequest, session: SessionDep) -> list[AlternativeOut]:
    found = await alternatives_for(session, await _itinerary(session, body), body.index)
    return [AlternativeOut(**a) for a in found]
