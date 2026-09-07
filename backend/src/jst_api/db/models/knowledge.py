"""Knowledge layer: sources, documents, embedded evidence, verification.

This is the RAG side of the split. It holds *unstructured operational prose* —
booking instructions, operator guidance, access caveats, human verification
notes — the things that resist normalisation into columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat, Vector

EMBEDDING_DIM = 384
"""Fixed at the schema level. Changing it is a migration, not a config flip —
see docs/adr/0004-postgres-pgvector.md."""


class Source(Base, TimestampMixin):
    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_region_type", "region_code", "source_type"),)

    id: Mapped[str] = id_column("src")
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str] = mapped_column(String(400))
    domain: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    official_source: Mapped[bool] = mapped_column(Boolean, default=False)
    trust_level: Mapped[str] = mapped_column(String(20), default="secondary")
    region_code: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    prefecture: Mapped[str | None] = mapped_column(String(80), nullable=True)
    place_slug: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    freshness_ttl_days: Mapped[int] = mapped_column(Integer, default=180)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    """active | changed | retired | quarantined"""
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list[SourceDocument]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id: Mapped[str] = id_column("doc")
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    raw_content: Mapped[str] = mapped_column(Text)
    cleaned_content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    doc_metadata: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[Source] = relationship(back_populates="documents")
    chunks: Mapped[list[EvidenceChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class EvidenceChunk(Base, TimestampMixin):
    """One retrievable unit. Carries both the vector and the lexical surface.

    ``search_text`` is the lexical field. On PostgreSQL a GIN index over
    ``to_tsvector('english', search_text)`` backs full-text search; on SQLite the
    repository falls back to token matching over the same column, so both
    dialects search identical text.
    """

    __tablename__ = "evidence_chunks"
    __table_args__ = (
        Index("ix_evidence_region_topic", "region_code", "topic"),
        Index("ix_evidence_place", "place_slug"),
    )

    id: Mapped[str] = id_column("ev")
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True, nullable=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    chunk_metadata: Mapped[dict] = mapped_column(JSONBCompat, default=dict)

    region_code: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    place_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    topic: Mapped[str] = mapped_column(String(40), default="general", index=True)
    transport_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    season_months: Mapped[list] = mapped_column(JSONBCompat, default=list)
    trust_level: Mapped[str] = mapped_column(String(20), default="secondary")
    official_source: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(80), default="demo-hash-384")
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    document: Mapped[SourceDocument | None] = relationship(back_populates="chunks")
    source: Mapped[Source] = relationship()


class VerificationRecord(Base, TimestampMixin):
    """A human (or tool) assertion that a specific fact held on a specific date."""

    __tablename__ = "verification_records"
    __table_args__ = (Index("ix_verification_subject_field", "subject", "field_name"),)

    id: Mapped[str] = id_column("ver")
    subject: Mapped[str] = mapped_column(String(200), index=True)
    """What the fact is about, e.g. "ginzan-onsen:last_shuttle"."""
    field_name: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_chunks.id"), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str] = mapped_column(String(120), default="system")
    verification_method: Mapped[str] = mapped_column(String(60), default="seed")
    """seed | official_page | operator_contact | human_review | provider_api"""
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    status: Mapped[str] = mapped_column(String(30), default="verified")
    """verified | superseded | disputed"""
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
