"""Tool-layer evaluation.

Measures the things that actually go wrong with tool calling in production:
argument validity, output shape, permission enforcement, failure handling and
recovery. Every call goes through the real MCP session, so a schema regression
in the gateway fails this suite.
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


def _dig(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _check(expect: dict[str, Any], ok: bool, data: dict[str, Any]) -> tuple[bool, str | None]:
    if expect.get("ok") is not None and expect["ok"] != ok:
        return False, f"expected ok={expect['ok']}, got ok={ok}"
    if not ok:
        return True, None

    path = expect.get("path")
    value = _dig(data, path) if path else None

    if "equals" in expect and value != expect["equals"]:
        return False, f"{path}={value!r}, expected {expect['equals']!r}"
    if "in" in expect and value not in expect["in"]:
        return False, f"{path}={value!r} not in {expect['in']}"
    if "min_length" in expect and len(value or []) < expect["min_length"]:
        return False, f"{path} length {len(value or [])} < {expect['min_length']}"
    if "min_value" in expect and (value is None or value < expect["min_value"]):
        return False, f"{path}={value!r} < {expect['min_value']}"
    if "min_options" in expect and len(data.get("options") or []) < expect["min_options"]:
        return (
            False,
            f"options length {len(data.get('options') or [])} < {expect['min_options']}",
        )
    if "min_issues" in expect and len(data.get("issues") or []) < expect["min_issues"]:
        return (
            False,
            f"issues length {len(data.get('issues') or [])} < {expect['min_issues']}",
        )
    if expect.get("has_message") and not data.get("message"):
        return False, "expected an explanatory message"
    return True, None


async def run(*, persist: bool = True, quiet: bool = False) -> SuiteResult:
    from jst_api.agents.common.tools import CONSUMER_ALLOWLISTS, ToolBelt, ToolBudget
    from jst_api.observability.tracing import RunTrace
    from jst_api.services.mcp_backend import JstTravelBackend
    from travel_mcp.session import TravelMcpSession

    harness = await build_harness()
    dataset = load_dataset("tool_v1.json")
    result = SuiteResult(
        suite="tool",
        dataset=dataset["dataset"],
        dataset_version=dataset["version"],
        git_sha=git_sha(),
    )
    backend = JstTravelBackend(harness.session_factory, harness.registry, harness.settings)
    latencies: list[float] = []
    unnecessary_calls = 0

    with Timer() as timer:
        async with TravelMcpSession(backend) as mcp:
            trace = RunTrace(graph_name="tool_eval", thread_id="eval")
            ToolBelt(
                session=mcp,
                consumer="where_next",
                trace=trace,
                budget=ToolBudget(max_calls=200),
            )
            # The eval exercises every tool, so it needs the union of allowlists.
            belt_all = ToolBelt(
                session=mcp,
                consumer="_eval_all",
                trace=trace,
                budget=ToolBudget(max_calls=200),
            )
            CONSUMER_ALLOWLISTS["_eval_all"] = set().union(*CONSUMER_ALLOWLISTS.values())

            # -- functional cases ------------------------------------------
            for case in dataset["cases"]:
                ok = True
                data: dict[str, Any] = {}
                error: str | None = None
                import time as _time

                started = _time.perf_counter()
                try:
                    data = await belt_all.call(case["tool"], case["args"])
                except Exception as exc:
                    ok = False
                    error = str(exc)[:300]
                latencies.append((_time.perf_counter() - started) * 1000)

                passed, failure = _check(case["expect"], ok, data)
                result.cases.append(
                    CaseResult(
                        case_id=case["id"],
                        passed=passed,
                        score=1.0 if passed else 0.0,
                        metrics={"ok": ok, "tool": case["tool"]},
                        detail={
                            "args": case["args"],
                            "error": error,
                            "expect": case["expect"],
                        },
                        failure=failure,
                    )
                )

            # -- permission cases ------------------------------------------
            for case in dataset["permission_cases"]:
                probe = ToolBelt(
                    session=mcp,
                    consumer=case["consumer"],
                    trace=trace,
                    budget=ToolBudget(max_calls=200),
                )
                allowed = probe.can_call(case["tool"])
                passed = allowed == case["allowed"]
                result.cases.append(
                    CaseResult(
                        case_id=case["id"],
                        passed=passed,
                        score=1.0 if passed else 0.0,
                        metrics={"allowed": allowed, "expected": case["allowed"]},
                        detail={
                            "consumer": case["consumer"],
                            "tool": case["tool"],
                            "why": case["reason"],
                        },
                        failure=None
                        if passed
                        else f"{case['consumer']} allowed={allowed}, expected {case['allowed']}",
                    )
                )

            # -- enforcement: a denied tool must raise, not merely return False
            enforcement_ok = False
            denied = ToolBelt(
                session=mcp,
                consumer="route_check",
                trace=trace,
                budget=ToolBudget(max_calls=200),
            )
            try:
                await denied.call(
                    "save_trip_decision",
                    {"trip_id": "x", "decision_kind": "candidate_selected"},
                )
            except Exception as exc:
                enforcement_ok = "not permitted" in str(exc)
            result.cases.append(
                CaseResult(
                    case_id="P10",
                    passed=enforcement_ok,
                    score=1.0 if enforcement_ok else 0.0,
                    metrics={},
                    detail={"why": "a disallowed tool must raise ForbiddenError before dispatch"},
                    failure=None if enforcement_ok else "denied tool did not raise",
                )
            )

            # -- budget: exceeding the tool budget must raise, not loop
            budget_ok = False
            tight = ToolBelt(
                session=mcp,
                consumer="where_next",
                trace=trace,
                budget=ToolBudget(max_calls=2),
            )
            try:
                for _ in range(5):
                    await tight.call("get_place_details", {"query": "Sendai"})
            except Exception as exc:
                budget_ok = "budget" in str(exc).lower()
            result.cases.append(
                CaseResult(
                    case_id="P11",
                    passed=budget_ok,
                    score=1.0 if budget_ok else 0.0,
                    metrics={},
                    detail={"why": "an exhausted tool budget must stop the run, not spin"},
                    failure=None if budget_ok else "budget was not enforced",
                )
            )

            # -- recovery: call_optional must degrade rather than raise
            recovery = await belt_all.call_optional(
                "get_place_details", {"query": "utter nonsense zzzz"}
            )
            recovered = recovery is not None and recovery.get("resolved") is False
            result.cases.append(
                CaseResult(
                    case_id="P12",
                    passed=recovered,
                    score=1.0 if recovered else 0.0,
                    metrics={},
                    detail={
                        "why": "an unresolvable place returns a negative result, never a guess"
                    },
                    failure=None if recovered else "unresolvable place did not degrade cleanly",
                )
            )

            failed_calls = [c for c in trace.tool_calls if not c.ok]
            unnecessary_calls = sum(1 for c in trace.tool_calls if c.cache_hit)

    result.duration_ms = timer.ms
    result.metrics = {
        "pass_rate": result.pass_rate,
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "mean_latency_ms": mean(latencies),
        "failed_tool_calls": len(failed_calls),
        "redundant_calls": unnecessary_calls,
    }
    if persist:
        await persist_suite(harness, result)
    if not quiet:
        print(
            f"  tool: {result.passed}/{len(result.cases)} passed, p50={result.metrics['p50_latency_ms']}ms"
        )
        for case in result.cases:
            if not case.passed:
                print(f"    FAIL {case.case_id}: {case.failure}")
    write_json("tool.json", result.to_dict())
    return result


if __name__ == "__main__":
    asyncio.run(run())
