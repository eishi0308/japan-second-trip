"""Saved plans, saved trips and demand-test clicks (PRODUCT_AMENDMENTS.md v2).

* ``plan_records``: the conditions behind ``/plan/[id]``. The plan itself is
  not stored. The planner is deterministic, so the page re-runs it from the
  stored request. Re-running also means a fact resolved by a reviewer shows
  up on the next view.
* ``saved_trips``: the traveller's chosen itinerary (``/trip/[id]``). It is
  edited with an owner token and read through a separate share id that
  grants read-only access.
  When a reviewer resolves a fact the trip depends on, the trip is re-checked
  and gets a notice (M5).
* ``demand_events``: clicks on "See full report". Payments are out of scope
  for v1, and this records whether people would want the report.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat


class PlanRecord(Base, TimestampMixin):
    __tablename__ = "plan_records"

    id: Mapped[str] = id_column("plan")
    request: Mapped[dict] = mapped_column(JSONBCompat, default=dict)


class SavedTrip(Base, TimestampMixin):
    __tablename__ = "saved_trips"

    id: Mapped[str] = id_column("strp")
    share_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="My next Japan trip")
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_records.id", ondelete="SET NULL"), nullable=True
    )
    check_request: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    last_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    """The verdict the traveller last saw, so a resolved fact can say what changed."""
    notices: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """Updates for the traveller, newest last: a fact a reviewer resolved, and how the
    trip's verdict moved because of it."""


class DemandEvent(Base, TimestampMixin):
    __tablename__ = "demand_events"

    id: Mapped[str] = id_column("dmd")
    kind: Mapped[str] = mapped_column(String(40), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    trip_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    context: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
