"""Ingestion pipeline.

    load (allowlisted URL | admin text | seed)
      -> clean + injection-neutralise
      -> heading-aware chunk (LangChain splitters)
      -> attach retrieval metadata
      -> embed (batched, cached by content hash)
      -> persist to PostgreSQL + pgvector

Re-ingesting an unchanged source is a no-op. Re-ingesting a *changed* source
replaces its chunks and, if any human-verified fact depended on that source,
raises a review task instead of silently overwriting the verified value
(§34 source-change detection).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.db.models import EvidenceChunk, Source, SourceDocument, VerificationRecord
from jst_api.domain.enums import EvidenceTopic, ReviewReason, SourceType, TrustLevel
from jst_api.knowledge.chunking import ChunkMetadata, build_search_text, chunk_document
from jst_api.knowledge.loaders import LoadedDocument, TextLoader, UrlLoader, content_hash

log = get_logger(__name__)


@dataclass
class IngestionResult:
    source_id: str
    document_id: str | None
    chunks_written: int
    changed: bool
    skipped: bool
    review_task_created: bool = False
    injection_flags: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "document_id": self.document_id,
            "chunks_written": self.chunks_written,
            "changed": self.changed,
            "skipped": self.skipped,
            "review_task_created": self.review_task_created,
            "injection_flags": self.injection_flags or [],
        }


class IngestionService:
    def __init__(self, session: AsyncSession, embeddings: Any, settings: Settings) -> None:
        self._session = session
        self._embeddings = embeddings
        self._settings = settings
        self._url_loader = UrlLoader(settings)
        self._text_loader = TextLoader()

    # -- public API ---------------------------------------------------------
    async def ingest_url(
        self,
        url: str,
        *,
        source_type: SourceType,
        region_code: str | None = None,
        place_slug: str | None = None,
        trust_level: TrustLevel = TrustLevel.SECONDARY,
        official_source: bool = False,
        title: str | None = None,
        force: bool = False,
    ) -> IngestionResult:
        loaded = await self._url_loader.load(url)
        return await self._persist(
            loaded,
            url=url,
            title=title or loaded.title or url,
            source_type=source_type,
            region_code=region_code,
            place_slug=place_slug,
            trust_level=trust_level,
            official_source=official_source,
            is_demo=False,
            force=force,
        )

    async def ingest_text(
        self,
        text: str,
        *,
        title: str,
        source_type: SourceType,
        region_code: str | None = None,
        place_slug: str | None = None,
        trust_level: TrustLevel = TrustLevel.SECONDARY,
        official_source: bool = False,
        url: str | None = None,
        is_demo: bool = True,
        topic: EvidenceTopic = EvidenceTopic.GENERAL,
        verified_at: datetime | None = None,
        force: bool = False,
    ) -> IngestionResult:
        loaded = await self._text_loader.load(
            text, title=title, metadata={"source_url": url} if url else None
        )
        return await self._persist(
            loaded,
            url=url,
            title=title,
            source_type=source_type,
            region_code=region_code,
            place_slug=place_slug,
            trust_level=trust_level,
            official_source=official_source,
            is_demo=is_demo,
            default_topic=topic,
            verified_at=verified_at,
            force=force,
        )

    async def refresh_source(self, source_id: str) -> IngestionResult:
        source = await self._session.get(Source, source_id)
        if source is None:
            raise ValueError(f"unknown source {source_id}")
        if not source.url:
            return IngestionResult(
                source_id=source_id, document_id=None, chunks_written=0, changed=False, skipped=True
            )
        return await self.ingest_url(
            source.url,
            source_type=SourceType(source.source_type),
            region_code=source.region_code,
            place_slug=source.place_slug,
            trust_level=TrustLevel(source.trust_level),
            official_source=source.official_source,
            title=source.title,
        )

    # -- internals ----------------------------------------------------------
    async def _persist(
        self,
        loaded: LoadedDocument,
        *,
        url: str | None,
        title: str,
        source_type: SourceType,
        region_code: str | None,
        place_slug: str | None,
        trust_level: TrustLevel,
        official_source: bool,
        is_demo: bool,
        default_topic: EvidenceTopic = EvidenceTopic.GENERAL,
        verified_at: datetime | None = None,
        force: bool = False,
    ) -> IngestionResult:
        now = datetime.now(UTC)
        source = await self._find_source(url=url, title=title)
        changed = source is not None and source.content_hash not in (None, loaded.hash)
        review_created = False

        if source is None:
            source = Source(
                url=url,
                title=title,
                domain=loaded.domain,
                source_type=source_type.value,
                official_source=official_source,
                trust_level=trust_level.value,
                region_code=region_code,
                place_slug=place_slug,
                fetched_at=now,
                verified_at=verified_at,
                freshness_ttl_days=self._settings.default_freshness_ttl_days,
                content_hash=loaded.hash,
                status="active",
                is_demo=is_demo,
            )
            self._session.add(source)
            await self._session.flush()
        else:
            if source.content_hash == loaded.hash and not force:
                log.info("ingest.unchanged", source_id=source.id, url=url)
                return IngestionResult(
                    source_id=source.id,
                    document_id=None,
                    chunks_written=0,
                    changed=False,
                    skipped=True,
                )
            if changed:
                review_created = await self._raise_change_review(source, loaded.hash)
            source.content_hash = loaded.hash
            source.fetched_at = now
            source.status = "changed" if changed else "active"

        document = SourceDocument(
            source_id=source.id,
            title=title,
            raw_content=loaded.raw[:2_000_000],
            cleaned_content=loaded.cleaned,
            content_hash=loaded.hash,
            doc_metadata={**loaded.document.metadata, "injection_flags": loaded.injection_flags},
            ingested_at=now,
        )
        self._session.add(document)
        await self._session.flush()

        metadata = ChunkMetadata(
            source_id=source.id,
            document_id=document.id,
            region_code=region_code,
            place_slug=place_slug,
            topic=default_topic,
            trust_level=trust_level,
            official_source=official_source,
            verified_at=verified_at or source.verified_at,
            is_demo=is_demo,
        )
        chunks = chunk_document(loaded.cleaned, metadata)
        if not chunks:
            document.chunk_count = 0
            return IngestionResult(
                source_id=source.id,
                document_id=document.id,
                chunks_written=0,
                changed=changed,
                skipped=False,
            )

        vectors = await self._embeddings.aembed_documents([c.page_content for c in chunks])

        # Replace this source's chunks atomically inside the caller's transaction.
        await self._session.execute(
            delete(EvidenceChunk).where(EvidenceChunk.source_id == source.id)
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            md = chunk.metadata
            self._session.add(
                EvidenceChunk(
                    source_id=source.id,
                    document_id=document.id,
                    chunk_index=int(md.get("chunk_index", 0)),
                    content=chunk.page_content,
                    search_text=build_search_text(chunk.page_content, md),
                    chunk_metadata=md,
                    region_code=md.get("region_code"),
                    place_slug=md.get("place_slug"),
                    topic=str(md.get("topic", EvidenceTopic.GENERAL.value)),
                    transport_mode=md.get("transport_mode"),
                    season_months=list(md.get("season_months") or []),
                    trust_level=str(md.get("trust_level", trust_level.value)),
                    official_source=bool(md.get("official_source", official_source)),
                    verified_at=verified_at or source.verified_at,
                    embedding_model=getattr(self._embeddings, "model", "unknown"),
                    embedding=vector,
                    token_estimate=max(1, len(chunk.page_content) // 4),
                    is_demo=is_demo,
                )
            )
        document.chunk_count = len(chunks)
        log.info("ingest.written", source_id=source.id, chunks=len(chunks), changed=changed)
        return IngestionResult(
            source_id=source.id,
            document_id=document.id,
            chunks_written=len(chunks),
            changed=changed,
            skipped=False,
            review_task_created=review_created,
            injection_flags=loaded.injection_flags,
        )

    async def _find_source(self, *, url: str | None, title: str) -> Source | None:
        if url:
            return await self._session.scalar(select(Source).where(Source.url == url))
        return await self._session.scalar(
            select(Source).where(Source.title == title, Source.url.is_(None))
        )

    async def _raise_change_review(self, source: Source, new_hash: str) -> bool:
        """A changed source that underpins a human-verified fact never
        auto-overwrites it — a reviewer confirms the new value first."""
        verified = list(
            (
                await self._session.scalars(
                    select(VerificationRecord).where(
                        VerificationRecord.source_id == source.id,
                        VerificationRecord.status == "verified",
                        VerificationRecord.verification_method.in_(
                            ["human_review", "operator_contact"]
                        ),
                    )
                )
            ).all()
        )
        if not verified:
            return False

        from jst_api.db.models import HumanReviewTask

        self._session.add(
            HumanReviewTask(
                reason=ReviewReason.SOURCE_CHANGED.value,
                subject=source.title,
                question=(
                    f"'{source.title}' changed since it was last verified "
                    f"({source.content_hash[:8] if source.content_hash else '?'} → {new_hash[:8]}). "
                    f"{len(verified)} human-verified fact(s) depend on it. Re-confirm each before use."
                ),
                candidate_values=[f"{v.field_name}={v.value}" for v in verified][:10],
                evidence_ids=[v.evidence_id for v in verified if v.evidence_id],
                priority="high",
            )
        )
        log.warning(
            "ingest.source_changed_review_raised", source_id=source.id, verified_facts=len(verified)
        )
        return True


def content_digest(text: str) -> str:
    return content_hash(text)
