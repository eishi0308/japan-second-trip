"""Hyper-parameter sweep for the fusion layer.

RRF has one free parameter, ``k``, and its value is not a matter of taste. With
``k`` large (the paper's 60), ``1/(k+1)`` and ``1/(k+7)`` are almost equal, so a
retriever that ranks the right document first is barely rewarded over one that
ranks it seventh. On a corpus this size that lets an uninformative lexical
result drag down a confident dense hit.

This sweep measures that instead of arguing about it, across ``k`` and the
dense/lexical weight ratio, and prints the configuration to adopt.
"""

from __future__ import annotations

import asyncio
from typing import Any

from evals.runners.common import (
    Harness,
    build_harness,
    load_dataset,
    mean,
    ndcg_at_k,
    reciprocal_rank,
    write_json,
)
from evals.runners.retrieval import FINAL_K, _title_index

RRF_K_VALUES = [5, 10, 20, 40, 60]
# The dense weight range extends below 1.0: once the lexical retriever's AND
# semantics were fixed it became the stronger signal on this corpus, so the
# question is no longer only 'how much more should dense count'.
DENSE_WEIGHTS = [0.5, 0.75, 1.0, 1.25, 1.5]


async def _score(
    harness: Harness,
    dataset: dict[str, Any],
    index: dict[str, set[str]],
    *,
    rrf_k: int,
    dense_weight: float,
) -> dict[str, float]:
    from jst_api.db.repositories.evidence_repo import (
        EvidenceFilters,
        EvidenceRepository,
    )
    from jst_api.knowledge.retrievers import (
        DenseRetriever,
        HybridRetriever,
        KeywordRetriever,
    )

    mrrs: list[float] = []
    ndcgs: list[float] = []
    top5 = 0

    async with harness.session_factory() as session:
        repo = EvidenceRepository(session)
        for case in dataset["cases"]:
            relevant: set[str] = set()
            for title in case["relevant_titles"]:
                relevant |= index.get(title, set())
            primary_ids = index.get(case.get("primary_title", ""), set())

            retriever = HybridRetriever(
                dense=DenseRetriever(
                    repository=repo,
                    embeddings=harness.embeddings,
                    k=harness.settings.retrieval_candidate_k,
                    filters=EvidenceFilters(),
                ),
                keyword=KeywordRetriever(
                    repository=repo,
                    k=harness.settings.retrieval_candidate_k,
                    filters=EvidenceFilters(),
                ),
                k=FINAL_K,
                rrf_k=rrf_k,
                dense_weight=dense_weight,
                keyword_weight=1.0,
            )
            docs = await retriever.ainvoke(case["query"])
            retrieved = [d.metadata["evidence_id"] for d in docs]
            primary = next((r for r in retrieved if r in primary_ids), None)
            mrrs.append(reciprocal_rank(retrieved, relevant))
            ndcgs.append(ndcg_at_k(retrieved, relevant, 8, primary=primary))
            if primary and retrieved.index(primary) < 5:
                top5 += 1

    return {
        "mrr": mean(mrrs),
        "ndcg@8": mean(ndcgs),
        "primary_top5": top5,
        "cases": len(dataset["cases"]),
    }


RERANK_FUSION_WEIGHTS = [0.45, 0.60, 0.75, 0.90]


async def _score_rerank(
    harness: Harness,
    dataset: dict[str, Any],
    index: dict[str, set[str]],
    *,
    fusion_weight: float,
) -> dict[str, float]:
    """Does reranking actually improve on the fused order, and at what weighting?

    The heuristic reranker mixes fusion score with trust, freshness, topic match
    and term coverage. If those secondary signals are weighted too heavily it
    promotes documents that are *reputable* over documents that are *relevant* —
    which is a real failure mode, not a hypothetical one.
    """
    from jst_api.db.repositories.evidence_repo import EvidenceFilters
    from jst_api.knowledge import rerank as rerank_module
    from jst_api.knowledge.rag import EvidencePipeline, RetrievalRequest
    from jst_api.knowledge.rerank import HeuristicReranker

    original = dict(rerank_module.HEURISTIC_WEIGHTS)
    remaining = 1.0 - fusion_weight
    share = remaining / 4.0
    rerank_module.HEURISTIC_WEIGHTS.update(
        {
            "fusion": fusion_weight,
            "trust": share,
            "freshness": share,
            "topic": share,
            "coverage": share,
        }
    )
    try:
        mrrs: list[float] = []
        ndcgs: list[float] = []
        top5 = 0
        async with harness.session_factory() as session:
            pipeline = EvidencePipeline(
                session,
                harness.embeddings,
                HeuristicReranker(),
                rrf_k=harness.settings.rrf_k,
                dense_weight=harness.settings.retrieval_dense_weight,
            )
            for case in dataset["cases"]:
                relevant: set[str] = set()
                for title in case["relevant_titles"]:
                    relevant |= index.get(title, set())
                primary_ids = index.get(case.get("primary_title", ""), set())
                outcome = await pipeline.run(
                    RetrievalRequest(
                        query=case["query"],
                        filters=EvidenceFilters(),
                        strategy="hybrid_rerank",
                        candidate_k=harness.settings.retrieval_candidate_k,
                        final_k=FINAL_K,
                        token_budget=100_000,
                    )
                )
                retrieved = [d.metadata["evidence_id"] for d in outcome.documents]
                primary = next((r for r in retrieved if r in primary_ids), None)
                mrrs.append(reciprocal_rank(retrieved, relevant))
                ndcgs.append(ndcg_at_k(retrieved, relevant, 8, primary=primary))
                if primary and retrieved.index(primary) < 5:
                    top5 += 1
        return {
            "mrr": mean(mrrs),
            "ndcg@8": mean(ndcgs),
            "primary_top5": top5,
            "cases": len(dataset["cases"]),
        }
    finally:
        rerank_module.HEURISTIC_WEIGHTS.clear()
        rerank_module.HEURISTIC_WEIGHTS.update(original)


async def run(quiet: bool = False) -> dict[str, Any]:
    harness = await build_harness()
    dataset = load_dataset("retrieval_v1.json")
    index = await _title_index(harness)

    grid: list[dict[str, Any]] = []
    for rrf_k in RRF_K_VALUES:
        for dense_weight in DENSE_WEIGHTS:
            metrics = await _score(harness, dataset, index, rrf_k=rrf_k, dense_weight=dense_weight)
            entry = {"rrf_k": rrf_k, "dense_weight": dense_weight, **metrics}
            grid.append(entry)
            if not quiet:
                print(
                    f"  rrf_k={rrf_k:<3} dense_weight={dense_weight:<5} "
                    f"mrr={metrics['mrr']:.3f} ndcg@8={metrics['ndcg@8']:.3f} "
                    f"top5={metrics['primary_top5']}/{metrics['cases']}"
                )

    best = max(grid, key=lambda e: (e["ndcg@8"], e["mrr"], e["primary_top5"]))
    if not quiet:
        print(
            f"\n  best fusion: rrf_k={best['rrf_k']} dense_weight={best['dense_weight']} (ndcg@8={best['ndcg@8']:.3f})"
        )
        print("\n  reranker fusion-weight sweep:")

    rerank_grid: list[dict[str, Any]] = []
    for fusion_weight in RERANK_FUSION_WEIGHTS:
        metrics = await _score_rerank(harness, dataset, index, fusion_weight=fusion_weight)
        entry = {"fusion_weight": fusion_weight, **metrics}
        rerank_grid.append(entry)
        if not quiet:
            print(
                f"    fusion_weight={fusion_weight:<5} mrr={metrics['mrr']:.3f} "
                f"ndcg@8={metrics['ndcg@8']:.3f} top5={metrics['primary_top5']}/{metrics['cases']}"
            )
    best_rerank = max(rerank_grid, key=lambda e: (e["ndcg@8"], e["mrr"], e["primary_top5"]))
    if not quiet:
        print(
            f"\n  best reranker fusion_weight={best_rerank['fusion_weight']} (ndcg@8={best_rerank['ndcg@8']:.3f})"
        )

    payload = {
        "grid": grid,
        "best": best,
        "rerank_grid": rerank_grid,
        "best_rerank": best_rerank,
    }
    write_json("retrieval_sweep.json", payload)
    return payload


if __name__ == "__main__":
    asyncio.run(run())
