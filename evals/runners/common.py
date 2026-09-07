"""Shared eval infrastructure: metrics, harness bootstrap and result shapes.

Design rules for this package:

* **Deterministic first.** Anything that can be checked mechanically (citation
  validity, schema validity, which rule fired, which node executed) is checked
  mechanically. LLM-as-judge is reserved for genuinely qualitative dimensions,
  and when used, the judge model and prompt version are recorded with the score
  so a judge change is never mistaken for a system change.
* **Reproducible.** Every suite runs against the demo provider registry by
  default, so results do not depend on which credentials happen to be present.
* **Comparable.** Results are persisted to ``eval_runs`` with a git SHA and the
  prompt versions in force, so a regression can be attributed.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "evals" / "datasets"
REPORTS = ROOT / "evals" / "reports"
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))


# ---------------------------------------------------------------------------
# Information-retrieval metrics
# ---------------------------------------------------------------------------
def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = len(set(retrieved[:k]) & relevant)
    return hits / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    window = retrieved[:k]
    if not window:
        return 0.0
    return len(set(window) & relevant) / len(window)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for index, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(
    retrieved: list[str], relevant: set[str], k: int, *, primary: str | None = None
) -> float:
    """Binary-gain NDCG, with the designated primary source weighted 2.

    Graded relevance matters here: several sources can be *relevant* to
    "which places need a car", but exactly one is the passage a traveller
    actually needed, and a retriever that buries it below three near-misses is
    worse than the flat metric suggests.
    """

    def gain(item: str) -> float:
        if primary and item == primary:
            return 2.0
        return 1.0 if item in relevant else 0.0

    dcg = sum(gain(item) / math.log2(i + 2) for i, item in enumerate(retrieved[:k]))
    ideal_gains = sorted((gain(r) for r in relevant), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_gains))
    return dcg / idcg if idcg else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100.0) * (len(ordered) - 1))))
    return round(ordered[index], 2)


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


# ---------------------------------------------------------------------------
# result shapes
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    case_id: str
    passed: bool
    score: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    failure: str | None = None


@dataclass
class SuiteResult:
    suite: str
    dataset: str
    dataset_version: str
    variant: str = "default"
    cases: list[CaseResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    git_sha: str | None = None
    prompt_versions: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if not c.passed)

    @property
    def pass_rate(self) -> float:
        return round(self.passed / len(self.cases), 4) if self.cases else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "dataset": self.dataset,
            "dataset_version": self.dataset_version,
            "variant": self.variant,
            "case_count": len(self.cases),
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "metrics": self.metrics,
            "duration_ms": self.duration_ms,
            "git_sha": self.git_sha,
            "prompt_versions": self.prompt_versions,
            "cases": [asdict(c) for c in self.cases],
        }


def git_sha() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return None


def load_dataset(name: str) -> dict[str, Any]:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
@dataclass
class Harness:
    settings: Any
    session_factory: Any
    registry: Any
    embeddings: Any


async def build_harness(*, demo: bool = True) -> Harness:
    """Bootstrap the app's own machinery, forced onto demo providers by default.

    Evals must be reproducible on any machine, including CI where no credentials
    exist. Running them against whatever provider happens to be configured would
    make a green run meaningless.
    """
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://jst:jst@localhost:5433/jst")
    os.environ.setdefault("LOG_LEVEL", "ERROR")

    from jst_api.core.config import get_settings
    from jst_api.core.logging import configure_logging
    from jst_api.db.base import build_engine, get_sessionmaker
    from jst_api.knowledge.embeddings import ProviderEmbeddings
    from jst_api.providers.registry import build_demo_registry, build_registry

    settings = get_settings()
    configure_logging("ERROR", json_output=False)
    build_engine(settings)
    session_factory = get_sessionmaker()
    registry = (build_demo_registry if demo else build_registry)(session_factory, settings)
    return Harness(
        settings=settings,
        session_factory=session_factory,
        registry=registry,
        embeddings=ProviderEmbeddings(registry.embeddings),
    )


async def persist_suite(harness: Harness, result: SuiteResult) -> str | None:
    """Store the run so the admin dashboard can trend it over time."""
    from jst_api.db.models import EvalResult, EvalRun

    try:
        async with harness.session_factory() as session:
            run = EvalRun(
                suite=result.suite,
                dataset=result.dataset,
                dataset_version=result.dataset_version,
                variant=result.variant,
                git_sha=result.git_sha,
                prompt_versions=result.prompt_versions,
                metrics=result.metrics,
                case_count=len(result.cases),
                passed=result.passed,
                failed=result.failed,
                duration_ms=result.duration_ms,
            )
            session.add(run)
            await session.flush()
            for case in result.cases:
                session.add(
                    EvalResult(
                        run_id=run.id,
                        case_key=case.case_id,
                        passed=case.passed,
                        score=case.score,
                        metrics=case.metrics,
                        detail=case.detail,
                    )
                )
            await session.commit()
            return run.id
    except Exception as exc:  # pragma: no cover - eval storage is best-effort
        print(f"  ! could not persist eval run: {exc}", file=sys.stderr)
        return None


def write_report(name: str, content: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / name
    path.write_text(content, encoding="utf-8")
    return path


def write_json(name: str, payload: Any) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / name
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


class Timer:
    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.ms = int((time.perf_counter() - self._t0) * 1000)

    ms: int = 0
