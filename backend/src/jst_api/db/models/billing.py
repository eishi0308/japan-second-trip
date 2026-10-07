"""Purchases. A record of what was paid for — never a gate the agent can open."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from jst_api.db.base import Base, TimestampMixin, id_column


class Purchase(Base, TimestampMixin):
    __tablename__ = "purchases"

    id: Mapped[str] = id_column("pur")
    plan_id: Mapped[str] = mapped_column(String(40), index=True)
    amount_aud: Mapped[int] = mapped_column(Integer)
    """Whole dollars, copied from configuration at checkout so a later price
    change never rewrites what somebody actually paid."""
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    """pending | paid | cancelled"""
    provider: Mapped[str] = mapped_column(String(20))
    """stripe | demo"""
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_session_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), index=True, nullable=True
    )
    trip_id: Mapped[str | None] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), index=True, nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
