"""Reranking.

The retrieval stage optimises recall (24–30 candidates). Reranking optimises
precision on the handful that will actually enter the model's context.

``HeuristicReranker`` is the default and the fallback: a documented, deterministic
scoring function over fusion score, source trust, freshness, topic match and
query-term coverage. It costs nothing and cannot fail.

``LLMReranker`` asks a cheap model to reorder the candidates by usefulness for
the specific travel question. It is bounded (single call, capped candidates,
strict schema) and **always** degrades to the heuristic on any failure, so a
reranker outage can never take retrieval down.

Which one to run in production is an eval decision, not a taste decision — see
docs/evals/retrieval-comparison.md.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from langchain_core.documents import Document

from jst_api.core.logging import get_logger
from jst_api.domain.enums import TRUST_WEIGHT, EvidenceTopic, FreshnessState, TrustLevel
from jst_api.domain.freshness import classify_freshness
from jst_api.domain.results import RerankVerdict

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Weights for the heuristic reranker, chosen by sweep (see
#: docs/evals/retrieval-comparison.md), not by taste. Weighting the secondary
#: signals too heavily promotes documents that are *reputable* over documents
#: that are *relevant* — a real failure mode this sweep caught.
#: The sum is not constrained to 1: the output is only ever used as an ordering,
#: never shown as a probability.
HEURISTIC_WEIGHTS = {
    "fusion": 0.45,
    "trust": 0.1375,
    "freshness": 0.1375,
    "topic": 0.1375,
    "coverage": 0.1375,
}

FRESHNESS_SCORE = {
    FreshnessState.FRESH: 1.0,
    FreshnessState.AGEING: 0.6,
    FreshnessState.STALE: 0.15,
    FreshnessState.UNVERIFIED: 0.35,
}


class Reranker(Protocol):
    name: str

    async def rerank(
        self,
        query: str,
        documents: list[Document],
        *,
        top_k: int,
        topics: list[EvidenceTopic] | None = None,
    ) -> list[Document]: ...


class HeuristicReranker:
    name = "heuristic"

    async def rerank(
        self,
        query: str,
        documents: list[Document],
        *,
        top_k: int,
        topics: list[EvidenceTopic] | None = None,
    ) -> list[Document]:
        if not documents:
            return []
        wanted = {t.value for t in (topics or [])}
        q_terms = set(_TOKEN_RE.findall(query.lower()))
        max_fusion = (
            max((float(d.metadata.get("fused_score") or 0.0) for d in documents), default=0.0)
            or 1.0
        )

        scored: list[tuple[float, int, Document]] = []
        for idx, doc in enumerate(documents):
            md = doc.metadata
            fusion = float(md.get("fused_score") or 0.0) / max_fusion
            trust = TRUST_WEIGHT.get(TrustLevel(md.get("trust_level", TrustLevel.SECONDARY)), 0.5)

            verified_at = md.get("verified_at")
            if verified_at:
                from datetime import datetime

                verified_dt = datetime.fromisoformat(verified_at)
            else:
                verified_dt = None
            topic = EvidenceTopic(md.get("topic", "general"))
            freshness = FRESHNESS_SCORE[classify_freshness(verified_dt, topic)]

            topic_match = 1.0 if (not wanted or md.get("topic") in wanted) else 0.35
            doc_terms = set(_TOKEN_RE.findall(doc.page_content.lower()))
            coverage = len(q_terms & doc_terms) / max(len(q_terms), 1)

            score = (
                HEURISTIC_WEIGHTS["fusion"] * fusion
                + HEURISTIC_WEIGHTS["trust"] * trust
                + HEURISTIC_WEIGHTS["freshness"] * freshness
                + HEURISTIC_WEIGHTS["topic"] * topic_match
                + HEURISTIC_WEIGHTS["coverage"] * coverage
            )
            scored.append((score, idx, doc))

        scored.sort(key=lambda t: (-t[0], t[1]))
        out: list[Document] = []
        for score, _idx, doc in scored[:top_k]:
            doc.metadata["rerank_score"] = round(score, 6)
            doc.metadata["reranker"] = self.name
            out.append(doc)
        return out


class LLMReranker:
    """Cheap-model listwise reranker with a hard fallback to the heuristic."""

    name = "llm"

    def __init__(self, llm: Any, model: str | None, prompts: Any, max_candidates: int = 30) -> None:
        self._llm = llm
        self._model = model
        self._prompts = prompts
        self._max_candidates = max_candidates
        self._fallback = HeuristicReranker()

    async def rerank(
        self,
        query: str,
        documents: list[Document],
        *,
        top_k: int,
        topics: list[EvidenceTopic] | None = None,
    ) -> list[Document]:
        if not documents:
            return []
        candidates = documents[: self._max_candidates]
        prompt = self._prompts.get("rerank")
        payload = {
            "query": query,
            "evidence": [
                {
                    "evidence_id": d.metadata["evidence_id"],
                    "topic": d.metadata.get("topic"),
                    "trust": d.metadata.get("trust_level"),
                    "verified_at": d.metadata.get("verified_at"),
                    "snippet": d.page_content[:400],
                }
                for d in candidates
            ],
        }
        try:
            from jst_api.providers.llm import structured_block

            verdict, _usage = await self._llm.complete_structured(
                system=prompt.system,
                user=f"{prompt.render_user(query=query)}\n\n{structured_block(payload)}",
                schema=RerankVerdict,
                model=self._model,
            )
        except Exception as exc:
            log.warning("rerank.llm_failed_falling_back", error=str(exc))
            return await self._fallback.rerank(query, documents, top_k=top_k, topics=topics)

        by_id = {d.metadata["evidence_id"]: d for d in candidates}
        ordered: list[Document] = []
        for position, evidence_id in enumerate(verdict.ranked_evidence_ids):
            doc = by_id.pop(evidence_id, None)
            if doc is None:
                continue  # a hallucinated id is dropped, never invented into context
            doc.metadata["rerank_score"] = round(1.0 - position / max(len(candidates), 1), 6)
            doc.metadata["reranker"] = self.name
            ordered.append(doc)
        if not ordered:
            log.warning("rerank.llm_returned_no_valid_ids_falling_back")
            return await self._fallback.rerank(query, documents, top_k=top_k, topics=topics)
        # Anything the model omitted keeps its fusion order behind the ranked set.
        ordered.extend(by_id.values())
        return ordered[:top_k]


def build_reranker(settings: Any, llm: Any, prompts: Any, router: Any) -> Reranker:
    if settings.reranker == "llm":
        from jst_api.providers.llm import TaskClass

        return LLMReranker(llm, router.model_for(TaskClass.RERANK), prompts)
    return HeuristicReranker()
