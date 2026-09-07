"""HTTP request/response schemas.

Separate from the domain models on purpose: the wire contract can stay stable
while the internal representation changes, and request bodies get their own
strict validation (max lengths, forbidden extras) at the edge.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jst_api.domain.enums import (
    BudgetLevel,
    DrivingWillingness,
    Interest,
    Pace,
    TravellerType,
)
from jst_api.domain.results import RouteCheckResult, WhereNextResult


class MobilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_free_required: bool = False
    limited_walking: bool = False
    notes: str | None = Field(default=None, max_length=500)


class TripContextIn(BaseModel):
    """The trip form. Almost everything is optional by design — a repeat visitor
    rarely has every detail settled when they start planning."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    total_nights: int | None = Field(default=None, ge=1, le=120)
    regional_nights: int | None = Field(default=None, ge=1, le=60)
    arrival_city: str | None = Field(default=None, max_length=80)
    departure_city: str | None = Field(default=None, max_length=80)
    visited_places: list[str] = Field(default_factory=list, max_length=100)
    traveller_type: TravellerType | None = None
    party_size: int | None = Field(default=None, ge=1, le=12)
    interests: list[Interest] = Field(default_factory=list, max_length=10)
    driving: DrivingWillingness | None = None
    budget: BudgetLevel | None = None
    pace: Pace | None = None
    large_luggage: bool | None = None
    mobility: MobilityIn | None = None
    free_text: str | None = Field(default=None, max_length=4000)


class WhereNextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip: TripContextIn
    trip_id: str | None = Field(default=None, max_length=40)
    save_trip: bool = True


class StopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    nights: int = Field(default=0, ge=0, le=30)


class RouteCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itinerary_text: str | None = Field(default=None, max_length=4000)
    stops: list[StopIn] = Field(default_factory=list, max_length=25)
    trip: TripContextIn | None = None
    trip_id: str | None = Field(default=None, max_length=40)
    save_trip: bool = True

    def has_input(self) -> bool:
        return bool((self.itinerary_text or "").strip() or self.stops)


class AnalysisEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    trip_id: str | None = None
    trip_token: str | None = None
    """Returned once, on trip creation. It is the capability to read that trip."""
    kind: str
    status: str
    demo_mode: bool
    demo_providers: dict[str, bool] = Field(default_factory=dict)
    latency_ms: int = 0
    trace: dict[str, Any] = Field(default_factory=dict)


class WhereNextResponse(AnalysisEnvelope):
    result: WhereNextResult


class RouteCheckResponse(AnalysisEnvelope):
    result: RouteCheckResult


class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="Japan trip", max_length=200)
    trip: TripContextIn


class TripUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    trip: TripContextIn | None = None
    candidate_region: str | None = Field(default=None, max_length=40)
    reject_region: str | None = Field(default=None, max_length=40)
    reject_reason: str | None = Field(default=None, max_length=500)
    acknowledge_warning: str | None = Field(default=None, max_length=500)


class TripOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    trip: dict[str, Any]
    visited: list[str] = Field(default_factory=list)
    candidate_region: str | None = None
    rejected_regions: dict[str, str] = Field(default_factory=dict)
    verified_warnings: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    analyses: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class TripCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip: TripOut
    trip_token: str


class EvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    content: str
    source_id: str
    source_title: str
    source_url: str | None = None
    source_type: str
    official_source: bool
    trust_level: str
    topic: str
    region_code: str | None = None
    place_slug: str | None = None
    verified_at: str | None = None
    freshness: str
    freshness_label: str
    is_demo: bool


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str | None = Field(default=None, max_length=40)
    trip_id: str | None = Field(default=None, max_length=40)
    rating: int | None = Field(default=None, ge=1, le=5)
    helpful: bool | None = None
    category: str | None = Field(default=None, max_length=60)
    comment: str | None = Field(default=None, max_length=2000)
    reported_inaccuracy: bool = False


class ReviewResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_value: str = Field(min_length=1, max_length=500)
    resolution_note: str | None = Field(default=None, max_length=2000)
    reviewer: str = Field(default="admin", max_length=120)
    source_url: str | None = Field(default=None, max_length=1000)
    dismiss: bool = False


class SourceCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=1000)
    text: str | None = Field(default=None, max_length=200_000)
    title: str = Field(min_length=1, max_length=400)
    source_type: str = Field(default="official_tourism", max_length=40)
    trust_level: str = Field(default="secondary", max_length=20)
    official_source: bool = False
    region_code: str | None = Field(default=None, max_length=40)
    place_slug: str | None = Field(default=None, max_length=80)
    topic: str = Field(default="general", max_length=40)
    terms_confirmed: bool = False
    """The admin asserts the source's terms permit ingestion. Required for URLs."""


class AdminAssistantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=3, max_length=1000)
    region_code: str | None = Field(default=None, max_length=40)


class PricingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    price_aud: int
    cadence: str
    description: str
    features: list[str]
    cta: str
    highlight: bool = False


class HealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    environment: str


class ReadyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    database: str
    evidence_chunks: int
    regions: int
    providers: dict[str, Any]
    demo_mode: bool
    checks: dict[str, bool]
