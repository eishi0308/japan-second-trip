"""Seed loader — populates a database with the demo catalogue and corpus.

Idempotent: running it twice does not duplicate rows. Every row it writes is
flagged ``is_demo=True``.

Used by ``scripts/seed.py``, by the test fixtures, and by the eval harness, so
all three run against identical data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.db.models import (
    BookingConstraint,
    EvidenceChunk,
    HumanReviewTask,
    Place,
    Region,
    Source,
    TransportConstraint,
    VerificationRecord,
)
from jst_api.domain.enums import EvidenceTopic, ReviewReason, SourceType, TrustLevel
from jst_api.knowledge.ingest import IngestionService
from jst_api.seed.booking import BOOKING_CONSTRAINTS
from jst_api.seed.evidence import DOCUMENTS, KNOWN_CONFLICTS
from jst_api.seed.places import PLACES
from jst_api.seed.regions import REGIONS
from jst_api.seed.transport import TRANSPORT

log = get_logger(__name__)


async def seed_catalogue(session: AsyncSession) -> dict[str, int]:
    """Regions, places, transport and booking constraints (structured facts)."""
    counts = {"regions": 0, "places": 0, "transport": 0, "booking": 0}

    existing_regions = set((await session.scalars(select(Region.code))).all())
    for data in REGIONS:
        if data["code"] in existing_regions:
            continue
        session.add(
            Region(
                code=data["code"],
                name=data["name"],
                tagline=data["tagline"],
                prefectures=data["prefectures"],
                hub_place_slug=data["hub_place_slug"],
                lat=data["lat"],
                lon=data["lon"],
                gateways=data["gateways"],
                min_recommended_nights=data["min_recommended_nights"],
                ideal_nights=data["ideal_nights"],
                max_useful_nights=data["max_useful_nights"],
                public_transport_score=data["public_transport_score"],
                car_free_possible=data["car_free_possible"],
                car_recommended=data["car_recommended"],
                car_required_highlights=data["car_required_highlights"],
                interest_strength=data["interest_strength"],
                seasonal=data["seasonal"],
                booking_complexity=data["booking_complexity"],
                luggage_friendliness=data["luggage_friendliness"],
                step_free_score=data["step_free_score"],
                typical_daily_cost_jpy=data["typical_daily_cost_jpy"],
                overlaps_with_visited=data["overlaps_with_visited"],
                is_demo=True,
            )
        )
        counts["regions"] += 1
    await session.flush()

    existing_places = set((await session.scalars(select(Place.slug))).all())
    for data in PLACES:
        if data["slug"] in existing_places:
            continue
        session.add(Place(**{**data, "is_demo": True}))
        counts["places"] += 1
    await session.flush()

    existing_transport = {
        (f, t, m)
        for f, t, m in (
            await session.execute(
                select(
                    TransportConstraint.from_slug,
                    TransportConstraint.to_slug,
                    TransportConstraint.mode,
                )
            )
        ).all()
    }
    verified_at = datetime.now(UTC) - timedelta(days=30)
    for data in TRANSPORT:
        key = (data["from_slug"], data["to_slug"], data["mode"])
        if key in existing_transport:
            continue
        session.add(TransportConstraint(**{**data, "verified_at": verified_at, "is_demo": True}))
        counts["transport"] += 1

    existing_booking = {
        (p, s)
        for p, s in (
            await session.execute(select(BookingConstraint.place_slug, BookingConstraint.subject))
        ).all()
    }
    for data in BOOKING_CONSTRAINTS:
        if (data["place_slug"], data["subject"]) in existing_booking:
            continue
        session.add(BookingConstraint(**{**data, "verified_at": verified_at, "is_demo": True}))
        counts["booking"] += 1

    await session.flush()
    log.info("seed.catalogue", **counts)
    return counts


async def seed_evidence(
    session: AsyncSession, embeddings: Any, settings: Settings
) -> dict[str, int]:
    """Ingest the demo corpus through the real ingestion pipeline.

    Deliberately not a direct row insert: the seed exercises the same chunker,
    metadata extractor and embedder that live ingestion uses, so a bug in that
    path shows up immediately rather than only in production.
    """
    service = IngestionService(session, embeddings, settings)
    counts = {"documents": 0, "chunks": 0, "skipped": 0}
    key_to_source: dict[str, str] = {}

    for doc in DOCUMENTS:
        result = await service.ingest_text(
            doc["body"],
            title=doc["title"],
            source_type=SourceType(doc["source_type"]),
            region_code=doc.get("region_code"),
            place_slug=doc.get("place_slug"),
            trust_level=TrustLevel(doc["trust_level"]),
            official_source=doc["official_source"],
            url=doc.get("url"),
            is_demo=True,
            topic=EvidenceTopic(doc.get("topic", "general")),
            verified_at=datetime.now(UTC) - timedelta(days=int(doc["verified_days_ago"])),
        )
        key_to_source[doc["key"]] = result.source_id
        if result.skipped:
            counts["skipped"] += 1
        else:
            counts["documents"] += 1
            counts["chunks"] += result.chunks_written

        if doc.get("season_months"):
            await session.flush()
            for chunk in (
                await session.scalars(
                    select(EvidenceChunk).where(EvidenceChunk.source_id == result.source_id)
                )
            ).all():
                if not chunk.season_months:
                    chunk.season_months = list(doc["season_months"])

    await session.flush()
    await _seed_verifications(session, key_to_source)
    await _seed_conflicts(session, key_to_source)
    log.info("seed.evidence", **counts)
    return counts


async def _seed_verifications(session: AsyncSession, key_to_source: dict[str, str]) -> None:
    """Record verified operational facts so freshness and HITL have real subjects."""
    if await session.scalar(select(func.count()).select_from(VerificationRecord)):
        return
    now = datetime.now(UTC)
    records = [
        (
            "ginzan-onsen:oishida_last_bus",
            "last_shuttle_departure",
            "18:10",
            key_to_source.get("ginzan-access"),
            55,
            "official_page",
            0.7,
        ),
        (
            "kamikochi:season",
            "closure_window",
            "16 Nov – 16 Apr",
            key_to_source.get("kamikochi-access"),
            50,
            "official_page",
            0.95,
        ),
        (
            "kurokawa-onsen:last_bus_from_yufuin",
            "last_bus_departure",
            "16:30",
            key_to_source.get("kyushu-onsen-access"),
            48,
            "official_page",
            0.9,
        ),
        (
            "naoshima:last_ferry",
            "last_ferry_departure",
            "18:05",
            key_to_source.get("naoshima-ferry"),
            35,
            "official_page",
            0.9,
        ),
        (
            "tateyama:season",
            "operating_window",
            "mid-Apr – end Nov",
            key_to_source.get("tateyama-season"),
            400,
            "seed",
            0.5,
        ),
    ]
    for subject, field_name, value, source_id, days, method, confidence in records:
        session.add(
            VerificationRecord(
                subject=subject,
                field_name=field_name,
                value=value,
                source_id=source_id,
                verified_at=now - timedelta(days=days),
                verified_by="seed",
                verification_method=method,
                confidence=confidence,
                status="verified",
                is_demo=True,
            )
        )
    await session.flush()


async def _seed_conflicts(session: AsyncSession, key_to_source: dict[str, str]) -> None:
    """Create the open human-review task for the seeded conflicting fact.

    This is not decoration: the admin queue, the HITL resume path and the
    conflict-detection eval all need a genuine conflict to act on.
    """
    for conflict in KNOWN_CONFLICTS:
        existing = await session.scalar(
            select(HumanReviewTask).where(HumanReviewTask.subject == conflict["subject"])
        )
        if existing is not None:
            continue
        source_ids = [key_to_source[k] for k in conflict["document_keys"] if k in key_to_source]
        evidence_ids: list[str] = []
        for source_id in source_ids:
            chunk = await session.scalar(
                select(EvidenceChunk).where(EvidenceChunk.source_id == source_id).limit(1)
            )
            if chunk:
                evidence_ids.append(chunk.id)
        session.add(
            HumanReviewTask(
                reason=ReviewReason.CONFLICTING_SOURCES.value,
                subject=conflict["subject"],
                field_name=conflict["field_name"],
                question=conflict["question"],
                candidate_values=conflict["values"],
                evidence_ids=evidence_ids,
                status="open",
                priority="high",
            )
        )
    await session.flush()


async def seed_all(session: AsyncSession, embeddings: Any, settings: Settings) -> dict[str, Any]:
    catalogue = await seed_catalogue(session)
    evidence = await seed_evidence(session, embeddings, settings)
    sources = int(await session.scalar(select(func.count()).select_from(Source)) or 0)
    chunks = int(await session.scalar(select(func.count()).select_from(EvidenceChunk)) or 0)
    return {
        "catalogue": catalogue,
        "evidence": evidence,
        "total_sources": sources,
        "total_chunks": chunks,
    }
