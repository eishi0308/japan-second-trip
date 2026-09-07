"""Structured region profiles.

These are *structured facts*, deliberately NOT vector-search content: nights,
gateway travel times, transport scores and seasonal profiles are numeric
constraints the deterministic rubric depends on. Putting them in a vector index
would make the fit score unreproducible. Qualitative colour ("difficult with
large luggage", "book the ryokan shuttle ahead") lives in the evidence index
instead — see docs/adr/0005-hybrid-search.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jst_api.domain.enums import Interest, TransportMode
from jst_api.domain.geo import LatLon


class GatewayAccess(BaseModel):
    """Door-to-region overhead from a common international gateway."""

    model_config = ConfigDict(extra="forbid")

    gateway: str
    hours_one_way: float = Field(ge=0, le=24)
    primary_mode: TransportMode
    transfers: int = Field(ge=0, le=6)
    note: str | None = None


class SeasonalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: month number (1-12) -> suitability 0..1
    month_scores: dict[int, float]
    notes: dict[int, str] = Field(default_factory=dict)

    def score_for(self, month: int | None) -> float:
        if month is None:
            return 0.7  # neutral prior when dates are unknown
        return self.month_scores.get(month, 0.6)

    def note_for(self, month: int | None) -> str | None:
        return self.notes.get(month) if month else None


class RegionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    tagline: str
    prefectures: list[str]
    hub_place_slug: str
    centroid: LatLon

    gateways: dict[str, GatewayAccess]
    min_recommended_nights: int = Field(ge=1, le=14)
    ideal_nights: int = Field(ge=1, le=21)
    max_useful_nights: int = Field(ge=1, le=30)

    public_transport_score: float = Field(ge=0, le=1)
    """1.0 = a good itinerary here is entirely doable on public transport."""
    car_free_possible: bool = True
    car_recommended: bool = False
    car_required_highlights: list[str] = Field(default_factory=list)

    interest_strength: dict[Interest, float] = Field(default_factory=dict)
    seasonal: SeasonalProfile
    booking_complexity: float = Field(ge=0, le=1, default=0.4)
    """0 = walk-up friendly, 1 = must be booked months ahead in Japanese."""
    luggage_friendliness: float = Field(ge=0, le=1, default=0.7)
    step_free_score: float = Field(ge=0, le=1, default=0.6)
    typical_daily_cost_jpy: dict[str, int] = Field(default_factory=dict)
    overlaps_with_visited: list[str] = Field(default_factory=list)
    """Golden-route places this region feels similar to — used for novelty scoring."""
    is_demo: bool = True

    def access_from(self, gateway: str | None) -> GatewayAccess | None:
        if not gateway:
            return None
        key = gateway.strip().lower()
        for name, access in self.gateways.items():
            if name.lower() == key or key in name.lower() or name.lower() in key:
                return access
        return None

    def best_gateway(self) -> GatewayAccess:
        return min(self.gateways.values(), key=lambda g: g.hours_one_way)
