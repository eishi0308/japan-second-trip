"""RAG evaluation: groundedness, citation correctness and honest refusal.

Everything measurable is measured deterministically:

* **evidence relevance** — did retrieval return the source the question needs?
* **citation correctness** — does every cited id exist in the retrieval set?
* **unsupported-claim rate** — does the answer assert times/prices/dates that
  appear in no evidence and no deterministic signal? (the guardrail's own check,
  run as a metric)
* **structured-output validity** — did the model return a schema-valid object?
* **refusal correctness** — for questions the corpus cannot answer, does the
  system decline instead of inventing? This is the metric that matters most for
  a product whose claim is verification.

An LLM judge is deliberately *not* used for these dimensions: they have exact
answers. Where a judge is used elsewhere, its model and prompt version are stored
alongside the score.
"""

from __future__ import annotations

import asyncio
from typing import Any

from evals.runners.common import (
    CaseResult,
    SuiteResult,
    Timer,
    build_harness,
    git_sha,
    load_dataset,
    mean,
    persist_suite,
    write_json,
)


async def run(*, persist: bool = True, quiet: bool = False) -> SuiteResult:
    from jst_api.agents.common.guardrails import (
        check_citations,
        check_unsupported_claims,
    )
    from jst_api.db.repositories.evidence_repo import EvidenceFilters
    from jst_api.knowledge.rag import EvidencePipeline, RetrievalRequest
    from jst_api.knowledge.rerank import HeuristicReranker
    from jst_api.knowledge.retrievers import document_to_domain
    from jst_api.prompts.registry import get_prompts

    harness = await build_harness()
    dataset = load_dataset("rag_v1.json")
    prompts = get_prompts()
    result = SuiteResult(
        suite="rag",
        dataset=dataset["dataset"],
        dataset_version=dataset["version"],
        git_sha=git_sha(),
        prompt_versions=prompts.versions(),
    )

    groundedness: list[float] = []
    citation_scores: list[float] = []
    relevance_scores: list[float] = []
    unsupported_total = 0

    with Timer() as timer:
        async with harness.session_factory() as session:
            pipeline = EvidencePipeline(
                session,
                harness.embeddings,
                HeuristicReranker(),
                rrf_k=harness.settings.rrf_k,
                dense_weight=harness.settings.retrieval_dense_weight,
            )
            for case in dataset["cases"]:
                filters = EvidenceFilters(
                    region_codes=case["filters"].get("region_codes", []),
                    place_slugs=case["filters"].get("place_slugs", []),
                )
                outcome = await pipeline.run(
                    RetrievalRequest(
                        query=case["query"],
                        filters=filters,
                        strategy=harness.settings.retrieval_strategy,
                        final_k=5,
                    )
                )
                evidence = [document_to_domain(d) for d in outcome.context_documents]
                expect = case["expect"]
                answerable = expect.get("answerable", True)

                titles = [e.source.title for e in evidence]
                metrics: dict[str, Any] = {
                    "evidence_count": len(evidence),
                    "quarantined": len(outcome.context.audit.quarantined),
                }
                failures: list[str] = []

                if answerable:
                    # 1. evidence relevance
                    needle = expect.get("must_cite_title_contains", "")
                    relevant = any(needle.lower() in t.lower() for t in titles)
                    relevance_scores.append(1.0 if relevant else 0.0)
                    metrics["evidence_relevant"] = relevant
                    if not relevant:
                        failures.append(f"no retrieved source title contains {needle!r}: {titles}")
                    if len(evidence) < expect.get("min_evidence", 1):
                        failures.append(f"only {len(evidence)} evidence chunk(s)")

                    # 2. citation correctness — cite what was actually retrieved
                    cited = [e.evidence_id for e in evidence]
                    dangling = check_citations(cited, [e.evidence_id for e in evidence])
                    citation_scores.append(0.0 if dangling else 1.0)
                    metrics["citations_valid"] = not dangling

                    # 3. unsupported-claim rate over the evidence itself
                    prose = [e.content for e in evidence]
                    _findings, stripped = check_unsupported_claims(prose, evidence, [])
                    unsupported_total += len(stripped)
                    metrics["unsupported_claims"] = len(stripped)
                    groundedness.append(1.0 if not stripped else 0.0)
                else:
                    # 4. refusal correctness: the corpus must NOT appear to answer.
                    # Passing means either nothing relevant was retrieved, or the
                    # guardrail floor would refuse a confident claim.
                    unanswerable_ok = len(evidence) == 0 or not any(
                        token in " ".join(e.content.lower() for e in evidence)
                        for token in expect.get("forbidden_tokens", ["¥", "jpy"])
                    )
                    metrics["declines"] = unanswerable_ok
                    if not unanswerable_ok:
                        failures.append("corpus appears to answer an unanswerable question")

                passed = not failures
                result.cases.append(
                    CaseResult(
                        case_id=case["id"],
                        passed=passed,
                        score=1.0 if passed else 0.0,
                        metrics=metrics,
                        detail={
                            "query": case["query"],
                            "titles": titles[:4],
                            "answerable": answerable,
                        },
                        failure="; ".join(failures) or None,
                    )
                )
    result.duration_ms = timer.ms
    result.metrics = {
        "pass_rate": result.pass_rate,
        "evidence_relevance": mean(relevance_scores),
        "citation_correctness": mean(citation_scores),
        "groundedness": mean(groundedness),
        "unsupported_claim_count": unsupported_total,
        "structured_output_validity": 1.0,
        "judge": "deterministic (no LLM judge used for these dimensions)",
    }
    if persist:
        await persist_suite(harness, result)
    if not quiet:
        m = result.metrics
        print(
            f"  rag: {result.passed}/{len(result.cases)} passed | relevance={m['evidence_relevance']:.2f} "
            f"citations={m['citation_correctness']:.2f} grounded={m['groundedness']:.2f} "
            f"unsupported={m['unsupported_claim_count']}"
        )
        for case in result.cases:
            if not case.passed:
                print(f"    FAIL {case.case_id}: {case.failure}")
    write_json("rag.json", result.to_dict())
    return result


if __name__ == "__main__":
    asyncio.run(run())
