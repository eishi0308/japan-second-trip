"""The human review loop for fragile facts (PRODUCT_AMENDMENTS.md §3, M5).

    a check meets a fact that is conflicting or stale-and-critical
        → the traveller sees "Being checked" (feasibility.py)
        → ``ensure_tasks`` opens one review task per fact (deduplicated)
    a reviewer answers in /admin
        → ``resolve`` updates the fact, records who verified it, from what, and when
        → closes the task
        → re-checks every saved trip that includes the place and adds a notice
          saying what changed ("Needs attention → Works")

The reviewer's value is the only way a disputed time becomes a fact. The
model never picks one, and neither does the code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.errors import NotFoundError, ValidationFailedError
from jst_api.core.logging import get_logger
from jst_api.db.models import (
    Destination,
    FragileLink,
    HumanReviewTask,
    SavedTrip,
    Source,
    VerificationRecord,
)
from jst_api.domain.enums import ReviewStatus
from jst_api.domain.fact_state import FactState, fact_state
from jst_api.planner.results import VERDICT_LABELS, CheckResult

log = get_logger(__name__)

TIMED_KINDS = ("last_connection", "ryokan_shuttle")
REASON = "fragile_fact"
_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def subject_of(fact_id: str) -> str:
    return f"fragile:{fact_id}"


async def _open_task(session: AsyncSession, fact_id: str) -> HumanReviewTask | None:
    return await session.scalar(
        select(HumanReviewTask).where(
            HumanReviewTask.subject == subject_of(fact_id),
            HumanReviewTask.status.in_([ReviewStatus.OPEN.value, ReviewStatus.IN_PROGRESS.value]),
        )
    )


async def ensure_tasks(session: AsyncSession, checks: Iterable[CheckResult | None]) -> list[str]:
    """Open a review task for every fact a check flagged, unless one is already open."""
    fact_ids = sorted(
        {
            issue.fact_id
            for check in checks
            if check is not None
            for issue in check.issues
            if issue.needs_review and issue.fact_id
        }
    )
    created: list[str] = []
    for fact_id in fact_ids:
        if await _open_task(session, fact_id) is not None:
            continue
        link = await session.get(FragileLink, fact_id)
        if link is None:
            continue
        destination = await session.scalar(
            select(Destination).where(Destination.slug == link.destination_slug)
        )
        place = destination.name if destination else link.destination_slug
        conflicting = link.status == "conflicting"
        task = HumanReviewTask(
            reason=REASON,
            subject=subject_of(fact_id),
            field_name="last_departure_local" if link.kind in TIMED_KINDS else "detail",
            question=(
                f"{place}: {link.title}. "
                + (
                    "Sources disagree. Which value is right today?"
                    if conflicting
                    else "Last confirmed a while ago. Is it still right?"
                )
            ),
            candidate_values=list(link.conflicting_values or [])
            or ([link.last_departure_local] if link.last_departure_local else []),
            evidence_ids=[],
            priority="high" if link.severity == "critical" else "normal",
        )
        session.add(task)
        await session.flush()
        created.append(task.id)
        log.info("fact_review.task_opened", fact_id=fact_id, task_id=task.id)
    return created


@dataclass
class QueueItem:
    fact_id: str
    destination: str
    destination_slug: str
    kind: str
    title: str
    detail: str
    state: str
    severity: str
    current_value: str | None
    candidate_values: list[str]
    verified_at: str | None
    task_id: str | None
    trips_affected: int


async def _trips_with(session: AsyncSession, slug: str, name: str) -> list[SavedTrip]:
    keys = {slug.lower(), name.lower(), slug.replace("-", " ").lower()}
    trips = (await session.scalars(select(SavedTrip))).all()
    return [
        t
        for t in trips
        if any(
            str(stop.get("name", "")).strip().lower() in keys
            for stop in (t.check_request or {}).get("stops", [])
        )
    ]


async def queue(session: AsyncSession, *, now: datetime | None = None) -> list[QueueItem]:
    """Facts that need a person: being checked first, then stale, then unverified."""
    now = now or datetime.now(UTC)
    order = {FactState.BEING_CHECKED: 0, FactState.STALE: 1, FactState.UNVERIFIED: 2}
    names = {d.slug: d.name for d in (await session.scalars(select(Destination))).all()}
    items: list[tuple[int, int, QueueItem]] = []
    for link in (await session.scalars(select(FragileLink))).all():
        state = fact_state(link.status, link.verified_at, link.freshness_ttl_days, now=now)
        if state is FactState.VERIFIED:
            continue
        task = await _open_task(session, link.id)
        name = names.get(link.destination_slug, link.destination_slug)
        items.append(
            (
                order[state],
                0 if link.severity == "critical" else 1,
                QueueItem(
                    fact_id=link.id,
                    destination=name,
                    destination_slug=link.destination_slug,
                    kind=link.kind,
                    title=link.title,
                    detail=link.detail,
                    state=state.value,
                    severity=link.severity,
                    current_value=None
                    if state is FactState.BEING_CHECKED
                    else link.last_departure_local,
                    candidate_values=list(link.conflicting_values or []),
                    verified_at=link.verified_at.isoformat() if link.verified_at else None,
                    task_id=task.id if task else None,
                    trips_affected=len(await _trips_with(session, link.destination_slug, name)),
                ),
            )
        )
    items.sort(key=lambda x: (x[0], x[1], x[2].destination, x[2].kind))
    return [item for _, _, item in items]


@dataclass
class Resolution:
    fact_id: str
    value: str | None
    verification_id: str
    tasks_closed: int
    trips_updated: list[dict[str, Any]]


async def resolve(
    session: AsyncSession,
    fact_id: str,
    *,
    value: str | None,
    reviewer: str,
    note: str | None = None,
    source_url: str | None = None,
    recheck_trip: Any = None,
) -> Resolution:
    """Record a reviewer's answer and update every saved trip that depends on it.

    ``recheck_trip`` is ``async (session, trip) -> CheckResult``. It is injected so
    this service does not import the API layer's request parsing.
    """
    link = await session.get(FragileLink, fact_id)
    if link is None:
        raise NotFoundError("That fact does not exist.", details={"fact_id": fact_id})
    timed = link.kind in TIMED_KINDS
    if timed:
        value = (value or "").strip() or (
            link.last_departure_local if link.status != "conflicting" else None
        )
        if not value or not _CLOCK.match(value):
            raise ValidationFailedError(
                "Give the confirmed time as HH:MM (for example 17:00).",
                details={"fact_id": fact_id},
            )
    now = datetime.now(UTC)
    destination = await session.scalar(
        select(Destination).where(Destination.slug == link.destination_slug)
    )
    place = destination.name if destination else link.destination_slug

    source = Source(
        url=source_url,
        title=f"Reviewer check: {place}, {link.title}",
        source_type="human_review",
        official_source=False,
        trust_level="primary" if source_url else "secondary",
        place_slug=link.destination_slug,
        verified_at=now,
        verified_by=reviewer,
        freshness_ttl_days=link.freshness_ttl_days,
        is_demo=False,
        notes=note,
    )
    session.add(source)
    await session.flush()

    old_value = link.last_departure_local
    link.status = "verified"
    link.conflicting_values = []
    link.verified_at = now
    link.source_id = source.id
    if timed:
        link.last_departure_local = value

    for row in (
        await session.scalars(
            select(VerificationRecord).where(
                VerificationRecord.subject == subject_of(fact_id),
                VerificationRecord.status == "verified",
            )
        )
    ).all():
        row.status = "superseded"
    record = VerificationRecord(
        subject=subject_of(fact_id),
        field_name="last_departure_local" if timed else "detail",
        value=value or "confirmed",
        source_id=source.id,
        verified_at=now,
        verified_by=reviewer,
        verification_method="human_review",
        confidence=0.98,
        status="verified",
        note=note,
        is_demo=False,
    )
    session.add(record)

    closed = 0
    for task in (
        await session.scalars(
            select(HumanReviewTask).where(
                HumanReviewTask.subject == subject_of(fact_id),
                HumanReviewTask.status.in_(
                    [ReviewStatus.OPEN.value, ReviewStatus.IN_PROGRESS.value]
                ),
            )
        )
    ).all():
        task.status = ReviewStatus.RESOLVED.value
        task.resolved_value = value or "confirmed"
        task.resolution_note = note
        task.resolved_by = reviewer
        task.resolved_at = now
        task.resumed = True
        closed += 1
    await session.flush()

    what = f"{place}: {link.title.lower()} confirmed"
    if timed:
        what += f" as {value}"
        if old_value and old_value != value:
            what += f" (previously {old_value})"
    what += f" on {now:%d %b %Y}"
    updated: list[dict[str, Any]] = []
    if recheck_trip is not None:
        for trip in await _trips_with(session, link.destination_slug, place):
            result: CheckResult = await recheck_trip(session, trip)
            before = trip.last_verdict
            after = result.verdict
            change = (
                f"{VERDICT_LABELS[before]} → {VERDICT_LABELS[after]}"
                if before and before != after
                else f"still {VERDICT_LABELS[after]}"
            )
            notice = {
                "at": now.isoformat(),
                "fact_id": fact_id,
                "text": f"{what}. We re-checked your trip: {change}.",
                "verdict_before": before,
                "verdict_after": after,
                "seen": False,
            }
            trip.notices = [*(trip.notices or []), notice]
            trip.last_verdict = after
            updated.append({"trip_id": trip.id, "verdict_before": before, "verdict_after": after})
        await session.flush()
    log.info("fact_review.resolved", fact_id=fact_id, reviewer=reviewer, trips=len(updated))
    return Resolution(fact_id, value, record.id, closed, updated)
