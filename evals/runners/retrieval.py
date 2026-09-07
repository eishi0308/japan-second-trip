"""Retrieval evaluation and the four-way strategy comparison.

Runs the same golden query set through four configurations and reports
Recall@K, Precision@K, MRR and NDCG@K for each:

    keyword        PostgreSQL full-text + trigram (BM25 on the SQLite fallback)
    vector         pgvector cosine over the embedding column
    hybrid         both, fused with Reciprocal Rank Fusion
    hybrid_rerank  hybrid, then reranked

The point is to *decide* with data rather than assume the most elaborate
pipeline wins. Results, including where each strategy loses, go to
docs/evals/retrieval-comparison.md.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from evals.runners.common import (
    CaseResult,
    Harness,
    SuiteResult,
    Timer,
    build_harness,
    git_sha,
    load_dataset,
    mean,
    ndcg_at_k,
    percentile,
    persist_suite,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    write_json,
)

STRATEGIES = ["keyword", "vector", "hybrid", "hybrid_rerank"]
K_VALUES = (3, 5, 8)
FINAL_K = 8


async def _title_index(harness: Harness) -> dict[str, set[str]]:
    """title -> evidence ids. Relevance is authored against titles so the
    dataset survives re-seeding."""
    from sqlalchemy import select

    from jst_api.db.models import EvidenceChunk, Source

    async with harness.session_factory() as session:
        rows = (
            await session.execute(
                select(EvidenceChunk.id, Source.title).join(
                    Source, Source.id == EvidenceChunk.source_id
                )
            )
        ).all()
    index: dict[str, set[str]] = {}
    for evidence_id, title in rows:
        index.setdefault(title, set()).add(evidence_id)
    return index


async def run_strategy(harness: Harness, dataset: dict[str, Any], strategy: str) -> SuiteResult:
    from jst_api.db.repositories.evidence_repo import EvidenceFilters
    from jst_api.knowledge.rag import EvidencePipeline, RetrievalRequest
    from jst_api.knowledge.rerank import HeuristicReranker

    index = await _title_index(harness)
    result = SuiteResult(
        suite="retrieval",
        dataset=dataset["dataset"],
        dataset_version=dataset["version"],
        variant=strategy,
        git_sha=git_sha(),
    )
    latencies: list[float] = []

    async with harness.session_factory() as session:
        # Both fusion parameters are passed explicitly. Relying on the
        # constructor defaults means the comparison can silently measure a
        # different configuration from the one the app runs — which happened
        # once and made the sweep and the comparison disagree.
        pipeline = EvidencePipeline(
            session,
            harness.embeddings,
            HeuristicReranker(),
            rrf_k=harness.settings.rrf_k,
            dense_weight=harness.settings.retrieval_dense_weight,
        )
        with Timer() as suite_timer:
            for case in dataset["cases"]:
                relevant: set[str] = set()
                for title in case["relevant_titles"]:
                    relevant |= index.get(title, set())
                primary_ids = index.get(case.get("primary_title", ""), set())

                outcome = await pipeline.run(
                    RetrievalRequest(
                        query=case["query"],
                        filters=EvidenceFilters(),
                        strategy=strategy,
                        candidate_k=harness.settings.retrieval_candidate_k,
                        final_k=FINAL_K,
                        token_budget=100_000,  # measure retrieval, not truncation
                    )
                )
                retrieved = [d.metadata["evidence_id"] for d in outcome.documents]
                latencies.append(outcome.latency_ms)

                # Credit any chunk of the primary source as the primary hit.
                primary = next((r for r in retrieved if r in primary_ids), None)
                metrics = {
                    **{
                        f"recall@{k}": round(recall_at_k(retrieved, relevant, k), 4)
                        for k in K_VALUES
                    },
                    **{
                        f"precision@{k}": round(precision_at_k(retrieved, relevant, k), 4)
                        for k in K_VALUES
                    },
                    "mrr": round(reciprocal_rank(retrieved, relevant), 4),
                    "ndcg@8": round(ndcg_at_k(retrieved, relevant, 8, primary=primary), 4),
                    "primary_rank": (retrieved.index(primary) + 1) if primary else None,
                    "latency_ms": outcome.latency_ms,
                }
                # A case passes when the primary source appears in the top 5 —
                # the practical bar for "the traveller would have seen it".
                passed = metrics["primary_rank"] is not None and metrics["primary_rank"] <= 5
                result.cases.append(
                    CaseResult(
                        case_id=case["id"],
                        passed=passed,
                        score=metrics["ndcg@8"],
                        metrics=metrics,
                        detail={
                            "class": case["class"],
                            "query": case["query"],
                            "retrieved_titles": [
                                d.metadata.get("source_title") for d in outcome.documents[:5]
                            ],
                        },
                        failure=None if passed else "primary source not in top 5",
                    )
                )
        result.duration_ms = suite_timer.ms

    by_class: dict[str, list[CaseResult]] = {}
    for case in result.cases:
        by_class.setdefault(case.detail["class"], []).append(case)

    result.metrics = {
        **{f"recall@{k}": mean([c.metrics[f"recall@{k}"] for c in result.cases]) for k in K_VALUES},
        **{
            f"precision@{k}": mean([c.metrics[f"precision@{k}"] for c in result.cases])
            for k in K_VALUES
        },
        "mrr": mean([c.metrics["mrr"] for c in result.cases]),
        "ndcg@8": mean([c.metrics["ndcg@8"] for c in result.cases]),
        "pass_rate": result.pass_rate,
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "by_class": {
            name: {
                "cases": len(cases),
                "pass_rate": round(sum(1 for c in cases if c.passed) / len(cases), 4),
                "mrr": mean([c.metrics["mrr"] for c in cases]),
                "ndcg@8": mean([c.metrics["ndcg@8"] for c in cases]),
            }
            for name, cases in sorted(by_class.items())
        },
    }
    return result


async def run(*, persist: bool = True, quiet: bool = False) -> dict[str, SuiteResult]:
    harness = await build_harness()
    dataset = load_dataset("retrieval_v1.json")
    results: dict[str, SuiteResult] = {}

    for strategy in STRATEGIES:
        result = await run_strategy(harness, dataset, strategy)
        results[strategy] = result
        if persist:
            await persist_suite(harness, result)
        if not quiet:
            m = result.metrics
            print(
                f"  {strategy:14} recall@5={m['recall@5']:.3f} precision@5={m['precision@5']:.3f} "
                f"mrr={m['mrr']:.3f} ndcg@8={m['ndcg@8']:.3f} pass={result.passed}/{len(result.cases)} "
                f"p50={m['p50_latency_ms']}ms"
            )

    write_json("retrieval.json", {k: v.to_dict() for k, v in results.items()})
    return results


def build_comparison_markdown(results: dict[str, SuiteResult]) -> str:
    """The report that justifies the production retrieval choice."""
    # Primary-in-top-5 first, then MRR. NDCG differences below ~0.01 on a 20-case
    # set are noise and must not decide a production default.
    best = max(results.values(), key=lambda r: (r.passed, r.metrics["mrr"]))
    lines = [
        "# Retrieval strategy comparison",
        "",
        (
            f"Dataset: `evals/datasets/retrieval_v1.json` v{next(iter(results.values())).dataset_version} — "
            f"{len(next(iter(results.values())).cases)} golden queries "
            "(6 lexical, 9 semantic, 5 mixed)."
        ),
        "",
        (
            "Generated by `python -m evals.run retrieval`. Every run uses the demo embedding provider so the "
            "numbers are reproducible on any machine, including CI with no credentials."
        ),
        "",
        "## Headline",
        "",
        "| Strategy | Recall@3 | Recall@5 | Recall@8 | Precision@5 | MRR | NDCG@8 | Primary in top-5 | p50 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, result in results.items():
        m = result.metrics
        lines.append(
            f"| `{name}` | {m['recall@3']:.3f} | {m['recall@5']:.3f} | {m['recall@8']:.3f} | "
            f"{m['precision@5']:.3f} | {m['mrr']:.3f} | {m['ndcg@8']:.3f} | "
            f"{result.passed}/{len(result.cases)} | {m['p50_latency_ms']}ms |"
        )

    lines += [
        "",
        "## By query class",
        "",
        "This is the interesting table. The headline average hides *where* each retriever earns its place.",
        "",
        "| Strategy | lexical MRR | semantic MRR | mixed MRR |",
        "| --- | --- | --- | --- |",
    ]
    for name, result in results.items():
        by_class = result.metrics["by_class"]
        lines.append(
            f"| `{name}` | {by_class.get('lexical', {}).get('mrr', 0):.3f} | "
            f"{by_class.get('semantic', {}).get('mrr', 0):.3f} | "
            f"{by_class.get('mixed', {}).get('mrr', 0):.3f} |"
        )

    lines += [
        "",
        "## Per-case detail",
        "",
        "| Case | Class | Query | " + " | ".join(f"`{s}` rank" for s in results) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in results) + " |",
    ]
    first = next(iter(results.values()))
    for index, case in enumerate(first.cases):
        ranks = []
        for result in results.values():
            rank = result.cases[index].metrics.get("primary_rank")
            ranks.append(str(rank) if rank else "—")
        query = case.detail["query"]
        lines.append(
            f"| {case.case_id} | {case.detail['class']} | {query[:52]} | "
            + " | ".join(ranks)
            + " |"
        )

    lines += [
        "",
        f"## Decision: `{best.variant}`",
        "",
        (
            f"Selected on primary-in-top-5 ({best.passed}/{len(best.cases)}) then MRR "
            f"({best.metrics['mrr']:.3f}) — the two things a traveller feels: did the right source "
            "appear at all, and how far down. `—` in the table above means the primary source was not "
            "retrieved in the top 8."
        ),
    ]

    # Say when the leaders are within noise, rather than letting a fourth-decimal
    # difference look like a decision.
    ranked = sorted(results.values(), key=lambda r: -r.metrics["ndcg@8"])
    if len(ranked) > 1 and abs(ranked[0].metrics["ndcg@8"] - ranked[1].metrics["ndcg@8"]) < 0.01:
        lines += [
            "",
            (
                f"`{ranked[0].variant}` and `{ranked[1].variant}` are **tied on NDCG@8** "
                f"({ranked[0].metrics['ndcg@8']:.4f} vs {ranked[1].metrics['ndcg@8']:.4f}) — a gap far "
                "inside the noise of a 20-case set. The tie is broken on MRR, which is a real "
                "difference, not on the fourth decimal of NDCG."
            ),
        ]

    lines += [
        "",
        (
            "Read the per-class table before generalising from the headline: the retrievers fail on "
            "different queries, which is the argument for fusing them rather than picking one."
        ),
    ]

    # State plainly whether reranking earns its place, rather than assuming it does.
    hybrid = results.get("hybrid")
    reranked = results.get("hybrid_rerank")
    if hybrid and reranked:
        delta_ndcg = reranked.metrics["ndcg@8"] - hybrid.metrics["ndcg@8"]
        delta_pass = reranked.passed - hybrid.passed
        lines += [
            "",
            "### Does reranking earn its place?",
            "",
            "| | NDCG@8 | MRR | Primary in top-5 | p50 |",
            "| --- | --- | --- | --- | --- |",
            (
                f"| `hybrid` | {hybrid.metrics['ndcg@8']:.3f} | {hybrid.metrics['mrr']:.3f} | "
                f"{hybrid.passed}/{len(hybrid.cases)} | {hybrid.metrics['p50_latency_ms']}ms |"
            ),
            (
                f"| `hybrid_rerank` | {reranked.metrics['ndcg@8']:.3f} | {reranked.metrics['mrr']:.3f} | "
                f"{reranked.passed}/{len(reranked.cases)} | {reranked.metrics['p50_latency_ms']}ms |"
            ),
            "",
        ]
        if delta_ndcg > 0.01 or delta_pass > 0:
            lines.append(
                f"**Yes** — reranking improves NDCG@8 by {delta_ndcg:+.3f} and primary-in-top-5 by "
                f"{delta_pass:+d}. It is the production default."
            )
        else:
            lines.append(
                f"**No, not on this corpus.** Reranking moves NDCG@8 by {delta_ndcg:+.3f} and "
                f"primary-in-top-5 by {delta_pass:+d}, in exchange for extra latency and, in its LLM "
                "form, a model call. It stays implemented and configurable "
                "(`RETRIEVAL_STRATEGY=hybrid_rerank`) but is **not** the default. Reranking earns its "
                f"place by adding precision over a large candidate set; {len(hybrid.cases)} queries "
                "over a few dozen chunks is not that. Re-evaluate as the corpus grows."
            )

    lines += [
        "",
        "### Caveat on corpus size",
        "",
        (
            "These numbers come from a small, hand-authored corpus whose vocabulary overlaps the golden "
            "queries more than a scraped corpus would, which flatters lexical search. The ranking of "
            "strategies should be re-measured after switching to a real embedding provider and as the "
            "corpus grows — both are called out in docs/deployment.md."
        ),
        "",
        "Reproduce with:",
        "",
        "```bash",
        "python -m evals.run retrieval      # the four-way comparison",
        "python -m evals.runners.sweep      # rrf_k, dense weight, reranker weights",
        "```",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    results = asyncio.run(run())
    from evals.runners.common import ROOT

    path = ROOT / "docs" / "evals" / "retrieval-comparison.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_comparison_markdown(results), encoding="utf-8")
    print(f"\nwrote {path.relative_to(ROOT)}", file=sys.stderr)
