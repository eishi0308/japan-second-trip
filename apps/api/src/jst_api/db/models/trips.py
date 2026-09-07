"""Trip workspace: users, trips, persistent memory and stored routes."""

from __future__ import annotations

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = id_column("usr")
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="traveller")
    """traveller | admin"""
    plan: Mapped[str] = mapped_column(String(30), default="free")
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True)

    trips: Mapped[list[Trip]] = relationship(back_populates="user")


class Trip(Base, TimestampMixin):
    __tablename__ = "trips"

    id: Mapped[str] = id_column("trip")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="Untitled trip")

    arrival_city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    departure_city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    start_date: Mapped[object | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[object | None] = mapped_column(Date, nullable=True)
    total_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_regional_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)

    traveller_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    driving: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pace: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget: Mapped[str | None] = mapped_column(String(20), nullable=True)
    large_luggage: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    interests: Mapped[list] = mapped_column(JSONBCompat, default=list)
    mobility: Mapped[dict | None] = mapped_column(JSONBCompat, nullable=True)
    preferences: Mapped[dict] = mapped_column(JSONBCompat, default=dict)

    candidate_region: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verified_warnings: Mapped[list] = mapped_column(JSONBCompat, default=list)
    decisions: Mapped[list] = mapped_column(JSONBCompat, default=list)

    user: Mapped[User | None] = relationship(back_populates="trips")
    visited: Mapped[list[VisitedPlace]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )
    candidates: Mapped[list[CandidateRegion]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )
    routes: Mapped[list[StoredRoute]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )


class VisitedPlace(Base, TimestampMixin):
    __tablename__ = "visited_places"
    __table_args__ = (UniqueConstraint("trip_id", "raw_name", name="uq_visited_trip_place"),)

    id: Mapped[str] = id_column("vis")
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    raw_name: Mapped[str] = mapped_column(String(160))
    place_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    visited_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trip: Mapped[Trip] = relationship(back_populates="visited")


class CandidateRegion(Base, TimestampMixin):
    """Per-trip record of a region considered — including ones ruled out.

    Rejections are memory: the system must not silently re-propose a region the
    traveller already discarded.
    """

    __tablename__ = "candidate_regions"
    __table_args__ = (UniqueConstraint("trip_id", "region_code", name="uq_candidate_trip_region"),)

    id: Mapped[str] = id_column("cnd")
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    region_code: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="considered")
    """considered | shortlisted | selected | rejected"""
    deterministic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fit_label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_breakdown: Mapped[dict] = mapped_column(JSONBCompat, default=dict)

    trip: Mapped[Trip] = relationship(back_populates="candidates")


class StoredRoute(Base, TimestampMixin):
    __tablename__ = "routes"

    id: Mapped[str] = id_column("rt")
    trip_id: Mapped[str | None] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=True
    )
    label: Mapped[str] = mapped_column(String(200), default="Proposed route")
    kind: Mapped[str] = mapped_column(String(20), default="user")
    """user | revised | suggested"""
    arrival_city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    departure_city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    """Full serialised ``domain.route.Route`` for replay."""

    trip: Mapped[Trip | None] = relationship(back_populates="routes")
    segments: Mapped[list[StoredRouteSegment]] = relationship(
        back_populates="route", cascade="all, delete-orphan"
    )


class StoredRouteSegment(Base, TimestampMixin):
    __tablename__ = "route_segments"

    id: Mapped[str] = id_column("seg")
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    from_order: Mapped[int] = mapped_column(Integer)
    to_order: Mapped[int] = mapped_column(Integer)
    from_name: Mapped[str] = mapped_column(String(160))
    to_name: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(40))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    transfers: Mapped[int] = mapped_column(Integer, default=0)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_car: Mapped[bool] = mapped_column(Boolean, default=False)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(40), default="demo")
    evidence_ids: Mapped[list] = mapped_column(JSONBCompat, default=list)

    route: Mapped[StoredRoute] = relationship(back_populates="segments")
