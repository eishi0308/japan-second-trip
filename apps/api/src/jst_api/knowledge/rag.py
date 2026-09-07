"""RAG composition with LangChain Runnables (LCEL).

The retrieval-to-answer path is expressed as a runnable pipeline so it is one
composable object the agents call, the evals call, and the admin assistant
calls — rather than three hand-rolled copies of the same sequence:

    filters
      -> HybridRetriever            (dense + lexical, RRF)
      -> Reranker                   (heuristic | LLM, with fallback)
      -> context assembler          (dedupe, quarantine, token budget)
      -> prompt (versioned)
      -> LLM (structured output)
      -> validated Pydantic result + citations

``EvidencePipeline`` is the retrieval half, reused everywhere. ``build_rag_chain``
wraps it with a prompt and a schema to produce a full grounded answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda

from jst_api.core.cache import Cache, cache_key
from jst_api.core.logging import get_logger
from jst_api.db.repositories.evidence_repo import EvidenceFilters, EvidenceRepository
from jst_api.domain.enums import EvidenceTopic
from jst_api.domain.evidence import Citation
from jst_api.knowledge.context import AssembledContext, assemble_evidence_context
from jst_api.knowledge.retrievers import (
    DenseRetriever,
    HybridRetriever,
    KeywordRetriever,
    document_to_domain,
)

log = get_logger(__name__)


@dataclass
class RetrievalRequest:
    query: str
    filters: EvidenceFilters
    topics: list[EvidenceTopic] | None = None
    candidate_k: int = 24
    final_k: int = 6
    token_budget: int = 2400
    strategy: str = "hybrid"
    """hybrid_rerank | hybrid | vector | keyword. Callers should pass
    ``settings.retrieval_strategy``; the eval sweeps all four."""


@dataclass
class RetrievalOutcome:
    documents: list[Document]
    context: AssembledContext
    strategy: str
    dense_count: int
    keyword_count: int
    latency_ms: int = 0
    cache_hit: bool = False

    @property
    def citations(self) -> list[Citation]:
        return [document_to_domain(d).citation() for d in self.context_documents]

    @property
    def context_documents(self) -> list[Document]:
        included = set(self.context.audit.included_ids)
        return [d for d in self.documents if d.metadata["evidence_id"] in included]


class EvidencePipeline:
    """Retriever → reranker → context assembler, as a LangChain Runnable.

    Exposed both as ``.as_runnable()`` (for LCEL composition) and as a plain
    ``await pipeline.run(request)`` for the graph nodes, which need the audit
    record as well as the text.
    """

    def __init__(
        self,
        session: Any,
        embeddings: Any,
        reranker: Any,
        *,
        rrf_k: int = 5,
        dense_weight: float = 0.5,
        cache: Cache | None = None,
    ) -> None:
        self._session = session
        self._embeddings = embeddings
        self._reranker = reranker
        self._rrf_k = rrf_k
        self._dense_weight = dense_weight
        self._cache = cache
        self._repo = EvidenceRepository(session)

    def _build(
        self, request: RetrievalRequest
    ) -> tuple[DenseRetriever, KeywordRetriever, HybridRetriever]:
        dense = DenseRetriever(
            repository=self._repo,
            embeddings=self._embeddings,
            k=request.candidate_k,
            filters=request.filters,
        )
        keyword = KeywordRetriever(
            repository=self._repo, k=request.candidate_k, filters=request.filters
        )
        hybrid = HybridRetriever(
            dense=dense,
            keyword=keyword,
            k=request.candidate_k,
            rrf_k=self._rrf_k,
            dense_weight=self._dense_weight,
        )
        return dense, keyword, hybrid

    async def run(self, request: RetrievalRequest) -> RetrievalOutcome:
        import time

        started = time.perf_counter()
        dense, keyword, hybrid = self._build(request)

        key = cache_key(
            "retrieval",
            {
                "q": request.query,
                "f": request.filters.cache_payload(),
                "s": request.strategy,
                "ck": request.candidate_k,
                "fk": request.final_k,
            },
        )
        cached_ids: list[str] | None = await self._cache.get(key) if self._cache else None

        if request.strategy == "vector":
            documents = await dense.ainvoke(request.query)
            dense_count, keyword_count = len(documents), 0
        elif request.strategy == "keyword":
            documents = await keyword.ainvoke(request.query)
            dense_count, keyword_count = 0, len(documents)
        else:
            documents = await hybrid.ainvoke(request.query)
            dense_count = sum(1 for d in documents if d.metadata.get("dense_rank"))
            keyword_count = sum(1 for d in documents if d.metadata.get("keyword_rank"))

        if request.strategy == "hybrid_rerank":
            documents = await self._reranker.rerank(
                request.query, documents, top_k=request.final_k, topics=request.topics
            )
        else:
            documents = documents[: request.final_k]

        context = assemble_evidence_context(documents, token_budget=request.token_budget)
        outcome = RetrievalOutcome(
            documents=documents,
            context=context,
            strategy=request.strategy,
            dense_count=dense_count,
            keyword_count=keyword_count,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cache_hit=bool(cached_ids and cached_ids == context.audit.included_ids),
        )
        if self._cache:
            await self._cache.set(key, context.audit.included_ids, ttl=600)
        log.debug(
            "retrieval.done",
            strategy=request.strategy,
            returned=len(documents),
            included=len(context.audit.included_ids),
            quarantined=len(context.audit.quarantined),
            ms=outcome.latency_ms,
        )
        return outcome

    def as_runnable(self) -> Runnable:
        return RunnableLambda(self.run).with_config(run_name="EvidencePipeline")


def build_rag_chain(
    pipeline: EvidencePipeline,
    llm: Any,
    prompt: Any,
    schema: type,
    *,
    model: str | None = None,
    extra_payload_fn: Any = None,
) -> Runnable:
    """Full grounded-answer chain: retrieve → assemble → prompt → structured output.

    Citations survive to the output because the context assembler emits evidence
    ids and the caller reattaches them from ``RetrievalOutcome.citations``; the
    model is never trusted to be the sole carrier of provenance.
    """
    from jst_api.providers.llm import structured_block

    async def _retrieve(request: RetrievalRequest) -> dict[str, Any]:
        outcome = await pipeline.run(request)
        return {"request": request, "outcome": outcome}

    async def _generate(state: dict[str, Any]) -> dict[str, Any]:
        request: RetrievalRequest = state["request"]
        outcome: RetrievalOutcome = state["outcome"]
        payload = {
            "query": request.query,
            "available_evidence_ids": outcome.context.audit.included_ids,
        }
        if extra_payload_fn is not None:
            payload.update(extra_payload_fn(state))
        user = (
            f"{prompt.render_user(query=request.query, evidence_block=outcome.context.block)}\n\n"
            f"{structured_block(payload)}"
        )
        result, usage = await llm.complete_structured(
            system=prompt.system, user=user, schema=schema, model=model
        )
        return {
            "result": result,
            "usage": usage,
            "outcome": outcome,
            "citations": outcome.citations,
            "prompt_version": prompt.label,
        }

    return (
        RunnableLambda(_retrieve).with_config(run_name="Retrieve")
        | RunnableLambda(_generate).with_config(run_name="GenerateGrounded")
    ).with_config(run_name="RAGChain")
