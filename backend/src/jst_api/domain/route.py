"""Itinerary structures: stops, segments and the derived travel load."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jst_api.domain.enums import PUBLIC_MODES, TransportMode
from jst_api.domain.geo import LatLon


class RouteStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=0)
    raw_name: str
    place_slug: str | None = None
    display_name: str | None = None
    nights: int = Field(ge=0, le=30)
    region_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    resolved: bool = False
    resolution_note: str | None = None

    @property
    def name(self) -> str:
        return self.display_name or self.raw_name

    @property
    def coords(self) -> LatLon | None:
        if self.lat is None or self.lon is None:
            return None
        return LatLon(self.lat, self.lon)


class RouteSegment(BaseModel):
    """One hop between consecutive stops.

    ``duration_minutes`` always comes from a transport provider or seeded
    structured data — never from the language model. ``is_estimate`` records
    when the value is a distance-derived fallback so the UI can say so.
    """

    model_config = ConfigDict(extra="forbid")

    from_order: int
    to_order: int
    from_name: str
    to_name: str
    mode: TransportMode
    duration_minutes: int = Field(ge=0, le=3000)
    transfers: int = Field(ge=0, le=12, default=0)
    distance_km: float | None = None
    requires_car: bool = False
    last_departure_local: str | None = None
    """e.g. "17:10" — the last departure of the day on this hop's FINAL local
    connection (the shuttle bus, the branch line). Only ever populated from
    structured provider data or verified evidence, never from the model."""
    final_leg_minutes: int | None = None
    """Duration of that final local connection, so the rules engine can work out
    when the traveller must reach the transfer point."""
    provider: str = "demo"
    is_estimate: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    notes: str | None = None

    @property
    def duration_hours(self) -> float:
        """Not a serialised field: ``Route`` round-trips through graph state and
        a computed field would be rejected on re-validation under extra=forbid."""
        return round(self.duration_minutes / 60.0, 2)

    @property
    def is_public_transport(self) -> bool:
        return self.mode in PUBLIC_MODES


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stops: list[RouteStop] = Field(default_factory=list)
    segments: list[RouteSegment] = Field(default_factory=list)
    arrival_city: str | None = None
    departure_city: str | None = None

    @property
    def total_nights(self) -> int:
        return sum(s.nights for s in self.stops)

    @property
    def overnight_stops(self) -> list[RouteStop]:
        return [s for s in self.stops if s.nights > 0]

    @property
    def accommodation_changes(self) -> int:
        """Number of times bags move to a new bed. Consecutive nights in one
        place count once."""
        changes = 0
        previous: str | None = None
        for stop in self.overnight_stops:
            key = stop.place_slug or stop.raw_name.lower()
            if key != previous:
                changes += 1
            previous = key
        return max(changes - 1, 0)

    @property
    def one_night_stays(self) -> list[RouteStop]:
        return [s for s in self.overnight_stops if s.nights == 1]

    @property
    def total_transit_minutes(self) -> int:
        return sum(s.duration_minutes for s in self.segments)

    @property
    def coordinate_path(self) -> list[LatLon]:
        return [s.coords for s in self.stops if s.coords is not None]

    def to_compact_text(self) -> str:
        return " → ".join(f"{s.name} {s.nights}N" if s.nights else s.name for s in self.stops)


class TravelLoad(BaseModel):
    """Deterministic summary of how much of the trip is spent moving."""

    model_config = ConfigDict(extra="forbid")

    total_nights: int
    total_transit_hours: float
    longest_segment_hours: float
    accommodation_changes: int
    one_night_stays: int
    transit_hours_per_night: float
    transit_share_of_daylight: float
    """Transit hours divided by (nights × 10 usable hours + transit hours)."""
    detour_ratio: float
    segments_requiring_car: int
    estimated_segments: int
    is_travel_dominated: bool = False
    """A stored field rather than a property: this object crosses the MCP
    boundary and LangGraph state, and both round-trip through strict validation."""


#: Above this share of usable hours, the leg is a journey with sightseeing
#: attached rather than a visit.
TRAVEL_DOMINATED_SHARE = 0.35


def compute_travel_load(route: Route) -> TravelLoad:
    from jst_api.domain.geo import detour_ratio

    nights = route.total_nights
    transit_hours = route.total_transit_minutes / 60.0
    usable = max(nights, 1) * 10.0
    longest = max((s.duration_minutes for s in route.segments), default=0) / 60.0
    return TravelLoad(
        total_nights=nights,
        total_transit_hours=round(transit_hours, 2),
        longest_segment_hours=round(longest, 2),
        accommodation_changes=route.accommodation_changes,
        one_night_stays=len(route.one_night_stays),
        transit_hours_per_night=round(transit_hours / max(nights, 1), 2),
        transit_share_of_daylight=round(transit_hours / (transit_hours + usable), 4),
        detour_ratio=round(detour_ratio(route.coordinate_path), 3),
        segments_requiring_car=sum(1 for s in route.segments if s.requires_car),
        estimated_segments=sum(1 for s in route.segments if s.is_estimate),
        is_travel_dominated=(transit_hours / (transit_hours + usable)) > TRAVEL_DOMINATED_SHARE,
    )
