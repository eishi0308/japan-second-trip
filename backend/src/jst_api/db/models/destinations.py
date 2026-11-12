"""Nationwide destination catalogue (PRODUCT_AMENDMENTS.md §6).

Four tables, all structured facts read with SQL:

* ``hubs`` — major cities that trains and flights connect.
* ``hub_links`` — the intercity backbone: hub-to-hub travel time and transfers.
* ``destinations`` — 100-200 places a repeat visitor might stay, each tied to a
  hub with a travel time, plus car need, month-by-month season fit, themes and
  popularity tier. Where Next selects destination *combinations* from here.
* ``fragile_links`` — the things that can break a stay at ~30 fragile
  destinations (last buses, ryokan shuttles, seasonal closures, booking
  difficulty), each with a source and a verified date.

The older ``regions`` / ``places`` tables stay: RouteCheck still resolves
itinerary stops against ``places``. ``destinations.place_slug`` links the two.
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
from sqlalchemy.orm import Mapped, mapped_column

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat


class Hub(Base, TimestampMixin):
    __tablename__ = "hubs"

    id: Mapped[str] = id_column("hub")
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    name_ja: Mapped[str | None] = mapped_column(String(120), nullable=True)
    area: Mapped[str] = mapped_column(String(20), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    airports: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """IATA codes of the airports that serve this hub."""
    is_international_gateway: Mapped[bool] = mapped_column(Boolean, default=False)
    """Can be an arrival or departure city for an overseas visitor."""
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class HubLink(Base, TimestampMixin):
    """One direction of one intercity connection. The seed writes both directions."""

    __tablename__ = "hub_links"
    __table_args__ = (
        UniqueConstraint("from_hub", "to_hub", "mode", name="uq_hub_links_pair_mode"),
        Index("ix_hub_links_from_to", "from_hub", "to_hub"),
    )

    id: Mapped[str] = id_column("hbl")
    from_hub: Mapped[str] = mapped_column(ForeignKey("hubs.slug"), index=True)
    to_hub: Mapped[str] = mapped_column(ForeignKey("hubs.slug"), index=True)
    mode: Mapped[str] = mapped_column(String(40))
    minutes: Mapped[int] = mapped_column(Integer)
    """Typical door-to-door time between city centres, including airport access for flights."""
    transfers: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class Destination(Base, TimestampMixin):
    __tablename__ = "destinations"
    __table_args__ = (
        Index("ix_destinations_area_tier", "area", "popularity_tier"),
        Index("ix_destinations_hub", "hub_slug"),
    )

    id: Mapped[str] = id_column("dst")
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    name_ja: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prefecture: Mapped[str] = mapped_column(String(80))
    area: Mapped[str] = mapped_column(String(20), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)

    hub_slug: Mapped[str] = mapped_column(ForeignKey("hubs.slug"))
    hub_minutes: Mapped[int] = mapped_column(Integer)
    """Typical public-transport time from the hub (by car where car_need is required)."""
    hub_transfers: Mapped[int] = mapped_column(Integer, default=0)
    access_mode: Mapped[str] = mapped_column(String(40))
    """Main mode for the last stretch from the hub (a TransportMode value)."""

    car_need: Mapped[str] = mapped_column(String(20), index=True)
    season_fit: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """Twelve integers, January first: 0 closed/avoid, 1 possible, 2 good, 3 best."""
    themes: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """Interest values (``domain.enums.Interest``) this destination is strong for."""
    popularity_tier: Mapped[str] = mapped_column(String(20), index=True)
    typical_nights: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(String(300), default="")
    place_slug: Mapped[str | None] = mapped_column(ForeignKey("places.slug"), nullable=True)
    has_fragile_links: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class FragileLink(Base, TimestampMixin):
    """A fact that can break a stay: a last bus, a shuttle, a closure, a booking rule."""

    __tablename__ = "fragile_links"
    __table_args__ = (
        UniqueConstraint("destination_slug", "kind", "title", name="uq_fragile_links_subject"),
        Index("ix_fragile_links_status", "status"),
    )

    id: Mapped[str] = id_column("frg")
    destination_slug: Mapped[str] = mapped_column(ForeignKey("destinations.slug"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    """``critical`` if missing it breaks the day, ``warning`` if it costs time or options."""
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)

    last_departure_local: Mapped[str | None] = mapped_column(String(5), nullable=True)
    closed_months: Mapped[list] = mapped_column(JSONBCompat, default=list)
    closed_weekdays: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """0 = Monday."""
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="verified")
    """A ``FactStatus`` value. Staleness is derived from ``verified_at`` + TTL."""
    conflicting_values: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """When sources disagree: every value seen. No single value is asserted."""
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_ttl_days: Mapped[int] = mapped_column(Integer, default=180)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
