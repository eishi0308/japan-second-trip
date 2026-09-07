"""Preconditions shared by the graph tests.

Both the in-memory interrupt test and the durable-checkpoint test drive a graph
directly, without going through ``analysis_service``. That means they have to
establish by hand the two things the service establishes for them: a real
``analyses`` row for the human-review foreign key, and an actually-open conflict
for the interrupt to fire on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest


@pytest.fixture
def create_analysis(session_factory) -> Callable[[str], Awaitable[None]]:
    """Commit a ``running`` analysis, exactly as ``analysis_service`` does first.

    ``human_review_tasks.analysis_id`` is a real foreign key. PostgreSQL rejects
    a task pointing at an analysis that does not exist, and so does SQLite now
    that the test engine enables ``PRAGMA foreign_keys``.
    """

    async def _create(analysis_id: str, kind: str = "route_check") -> None:
        from jst_api.db.models import Analysis
        from jst_api.domain.enums import AnalysisStatus

        async with session_factory() as session:
            session.add(
                Analysis(
                    id=analysis_id,
                    trip_id=None,
                    kind=kind,
                    status=AnalysisStatus.RUNNING.value,
                    input_payload={},
                    result_payload={},
                )
            )
            await session.commit()

    return _create


@pytest.fixture
def reopen_conflict(session_factory) -> Callable[[], Awaitable[None]]:
    """Reset the seeded conflict to unresolved.

    The interrupt only fires if something genuinely needs a human, and an earlier
    test in the session may already have resolved it.
    """

    async def _reopen() -> None:
        from sqlalchemy import select

        from jst_api.db.models import HumanReviewTask, VerificationRecord

        async with session_factory() as session:
            task = await session.scalar(
                select(HumanReviewTask).where(HumanReviewTask.reason == "conflicting_sources")
            )
            assert task is not None
            task.status = "open"
            task.resolved_value = None
            task.resolved_at = None
            task.resumed = False
            task.analysis_id = None
            for record in (
                await session.scalars(
                    select(VerificationRecord).where(
                        VerificationRecord.verification_method == "human_review"
                    )
                )
            ).all():
                await session.delete(record)
            await session.commit()

    return _reopen
