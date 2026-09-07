"""Evidence, citations and freshness — the trust layer of the product."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from jst_api.domain.enums import (
    EvidenceTopic,
    FreshnessState,
    SourceType,
    TrustLevel,
)


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    url: str | None = None
    domain: str | None = None
    source_type: SourceType
    official_source: bool = False
    trust_level: TrustLevel = TrustLevel.SECONDARY
    language: str = "en"
    fetched_at: datetime | None = None
    verified_at: datetime | None = None
    is_demo: bool = False

    @property
    def display_label(self) -> str:
        """Title as it appears *in a prompt* — the model is told when it is
        reading seeded data. API responses carry the raw ``title`` plus the
        ``is_demo`` flag instead, so the UI can badge it without the marker being
        baked into the string (and appended twice on a round trip)."""
        if self.is_demo and not self.title.endswith("(demo data)"):
            return f"{self.title} (demo data)"
        return self.title


class EvidenceChunk(BaseModel):
    """A retrieved unit of grounded knowledge, with everything needed to cite it."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source: SourceRef
    content: str
    topic: EvidenceTopic = EvidenceTopic.GENERAL
    region_code: str | None = None
    place_slug: str | None = None
    freshness: FreshnessState = FreshnessState.UNVERIFIED
    verified_at: datetime | None = None
    score: float = 0.0
    dense_rank: int | None = None
    keyword_rank: int | None = None
    fused_score: float | None = None
    rerank_score: float | None = None

    @property
    def is_demo(self) -> bool:
        return self.source.is_demo

    def citation(self) -> Citation:
        return Citation(
            evidence_id=self.evidence_id,
            source_id=self.source.source_id,
            title=self.source.title,
            url=self.source.url,
            source_type=self.source.source_type,
            official_source=self.source.official_source,
            verified_at=self.verified_at or self.source.verified_at,
            freshness=self.freshness,
            is_demo=self.is_demo,
        )

    def to_context_block(self, index: int, max_chars: int = 700) -> str:
        body = self.content.strip()
        if len(body) > max_chars:
            body = body[: max_chars - 1].rsplit(" ", 1)[0] + "…"
        verified = self.verified_at or self.source.verified_at
        stamp = verified.date().isoformat() if verified else "unverified"
        return (
            f"[E{index}] id={self.evidence_id} source={self.source.display_label} "
            f"type={self.source.source_type.value} trust={self.source.trust_level.value} "
            f"last_verified={stamp} freshness={self.freshness.value}\n{body}"
        )


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str
    title: str
    url: str | None = None
    source_type: SourceType
    official_source: bool = False
    verified_at: datetime | None = None
    freshness: FreshnessState = FreshnessState.UNVERIFIED
    is_demo: bool = False


class ConflictingEvidence(BaseModel):
    """Two approved sources disagree about the same operational fact.

    The system never picks a winner on its own — this becomes a human review
    task (see ``services/review_service.py``).
    """

    model_config = ConfigDict(extra="forbid")

    field_name: str
    subject: str
    values: list[str]
    evidence_ids: list[str]
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
