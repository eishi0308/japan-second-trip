"""Traveller feedback. Feeds the eval backlog, not a model."""

from __future__ import annotations

from fastapi import APIRouter

from jst_api.api.deps import RateLimitDep, SessionDep
from jst_api.api.schemas import FeedbackIn
from jst_api.core.logging import get_logger
from jst_api.db.models import Feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])
log = get_logger(__name__)


@router.post("", status_code=201)
async def submit_feedback(
    payload: FeedbackIn, session: SessionDep, _rate: RateLimitDep
) -> dict[str, str]:
    row = Feedback(
        analysis_id=payload.analysis_id,
        trip_id=payload.trip_id,
        rating=payload.rating,
        helpful=payload.helpful,
        category=payload.category,
        comment=payload.comment,
        reported_inaccuracy=payload.reported_inaccuracy,
    )
    session.add(row)
    await session.flush()
    log.info(
        "feedback.received",
        analysis_id=payload.analysis_id,
        rating=payload.rating,
        reported_inaccuracy=payload.reported_inaccuracy,
    )
    return {"id": row.id, "status": "recorded"}
