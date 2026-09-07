"""Process-local latency, cost and reliability counters.

Deliberately simple: an in-process reservoir with percentile calculation, plus
counters. It backs ``GET /api/v1/admin/metrics`` and the production-eval numbers
without requiring a metrics backend to be stood up. In a real deployment these
same values are exported over OTLP; this is the always-available floor.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

MAX_SAMPLES = 2000


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round((p / 100.0) * (len(ordered) - 1))))
    return round(ordered[index], 2)


@dataclass
class MetricsRegistry:
    _latencies: dict[str, deque[float]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
    )
    _counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _costs: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_SAMPLES))
    _tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe_latency(self, name: str, ms: float) -> None:
        with self._lock:
            self._latencies[name].append(float(ms))

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe_cost(self, usd: float) -> None:
        with self._lock:
            self._costs.append(float(usd))

    def add_tokens(self, prompt: int, completion: int) -> None:
        with self._lock:
            self._tokens["prompt"] += prompt
            self._tokens["completion"] += completion

    def record_run(self, summary: dict[str, Any]) -> None:
        self.observe_latency(
            f"graph.{summary.get('graph', 'unknown')}", summary.get("latency_ms", 0)
        )
        self.observe_cost(summary.get("estimated_cost_usd", 0.0))
        self.add_tokens(summary.get("prompt_tokens", 0), summary.get("completion_tokens", 0))
        self.increment("runs.total")
        if summary.get("error"):
            self.increment("runs.failed")
        self.increment("tool_calls.total", summary.get("tool_calls", 0))
        self.increment("tool_calls.failed", summary.get("failed_tool_calls", 0))
        self.increment("tool_calls.cache_hits", summary.get("cache_hits", 0))
        self.increment("retries.total", summary.get("retries", 0))
        self.increment("fallbacks.total", len(summary.get("fallbacks", [])))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies = {
                name: {
                    "count": len(samples),
                    "p50_ms": percentile(list(samples), 50),
                    "p95_ms": percentile(list(samples), 95),
                    "p99_ms": percentile(list(samples), 99),
                }
                for name, samples in self._latencies.items()
            }
            costs = list(self._costs)
            counters = dict(self._counters)
            tokens = dict(self._tokens)

        total_runs = counters.get("runs.total", 0)
        total_tools = counters.get("tool_calls.total", 0)
        return {
            "latency": latencies,
            "counters": counters,
            "tokens": tokens,
            "cost": {
                "total_usd": round(sum(costs), 6),
                "mean_usd_per_run": round(sum(costs) / len(costs), 6) if costs else 0.0,
                "p95_usd": percentile(costs, 95),
            },
            "rates": {
                "run_failure_rate": round(counters.get("runs.failed", 0) / total_runs, 4)
                if total_runs
                else 0.0,
                "tool_failure_rate": round(counters.get("tool_calls.failed", 0) / total_tools, 4)
                if total_tools
                else 0.0,
                "tool_cache_hit_rate": round(
                    counters.get("tool_calls.cache_hits", 0) / total_tools, 4
                )
                if total_tools
                else 0.0,
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._latencies.clear()
            self._counters.clear()
            self._costs.clear()
            self._tokens.clear()


METRICS = MetricsRegistry()
