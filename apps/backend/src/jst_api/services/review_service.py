"""Human-in-the-loop resolution.

When a reviewer answers a task, three things happen:

1. the task is closed with the verified value, the reviewer and the date;
2. a ``VerificationRecord`` is written, which resets the freshness clock for that
   fact and supersedes any earlier record for the same subject and field;
3. the blocked analysis is **resumed** — re-run with the resolved fact injected
   as an authoritative structured input.

Resumption is by re-execution rather than by holding a paused process open.
A reviewer may answer days later, in another process, after a deploy; a durable
resume has to survive all three. The LangGraph ``interrupt()`` path exists too
and is used by the interactive runner and the HITL tests, where the pause and
the answer share a process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.errors import ConflictError, NotFoundError
from jst_api.core.logging import get_logger
from jst_api.db.models import Analysis, HumanReviewTask, VerificationRecord
from jst_api.domain.enums import AnalysisStatus, ReviewStatus
from jst_api.services.analysis_service import AnalysisService

log = get_logger(__name__)


@dataclass
class ResolutionOutcome:
    task_id: str
    status: str
    verification_id: str | None
    resumed_analysis_id: str | None
    resumed: bool
    message: str


class ReviewService:
    def __init__(
        self, session: AsyncSession, analysis_service: AnalysisService | None = None
    ) -> None:
        self._session = session
        self._analysis_service = analysis_service

    async def list_open(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[HumanReviewTask]:
        stmt = select(HumanReviewTask)
        if status:
            stmt = stmt.where(HumanReviewTask.status == status)
        else:
            stmt = stmt.where(
                HumanReviewTask.status.in_(
                    [ReviewStatus.OPEN.value, ReviewStatus.IN_PROGRESS.value]
                )
            )
        stmt = stmt.order_by(
            HumanReviewTask.priority.desc(), HumanReviewTask.created_at.asc()
        ).limit(limit)
        return list((await self._session.scalars(stmt)).all())

    async def get(self, task_id: str) -> HumanReviewTask:
        task = await self._session.get(HumanReviewTask, task_id)
        if task is None:
            raise NotFoundError(f"Review task {task_id} not found", details={"task_id": task_id})
        return task

    async def resolve(
        self,
        task_id: str,
        *,
        resolved_value: str,
        resolution_note: str | None,
        reviewer: str,
        source_url: str | None = None,
        dismiss: bool = False,
    ) -> ResolutionOutcome:
        task = await self.get(task_id)
        if task.status in (ReviewStatus.RESOLVED.value, ReviewStatus.DISMISSED.value):
            raise ConflictError(
                f"Review task {task_id} is already {task.status}", details={"task_id": task_id}
            )

        now = datetime.now(UTC)
        task.status = ReviewStatus.DISMISSED.value if dismiss else ReviewStatus.RESOLVED.value
        task.resolved_value = resolved_value
        task.resolution_note = resolution_note
        task.resolved_by = reviewer
        task.resolved_at = now

        verification_id: str | None = None
        if not dismiss and task.field_name:
            verification_id = await self._record_verification(
                task, resolved_value, reviewer, now, source_url
            )

        # Commit the human decision BEFORE resuming anything. The re-run executes
        # in its own sessions and must observe the task as resolved — otherwise it
        # re-detects the same conflict and escalates again, and the reviewer's
        # work appears to have done nothing.
        await self._session.commit()
        log.info("hitl.resolved", task_id=task_id, dismissed=dismiss, reviewer=reviewer)

        resumed_id, resumed = await self._resume(task, resolved_value, reviewer)
        await self._session.commit()

        return ResolutionOutcome(
            task_id=task_id,
            status=task.status,
            verification_id=verification_id,
            resumed_analysis_id=resumed_id,
            resumed=resumed,
            message=(
                "Resolved and the blocked analysis was re-run with the verified value."
                if resumed
                else "Resolved."
            ),
        )

    async def _record_verification(
        self,
        task: HumanReviewTask,
        value: str,
        reviewer: str,
        now: datetime,
        source_url: str | None,
    ) -> str:
        """Supersede any earlier record for the same fact, then write the new one.

        Superseding rather than overwriting keeps the history: what was believed,
        by whom, and when it changed.
        """
        previous = list(
            (
                await self._session.scalars(
                    select(VerificationRecord).where(
                        VerificationRecord.subject == task.subject,
                        VerificationRecord.field_name == task.field_name,
                        VerificationRecord.status == "verified",
                    )
                )
            ).all()
        )
        for row in previous:
            row.status = "superseded"

        record = VerificationRecord(
            subject=task.subject,
            field_name=task.field_name or "resolved_value",
            value=value,
            verified_at=now,
            verified_by=reviewer,
            verification_method="human_review",
            confidence=0.98,
            status="verified",
            note=(task.resolution_note or "") + (f" source: {source_url}" if source_url else ""),
            is_demo=False,
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def _blocked_analyses(self, task: HumanReviewTask) -> list[Analysis]:
        """Every analysis waiting on this task.

        A single conflicting fact can block several analyses — the task is
        deduplicated, the analyses are not. Resolving the fact should release all
        of them, so this looks past ``task.analysis_id`` to any pending analysis
        whose result cites this task id.
        """
        found: dict[str, Analysis] = {}
        if task.analysis_id:
            direct = await self._session.get(Analysis, task.analysis_id)
            if direct is not None and direct.status == AnalysisStatus.NEEDS_HUMAN_REVIEW.value:
                found[direct.id] = direct

        pending = list(
            (
                await self._session.scalars(
                    select(Analysis)
                    .where(Analysis.status == AnalysisStatus.NEEDS_HUMAN_REVIEW.value)
                    .order_by(Analysis.created_at.desc())
                    .limit(50)
                )
            ).all()
        )
        for row in pending:
            if (row.result_payload or {}).get("human_review_task_id") == task.id:
                found[row.id] = row
        return list(found.values())

    async def _resume(
        self, task: HumanReviewTask, resolved_value: str, reviewer: str
    ) -> tuple[str | None, bool]:
        """Re-run every blocked analysis with the verified fact injected."""
        if self._analysis_service is None:
            return None, False
        blocked = await self._blocked_analyses(task)
        if not blocked:
            return None, False

        newest: str | None = None
        resumed_any = False
        for analysis in blocked:
            resumed_id = await self._resume_one(analysis, task, resolved_value, reviewer)
            if resumed_id:
                resumed_any = True
                newest = resumed_id
        if resumed_any:
            task.resumed = True
        return newest, resumed_any

    async def _resume_one(
        self, analysis: Analysis, task: HumanReviewTask, resolved_value: str, reviewer: str
    ) -> str | None:
        if self._analysis_service is None:
            raise RuntimeError(
                "ReviewService was constructed without an AnalysisService; "
                "a resolved review cannot be resumed without one."
            )
        payload = dict(analysis.input_payload or {})
        resolution = {
            "subject": task.subject,
            "field": task.field_name,
            "value": resolved_value,
            "verified_by": reviewer,
            "verified_at": datetime.now(UTC).isoformat(),
        }
        try:
            if analysis.kind == "where_next":
                run = await self._analysis_service.run_where_next(payload, trip_id=analysis.trip_id)
            else:
                run = await self._analysis_service.run_route_check(
                    payload, trip_id=analysis.trip_id
                )
        except Exception as exc:  # pragma: no cover - resume must not lose the resolution
            log.warning(
                "hitl.resume_failed", task_id=task.id, analysis_id=analysis.id, error=str(exc)[:300]
            )
            return None

        analysis.status = AnalysisStatus.COMPLETE.value
        result = dict(analysis.result_payload or {})
        result["status"] = AnalysisStatus.COMPLETE.value
        result["human_review_required"] = False
        result.setdefault("resolved_facts", []).append(resolution)
        result["superseded_by"] = run.analysis_id
        analysis.result_payload = result
        analysis.human_review_required = False
        log.info("hitl.resumed", task_id=task.id, original=analysis.id, rerun=run.analysis_id)
        return run.analysis_id

    async def stale_and_conflicting(self, limit: int = 50) -> dict[str, Any]:
        """Backing data for the admin verification queue."""
        from jst_api.db.models import EvidenceChunk, Source
        from jst_api.domain.freshness import classify_freshness, requires_reverification

        records = list((await self._session.scalars(select(VerificationRecord).limit(200))).all())
        stale: list[dict[str, Any]] = []
        for record in records:
            if record.status != "verified":
                continue
            from jst_api.services.mcp_backend import _topic_for_field

            topic = _topic_for_field(record.field_name)
            freshness = classify_freshness(record.verified_at, topic)
            if requires_reverification(freshness, topic):
                stale.append(
                    {
                        "subject": record.subject,
                        "field_name": record.field_name,
                        "value": record.value,
                        "verified_at": record.verified_at.isoformat()
                        if record.verified_at
                        else None,
                        "freshness": freshness.value,
                        "topic": topic.value,
                        "source_id": record.source_id,
                    }
                )

        chunk_rows = (
            await self._session.execute(
                select(EvidenceChunk, Source)
                .join(Source, Source.id == EvidenceChunk.source_id)
                .where(Source.status == "changed")
                .limit(limit)
            )
        ).all()
        changed_sources = [
            {"source_id": s.id, "title": s.title, "url": s.url, "content_hash": s.content_hash}
            for _c, s in chunk_rows
        ]

        open_tasks = await self.list_open(limit=limit)
        return {
            "stale_facts": stale[:limit],
            "changed_sources": changed_sources,
            "open_reviews": [
                {
                    "id": t.id,
                    "reason": t.reason,
                    "subject": t.subject,
                    "field_name": t.field_name,
                    "question": t.question,
                    "candidate_values": list(t.candidate_values or []),
                    "evidence_ids": list(t.evidence_ids or []),
                    "priority": t.priority,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in open_tasks
            ],
        }
