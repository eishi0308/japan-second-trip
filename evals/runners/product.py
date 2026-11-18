"""Product evals: the promises PRODUCT_AMENDMENTS.md makes to a traveller.

Four properties, each checked mechanically on every case:

* **Option diversity.** Three options, three different characters (Classic /
  Unexpected / Slow-paced), and no place shared between two options.
* **Rejection correctness.** An area under "Not for this trip" really has no
  option in it, gives a reason, and its "if you change X" note is honest:
  apply X to the request and plan again, and the area must become an option
  when the note says the area "becomes" an option, and at least stop being
  ruled out when it only says the area "fits too".
* **Pinned-stop preservation.** A must-include place is pinned in every option,
  and no fix anywhere (options or RouteCheck) removes a pinned stop.
* **No uncited operational facts.** Every warning built on a fragile fact names
  that fact and its dated source; a fact that is being checked never shows its
  conflicting values; every booking deadline comes with dated evidence.

Every case goes through the real API on the real seeded catalogue. The suite
seeds its own throwaway SQLite database, so it needs no database server and
gives the same answer on every machine (the planner is deterministic).
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from evals.runners.common import (
    CaseResult,
    SuiteResult,
    Timer,
    git_sha,
    load_dataset,
    mean,
    write_json,
)

CHARACTERS = ["Classic", "Unexpected", "Slow-paced"]
CLOCK = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")


# ---------------------------------------------------------------------------
# the app, on a throwaway seeded database
# ---------------------------------------------------------------------------
class App:
    def __init__(self) -> None:
        self.client: Any = None
        self.session_factory: Any = None
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._engine: Any = None

    async def __aenter__(self) -> App:
        url = os.environ.get("PRODUCT_EVAL_DATABASE_URL")
        if not url:
            self._tmp = tempfile.TemporaryDirectory(prefix="jst-product-eval-")
            url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'product.db'}"
        os.environ.setdefault("LOG_LEVEL", "ERROR")
        os.environ.setdefault("ADMIN_TOKEN", "product-eval-admin")

        from httpx import ASGITransport, AsyncClient
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from jst_api.core.config import get_settings
        from jst_api.db import base as db_base
        from jst_api.db import models  # noqa: F401
        from jst_api.knowledge.embeddings import ProviderEmbeddings
        from jst_api.main import create_app
        from jst_api.providers.embeddings import DemoEmbeddingProvider
        from jst_api.providers.registry import build_demo_registry
        from jst_api.security.ratelimit import RateLimiter
        from jst_api.seed.loader import seed_all
        from jst_api.services.analysis_service import AnalysisService
        from jst_api.services.mcp_backend import JstTravelBackend

        settings = get_settings().model_copy(update={"database_url": url})
        self._engine = db_base.build_engine(settings)
        async with self._engine.begin() as conn:
            await conn.run_sync(db_base.Base.metadata.drop_all)
            await conn.run_sync(db_base.Base.metadata.create_all)
        factory = async_sessionmaker(self._engine, expire_on_commit=False, class_=AsyncSession)
        self.session_factory = factory
        async with factory() as session:
            embeddings = ProviderEmbeddings(DemoEmbeddingProvider(dim=settings.embedding_dim))
            await seed_all(session, embeddings, settings)
            await session.commit()

        registry = build_demo_registry(factory, settings)
        app = create_app(settings)

        async def _no_lifespan(_app: Any) -> Any:
            class _Ctx:
                async def __aenter__(self) -> None:
                    return None

                async def __aexit__(self, *_: object) -> bool:
                    return False

            return _Ctx()

        app.router.lifespan_context = _no_lifespan  # type: ignore[assignment]
        app.state.session_factory = factory
        app.state.registry = registry
        app.state.backend = JstTravelBackend(factory, registry, settings)
        app.state.analysis_service = AnalysisService(factory, registry, settings)
        app.state.rate_limiter = RateLimiter(limit=100_000)

        async def _session() -> Any:
            async with factory() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[db_base.get_session] = _session
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://eval")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()
        await self._engine.dispose()
        if self._tmp:
            self._tmp.cleanup()

    async def plan(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post("/api/v1/plans", json={**body, "save": False})
        if response.status_code != 200:
            raise RuntimeError(f"/plans {response.status_code}: {response.text[:300]}")
        return response.json()

    async def check(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post("/api/v1/checks", json=body)
        if response.status_code != 200:
            raise RuntimeError(f"/checks {response.status_code}: {response.text[:300]}")
        return response.json()

    async def conflicting_values(self) -> dict[str, list[str]]:
        from sqlalchemy import select

        from jst_api.db.models import FragileLink

        async with self.session_factory() as session:
            links = (await session.scalars(select(FragileLink))).all()
            return {
                link.id: [str(v) for v in link.conflicting_values or []]
                for link in links
                if link.conflicting_values
            }


# ---------------------------------------------------------------------------
# the four properties
# ---------------------------------------------------------------------------
def option_sets(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every option set a plan response carries (one, or one per season/length)."""
    sets = [plan["result"]] if plan.get("result") else []
    sets += [s["result"] for s in plan.get("seasons", [])]
    sets += [n["result"] for n in plan.get("nights_options", [])]
    return sets


def diversity(options: list[dict[str, Any]]) -> tuple[list[str], float]:
    problems = []
    labels = [o["character_label"] for o in options]
    if len(options) == 3 and labels != CHARACTERS:
        problems.append(f"characters {labels}, expected {CHARACTERS}")
    if len(set(labels)) != len(labels):
        problems.append(f"repeated character in {labels}")
    stops = [{s["slug"] for s in o["stops"] if not s["pinned"]} for o in options]
    worst = 0.0
    for i in range(len(stops)):
        for j in range(i + 1, len(stops)):
            union = stops[i] | stops[j]
            overlap = len(stops[i] & stops[j]) / len(union) if union else 0.0
            worst = max(worst, overlap)
            if overlap:
                problems.append(f"{labels[i]} and {labels[j]} share {sorted(stops[i] & stops[j])}")
    return problems, worst


def rejection_shape(result: dict[str, Any]) -> list[str]:
    problems = []
    option_areas = {s["area"] for o in result["options"] for s in o["stops"]}
    for r in result["not_for_this_trip"]:
        if r["area"] in option_areas:
            problems.append(f"{r['area']} is ruled out but appears in an option")
        if not r["reason"].strip():
            problems.append(f"{r['area']} is ruled out without a reason")
    return problems


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def apply_change(request: dict[str, Any], note: str) -> dict[str, Any] | None:
    """Turn an "if you change X" sentence back into the request it promises."""
    if m := re.match(r"If you can fly out of (.+?), ", note):
        return {**request, "departure_city": m.group(1)}
    if m := re.match(r"If you fly into and out of (.+?), ", note):
        return {**request, "arrival_city": m.group(1), "departure_city": m.group(1)}
    if m := re.match(r"With (\d+) regional nights, ", note):
        return {**request, "regional_nights": int(m.group(1))}
    if note.startswith("If you can drive, "):
        return {**request, "transport": "can_drive"}
    if m := re.match(r"In (.+?), ", note):
        first = re.match(r"([A-Z][a-z]+)", m.group(1))
        if first and first.group(1) in MONTHS:
            out = {**request, "month": MONTHS.index(first.group(1)) + 1}
            out.pop("start_date", None)
            return out
    return None


def pins_kept(check: dict[str, Any]) -> list[str]:
    pinned = {s["slug"] or s["name"] for s in check["stops"] if s["pinned"]}
    problems = []
    for issue in check["issues"]:
        for fix in issue["fixes"]:
            kept = {s["slug"] or s["name"] for s in fix["stops"] if s["pinned"]}
            if missing := pinned - kept:
                problems.append(f"fix '{fix['label']}' drops pinned {sorted(missing)}")
    return problems


def citations(check: dict[str, Any], conflicts: dict[str, list[str]]) -> tuple[list[str], int]:
    """Returns (problems, number of operational claims inspected)."""
    problems = []
    claims = 0
    for issue in check["issues"]:
        if issue["severity"] == "info" or issue["kind"] == "not_in_database":
            continue
        claims += 1
        if not issue["evidence"]:
            problems.append(f"'{issue['title']}' has no evidence")
            continue
        for ev in issue["evidence"]:
            if not ev["source_id"]:
                problems.append(f"'{issue['title']}' cites evidence without a source")
            if ev["fact_state"] in ("verified", "stale") and not ev["verified_at"]:
                problems.append(f"'{issue['title']}' cites {ev['fact_state']} evidence undated")
        if issue["fact_id"] is None and issue["kind"] in (
            "last_connection",
            "ryokan_shuttle",
            "weekly_closure",
            "booking_difficulty",
        ):
            problems.append(f"fragile issue '{issue['title']}' does not name its fact")
        if issue["needs_review"] and issue["fact_id"] in conflicts:
            text = f"{issue['title']} {issue['why']}"
            leaked = [v for v in conflicts[issue["fact_id"]] if v in text]
            if leaked:
                problems.append(f"'{issue['title']}' asserts conflicting value(s) {leaked}")
        elif (
            CLOCK.search(issue["why"])
            and issue["fact_id"]
            and not any(ev["verified_at"] for ev in issue["evidence"])
        ):
            problems.append(f"'{issue['title']}' states a time with no dated source")
    for item in check["booking"]:
        claims += 1
        if not (item["evidence"]["source_id"] and item["evidence"]["verified_at"]):
            problems.append(f"booking '{item['text']}' has no dated evidence")
    return problems, claims


def hard_item_citations(option: dict[str, Any]) -> tuple[list[str], int]:
    problems, claims = [], 0
    for item in option["whats_hard"]:
        if item["fact_state"] is None:
            continue  # derived from the trip itself (hotel changes, moving time)
        claims += 1
        if item["fact_state"] == "unverified":
            # "No verified info yet" asserts nothing, so it needs no source; it must
            # not slip in an operational time either.
            if CLOCK.search(item["text"]):
                problems.append(f"'{item['text']}' states a time from an unverified fact")
            continue
        if not item["source_id"]:
            problems.append(f"'{item['text']}' has a fact state but no source")
        if item["fact_state"] in ("verified", "stale") and not item["verified_at"]:
            problems.append(f"'{item['text']}' is {item['fact_state']} but undated")
    return problems, claims


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------
async def run(*, persist: bool = True, quiet: bool = False) -> SuiteResult:
    del persist  # the suite's database is throwaway; the JSON report is the record
    dataset = load_dataset("product_v1.json")
    thresholds = dataset["thresholds"]
    result = SuiteResult(
        suite="product",
        dataset=dataset["name"],
        dataset_version=dataset["version"],
        git_sha=git_sha(),
    )
    tally: dict[str, list[float]] = {
        "diversity": [],
        "rejection_shape": [],
        "counterfactual_honoured": [],
        "counterfactual_in_options": [],
        "pins_kept": [],
        "cited": [],
    }
    claims_inspected = 0

    with Timer() as timer:
        async with App() as app:
            conflicts = await app.conflicting_values()

            for case in dataset["plans"]:
                failures: list[str] = []
                detail: dict[str, Any] = {}
                expect = case.get("expect", {})
                try:
                    body = await app.plan(case["request"])
                except RuntimeError as exc:
                    result.cases.append(CaseResult(f"plan:{case['id']}", False, failure=str(exc)))
                    continue
                plan = body["plan"]
                if expect.get("kind") and plan["kind"] != expect["kind"]:
                    failures.append(f"kind {plan['kind']}, expected {expect['kind']}")
                labels = [a["label"] for a in plan["assumptions"]]
                for label in expect.get("assumption_labels", []):
                    if label not in labels:
                        failures.append(f"missing assumption '{label}' (got {labels})")

                sets = option_sets(plan)
                if not any(s["options"] for s in sets):
                    failures.append("no options at all")
                worst_overlap = 0.0
                counterfactuals: list[dict[str, Any]] = []
                for s in sets:
                    if not s["options"]:
                        continue
                    div, overlap = diversity(s["options"])
                    worst_overlap = max(worst_overlap, overlap)
                    tally["diversity"].append(0.0 if div else 1.0)
                    failures += [f"[diversity m{s['month']}] {p}" for p in div]

                    shape = rejection_shape(s)
                    tally["rejection_shape"].append(0.0 if shape else 1.0)
                    failures += [f"[rejection m{s['month']}] {p}" for p in shape]

                    for option in s["options"]:
                        pinned = {st["slug"] for st in option["stops"] if st["pinned"]}
                        for slug in expect.get("pinned_in_every_option", []):
                            if slug not in pinned:
                                failures.append(f"[pins] {option['title']} lacks pinned {slug}")
                        if option.get("check"):
                            kept = pins_kept(option["check"])
                            tally["pins_kept"].append(0.0 if kept else 1.0)
                            failures += [f"[pins] {option['title']}: {p}" for p in kept]
                            cited, n = citations(option["check"], conflicts)
                            hard, m = hard_item_citations(option)
                            claims_inspected += n + m
                            tally["cited"].append(0.0 if cited or hard else 1.0)
                            failures += [f"[cited] {option['title']}: {p}" for p in cited + hard]

                if plan["kind"] == "options" and plan["result"]:
                    s = plan["result"]
                    rejected = {r["area"] for r in s["not_for_this_trip"]}
                    for area in expect.get("rejected_areas", []):
                        if area not in rejected:
                            failures.append(f"[rejection] expected {area} under Not for this trip")
                    areas = {st["area"] for o in s["options"] for st in o["stops"]}
                    for area in expect.get("option_areas", []):
                        if area not in areas:
                            failures.append(f"expected an option in {area} (got {sorted(areas)})")

                    # Counterfactuals: apply the change and plan again.
                    for r in s["not_for_this_trip"]:
                        note = r.get("if_you_change")
                        if not note:
                            continue
                        changed = apply_change(case["request"], note)
                        if changed is None:
                            counterfactuals.append({"area": r["area"], "note": note, "ok": False})
                            failures.append(f"[counterfactual] cannot apply '{note}'")
                            tally["counterfactual_honoured"].append(0.0)
                            continue
                        again = (await app.plan(changed))["plan"]["result"]
                        now_areas = {st["area"] for o in again["options"] for st in o["stops"]}
                        still = {x["area"]: x["reason"] for x in again["not_for_this_trip"]}
                        in_options = r["area"] in now_areas
                        if " becomes a " in note:
                            # A promise that the area becomes an option: it must be one.
                            honoured = in_options
                        else:
                            honoured = in_options or still.get(r["area"]) != r["reason"]
                        tally["counterfactual_honoured"].append(1.0 if honoured else 0.0)
                        tally["counterfactual_in_options"].append(1.0 if in_options else 0.0)
                        counterfactuals.append(
                            {
                                "area": r["area"],
                                "note": note,
                                "in_options": in_options,
                                "ok": honoured,
                            }
                        )
                        if not honoured:
                            failures.append(
                                f"[counterfactual] '{note}' did not change {r['area']}: "
                                f"still '{still.get(r['area'])}'"
                            )
                detail.update(
                    kind=plan["kind"],
                    worst_overlap=worst_overlap,
                    counterfactuals=counterfactuals,
                )
                if worst_overlap > thresholds["max_stop_overlap"]:
                    failures.append(f"stop overlap {worst_overlap:.2f}")
                result.cases.append(
                    CaseResult(
                        f"plan:{case['id']}",
                        not failures,
                        score=0.0 if failures else 1.0,
                        detail=detail,
                        failure="; ".join(failures) or None,
                    )
                )

            for case in dataset["checks"]:
                failures = []
                expect = case.get("expect", {})
                try:
                    check = (await app.check(case["request"]))["check"]
                except RuntimeError as exc:
                    result.cases.append(CaseResult(f"check:{case['id']}", False, failure=str(exc)))
                    continue
                kept = pins_kept(check)
                tally["pins_kept"].append(0.0 if kept else 1.0)
                failures += [f"[pins] {p}" for p in kept]
                cited, n = citations(check, conflicts)
                claims_inspected += n
                tally["cited"].append(0.0 if cited else 1.0)
                failures += [f"[cited] {p}" for p in cited]
                fixes = sum(len(i["fixes"]) for i in check["issues"])
                if fixes < expect.get("min_fixes", 0):
                    failures.append(f"{fixes} fixes, expected at least {expect['min_fixes']}")
                kinds = {i["kind"] for i in check["issues"]}
                for kind in expect.get("issue_kinds", []):
                    if kind not in kinds:
                        failures.append(f"expected a {kind} issue (got {sorted(kinds)})")
                # Every pinned stop the traveller asked for is still in the trip.
                asked = {s["name"] for s in case["request"]["stops"] if s.get("pinned")}
                shown = {s["name"] for s in check["stops"] if s["pinned"]}
                if asked - shown:
                    failures.append(f"pinned {sorted(asked - shown)} missing from the check")
                result.cases.append(
                    CaseResult(
                        f"check:{case['id']}",
                        not failures,
                        score=0.0 if failures else 1.0,
                        detail={"verdict": check["verdict"], "fixes": fixes},
                        failure="; ".join(failures) or None,
                    )
                )

    honoured = mean(tally["counterfactual_honoured"]) if tally["counterfactual_honoured"] else 1.0
    if honoured < thresholds["min_counterfactual_honoured"]:
        result.cases.append(
            CaseResult(
                "aggregate:counterfactual_honoured",
                False,
                failure=f"{honoured:.2f} < {thresholds['min_counterfactual_honoured']}",
            )
        )
    result.metrics = {
        "option_diversity": mean(tally["diversity"]),
        "rejection_correctness": mean(tally["rejection_shape"]),
        "counterfactual_honoured": honoured,
        "counterfactual_in_options": mean(tally["counterfactual_in_options"]),
        "counterfactuals_tested": len(tally["counterfactual_honoured"]),
        "pinned_stop_preservation": mean(tally["pins_kept"]),
        "cited_operational_facts": mean(tally["cited"]),
        "operational_claims_inspected": claims_inspected,
    }
    result.duration_ms = timer.ms
    write_json("product.json", result.to_dict())
    if not quiet:
        for case in result.cases:
            mark = "PASS" if case.passed else "FAIL"
            print(f"  {mark}  {case.case_id}" + (f"  — {case.failure}" if case.failure else ""))
        for key, value in result.metrics.items():
            print(f"  {key:30} {value}")
    return result
