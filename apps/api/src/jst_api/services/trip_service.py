"""Trip persistence — the durable half of the memory design.

LangGraph state is the *active workflow*; these tables are what survives it.
Only structured, decision-relevant facts are stored: visited places, the current
candidate, rejected regions with reasons, confirmed preferences, acknowledged
warnings. No conversation transcript, because replaying one into a prompt is how
context budgets and coherence both get lost.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.errors import NotFoundError
from jst_api.core.logging import get_logger
from jst_api.db.models import Analysis, CandidateRegion, Trip, VisitedPlace
from jst_api.domain.trip import TripContext

log = get_logger(__name__)


class TripService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, title: str, trip: TripContext) -> Trip:
        row = Trip(
            title=title,
            arrival_city=trip.arrival_city,
            departure_city=trip.departure_city,
            start_date=trip.start_date,
            end_date=trip.end_date,
            total_nights=trip.total_nights,
            available_regional_nights=trip.regional_nights,
            traveller_type=trip.traveller_type.value if trip.traveller_type else None,
            party_size=trip.party_size,
            driving=trip.driving.value if trip.driving else None,
            pace=trip.pace.value if trip.pace else None,
            budget=trip.budget.value if trip.budget else None,
            large_luggage=trip.large_luggage,
            interests=[i.value for i in trip.interests],
            mobility=trip.mobility.model_dump() if trip.mobility else None,
            preferences={},
        )
        self._session.add(row)
        await self._session.flush()
        for name in trip.visited_places:
            self._session.add(VisitedPlace(trip_id=row.id, raw_name=name.strip()))
        await self._session.flush()
        log.info("trip.created", trip_id=row.id)
        return row

    async def get(self, trip_id: str) -> Trip:
        row = await self._session.get(Trip, trip_id)
        if row is None:
            raise NotFoundError(f"Trip {trip_id} not found", details={"trip_id": trip_id})
        return row

    async def to_context(self, trip: Trip) -> TripContext:
        visited = list(
            (
                await self._session.scalars(
                    select(VisitedPlace).where(VisitedPlace.trip_id == trip.id)
                )
            ).all()
        )
        return TripContext.model_validate(
            {
                "start_date": trip.start_date,
                "end_date": trip.end_date,
                "total_nights": trip.total_nights,
                "regional_nights": trip.available_regional_nights,
                "arrival_city": trip.arrival_city,
                "departure_city": trip.departure_city,
                "visited_places": [v.raw_name for v in visited],
                "traveller_type": trip.traveller_type,
                "party_size": trip.party_size,
                "interests": list(trip.interests or []),
                "driving": trip.driving,
                "budget": trip.budget,
                "pace": trip.pace,
                "large_luggage": trip.large_luggage,
                "mobility": trip.mobility,
            }
        )

    async def apply_update(
        self,
        trip: Trip,
        *,
        title: str | None = None,
        context: TripContext | None = None,
        candidate_region: str | None = None,
        reject_region: str | None = None,
        reject_reason: str | None = None,
        acknowledge_warning: str | None = None,
    ) -> Trip:
        if title:
            trip.title = title
        if context is not None:
            trip.arrival_city = context.arrival_city or trip.arrival_city
            trip.departure_city = context.departure_city or trip.departure_city
            trip.start_date = context.start_date or trip.start_date
            trip.end_date = context.end_date or trip.end_date
            trip.total_nights = context.total_nights or trip.total_nights
            trip.available_regional_nights = (
                context.regional_nights or trip.available_regional_nights
            )
            if context.interests:
                trip.interests = [i.value for i in context.interests]
            if context.driving:
                trip.driving = context.driving.value
            if context.pace:
                trip.pace = context.pace.value
            if context.budget:
                trip.budget = context.budget.value
            if context.large_luggage is not None:
                trip.large_luggage = context.large_luggage
            for name in context.visited_places:
                await self._add_visited(trip.id, name)

        if candidate_region:
            trip.candidate_region = candidate_region
            await self._upsert_candidate(trip.id, candidate_region, "selected", None)
        if reject_region:
            await self._upsert_candidate(trip.id, reject_region, "rejected", reject_reason)
            if trip.candidate_region == reject_region:
                trip.candidate_region = None
        if acknowledge_warning:
            warnings = list(trip.verified_warnings or [])
            if acknowledge_warning not in warnings:
                warnings.append(acknowledge_warning)
            trip.verified_warnings = warnings

        await self._session.flush()
        return trip

    async def record_analysis_outcome(self, trip: Trip, kind: str, result: dict[str, Any]) -> None:
        """Feed an analysis back into memory so the next one starts informed."""
        if kind == "where_next":
            recommended = result.get("recommended")
            if recommended:
                trip.candidate_region = recommended["region_code"]
                await self._upsert_candidate(
                    trip.id,
                    recommended["region_code"],
                    "shortlisted",
                    recommended.get("headline"),
                    score=recommended.get("deterministic_score"),
                    label=recommended.get("fit_label"),
                )
            for entry in result.get("rejected", []):
                await self._upsert_candidate(
                    trip.id,
                    entry["region_code"],
                    "rejected",
                    (entry.get("rejected_reasons") or ["Failed a hard constraint for this trip."])[
                        0
                    ],
                    score=entry.get("deterministic_score"),
                    label=entry.get("fit_label"),
                )
        elif kind == "route_check":
            warnings = list(trip.verified_warnings or [])
            for issue in result.get("critical_issues", [])[:3]:
                text = f"{issue['title']} — {issue.get('rule_id', '')}"
                if text not in warnings:
                    warnings.append(text)
            trip.verified_warnings = warnings[-20:]
        await self._session.flush()

    async def list_analyses(self, trip_id: str) -> list[dict[str, Any]]:
        rows = list(
            (
                await self._session.scalars(
                    select(Analysis)
                    .where(Analysis.trip_id == trip_id)
                    .order_by(Analysis.created_at.desc())
                    .limit(20)
                )
            ).all()
        )
        return [
            {
                "analysis_id": r.id,
                "kind": r.kind,
                "status": r.status,
                "confidence": r.confidence,
                "human_review_required": r.human_review_required,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "summary": _analysis_summary(r),
            }
            for r in rows
        ]

    async def rejected_regions(self, trip_id: str) -> dict[str, str]:
        rows = list(
            (
                await self._session.scalars(
                    select(CandidateRegion).where(
                        CandidateRegion.trip_id == trip_id, CandidateRegion.status == "rejected"
                    )
                )
            ).all()
        )
        return {r.region_code: (r.reason or "rejected") for r in rows}

    async def visited(self, trip_id: str) -> list[str]:
        rows = list(
            (
                await self._session.scalars(
                    select(VisitedPlace).where(VisitedPlace.trip_id == trip_id)
                )
            ).all()
        )
        return [r.raw_name for r in rows]

    # -- internals ----------------------------------------------------------
    async def _add_visited(self, trip_id: str, name: str) -> None:
        clean = name.strip()
        if not clean:
            return
        existing = await self._session.scalar(
            select(VisitedPlace).where(
                VisitedPlace.trip_id == trip_id, VisitedPlace.raw_name == clean
            )
        )
        if existing is None:
            self._session.add(VisitedPlace(trip_id=trip_id, raw_name=clean))

    async def _upsert_candidate(
        self,
        trip_id: str,
        region_code: str,
        status: str,
        reason: str | None,
        *,
        score: float | None = None,
        label: str | None = None,
    ) -> None:
        row = await self._session.scalar(
            select(CandidateRegion).where(
                CandidateRegion.trip_id == trip_id, CandidateRegion.region_code == region_code
            )
        )
        if row is None:
            self._session.add(
                CandidateRegion(
                    trip_id=trip_id,
                    region_code=region_code,
                    status=status,
                    reason=reason,
                    deterministic_score=score,
                    fit_label=label,
                )
            )
            return
        # A traveller's explicit rejection outranks a later automated shortlisting.
        if row.status == "rejected" and status != "rejected":
            return
        row.status = status
        if reason:
            row.reason = reason
        if score is not None:
            row.deterministic_score = score
        if label:
            row.fit_label = label


def _analysis_summary(row: Analysis) -> str:
    payload = row.result_payload or {}
    if row.kind == "where_next":
        recommended = payload.get("recommended")
        return f"Best fit: {recommended['region_name']}" if recommended else "No region recommended"
    return payload.get("health_summary", "")[:160] or "Route checked"


def parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None
