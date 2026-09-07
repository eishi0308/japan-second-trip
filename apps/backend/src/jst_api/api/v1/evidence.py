"""Evidence inspection — every citation in the UI is clickable through to this."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from jst_api.api.deps import RateLimitDep, SessionDep
from jst_api.api.schemas import EvidenceOut
from jst_api.core.errors import NotFoundError
from jst_api.db.models import EvidenceChunk, Source
from jst_api.domain.enums import EvidenceTopic
from jst_api.domain.freshness import classify_freshness, freshness_label

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{evidence_id}", response_model=EvidenceOut)
async def get_evidence(evidence_id: str, session: SessionDep, _rate: RateLimitDep) -> EvidenceOut:
    row = (
        await session.execute(
            select(EvidenceChunk, Source)
            .join(Source, Source.id == EvidenceChunk.source_id)
            .where(EvidenceChunk.id == evidence_id)
        )
    ).first()
    if row is None:
        raise NotFoundError(
            f"Evidence {evidence_id} not found", details={"evidence_id": evidence_id}
        )
    chunk, source = row
    topic = EvidenceTopic(chunk.topic) if chunk.topic else EvidenceTopic.GENERAL
    freshness = classify_freshness(chunk.verified_at, topic)
    return EvidenceOut(
        evidence_id=chunk.id,
        content=chunk.content,
        source_id=source.id,
        source_title=source.title,
        source_url=source.url,
        source_type=source.source_type,
        official_source=source.official_source,
        trust_level=chunk.trust_level,
        topic=chunk.topic,
        region_code=chunk.region_code,
        place_slug=chunk.place_slug,
        verified_at=chunk.verified_at.isoformat() if chunk.verified_at else None,
        freshness=freshness.value,
        freshness_label=freshness_label(freshness, chunk.verified_at),
        is_demo=chunk.is_demo,
    )
