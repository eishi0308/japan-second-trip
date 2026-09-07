"""LangChain retrievers over PostgreSQL + pgvector.

Three ``BaseRetriever`` implementations so the whole retrieval stack composes
with LangChain runnables and can be swapped inside an LCEL chain:

``DenseRetriever``     semantic recall — "difficult without a car"
``KeywordRetriever``   exact proper nouns — "Ginzan Onsen", "JR East"
``HybridRetriever``    both, fused with RRF, then optionally reranked

Every retriever returns LangChain ``Document`` objects whose ``metadata``
carries the evidence id, source id, trust level and verification date. Those
fields survive all the way to the citation shown in the UI — a citation that
loses its evidence id is a citation that cannot be audited.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from jst_api.core.logging import get_logger
from jst_api.db.models import EvidenceChunk, Source
from jst_api.db.repositories.evidence_repo import EvidenceFilters, EvidenceRepository, ScoredChunk
from jst_api.domain.enums import EvidenceTopic, FreshnessState, SourceType, TrustLevel
from jst_api.domain.evidence import EvidenceChunk as DomainEvidence
from jst_api.domain.evidence import SourceRef
from jst_api.domain.freshness import classify_freshness
from jst_api.knowledge.fusion import reciprocal_rank_fusion

log = get_logger(__name__)

RETRIEVER_DENSE = "dense"
RETRIEVER_KEYWORD = "keyword"


def chunk_to_document(scored: ScoredChunk, retriever: str) -> Document:
    chunk, source = scored.chunk, scored.source
    return Document(
        id=chunk.id,
        page_content=chunk.content,
        metadata={
            "evidence_id": chunk.id,
            "source_id": source.id,
            "source_title": source.title,
            "source_url": source.url,
            "source_type": source.source_type,
            "official_source": source.official_source,
            "trust_level": chunk.trust_level,
            "region_code": chunk.region_code,
            "place_slug": chunk.place_slug,
            "topic": chunk.topic,
            "transport_mode": chunk.transport_mode,
            "season_months": list(chunk.season_months or []),
            "verified_at": chunk.verified_at.isoformat() if chunk.verified_at else None,
            "is_demo": chunk.is_demo,
            "retriever": retriever,
            "score": scored.score,
            "rank": scored.rank,
        },
    )


def document_to_domain(doc: Document) -> DomainEvidence:
    md = doc.metadata
    verified_raw = md.get("verified_at")
    verified_at = None
    if verified_raw:
        from datetime import datetime

        verified_at = datetime.fromisoformat(verified_raw)
    topic = EvidenceTopic(md.get("topic", "general")) if md.get("topic") else EvidenceTopic.GENERAL
    return DomainEvidence(
        evidence_id=md["evidence_id"],
        source=SourceRef(
            source_id=md["source_id"],
            title=md.get("source_title", "Untitled source"),
            url=md.get("source_url"),
            source_type=SourceType(md.get("source_type", SourceType.DEMO_SEED)),
            official_source=bool(md.get("official_source")),
            trust_level=TrustLevel(md.get("trust_level", TrustLevel.SECONDARY)),
            verified_at=verified_at,
            is_demo=bool(md.get("is_demo", True)),
        ),
        content=doc.page_content,
        topic=topic,
        region_code=md.get("region_code"),
        place_slug=md.get("place_slug"),
        freshness=classify_freshness(verified_at, topic),
        verified_at=verified_at,
        score=float(md.get("score", 0.0)),
        dense_rank=md.get("dense_rank"),
        keyword_rank=md.get("keyword_rank"),
        fused_score=md.get("fused_score"),
        rerank_score=md.get("rerank_score"),
    )


class _AsyncOnlyRetriever(BaseRetriever):
    """Shared base: this application is async end-to-end.

    LangChain's sync entry point is deliberately unimplemented rather than
    bridged with ``asyncio.run`` — calling it from inside the running event loop
    would deadlock, and a loud error is better than a hung request.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        raise NotImplementedError(
            f"{type(self).__name__} is async-only; use ainvoke()/aget_relevant_documents()."
        )


class DenseRetriever(_AsyncOnlyRetriever):
    """pgvector cosine-similarity retrieval."""

    repository: Any
    embeddings: Any
    k: int = 20
    filters: EvidenceFilters = Field(default_factory=EvidenceFilters)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        vector = await self.embeddings.aembed_query(query)
        scored = await self.repository.dense_search(vector, k=self.k, filters=self.filters)
        docs = []
        for item in scored:
            doc = chunk_to_document(item, RETRIEVER_DENSE)
            doc.metadata["dense_rank"] = item.rank
            docs.append(doc)
        return docs


class KeywordRetriever(_AsyncOnlyRetriever):
    """PostgreSQL full-text (+ trigram) retrieval; BM25 on the SQLite fallback."""

    repository: Any
    k: int = 20
    filters: EvidenceFilters = Field(default_factory=EvidenceFilters)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        scored = await self.repository.keyword_search(query, k=self.k, filters=self.filters)
        docs = []
        for item in scored:
            doc = chunk_to_document(item, RETRIEVER_KEYWORD)
            doc.metadata["keyword_rank"] = item.rank
            docs.append(doc)
        return docs


class HybridRetriever(_AsyncOnlyRetriever):
    """Dense + lexical, fused with Reciprocal Rank Fusion.

    Runs both retrievers over identical filters, fuses on rank, and returns the
    top ``k`` documents with the full provenance of *how* each one was found —
    which retriever surfaced it, at what rank, and what each contributed to the
    fused score. That provenance is what the retrieval eval measures.
    """

    dense: DenseRetriever
    keyword: KeywordRetriever
    k: int = 8
    rrf_k: int = 60
    dense_weight: float = 1.0
    keyword_weight: float = 1.0

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        dense_docs = await self.dense._aget_relevant_documents(query, run_manager=run_manager)
        keyword_docs = await self.keyword._aget_relevant_documents(query, run_manager=run_manager)

        by_id: dict[str, Document] = {}
        for doc in [*keyword_docs, *dense_docs]:
            evidence_id = str(doc.metadata["evidence_id"])
            existing = by_id.get(evidence_id)
            if existing is None:
                by_id[evidence_id] = doc
            else:
                # Merge provenance so a document found by both keeps both ranks.
                existing.metadata.setdefault("dense_rank", doc.metadata.get("dense_rank"))
                existing.metadata.setdefault("keyword_rank", doc.metadata.get("keyword_rank"))
                if doc.metadata.get("dense_rank") is not None:
                    existing.metadata["dense_rank"] = doc.metadata["dense_rank"]
                if doc.metadata.get("keyword_rank") is not None:
                    existing.metadata["keyword_rank"] = doc.metadata["keyword_rank"]

        fused = reciprocal_rank_fusion(
            {
                RETRIEVER_DENSE: [d.metadata["evidence_id"] for d in dense_docs],
                RETRIEVER_KEYWORD: [d.metadata["evidence_id"] for d in keyword_docs],
            },
            k=self.rrf_k,
            weights={RETRIEVER_DENSE: self.dense_weight, RETRIEVER_KEYWORD: self.keyword_weight},
        )

        results: list[Document] = []
        for item in fused[: self.k]:
            fused_doc = by_id.get(item.key)
            if fused_doc is None:
                continue
            fused_doc.metadata["fused_score"] = round(item.score, 6)
            fused_doc.metadata["fusion_ranks"] = item.ranks
            fused_doc.metadata["retriever"] = "hybrid"
            results.append(fused_doc)
        return results


def build_filters_for_trip(
    *,
    region_codes: list[str] | None = None,
    place_slugs: list[str] | None = None,
    topics: list[EvidenceTopic] | None = None,
    month: int | None = None,
    min_trust: TrustLevel | None = None,
) -> EvidenceFilters:
    return EvidenceFilters(
        region_codes=region_codes or [],
        place_slugs=place_slugs or [],
        topics=[t.value for t in (topics or [])],
        season_month=month,
        min_trust=min_trust,
    )


def build_hybrid_retriever(
    session: Any,
    embeddings: Any,
    *,
    candidate_k: int = 24,
    final_k: int = 8,
    rrf_k: int = 60,
    filters: EvidenceFilters | None = None,
) -> HybridRetriever:
    repo = EvidenceRepository(session)
    filters = filters or EvidenceFilters()
    return HybridRetriever(
        dense=DenseRetriever(
            repository=repo, embeddings=embeddings, k=candidate_k, filters=filters
        ),
        keyword=KeywordRetriever(repository=repo, k=candidate_k, filters=filters),
        k=final_k,
        rrf_k=rrf_k,
    )


__all__ = [
    "DenseRetriever",
    "EvidenceChunk",
    "FreshnessState",
    "HybridRetriever",
    "KeywordRetriever",
    "Source",
    "build_filters_for_trip",
    "build_hybrid_retriever",
    "chunk_to_document",
    "document_to_domain",
]
