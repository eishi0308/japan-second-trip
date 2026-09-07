"""Agent evaluation: does the whole workflow behave, end to end?

Asserts on the checkable parts of a run rather than on prose:

* **node progression** — did the graph actually execute the nodes it claims?
* **route-issue detection** — did the right rules fire, at the right severity?
* **candidate rejection** — was a region ruled out for a stated constraint?
* **failure recovery** — does an unresolvable stop degrade instead of crashing?
* **human escalation** — does a conflicting fact escalate rather than resolve?
* **state persistence** — is the decision available to the next analysis?
* **loop limits** — does the run stay inside its step and tool budgets?
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
    percentile,
    persist_suite,
    write_json,
)


def _check_where_next(case: dict[str, Any], run: Any) -> list[str]:
    result, trace = run.result, run.trace_summary
    expect = case["expect"]
    failures: list[str] = []

    if "status" in expect and result["status"] != expect["status"]:
        failures.append(f"status={result['status']}, expected {expect['status']}")

    rejected = {r["region_code"] for r in result.get("rejected", [])}
    for code in expect.get("rejected_region_codes", []):
        if code not in rejected:
            failures.append(f"{code} was not rejected (rejected: {sorted(rejected)})")

    if expect.get("recommended_in"):
        recommended = (result.get("recommended") or {}).get("region_code")
        if recommended not in expect["recommended_in"]:
            failures.append(
                f"recommended={recommended}, expected one of {expect['recommended_in']}"
            )

    if len(result.get("citations", [])) < expect.get("min_citations", 0):
        failures.append(f"only {len(result.get('citations', []))} citations")

    if len(result.get("assumptions", [])) < expect.get("min_assumptions", 0):
        failures.append(f"only {len(result.get('assumptions', []))} assumptions declared")

    if len(result.get("missing_information", [])) < expect.get("min_missing_information", 0):
        failures.append(
            f"only {len(result.get('missing_information', []))} missing fields reported"
        )

    for node in expect.get("nodes_include", []):
        if node not in trace["nodes"]:
            failures.append(f"node {node} did not execute")
    return failures


def _check_route_check(case: dict[str, Any], run: Any) -> list[str]:
    result, trace = run.result, run.trace_summary
    expect = case["expect"]
    failures: list[str] = []

    all_issues = result["critical_issues"] + result["warnings"] + result["strengths"]
    fired = {i.get("rule_id") for i in all_issues}
    critical = {i.get("rule_id") for i in result["critical_issues"]}
    strengths = {i.get("rule_id") for i in result["strengths"]}

    if expect.get("health_in") and result["health"] not in expect["health_in"]:
        failures.append(f"health={result['health']}, expected one of {expect['health_in']}")
    for rule in expect.get("rules_fired", []):
        if rule not in fired:
            failures.append(f"rule {rule} did not fire (fired: {sorted(r for r in fired if r)})")
    for rule in expect.get("critical_rules", []):
        if rule not in critical:
            failures.append(f"rule {rule} was not critical")
    for rule in expect.get("strength_rules", []):
        if rule not in strengths:
            failures.append(f"strength {rule} not reported")
    if (
        "max_critical_issues" in expect
        and len(result["critical_issues"]) > expect["max_critical_issues"]
    ):
        failures.append(
            f"{len(result['critical_issues'])} critical issues > {expect['max_critical_issues']}"
        )

    revised = result.get("revised_route")
    for name in expect.get("revision_drops", []):
        if revised is None:
            failures.append(f"no revision offered, expected {name} to be dropped")
        elif name in revised["stops"]:
            failures.append(f"revision kept {name}")

    if expect.get("revision_reduces_transit"):
        before = (result.get("travel_load") or {}).get("total_transit_hours")
        after = ((revised or {}).get("travel_load") or {}).get("total_transit_hours")
        if before is None or after is None or after >= before:
            failures.append(f"revision did not reduce transit ({before}h -> {after}h)")

    if expect.get("human_review_required") and not result["human_review_required"]:
        failures.append("expected escalation to human review")
    if len(result.get("conflicts", [])) < expect.get("min_conflicts", 0):
        failures.append("expected a detected source conflict")
    if len(result.get("unresolved_places", [])) < expect.get("min_unresolved", 0):
        failures.append("expected an unresolved place to be reported")

    for node in expect.get("nodes_include", []):
        if node not in trace["nodes"]:
            failures.append(f"node {node} did not execute")
    return failures


async def ensure_fixtures(harness: Any) -> None:
    """Re-open the seeded source conflict.

    Case A08 asserts that a conflicting operational fact escalates to a human.
    That precondition is destroyed the moment anyone resolves the task through
    the admin UI, so the suite restores it rather than depending on database
    history. An eval that silently passes because a fixture disappeared is worse
    than no eval.
    """
    from sqlalchemy import select

    from jst_api.db.models import HumanReviewTask, VerificationRecord

    async with harness.session_factory() as session:
        task = await session.scalar(
            select(HumanReviewTask).where(HumanReviewTask.reason == "conflicting_sources")
        )
        if task is not None:
            task.status = "open"
            task.resolved_value = None
            task.resolved_by = None
            task.resolved_at = None
            task.resumed = False
            task.analysis_id = None
            task.thread_id = None
        for record in (
            await session.scalars(
                select(VerificationRecord).where(
                    VerificationRecord.verification_method == "human_review"
                )
            )
        ).all():
            await session.delete(record)
        for record in (
            await session.scalars(
                select(VerificationRecord).where(VerificationRecord.status == "superseded")
            )
        ).all():
            record.status = "verified"
        await session.commit()


async def run(*, persist: bool = True, quiet: bool = False) -> SuiteResult:
    from jst_api.prompts.registry import get_prompts
    from jst_api.services.analysis_service import AnalysisService

    harness = await build_harness()
    await ensure_fixtures(harness)
    dataset = load_dataset("agent_v1.json")
    service = AnalysisService(harness.session_factory, harness.registry, harness.settings)
    result = SuiteResult(
        suite="agent",
        dataset=dataset["dataset"],
        dataset_version=dataset["version"],
        git_sha=git_sha(),
        prompt_versions=get_prompts().versions(),
    )
    latencies: list[float] = []
    step_counts: list[float] = []
    tool_counts: list[float] = []
    recoveries = 0
    escalations = 0

    with Timer() as timer:
        for case in dataset["cases"]:
            if case["graph"] == "where_next":
                run_out = await service.run_where_next(case["input"])
                failures = _check_where_next(case, run_out)
            else:
                run_out = await service.run_route_check(case["input"])
                failures = _check_route_check(case, run_out)

            trace = run_out.trace_summary
            latencies.append(trace["latency_ms"])
            step_counts.append(trace["steps"])
            tool_counts.append(trace["tool_calls"])

            # Budgets are a correctness property, not a nicety: an agent that
            # loops is an outage and a bill.
            if trace["steps"] > harness.settings.agent_max_steps:
                failures.append(f"step budget exceeded ({trace['steps']})")
            if trace["tool_calls"] > harness.settings.agent_max_tool_calls:
                failures.append(f"tool budget exceeded ({trace['tool_calls']})")
            if trace.get("error"):
                failures.append(f"run errored: {trace['error']}")

            if run_out.result.get("unresolved_places"):
                recoveries += 1
            if run_out.result.get("human_review_required"):
                escalations += 1

            passed = not failures
            result.cases.append(
                CaseResult(
                    case_id=case["id"],
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    metrics={
                        "latency_ms": trace["latency_ms"],
                        "steps": trace["steps"],
                        "tool_calls": trace["tool_calls"],
                        "failed_tool_calls": trace["failed_tool_calls"],
                        "model_calls": trace["model_calls"],
                        "estimated_cost_usd": trace["estimated_cost_usd"],
                    },
                    detail={
                        "graph": case["graph"],
                        "description": case["description"],
                        "nodes": trace["nodes"],
                    },
                    failure="; ".join(failures) or None,
                )
            )
    result.duration_ms = timer.ms
    result.metrics = {
        "pass_rate": result.pass_rate,
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "mean_steps": mean(step_counts),
        "mean_tool_calls": mean(tool_counts),
        "graceful_recoveries": recoveries,
        "human_escalations": escalations,
        "total_cost_usd": round(sum(c.metrics["estimated_cost_usd"] for c in result.cases), 6),
    }
    if persist:
        await persist_suite(harness, result)
    if not quiet:
        m = result.metrics
        print(
            f"  agent: {result.passed}/{len(result.cases)} passed | p50={m['p50_latency_ms']}ms "
            f"p95={m['p95_latency_ms']}ms steps={m['mean_steps']} tools={m['mean_tool_calls']} "
            f"escalations={m['human_escalations']}"
        )
        for case in result.cases:
            if not case.passed:
                print(f"    FAIL {case.case_id}: {case.failure}")
    write_json("agent.json", result.to_dict())
    return result


if __name__ == "__main__":
    asyncio.run(run())
