"""Security regression suite.

Asserts specific defensive properties rather than "nothing crashed":

* injection detection and quarantine on hostile text, and *no* false positive on
  benign text that merely mentions prompts or system messages;
* the seeded canary document — a live injection payload sitting in the corpus —
  is quarantined before it can reach a prompt, even when retrieval surfaces it;
* the ingestion allowlist refuses non-https, unknown domains, lookalike parent
  domains and non-web schemes;
* PII redaction removes emails, phone numbers, cards and passport numbers from
  logs and traces, while leaving structural identifiers intact;
* tool permissions cannot be bypassed by a successful injection, because the
  model never dispatches a tool — a graph node does, from an allowlist.
"""

from __future__ import annotations

import asyncio

from evals.runners.common import (
    CaseResult,
    SuiteResult,
    Timer,
    build_harness,
    git_sha,
    load_dataset,
    persist_suite,
    write_json,
)


async def run(*, persist: bool = True, quiet: bool = False) -> SuiteResult:
    from jst_api.core.logging import redact_text
    from jst_api.security.allowlist import assert_ingestable
    from jst_api.security.injection import neutralise, scan_for_injection

    harness = await build_harness()
    dataset = load_dataset("security_v1.json")
    result = SuiteResult(
        suite="security",
        dataset=dataset["dataset"],
        dataset_version=dataset["version"],
        git_sha=git_sha(),
    )

    with Timer() as timer:
        # -- 1. injection detection -----------------------------------------
        for case in dataset["injection_cases"]:
            scan = scan_for_injection(case["text"])
            failures = []
            if scan.suspicious != case["expect_detected"]:
                failures.append(f"detected={scan.suspicious}, expected {case['expect_detected']}")
            if scan.quarantine != case["expect_quarantine"]:
                failures.append(
                    f"quarantine={scan.quarantine}, expected {case['expect_quarantine']}"
                )
            # Neutralisation must defang the markup without destroying the text.
            cleaned = neutralise(case["text"])
            if "<system>" in cleaned.lower():
                failures.append("system markup survived neutralisation")
            result.cases.append(
                CaseResult(
                    case_id=case["id"],
                    passed=not failures,
                    score=0.0 if failures else 1.0,
                    metrics={"rules": scan.matched_rules, "score": scan.score},
                    detail={"text": case["text"][:120]},
                    failure="; ".join(failures) or None,
                )
            )

        # -- 2. the seeded canary must be quarantined in context assembly ----
        corpus_case = dataset["corpus_case"]
        from jst_api.db.repositories.evidence_repo import EvidenceFilters
        from jst_api.knowledge.rag import EvidencePipeline, RetrievalRequest
        from jst_api.knowledge.rerank import HeuristicReranker

        async with harness.session_factory() as session:
            pipeline = EvidencePipeline(
                session,
                harness.embeddings,
                HeuristicReranker(),
                rrf_k=harness.settings.rrf_k,
                dense_weight=harness.settings.retrieval_dense_weight,
            )
            outcome = await pipeline.run(
                RetrievalRequest(
                    query=corpus_case["query"],
                    filters=EvidenceFilters(),
                    strategy=harness.settings.retrieval_strategy,
                    candidate_k=30,
                    final_k=10,
                )
            )
        retrieved_titles = [d.metadata.get("source_title", "") for d in outcome.documents]
        canary_retrieved = any(
            corpus_case["canary_title_contains"] in title for title in retrieved_titles
        )
        quarantined_ids = {e for e, _ in outcome.context.audit.quarantined}
        canary_ids = {
            d.metadata["evidence_id"]
            for d in outcome.documents
            if corpus_case["canary_title_contains"] in d.metadata.get("source_title", "")
        }
        canary_in_context = bool(canary_ids & set(outcome.context.audit.included_ids))
        # The property that matters: whether or not retrieval surfaces it, the
        # payload must never reach the prompt.
        passed = not canary_in_context
        result.cases.append(
            CaseResult(
                case_id=corpus_case["id"],
                passed=passed,
                score=1.0 if passed else 0.0,
                metrics={
                    "canary_retrieved": canary_retrieved,
                    "quarantined_count": len(quarantined_ids),
                    "canary_in_context": canary_in_context,
                },
                detail={
                    "titles": retrieved_titles[:5],
                    "why": corpus_case["description"],
                },
                failure=None if passed else "injection payload reached the assembled context",
            )
        )

        # -- 3. ingestion allowlist ------------------------------------------
        for case in dataset["allowlist_cases"]:
            allowed = True
            error = None
            try:
                assert_ingestable(
                    case["url"],
                    harness.settings.ingest_domain_allowlist,
                    check_dns=False,
                )
            except Exception as exc:
                allowed = False
                error = str(exc)[:160]
            passed = allowed == case["allowed"]
            result.cases.append(
                CaseResult(
                    case_id=case["id"],
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    metrics={"allowed": allowed},
                    detail={
                        "url": case["url"],
                        "error": error,
                        "why": case.get("reason", ""),
                    },
                    failure=None if passed else f"allowed={allowed}, expected {case['allowed']}",
                )
            )

        # -- 4. PII redaction --------------------------------------------------
        for case in dataset["pii_cases"]:
            redacted = redact_text(case["text"])
            failures = [f"leaked {t!r}" for t in case.get("must_not_contain", []) if t in redacted]
            failures += [
                f"destroyed {t!r}" for t in case.get("must_contain", []) if t not in redacted
            ]
            result.cases.append(
                CaseResult(
                    case_id=case["id"],
                    passed=not failures,
                    score=0.0 if failures else 1.0,
                    metrics={},
                    detail={"redacted": redacted[:160]},
                    failure="; ".join(failures) or None,
                )
            )

        # -- 5. capability control: injection cannot reach a write tool -------
        from jst_api.agents.common.tools import CONSUMER_ALLOWLISTS

        leaks = [
            consumer
            for consumer, tools in CONSUMER_ALLOWLISTS.items()
            if consumer in {"route_check", "admin_assistant"} and "save_trip_decision" in tools
        ]
        result.cases.append(
            CaseResult(
                case_id="S40",
                passed=not leaks,
                score=0.0 if leaks else 1.0,
                metrics={"consumers_with_write": leaks},
                detail={
                    "why": "A successful injection still cannot write: the model never dispatches a tool, "
                    "and consumers that have no reason to write state do not hold the capability."
                },
                failure=f"{leaks} unexpectedly hold a write capability" if leaks else None,
            )
        )

    result.duration_ms = timer.ms
    result.metrics = {
        "pass_rate": result.pass_rate,
        "injection_cases": len(dataset["injection_cases"]),
        "allowlist_cases": len(dataset["allowlist_cases"]),
        "pii_cases": len(dataset["pii_cases"]),
    }
    if persist:
        await persist_suite(harness, result)
    if not quiet:
        print(f"  security: {result.passed}/{len(result.cases)} passed")
        for case in result.cases:
            if not case.passed:
                print(f"    FAIL {case.case_id}: {case.failure}")
    write_json("security.json", result.to_dict())
    return result


if __name__ == "__main__":
    asyncio.run(run())
