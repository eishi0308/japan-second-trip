#!/usr/bin/env python
"""Eval CLI.

    python -m evals.run all         # every suite (nightly / pre-release)
    python -m evals.run ci          # the fast subset CI runs on every PR
    python -m evals.run retrieval   # one suite
    python -m evals.run sweep       # retrieval hyper-parameter sweep

CI runs a subset on purpose: the full suite is for nightly and release gates.
Making every PR pay for the whole thing trains people to skip it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# The repo root has to be importable before the runners are imported, so these
# imports are deliberately not at the top of the file.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ruff: noqa: E402

from evals.runners import (
    agent,
    production,
    rag,
    retrieval,
    security,
    sweep,
    tool,
)
from evals.runners.common import write_json

#: Suites that must be green for a PR to merge. Fast, deterministic, no network.
CI_SUITES = ["retrieval", "tool", "security", "rag"]
ALL_SUITES = ["retrieval", "tool", "security", "rag", "agent", "production"]


async def _run_suite(name: str, *, persist: bool) -> dict:
    print(f"\n[{name}]")
    if name == "retrieval":
        results = await retrieval.run(persist=persist)
        path = ROOT / "docs" / "evals" / "retrieval-comparison.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(retrieval.build_comparison_markdown(results), encoding="utf-8")
        print(f"  report: {path.relative_to(ROOT)}")
        # Same rule as the report: primary-in-top-5, then MRR.
        best = max(results.values(), key=lambda r: (r.passed, r.metrics["mrr"]))
        return {
            "suite": "retrieval",
            "passed": best.passed,
            "total": len(best.cases),
            "metrics": {k: v.metrics for k, v in results.items()},
            "ok": best.metrics["ndcg@8"] >= 0.60,
        }
    module = {
        "tool": tool,
        "security": security,
        "rag": rag,
        "agent": agent,
        "production": production,
    }[name]
    result = await module.run(persist=persist)
    return {
        "suite": name,
        "passed": result.passed,
        "total": len(result.cases),
        "metrics": result.metrics,
        "ok": result.failed == 0,
    }


async def main(target: str, *, persist: bool) -> int:
    suites = {"all": ALL_SUITES, "ci": CI_SUITES}.get(target, [target])
    if target == "sweep":
        await sweep.run()
        return 0
    if suites != ALL_SUITES and suites != CI_SUITES and suites[0] not in ALL_SUITES:
        print(f"unknown suite '{target}'. Choose from: {', '.join(ALL_SUITES)}, ci, all, sweep")
        return 2

    summaries = []
    for name in suites:
        summaries.append(await _run_suite(name, persist=persist))

    write_json("summary.json", summaries)
    print("\n" + "=" * 66)
    failed = [s for s in summaries if not s["ok"]]
    for summary in summaries:
        status = "PASS" if summary["ok"] else "FAIL"
        print(f"  {status}  {summary['suite']:12} {summary['passed']}/{summary['total']}")
    print("=" * 66)
    if failed:
        print(f"\n{len(failed)} suite(s) failed: {', '.join(s['suite'] for s in failed)}")
        return 1
    print("\nAll suites passed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Japan Second Trip evals")
    parser.add_argument("target", nargs="?", default="ci", help="all | ci | sweep | <suite>")
    parser.add_argument("--no-persist", action="store_true", help="do not write eval_runs rows")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.target, persist=not args.no_persist)))
