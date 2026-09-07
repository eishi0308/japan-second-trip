"""Deterministic rank fusion.

Reciprocal Rank Fusion (Cormack et al., 2009):

    score(d) = Σ_r  w_r / (k + rank_r(d))

RRF is chosen over score normalisation because the two retrievers produce
incomparable scales — cosine similarity in [-1, 1] versus ``ts_rank_cd``/BM25 on
an unbounded scale. RRF only consumes *ranks*, so no min-max normalisation
heuristic is needed and the result is reproducible. ``k`` damps the influence of
the very top ranks; 60 is the value from the original paper and is configurable
via ``settings.rrf_k``.

See docs/adr/0005-hybrid-search.md and docs/evals/retrieval-comparison.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FusedResult:
    key: str
    score: float
    ranks: dict[str, int] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    ranked_lists: dict[str, list[str]],
    *,
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[FusedResult]:
    """Fuse named ranked-id lists into one ordering.

    Ties break on the best single rank achieved, then on the id, so the output
    is fully deterministic for a fixed input.
    """
    weights = weights or {}
    accumulated: dict[str, FusedResult] = {}

    for retriever_name, ids in ranked_lists.items():
        weight = weights.get(retriever_name, 1.0)
        for rank, doc_id in enumerate(ids, start=1):
            entry = accumulated.setdefault(doc_id, FusedResult(key=doc_id, score=0.0))
            contribution = weight / (k + rank)
            entry.score += contribution
            entry.ranks[retriever_name] = rank
            entry.contributions[retriever_name] = contribution

    return sorted(
        accumulated.values(),
        key=lambda r: (-r.score, min(r.ranks.values()), r.key),
    )
