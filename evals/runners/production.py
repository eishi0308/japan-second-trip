"""Production-characteristics evaluation.

Latency, token spend, cost, cache effectiveness, retry and fallback behaviour —
measured on a repeatable workload rather than guessed at. These are the numbers
that decide whether the thing can be operated, and they belong in the eval suite
for the same reason correctness does: so a regression is visible.

Costs here are the *demo* provider's (zero). The value of the measurement is the
token counts and the call shape, which is what a live bill scales with.
"""

from __future__ import annotations

import asyncio

from evals.runners.common import (
    CaseResult,
    SuiteResult,
    Timer,
    build_harness,
    git_sha,
    mean,
    percentile,
    persist_suite,
    write_json,
)

WORKLOAD = [
    (
        "where_next",
        {
            "regional_nights": 4,
            "arrival_city": "Tokyo",
            "departure_city": "Tokyo",
            "interests": ["food", "onsen"],
            "driving": "no_car",
            "start_date": "2026-10-12",
        },
    ),
    (
        "where_next",
        {
            "regional_nights": 6,
            "arrival_city": "Osaka",
            "departure_city": "Osaka",
            "interests": ["art", "coast"],
            "driving": "willing",
        },
    ),
    (
        "route_check",
        {
            "itinerary_text": "Tokyo 3 nights, Sendai 2 nights, Aomori 2 nights, then Tokyo",
            "trip_context": {"arrival_city": "Tokyo", "departure_city": "Tokyo"},
        },
    ),
    (
        "route_check",
        {
            "itinerary_text": "Osaka 2 nights, Takamatsu 2 nights, Naoshima 1 night, Matsuyama 2 nights, Osaka",
            "trip_context": {
                "arrival_city": "Osaka",
                "departure_city": "Osaka",
                "driving": "no_car",
            },
        },
    ),
]
REPEATS = 3


async def run(*, persist: bool = True, quiet: bool = False) -> SuiteResult:
    from jst_api.observability.metrics import METRICS
    from jst_api.services.analysis_service import AnalysisService

    harness = await build_harness()
    service = AnalysisService(harness.session_factory, harness.registry, harness.settings)
    result = SuiteResult(
        suite="production",
        dataset="workload",
        dataset_version="1.0.0",
        git_sha=git_sha(),
    )

    latencies: list[float] = []
    prompt_tokens = 0
    completion_tokens = 0
    cost = 0.0
    retries = 0
    fallbacks = 0
    failed_tools = 0

    METRICS.reset()
    with Timer() as timer:
        for repeat in range(REPEATS):
            for index, (kind, payload) in enumerate(WORKLOAD):
                if kind == "where_next":
                    run_out = await service.run_where_next(payload)
                else:
                    run_out = await service.run_route_check(payload)
                trace = run_out.trace_summary
                latencies.append(trace["latency_ms"])
                prompt_tokens += trace["prompt_tokens"]
                completion_tokens += trace["completion_tokens"]
                cost += trace["estimated_cost_usd"]
                retries += trace["retries"]
                fallbacks += len(trace["fallbacks"])
                failed_tools += trace["failed_tool_calls"]
                result.cases.append(
                    CaseResult(
                        case_id=f"W{index + 1}r{repeat + 1}",
                        passed=not trace.get("error"),
                        score=1.0 if not trace.get("error") else 0.0,
                        metrics={
                            "kind": kind,
                            "latency_ms": trace["latency_ms"],
                            "tool_calls": trace["tool_calls"],
                            "model_calls": trace["model_calls"],
                            "prompt_tokens": trace["prompt_tokens"],
                            "completion_tokens": trace["completion_tokens"],
                            "estimated_cost_usd": trace["estimated_cost_usd"],
                            "cache_hits": trace["cache_hits"],
                        },
                        detail={"repeat": repeat + 1},
                        failure=trace.get("error"),
                    )
                )

    result.duration_ms = timer.ms
    snapshot = METRICS.snapshot()
    n = len(result.cases)
    result.metrics = {
        "runs": n,
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "p99_latency_ms": percentile(latencies, 99),
        "mean_latency_ms": mean(latencies),
        "prompt_tokens_total": prompt_tokens,
        "completion_tokens_total": completion_tokens,
        "mean_tokens_per_run": round((prompt_tokens + completion_tokens) / n, 1) if n else 0,
        "estimated_cost_usd_total": round(cost, 6),
        "estimated_cost_usd_per_run": round(cost / n, 6) if n else 0.0,
        "retry_count": retries,
        "fallback_count": fallbacks,
        "failed_tool_calls": failed_tools,
        "failure_rate": round(result.failed / n, 4) if n else 0.0,
        "tool_failure_rate": snapshot["rates"]["tool_failure_rate"],
        "cache_hit_rate": snapshot["rates"]["tool_cache_hit_rate"],
        "note": "Costs are the demo provider's (zero). Token counts are the quantity a live bill scales with.",
    }
    if persist:
        await persist_suite(harness, result)
    if not quiet:
        m = result.metrics
        print(
            f"  production: {result.passed}/{n} runs ok | p50={m['p50_latency_ms']}ms p95={m['p95_latency_ms']}ms "
            f"tokens/run={m['mean_tokens_per_run']} retries={m['retry_count']} fallbacks={m['fallback_count']}"
        )
    write_json("production.json", result.to_dict())
    return result


if __name__ == "__main__":
    asyncio.run(run())
