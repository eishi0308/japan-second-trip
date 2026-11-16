"""Admin: the verification queue for fragile facts and the resolve action (M5)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jst_api.api.deps import AdminDep, SessionDep
from jst_api.api.v1.saved_trips import recheck_trip
from jst_api.services.fact_review_service import queue, resolve

router = APIRouter(prefix="/admin/facts", tags=["admin"])


class ResolveIn(BaseModel):
    value: str | None = Field(default=None, max_length=40)
    """The confirmed value. For a last bus or shuttle, the time as HH:MM. Leave empty
    to confirm that a stale value is still right."""
    note: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000, pattern=r"^https?://")
    reviewer: str = Field(default="admin", min_length=1, max_length=120)


@router.get("/queue")
async def fact_queue(_admin: AdminDep, session: SessionDep) -> dict[str, Any]:
    items = await queue(session)
    return {"items": [asdict(i) for i in items], "count": len(items)}


@router.post("/{fact_id}/resolve")
async def resolve_fact(
    fact_id: str, body: ResolveIn, _admin: AdminDep, session: SessionDep
) -> dict[str, Any]:
    result = await resolve(
        session,
        fact_id,
        value=body.value,
        reviewer=body.reviewer,
        note=body.note,
        source_url=body.source_url,
        recheck_trip=recheck_trip,
    )
    return asdict(result)
