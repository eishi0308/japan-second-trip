"""Trip workspace endpoints — the persistent memory surface."""

from __future__ import annotations

from fastapi import APIRouter

from jst_api.api.deps import PrincipalDep, RateLimitDep, SessionDep
from jst_api.api.schemas import TripCreate, TripCreateResponse, TripOut, TripUpdate
from jst_api.domain.trip import TripContext
from jst_api.security.auth import assert_trip_access, issue_trip_token
from jst_api.services.trip_service import TripService

router = APIRouter(prefix="/trips", tags=["trips"])


async def _to_out(service: TripService, trip) -> TripOut:  # type: ignore[no-untyped-def]
    context = await service.to_context(trip)
    return TripOut(
        id=trip.id,
        title=trip.title,
        trip=context.model_dump(mode="json"),
        visited=await service.visited(trip.id),
        candidate_region=trip.candidate_region,
        rejected_regions=await service.rejected_regions(trip.id),
        verified_warnings=list(trip.verified_warnings or []),
        decisions=list(trip.decisions or []),
        analyses=await service.list_analyses(trip.id),
        created_at=trip.created_at.isoformat() if trip.created_at else None,
        updated_at=trip.updated_at.isoformat() if trip.updated_at else None,
    )


@router.post("", response_model=TripCreateResponse, status_code=201)
async def create_trip(
    payload: TripCreate, session: SessionDep, _rate: RateLimitDep
) -> TripCreateResponse:
    service = TripService(session)
    context = TripContext.model_validate(payload.trip.model_dump(mode="json"))
    trip = await service.create(payload.title, context)
    return TripCreateResponse(
        trip=await _to_out(service, trip), trip_token=issue_trip_token(trip.id)
    )


@router.get("/{trip_id}", response_model=TripOut)
async def get_trip(trip_id: str, session: SessionDep, principal: PrincipalDep) -> TripOut:
    assert_trip_access(principal, trip_id)
    service = TripService(session)
    return await _to_out(service, await service.get(trip_id))


@router.patch("/{trip_id}", response_model=TripOut)
async def update_trip(
    trip_id: str,
    payload: TripUpdate,
    session: SessionDep,
    principal: PrincipalDep,
    _rate: RateLimitDep,
) -> TripOut:
    assert_trip_access(principal, trip_id)
    service = TripService(session)
    trip = await service.get(trip_id)
    context = (
        TripContext.model_validate(payload.trip.model_dump(mode="json")) if payload.trip else None
    )
    await service.apply_update(
        trip,
        title=payload.title,
        context=context,
        candidate_region=payload.candidate_region,
        reject_region=payload.reject_region,
        reject_reason=payload.reject_reason,
        acknowledge_warning=payload.acknowledge_warning,
    )
    return await _to_out(service, trip)
