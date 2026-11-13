"""Saved trips (``/trip/[id]``), read-only share links, and the demand test.

Saving is where sign-up happens: the traveller may leave an email, and gets
an owner token that edits the trip. The share id opens a read-only copy with
no email and no token. Every read re-runs the feasibility check, so a saved
trip always shows today's facts (and a reviewer's resolution, in M5).
"""

from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jst_api.api.deps import PrincipalDep, SessionDep
from jst_api.api.v1.checks import CheckRequest, CheckResponse, _itinerary
from jst_api.core.errors import ForbiddenError, NotFoundError
from jst_api.db.models import DemandEvent, PlanRecord, SavedTrip
from jst_api.security.auth import Principal, issue_trip_token
from jst_api.services.check_service import run_check

router = APIRouter(tags=["saved trips"])

EMAIL = r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$"


class SaveTripIn(BaseModel):
    title: str = Field(default="My next Japan trip", min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL)
    plan_id: str | None = Field(default=None, max_length=40)
    check: CheckRequest


class UpdateTripIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    check: CheckRequest | None = None


class SavedTripOut(BaseModel):
    id: str | None
    share_id: str
    title: str
    plan_id: str | None
    has_email: bool | None
    read_only: bool
    check_request: CheckRequest
    result: CheckResponse
    updated_at: str | None


class SaveTripResponse(BaseModel):
    trip: SavedTripOut
    token: str


class DemandIn(BaseModel):
    kind: Literal["full_report"] = "full_report"
    plan_id: str | None = Field(default=None, max_length=40)
    trip_id: str | None = Field(default=None, max_length=40)
    option: int | None = Field(default=None, ge=0, le=2)


def _owner(principal: Principal, trip_id: str) -> None:
    if principal.is_admin or trip_id in principal.trip_ids:
        return
    raise ForbiddenError("Only the trip's owner can change it. Use the share link to view it.")


async def _out(session: SessionDep, trip: SavedTrip, *, read_only: bool) -> SavedTripOut:
    request = CheckRequest.model_validate(trip.check_request)
    outcome = await run_check(session, await _itinerary(session, request))
    return SavedTripOut(
        id=None if read_only else trip.id,
        share_id=trip.share_id,
        title=trip.title,
        plan_id=trip.plan_id,
        has_email=None if read_only else trip.email is not None,
        read_only=read_only,
        check_request=request,
        result=CheckResponse(check=outcome.check, also_consider=outcome.also_consider),
        updated_at=trip.updated_at.isoformat() if trip.updated_at else None,
    )


@router.post("/saved-trips", response_model=SaveTripResponse, status_code=201)
async def save_trip(body: SaveTripIn, session: SessionDep) -> SaveTripResponse:
    await _itinerary(session, body.check)  # validates cities before anything is stored
    plan_id = body.plan_id if body.plan_id and await session.get(PlanRecord, body.plan_id) else None
    trip = SavedTrip(
        title=body.title,
        email=body.email,
        plan_id=plan_id,
        share_id=secrets.token_urlsafe(12),
        check_request=body.check.model_dump(mode="json"),
    )
    session.add(trip)
    await session.flush()
    return SaveTripResponse(
        trip=await _out(session, trip, read_only=False), token=issue_trip_token(trip.id)
    )


@router.get("/saved-trips/{trip_id}", response_model=SavedTripOut)
async def get_saved_trip(
    trip_id: str, session: SessionDep, principal: PrincipalDep
) -> SavedTripOut:
    _owner(principal, trip_id)
    trip = await session.get(SavedTrip, trip_id)
    if trip is None:
        raise NotFoundError("That trip does not exist.")
    return await _out(session, trip, read_only=False)


@router.put("/saved-trips/{trip_id}", response_model=SavedTripOut)
async def update_saved_trip(
    trip_id: str, body: UpdateTripIn, session: SessionDep, principal: PrincipalDep
) -> SavedTripOut:
    _owner(principal, trip_id)
    trip = await session.get(SavedTrip, trip_id)
    if trip is None:
        raise NotFoundError("That trip does not exist.")
    if body.title is not None:
        trip.title = body.title
    if body.check is not None:
        await _itinerary(session, body.check)
        trip.check_request = body.check.model_dump(mode="json")
    await session.flush()
    return await _out(session, trip, read_only=False)


@router.get("/shared/{share_id}", response_model=SavedTripOut)
async def get_shared_trip(share_id: str, session: SessionDep) -> SavedTripOut:
    from sqlalchemy import select

    trip = await session.scalar(select(SavedTrip).where(SavedTrip.share_id == share_id))
    if trip is None:
        raise NotFoundError("That share link does not exist.")
    return await _out(session, trip, read_only=True)


@router.post("/demand", status_code=201)
async def record_demand(body: DemandIn, session: SessionDep) -> dict[str, str]:
    """ "See full report" records the click and nothing else (no payments in v1)."""
    event = DemandEvent(
        kind=body.kind,
        plan_id=body.plan_id,
        trip_id=body.trip_id,
        context={"option": body.option},
    )
    session.add(event)
    await session.flush()
    return {"status": "recorded", "message": "Thanks. The full report is not available yet."}
