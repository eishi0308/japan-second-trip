"""WhereNext and RouteCheck endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from jst_api.api.deps import (
    AnalysisDep,
    AnalysisRateLimitDep,
    PrincipalDep,
    RegistryDep,
    SessionDep,
)
from jst_api.api.schemas import (
    RouteCheckRequest,
    RouteCheckResponse,
    WhereNextRequest,
    WhereNextResponse,
)
from jst_api.core.errors import NotFoundError, ValidationFailedError
from jst_api.db.models import Analysis
from jst_api.domain.results import RouteCheckResult, WhereNextResult
from jst_api.domain.trip import TripContext
from jst_api.security.auth import assert_trip_access, issue_trip_token
from jst_api.services.trip_service import TripService

router = APIRouter(tags=["analysis"])


async def _resolve_trip(
    trips: TripService,
    session: SessionDep,
    principal: Any,
    *,
    trip_id: str | None,
    save_trip: bool,
    title: str,
    trip_context: TripContext,
) -> tuple[str | None, str | None, TripContext]:
    """Create or update the trip, and COMMIT before the analysis starts.

    The agent graph runs in its own database sessions (MCP tool calls are
    concurrent and must not join the request transaction), so a trip that is
    only flushed here is invisible to them. Committing first also means the trip
    survives an analysis that fails — it is a resource in its own right.
    """
    if trip_id:
        assert_trip_access(principal, trip_id)
        trip = await trips.get(trip_id)
        await trips.apply_update(trip, context=trip_context)
        resolved_context = await trips.to_context(trip)
        await session.commit()
        return trip_id, None, resolved_context

    if save_trip:
        trip = await trips.create(title=title, trip=trip_context)
        await session.commit()
        return trip.id, issue_trip_token(trip.id), trip_context

    return None, None, trip_context


@router.post("/where-next", response_model=WhereNextResponse, status_code=201)
async def create_where_next(
    payload: WhereNextRequest,
    service: AnalysisDep,
    registry: RegistryDep,
    session: SessionDep,
    principal: PrincipalDep,
    _rate: AnalysisRateLimitDep,
) -> WhereNextResponse:
    trips = TripService(session)
    trip_context = TripContext.model_validate(payload.trip.model_dump(mode="json"))
    trip_id, trip_token, trip_context = await _resolve_trip(
        trips,
        session,
        principal,
        trip_id=payload.trip_id,
        save_trip=payload.save_trip,
        title="Where next",
        trip_context=trip_context,
    )

    run = await service.run_where_next(trip_context.model_dump(mode="json"), trip_id=trip_id)

    if trip_id:
        trip = await trips.get(trip_id)
        await trips.record_analysis_outcome(trip, "where_next", run.result)

    return WhereNextResponse(
        analysis_id=run.analysis_id,
        trip_id=trip_id,
        trip_token=trip_token,
        kind="where_next",
        status=run.result["status"],
        demo_mode=registry.any_demo,
        demo_providers=registry.demo_flags,
        latency_ms=run.trace_summary["latency_ms"],
        trace=run.trace_summary,
        result=WhereNextResult.model_validate(run.result),
    )


@router.get("/where-next/{analysis_id}", response_model=WhereNextResponse)
async def get_where_next(
    analysis_id: str, session: SessionDep, registry: RegistryDep
) -> WhereNextResponse:
    row = await session.get(Analysis, analysis_id)
    if row is None or row.kind != "where_next":
        raise NotFoundError(
            f"Analysis {analysis_id} not found", details={"analysis_id": analysis_id}
        )
    return WhereNextResponse(
        analysis_id=row.id,
        trip_id=row.trip_id,
        kind=row.kind,
        status=row.status,
        demo_mode=registry.any_demo,
        demo_providers=registry.demo_flags,
        trace={},
        result=WhereNextResult.model_validate(row.result_payload),
    )


@router.post("/route-check", response_model=RouteCheckResponse, status_code=201)
async def create_route_check(
    payload: RouteCheckRequest,
    service: AnalysisDep,
    registry: RegistryDep,
    session: SessionDep,
    principal: PrincipalDep,
    _rate: AnalysisRateLimitDep,
) -> RouteCheckResponse:
    if not payload.has_input():
        raise ValidationFailedError("Provide either itinerary_text or at least one stop")

    trips = TripService(session)
    trip_context = (
        TripContext.model_validate(payload.trip.model_dump(mode="json"))
        if payload.trip
        else TripContext()
    )
    trip_id, trip_token, trip_context = await _resolve_trip(
        trips,
        session,
        principal,
        trip_id=payload.trip_id,
        save_trip=payload.save_trip,
        title="Route check",
        trip_context=trip_context,
    )

    run = await service.run_route_check(
        {
            "itinerary_text": payload.itinerary_text,
            "stops": [s.model_dump() for s in payload.stops],
            "trip_context": trip_context.model_dump(mode="json"),
        },
        trip_id=trip_id,
    )

    if trip_id:
        trip = await trips.get(trip_id)
        await trips.record_analysis_outcome(trip, "route_check", run.result)

    return RouteCheckResponse(
        analysis_id=run.analysis_id,
        trip_id=trip_id,
        trip_token=trip_token,
        kind="route_check",
        status=run.result["status"],
        demo_mode=registry.any_demo,
        demo_providers=registry.demo_flags,
        latency_ms=run.trace_summary["latency_ms"],
        trace=run.trace_summary,
        result=RouteCheckResult.model_validate(run.result),
    )


@router.get("/route-check/{analysis_id}", response_model=RouteCheckResponse)
async def get_route_check(
    analysis_id: str, session: SessionDep, registry: RegistryDep
) -> RouteCheckResponse:
    row = await session.get(Analysis, analysis_id)
    if row is None or row.kind != "route_check":
        raise NotFoundError(
            f"Analysis {analysis_id} not found", details={"analysis_id": analysis_id}
        )
    return RouteCheckResponse(
        analysis_id=row.id,
        trip_id=row.trip_id,
        kind=row.kind,
        status=row.status,
        demo_mode=registry.any_demo,
        demo_providers=registry.demo_flags,
        trace={},
        result=RouteCheckResult.model_validate(row.result_payload),
    )
