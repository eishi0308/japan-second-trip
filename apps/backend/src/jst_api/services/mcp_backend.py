"""The application's implementation of the MCP gateway's ``TravelBackend`` port.

This is where AI-facing capabilities meet real data: the retrieval pipeline, the
place catalogue, the transport provider, the deterministic rules engine and the
trip-memory tables.

Each handler opens its own short database session, because MCP tool calls arrive
concurrently and must not share a transaction with the caller's request.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from jst_api.core.config import Settings, get_settings
from jst_api.core.logging import get_logger
from jst_api.db.models import (
    BookingConstraint,
    EvidenceChunk,
    HumanReviewTask,
    Place,
    Source,
    Trip,
    VerificationRecord,
    VisitedPlace,
)
from jst_api.db.repositories.evidence_repo import EvidenceFilters
from jst_api.domain.enums import DrivingWillingness, EvidenceTopic, Pace, ReviewReason
from jst_api.domain.freshness import classify_freshness, requires_reverification
from jst_api.domain.route import compute_travel_load
from jst_api.domain.route_rules import RULES_VERSION, grade_health, run_rules
from jst_api.domain.trip import TripContext
from jst_api.knowledge.embeddings import ProviderEmbeddings
from jst_api.knowledge.rag import EvidencePipeline, RetrievalRequest
from jst_api.knowledge.rerank import build_reranker
from jst_api.knowledge.retrievers import document_to_domain
from jst_api.prompts.registry import get_prompts
from jst_api.providers.registry import ProviderRegistry
from jst_api.services.route_service import RouteService
from shared_schemas.tools import (
    BookingRule,
    CalculateTravelLoadInput,
    CalculateTravelLoadOutput,
    CheckRouteConstraintsInput,
    CheckRouteConstraintsOutput,
    ConflictEntry,
    CreateHumanReviewInput,
    CreateHumanReviewOutput,
    EvidenceRef,
    GetBookingRequirementsInput,
    GetBookingRequirementsOutput,
    GetPlaceConstraintsInput,
    GetPlaceConstraintsOutput,
    GetPlaceDetailsInput,
    GetPlaceDetailsOutput,
    GetRouteContextInput,
    GetRouteContextOutput,
    GetSourceEvidenceInput,
    GetSourceEvidenceOutput,
    GetTripContextInput,
    GetTripContextOutput,
    GetVerificationStatusInput,
    GetVerificationStatusOutput,
    GetWeatherContextInput,
    GetWeatherContextOutput,
    PlaceDetails,
    ProviderStamp,
    RouteIssueOut,
    SaveTripDecisionInput,
    SaveTripDecisionOutput,
    SearchEvidenceInput,
    SearchEvidenceOutput,
    SearchTransportInput,
    SearchTransportOutput,
    TransportLeg,
    VerificationEntry,
)

log = get_logger(__name__)

VALID_REVIEW_REASONS = {r.value for r in ReviewReason}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


#: A verified fact ages at the rate of the topic it belongs to, not a global TTL.
#: Departure times go stale fastest; a closure window is seasonal; the rest is general.
_FIELD_TOPIC_HINTS: tuple[tuple[tuple[str, ...], EvidenceTopic], ...] = (
    (
        ("departure", "shuttle", "bus", "ferry", "train", "access", "transfer"),
        EvidenceTopic.TRANSPORT_ACCESS,
    ),
    (("booking", "reservation", "lead_time"), EvidenceTopic.BOOKING),
    (("closure", "season", "operating", "opening"), EvidenceTopic.SEASONAL),
    (("price", "fare", "cost"), EvidenceTopic.COST),
)


def _topic_for_field(field_name: str) -> EvidenceTopic:
    lowered = field_name.lower()
    for needles, topic in _FIELD_TOPIC_HINTS:
        if any(n in lowered for n in needles):
            return topic
    return EvidenceTopic.GENERAL


class JstTravelBackend:
    """Concrete backend for ``travel-intelligence-mcp``."""

    def __init__(
        self, session_factory: Any, registry: ProviderRegistry, settings: Settings | None = None
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._settings = settings or registry.settings
        self._embeddings = ProviderEmbeddings(registry.embeddings)
        self._reranker = build_reranker(
            self._settings, registry.llm, get_prompts(), registry.router
        )
        self._routes = RouteService(registry.places, registry.transport)

    # -- helpers ------------------------------------------------------------
    def _pipeline(self, session: Any) -> EvidencePipeline:
        return EvidencePipeline(
            session,
            self._embeddings,
            self._reranker,
            rrf_k=self._settings.rrf_k,
            dense_weight=self._settings.retrieval_dense_weight,
            cache=self._registry.cache,
        )

    @staticmethod
    def _to_ref(doc: Any) -> EvidenceRef:
        chunk = document_to_domain(doc)
        return EvidenceRef(
            evidence_id=chunk.evidence_id,
            source_id=chunk.source.source_id,
            source_title=chunk.source.title,
            source_url=chunk.source.url,
            source_type=chunk.source.source_type.value,
            official_source=chunk.source.official_source,
            trust_level=chunk.source.trust_level.value,
            topic=chunk.topic.value,
            region_code=chunk.region_code,
            place_slug=chunk.place_slug,
            verified_at=_iso(chunk.verified_at),
            freshness=chunk.freshness.value,
            is_demo=chunk.is_demo,
            score=round(
                float(
                    doc.metadata.get("rerank_score")
                    or doc.metadata.get("fused_score")
                    or doc.metadata.get("score")
                    or 0.0
                ),
                6,
            ),
            snippet=chunk.content[:400],
        )

    @staticmethod
    def _leg(option: Any) -> TransportLeg:
        return TransportLeg(
            mode=option.mode.value if hasattr(option.mode, "value") else str(option.mode),
            duration_minutes=option.duration_minutes,
            transfers=option.transfers,
            distance_km=option.distance_km,
            requires_car=option.requires_car,
            last_departure_local=option.last_departure_local,
            final_leg_minutes=option.final_leg_minutes,
            frequency_per_day=option.frequency_per_day,
            operator=option.operator,
            is_estimate=option.is_estimate,
            notes=option.notes,
            provider=ProviderStamp(
                provider=option.meta.provider,
                is_demo=option.meta.is_demo,
                cached=option.meta.cached,
            ),
        )

    async def _resolve_slug(self, query: str) -> str | None:
        place = await self._registry.places.resolve_place(query)
        return place.slug if place else None

    # -- evidence -----------------------------------------------------------
    async def search_verified_evidence(self, args: SearchEvidenceInput) -> SearchEvidenceOutput:
        filters = EvidenceFilters(
            region_codes=args.region_codes,
            place_slugs=args.place_slugs,
            topics=args.topics,
            season_month=args.month,
            official_only=args.official_only,
        )
        topics = [EvidenceTopic(t) for t in args.topics if t in {e.value for e in EvidenceTopic}]
        async with self._session_factory() as session:
            outcome = await self._pipeline(session).run(
                RetrievalRequest(
                    query=args.query,
                    filters=filters,
                    topics=topics or None,
                    candidate_k=self._settings.retrieval_candidate_k,
                    final_k=args.limit,
                    strategy=self._settings.retrieval_strategy,
                )
            )
        return SearchEvidenceOutput(
            evidence=[self._to_ref(d) for d in outcome.context_documents],
            strategy=outcome.strategy,
            total_candidates=len(outcome.documents),
            quarantined_count=len(outcome.context.audit.quarantined),
        )

    async def get_source_evidence(self, args: GetSourceEvidenceInput) -> GetSourceEvidenceOutput:
        async with self._session_factory() as session:
            stmt = select(EvidenceChunk, Source).join(Source, Source.id == EvidenceChunk.source_id)
            if args.evidence_ids:
                stmt = stmt.where(EvidenceChunk.id.in_(args.evidence_ids))
            elif args.source_id:
                stmt = stmt.where(EvidenceChunk.source_id == args.source_id)
            else:
                return GetSourceEvidenceOutput()
            rows = (await session.execute(stmt.limit(20))).all()

        refs: list[EvidenceRef] = []
        texts: dict[str, str] = {}
        for chunk, source in rows:
            topic = EvidenceTopic(chunk.topic) if chunk.topic else EvidenceTopic.GENERAL
            refs.append(
                EvidenceRef(
                    evidence_id=chunk.id,
                    source_id=source.id,
                    source_title=source.title,
                    source_url=source.url,
                    source_type=source.source_type,
                    official_source=source.official_source,
                    trust_level=chunk.trust_level,
                    topic=chunk.topic,
                    region_code=chunk.region_code,
                    place_slug=chunk.place_slug,
                    verified_at=_iso(chunk.verified_at),
                    freshness=classify_freshness(chunk.verified_at, topic).value,
                    is_demo=chunk.is_demo,
                    snippet=chunk.content[:400],
                )
            )
            texts[chunk.id] = chunk.content
        return GetSourceEvidenceOutput(evidence=refs, full_texts=texts)

    # -- places -------------------------------------------------------------
    async def get_place_details(self, args: GetPlaceDetailsInput) -> GetPlaceDetailsOutput:
        result = await self._registry.places.resolve_place(args.query)
        if result is None:
            return GetPlaceDetailsOutput(
                resolved=False,
                message=f"'{args.query}' is not in the place catalogue. It is excluded from route checks rather than guessed at.",
            )
        async with self._session_factory() as session:
            place = await session.scalar(select(Place).where(Place.slug == result.slug))
        return GetPlaceDetailsOutput(
            resolved=True,
            place=PlaceDetails(
                slug=result.slug,
                name=result.name,
                name_ja=result.name_ja,
                lat=result.lat,
                lon=result.lon,
                region_code=result.region_code,
                prefecture=result.prefecture,
                place_kind=result.place_kind,
                nearest_station=result.nearest_station,
                typical_stay_nights=place.typical_stay_nights if place else 1,
                car_recommended=result.car_recommended,
                step_free=place.step_free if place else True,
                summary=result.summary,
                tags=result.tags,
                resolution_confidence=result.confidence,
                match_kind=result.match_kind,
                provider=ProviderStamp(provider=result.meta.provider, is_demo=result.meta.is_demo),
            ),
        )

    async def get_place_constraints(
        self, args: GetPlaceConstraintsInput
    ) -> GetPlaceConstraintsOutput:
        async with self._session_factory() as session:
            place = await session.scalar(select(Place).where(Place.slug == args.place_slug))
            rows = list(
                (
                    await session.scalars(
                        select(BookingConstraint).where(
                            BookingConstraint.place_slug == args.place_slug
                        )
                    )
                ).all()
            )
            outcome = await self._pipeline(session).run(
                RetrievalRequest(
                    query=f"{args.place_slug.replace('-', ' ')} access booking constraints",
                    filters=EvidenceFilters(place_slugs=[args.place_slug], season_month=args.month),
                    final_k=4,
                    token_budget=1200,
                )
            )

        rules = [
            BookingRule(
                subject=r.subject,
                lead_time_days=r.lead_time_days,
                english_booking_available=r.english_booking_available,
                requires_deposit=r.requires_deposit,
                closed_months=list(r.closed_months or []),
                closed_weekdays=list(r.closed_weekdays or []),
                note=r.note,
                verified_at=_iso(r.verified_at),
                is_demo=r.is_demo,
            )
            for r in rows
        ]
        closed = bool(args.month and any(args.month in (r.closed_months or []) for r in rows))
        return GetPlaceConstraintsOutput(
            place_slug=args.place_slug,
            booking_rules=rules,
            closed_this_month=closed,
            car_recommended=place.car_recommended if place else False,
            step_free=place.step_free if place else True,
            evidence=[self._to_ref(d) for d in outcome.context_documents],
        )

    # -- transport ----------------------------------------------------------
    async def search_transport(self, args: SearchTransportInput) -> SearchTransportOutput:
        from_slug = await self._resolve_slug(args.from_place)
        to_slug = await self._resolve_slug(args.to_place)
        if not from_slug or not to_slug:
            unknown = args.from_place if not from_slug else args.to_place
            return SearchTransportOutput(
                from_slug=from_slug or args.from_place,
                to_slug=to_slug or args.to_place,
                resolved=False,
                message=f"Could not resolve '{unknown}' to a known place, so no transport data is available for this hop.",
            )
        travel_date: date | None = None
        if args.travel_date:
            try:
                travel_date = date.fromisoformat(args.travel_date)
            except ValueError:
                travel_date = None

        options = await self._registry.transport.search_transport(
            from_slug, to_slug, travel_date=travel_date, allow_car=args.allow_car
        )
        legs = [self._leg(o) for o in options]
        public = [leg for leg in legs if not leg.requires_car]
        return SearchTransportOutput(
            from_slug=from_slug,
            to_slug=to_slug,
            resolved=True,
            options=legs,
            best_public_option=min(public, key=lambda leg: leg.duration_minutes)
            if public
            else None,
        )

    async def get_route_context(self, args: GetRouteContextInput) -> GetRouteContextOutput:
        route, resolved = await self._routes.build_route(
            args.place_slugs,
            args.nights,
            allow_car=args.allow_car,
            arrival_city=args.arrival_city,
            departure_city=args.departure_city,
        )
        legs = [
            TransportLeg(
                mode=s.mode.value,
                duration_minutes=s.duration_minutes,
                transfers=s.transfers,
                distance_km=s.distance_km,
                requires_car=s.requires_car,
                last_departure_local=s.last_departure_local,
                final_leg_minutes=s.final_leg_minutes,
                operator=None,
                is_estimate=s.is_estimate,
                notes=s.notes,
                provider=ProviderStamp(provider=s.provider, is_demo=True),
            )
            for s in route.segments
        ]
        return GetRouteContextOutput(
            legs=legs,
            unresolved=[r.raw_name for r in resolved if not r.resolved],
            total_transit_minutes=route.total_transit_minutes,
            estimated_legs=sum(1 for s in route.segments if s.is_estimate),
        )

    async def calculate_travel_load(
        self, args: CalculateTravelLoadInput
    ) -> CalculateTravelLoadOutput:
        route, _ = await self._routes.build_route(
            args.place_slugs, args.nights, allow_car=args.allow_car
        )
        load = compute_travel_load(route)
        return CalculateTravelLoadOutput(**load.model_dump())

    async def check_route_constraints(
        self, args: CheckRouteConstraintsInput
    ) -> CheckRouteConstraintsOutput:
        route, resolved = await self._routes.build_route(
            args.place_slugs,
            args.nights,
            allow_car=not args.public_transport_only,
            arrival_city=args.arrival_city,
            departure_city=args.departure_city,
        )
        trip = TripContext(
            arrival_city=args.arrival_city,
            departure_city=args.departure_city,
            driving=DrivingWillingness.NO_CAR if args.public_transport_only else None,
            large_luggage=args.large_luggage,
            pace=Pace(args.pace) if args.pace in {p.value for p in Pace} else None,
        )
        issues, load = run_rules(route, trip)
        return CheckRouteConstraintsOutput(
            health=grade_health(issues).value,
            issues=[
                RouteIssueOut(
                    rule_id=i.rule_id or "unknown",
                    issue_type=i.issue_type.value,
                    severity=i.severity.value,
                    segment=i.segment,
                    title=i.title,
                    explanation=i.explanation,
                    deterministic_signal=i.deterministic_signal,
                    proposed_fix=i.proposed_fix,
                    evidence_ids=i.evidence_ids,
                )
                for i in issues
            ],
            travel_load=CalculateTravelLoadOutput(**load.model_dump()),
            rules_version=RULES_VERSION,
            unresolved_places=[r.raw_name for r in resolved if not r.resolved],
        )

    # -- booking / weather --------------------------------------------------
    async def get_booking_requirements(
        self, args: GetBookingRequirementsInput
    ) -> GetBookingRequirementsOutput:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(BookingConstraint).where(
                            BookingConstraint.place_slug.in_(args.place_slugs)
                        )
                    )
                ).all()
            )
            outcome = await self._pipeline(session).run(
                RetrievalRequest(
                    query="booking lead time reservation in advance English",
                    filters=EvidenceFilters(
                        place_slugs=args.place_slugs,
                        topics=[EvidenceTopic.BOOKING.value],
                        season_month=args.month,
                    ),
                    topics=[EvidenceTopic.BOOKING],
                    final_k=4,
                    token_budget=1200,
                )
            )

        by_place: dict[str, list[BookingRule]] = {}
        gaps: list[str] = []
        closed: list[str] = []
        max_lead: int | None = None
        for row in rows:
            rule = BookingRule(
                subject=row.subject,
                lead_time_days=row.lead_time_days,
                english_booking_available=row.english_booking_available,
                requires_deposit=row.requires_deposit,
                closed_months=list(row.closed_months or []),
                closed_weekdays=list(row.closed_weekdays or []),
                note=row.note,
                verified_at=_iso(row.verified_at),
                is_demo=row.is_demo,
            )
            by_place.setdefault(row.place_slug, []).append(rule)
            if row.lead_time_days is not None:
                max_lead = (
                    row.lead_time_days if max_lead is None else max(max_lead, row.lead_time_days)
                )
            if row.english_booking_available is False:
                gaps.append(f"{row.place_slug}: {row.subject}")
            if args.month and args.month in (row.closed_months or []):
                closed.append(f"{row.place_slug}: {row.subject}")

        return GetBookingRequirementsOutput(
            rules=by_place,
            max_lead_time_days=max_lead,
            english_booking_gaps=gaps,
            closed_in_month=closed,
            evidence=[self._to_ref(d) for d in outcome.context_documents],
        )

    async def get_weather_context(self, args: GetWeatherContextInput) -> GetWeatherContextOutput:
        context = await self._registry.weather.get_weather_context(args.place_slug, args.month)
        if context is None:
            return GetWeatherContextOutput(
                resolved=False, place_slug=args.place_slug, month=args.month
            )
        return GetWeatherContextOutput(
            resolved=True,
            place_slug=context.place_slug,
            month=context.month,
            typical_high_c=context.typical_high_c,
            typical_low_c=context.typical_low_c,
            rain_days=context.rain_days,
            snow_likely=context.snow_likely,
            summary=context.summary,
            provider=ProviderStamp(provider=context.meta.provider, is_demo=context.meta.is_demo),
        )

    # -- verification / HITL -------------------------------------------------
    async def get_verification_status(
        self, args: GetVerificationStatusInput
    ) -> GetVerificationStatusOutput:
        async with self._session_factory() as session:
            stmt = select(VerificationRecord)
            if args.subjects:
                stmt = stmt.where(VerificationRecord.subject.in_(args.subjects))
            records = list((await session.scalars(stmt.limit(args.limit))).all())
            open_tasks = list(
                (
                    await session.scalars(
                        select(HumanReviewTask).where(
                            HumanReviewTask.status.in_(["open", "in_progress"])
                        )
                    )
                ).all()
            )

        entries: list[VerificationEntry] = []
        stale = 0
        for record in records:
            topic = _topic_for_field(record.field_name)
            freshness = classify_freshness(record.verified_at, topic)
            needs = requires_reverification(freshness, topic)
            if needs:
                stale += 1
            if args.stale_only and not needs:
                continue
            entries.append(
                VerificationEntry(
                    subject=record.subject,
                    field_name=record.field_name,
                    value=record.value,
                    verified_at=_iso(record.verified_at),
                    verified_by=record.verified_by,
                    verification_method=record.verification_method,
                    confidence=record.confidence,
                    status=record.status,
                    freshness=freshness.value,
                    requires_reverification=needs,
                    source_id=record.source_id,
                )
            )

        conflicts = [
            ConflictEntry(
                subject=task.subject,
                field_name=task.field_name or "",
                values=list(task.candidate_values or []),
                evidence_ids=list(task.evidence_ids or []),
                open_review_task_id=task.id,
            )
            for task in open_tasks
            if task.reason == ReviewReason.CONFLICTING_SOURCES.value
        ]
        return GetVerificationStatusOutput(entries=entries, conflicts=conflicts, stale_count=stale)

    async def create_human_review_request(
        self, args: CreateHumanReviewInput
    ) -> CreateHumanReviewOutput:
        reason = (
            args.reason
            if args.reason in VALID_REVIEW_REASONS
            else ReviewReason.MISSING_EVIDENCE.value
        )
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(HumanReviewTask).where(
                    HumanReviewTask.subject == args.subject,
                    HumanReviewTask.field_name == args.field_name,
                    HumanReviewTask.status.in_(["open", "in_progress"]),
                )
            )
            if existing is not None:
                # Idempotent: an agent retrying must not spam the review queue.
                # But an existing task must learn which analysis it now blocks,
                # otherwise resolving it cannot resume anything.
                changed = False
                if args.analysis_id and not existing.analysis_id:
                    existing.analysis_id = args.analysis_id
                    changed = True
                if args.thread_id and not existing.thread_id:
                    existing.thread_id = args.thread_id
                    changed = True
                if args.evidence_ids and not existing.evidence_ids:
                    existing.evidence_ids = args.evidence_ids
                    changed = True
                if changed:
                    await session.commit()
                return CreateHumanReviewOutput(
                    task_id=existing.id, status=existing.status, created=False
                )
            task = HumanReviewTask(
                analysis_id=args.analysis_id,
                thread_id=args.thread_id,
                reason=reason,
                subject=args.subject,
                field_name=args.field_name,
                question=args.question,
                candidate_values=args.candidate_values,
                evidence_ids=args.evidence_ids,
                status="open",
                priority=args.priority if args.priority in {"low", "normal", "high"} else "normal",
            )
            session.add(task)
            await session.commit()
            log.info("hitl.task_created", task_id=task.id, reason=reason, subject=args.subject)
            return CreateHumanReviewOutput(task_id=task.id, status="open", created=True)

    # -- trip state ----------------------------------------------------------
    async def get_trip_context(self, args: GetTripContextInput) -> GetTripContextOutput:
        async with self._session_factory() as session:
            trip = await session.get(Trip, args.trip_id)
            if trip is None:
                return GetTripContextOutput(found=False, trip_id=args.trip_id)
            visited = list(
                (
                    await session.scalars(
                        select(VisitedPlace).where(VisitedPlace.trip_id == trip.id)
                    )
                ).all()
            )
            from jst_api.db.models import CandidateRegion

            candidates = list(
                (
                    await session.scalars(
                        select(CandidateRegion).where(CandidateRegion.trip_id == trip.id)
                    )
                ).all()
            )
        return GetTripContextOutput(
            found=True,
            trip_id=trip.id,
            visited=[v.raw_name for v in visited],
            candidate_region=trip.candidate_region,
            rejected_regions={
                c.region_code: (c.reason or "rejected")
                for c in candidates
                if c.status == "rejected"
            },
            confirmed_preferences={k: str(v) for k, v in (trip.preferences or {}).items()},
            verified_warnings=list(trip.verified_warnings or []),
            decisions=list(trip.decisions or []),
            arrival_city=trip.arrival_city,
            departure_city=trip.departure_city,
            regional_nights=trip.available_regional_nights,
        )

    async def save_trip_decision(self, args: SaveTripDecisionInput) -> SaveTripDecisionOutput:

        async with self._session_factory() as session:
            trip = await session.get(Trip, args.trip_id)
            if trip is None:
                return SaveTripDecisionOutput(
                    saved=False, trip_id=args.trip_id, message="Unknown trip id."
                )

            note = args.note or args.reason or ""
            stamp = datetime.now(UTC).date().isoformat()

            if args.decision_kind == "candidate_selected" and args.region_code:
                trip.candidate_region = args.region_code
                await self._upsert_candidate(
                    session, trip.id, args.region_code, "selected", args.reason
                )
                message = f"{args.region_code} recorded as the current candidate."
            elif args.decision_kind == "region_rejected" and args.region_code:
                await self._upsert_candidate(
                    session, trip.id, args.region_code, "rejected", args.reason
                )
                if trip.candidate_region == args.region_code:
                    trip.candidate_region = None
                message = f"{args.region_code} recorded as rejected."
            elif args.decision_kind == "preference_confirmed" and args.preference_key:
                prefs = dict(trip.preferences or {})
                prefs[args.preference_key] = args.preference_value or ""
                trip.preferences = prefs
                message = f"Preference {args.preference_key} recorded."
            elif args.decision_kind == "warning_acknowledged":
                warnings = list(trip.verified_warnings or [])
                if note and note not in warnings:
                    warnings.append(note)
                trip.verified_warnings = warnings
                message = "Warning recorded on the trip."
            else:
                return SaveTripDecisionOutput(
                    saved=False,
                    trip_id=args.trip_id,
                    message=f"Unsupported decision_kind '{args.decision_kind}'.",
                )

            decisions = list(trip.decisions or [])
            decisions.append(
                f"{stamp} {args.decision_kind}: {args.region_code or args.preference_key or ''} {note}".strip()
            )
            trip.decisions = decisions[-50:]
            await session.commit()
            log.info("trip.decision_saved", trip_id=trip.id, kind=args.decision_kind)
            return SaveTripDecisionOutput(saved=True, trip_id=trip.id, message=message)

    @staticmethod
    async def _upsert_candidate(
        session: Any, trip_id: str, region_code: str, status: str, reason: str | None
    ) -> None:
        from jst_api.db.models import CandidateRegion

        row = await session.scalar(
            select(CandidateRegion).where(
                CandidateRegion.trip_id == trip_id, CandidateRegion.region_code == region_code
            )
        )
        if row is None:
            session.add(
                CandidateRegion(
                    trip_id=trip_id, region_code=region_code, status=status, reason=reason
                )
            )
        else:
            row.status = status
            if reason:
                row.reason = reason


def build_backend() -> JstTravelBackend:
    """Factory used by the stdio MCP entry point."""
    from jst_api.core.logging import configure_logging
    from jst_api.db.base import build_engine, get_sessionmaker
    from jst_api.providers.registry import build_registry

    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    build_engine(settings)
    session_factory = get_sessionmaker()
    return JstTravelBackend(session_factory, build_registry(session_factory, settings), settings)
