"""Structured travel catalogue: regions, places and normalised constraints.

These tables hold *facts with a shape* — numbers, coordinates, booleans, dates.
They are queried with SQL, never through vector search, because the
deterministic rules engine depends on them being exact and reproducible.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat


class Region(Base, TimestampMixin):
    __tablename__ = "regions"

    id: Mapped[str] = id_column("reg")
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    tagline: Mapped[str] = mapped_column(String(240), default="")
    prefectures: Mapped[list] = mapped_column(JSONBCompat, default=list)
    hub_place_slug: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)

    gateways: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    min_recommended_nights: Mapped[int] = mapped_column(Integer, default=2)
    ideal_nights: Mapped[int] = mapped_column(Integer, default=4)
    max_useful_nights: Mapped[int] = mapped_column(Integer, default=8)

    public_transport_score: Mapped[float] = mapped_column(Float, default=0.6)
    car_free_possible: Mapped[bool] = mapped_column(Boolean, default=True)
    car_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    car_required_highlights: Mapped[list] = mapped_column(JSONBCompat, default=list)

    interest_strength: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    seasonal: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    booking_complexity: Mapped[float] = mapped_column(Float, default=0.4)
    luggage_friendliness: Mapped[float] = mapped_column(Float, default=0.7)
    step_free_score: Mapped[float] = mapped_column(Float, default=0.6)
    typical_daily_cost_jpy: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    overlaps_with_visited: Mapped[list] = mapped_column(JSONBCompat, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    places: Mapped[list[Place]] = relationship(back_populates="region")


class Place(Base, TimestampMixin):
    __tablename__ = "places"
    __table_args__ = (Index("ix_places_region_slug", "region_code", "slug"),)

    id: Mapped[str] = id_column("plc")
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    name_ja: Mapped[str | None] = mapped_column(String(160), nullable=True)
    aliases: Mapped[list] = mapped_column(JSONBCompat, default=list)
    region_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"), nullable=True)
    prefecture: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    place_kind: Mapped[str] = mapped_column(String(40), default="town")
    is_gateway: Mapped[bool] = mapped_column(Boolean, default=False)
    nearest_station: Mapped[str | None] = mapped_column(String(160), nullable=True)
    typical_stay_nights: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSONBCompat, default=list)
    car_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    step_free: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    region: Mapped[Region | None] = relationship(back_populates="places")


class TransportConstraint(Base, TimestampMixin):
    """A structured, normalised transport fact between two places.

    Populated from seeded verified data or a transport provider. Consumed
    directly by ``domain/route_rules.py``.
    """

    __tablename__ = "transport_constraints"
    __table_args__ = (
        UniqueConstraint("from_slug", "to_slug", "mode", name="uq_transport_pair_mode"),
        Index("ix_transport_from_to", "from_slug", "to_slug"),
    )

    id: Mapped[str] = id_column("trc")
    from_slug: Mapped[str] = mapped_column(String(80), index=True)
    to_slug: Mapped[str] = mapped_column(String(80), index=True)
    mode: Mapped[str] = mapped_column(String(40))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    transfers: Mapped[int] = mapped_column(Integer, default=0)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_car: Mapped[bool] = mapped_column(Boolean, default=False)
    last_departure_local: Mapped[str | None] = mapped_column(String(5), nullable=True)
    final_leg_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seasonal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class BookingConstraint(Base, TimestampMixin):
    """Normalised booking rules (lead time, language, closure windows)."""

    __tablename__ = "booking_constraints"

    id: Mapped[str] = id_column("bkc")
    place_slug: Mapped[str] = mapped_column(String(80), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    english_booking_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    closed_months: Mapped[list] = mapped_column(JSONBCompat, default=list)
    closed_weekdays: Mapped[list] = mapped_column(JSONBCompat, default=list)
    requires_deposit: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
