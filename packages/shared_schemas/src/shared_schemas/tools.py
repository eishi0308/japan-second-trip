"""Typed input/output contracts for every AI-facing travel capability.

These are the MCP tool schemas. They are defined here, once, so that:

* the MCP server can publish them as JSON Schema,
* every consumer validates against the same shapes,
* argument validation happens *before* dispatch rather than inside a handler,
* the tool eval can assert on argument correctness mechanically.

Each contract also declares a permission level. Read tools are freely callable;
write tools mutate trip state and are restricted per consumer; human tools
create review tasks. Nothing here can book, pay, or contact anybody.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ToolPermission(StrEnum):
    READ = "read"
    WRITE_STATE = "write_state"
    HUMAN_REVIEW = "human_review"


class ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str
    permission: ToolPermission
    timeout_seconds: float = 10.0
    max_attempts: int = 2
    cacheable: bool = True
    freshness_sensitive: bool = False
    """True when the result carries an operational fact whose age matters."""


# ---------------------------------------------------------------------------
# shared value objects
# ---------------------------------------------------------------------------
class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str
    source_title: str
    source_url: str | None = None
    source_type: str
    official_source: bool = False
    trust_level: str
    topic: str
    region_code: str | None = None
    place_slug: str | None = None
    verified_at: str | None = None
    freshness: str
    is_demo: bool = True
    score: float = 0.0
    snippet: str = ""


class ProviderStamp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    is_demo: bool = True
    cached: bool = False


# ---------------------------------------------------------------------------
# search_verified_evidence
# ---------------------------------------------------------------------------
class SearchEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    region_codes: list[str] = Field(default_factory=list, max_length=8)
    place_slugs: list[str] = Field(default_factory=list, max_length=12)
    topics: list[str] = Field(default_factory=list, max_length=6)
    month: int | None = Field(default=None, ge=1, le=12)
    official_only: bool = False
    limit: int = Field(default=6, ge=1, le=20)


class SearchEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: list[EvidenceRef] = Field(default_factory=list)
    strategy: str = "hybrid_rerank"
    total_candidates: int = 0
    quarantined_count: int = 0
    """Chunks dropped because they contained an injection attempt."""


# ---------------------------------------------------------------------------
# get_source_evidence
# ---------------------------------------------------------------------------
class GetSourceEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    source_id: str | None = None


class GetSourceEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: list[EvidenceRef] = Field(default_factory=list)
    full_texts: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# get_place_details
# ---------------------------------------------------------------------------
class GetPlaceDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=120)
    """A slug or a free-text place name as the traveller wrote it."""


class PlaceDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    name_ja: str | None = None
    lat: float
    lon: float
    region_code: str | None = None
    prefecture: str | None = None
    place_kind: str = "town"
    nearest_station: str | None = None
    typical_stay_nights: int = 1
    car_recommended: bool = False
    step_free: bool = True
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    resolution_confidence: float = 1.0
    #: ``exact`` | ``contains`` | ``fuzzy`` — see ``PlaceResult.match_kind``.
    #: A ``fuzzy`` match is a suggestion, never a resolution.
    match_kind: str = "exact"
    provider: ProviderStamp


class GetPlaceDetailsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved: bool
    place: PlaceDetails | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# get_place_constraints
# ---------------------------------------------------------------------------
class GetPlaceConstraintsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slug: str = Field(min_length=1, max_length=80)
    month: int | None = Field(default=None, ge=1, le=12)


class BookingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    lead_time_days: int | None = None
    english_booking_available: bool | None = None
    requires_deposit: bool = False
    closed_months: list[int] = Field(default_factory=list)
    closed_weekdays: list[int] = Field(default_factory=list)
    note: str = ""
    verified_at: str | None = None
    is_demo: bool = True


class GetPlaceConstraintsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slug: str
    booking_rules: list[BookingRule] = Field(default_factory=list)
    closed_this_month: bool = False
    car_recommended: bool = False
    step_free: bool = True
    evidence: list[EvidenceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# search_transport
# ---------------------------------------------------------------------------
class SearchTransportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_place: str = Field(min_length=1, max_length=120)
    to_place: str = Field(min_length=1, max_length=120)
    travel_date: str | None = Field(default=None, max_length=10)
    allow_car: bool = True


class TransportLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    duration_minutes: int
    transfers: int = 0
    distance_km: float | None = None
    requires_car: bool = False
    last_departure_local: str | None = None
    final_leg_minutes: int | None = None
    frequency_per_day: int | None = None
    operator: str | None = None
    is_estimate: bool = False
    notes: str | None = None
    provider: ProviderStamp


class SearchTransportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_slug: str
    to_slug: str
    resolved: bool = True
    options: list[TransportLeg] = Field(default_factory=list)
    best_public_option: TransportLeg | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# get_route_context
# ---------------------------------------------------------------------------
class GetRouteContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slugs: list[str] = Field(min_length=1, max_length=15)
    nights: list[int] = Field(default_factory=list, max_length=15)
    allow_car: bool = True
    arrival_city: str | None = None
    departure_city: str | None = None


class GetRouteContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legs: list[TransportLeg] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    total_transit_minutes: int = 0
    estimated_legs: int = 0
    """How many legs are geometric estimates rather than verified records."""


# ---------------------------------------------------------------------------
# calculate_travel_load  (deterministic — no model involved)
# ---------------------------------------------------------------------------
class CalculateTravelLoadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slugs: list[str] = Field(min_length=1, max_length=15)
    nights: list[int] = Field(min_length=1, max_length=15)
    allow_car: bool = True


class CalculateTravelLoadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_nights: int
    total_transit_hours: float
    longest_segment_hours: float
    accommodation_changes: int
    one_night_stays: int
    transit_hours_per_night: float
    transit_share_of_daylight: float
    detour_ratio: float
    segments_requiring_car: int
    estimated_segments: int
    is_travel_dominated: bool


# ---------------------------------------------------------------------------
# check_route_constraints
# ---------------------------------------------------------------------------
class CheckRouteConstraintsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slugs: list[str] = Field(min_length=1, max_length=15)
    nights: list[int] = Field(min_length=1, max_length=15)
    public_transport_only: bool = False
    large_luggage: bool = False
    pace: str | None = None
    arrival_city: str | None = None
    departure_city: str | None = None
    month: int | None = Field(default=None, ge=1, le=12)


class RouteIssueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    issue_type: str
    severity: str
    segment: str | None = None
    title: str
    explanation: str
    deterministic_signal: dict[str, float | int | str | bool] = Field(default_factory=dict)
    proposed_fix: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class CheckRouteConstraintsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health: str
    issues: list[RouteIssueOut] = Field(default_factory=list)
    travel_load: CalculateTravelLoadOutput | None = None
    rules_version: str = "1.0.0"
    unresolved_places: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# get_booking_requirements
# ---------------------------------------------------------------------------
class GetBookingRequirementsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slugs: list[str] = Field(min_length=1, max_length=12)
    month: int | None = Field(default=None, ge=1, le=12)


class GetBookingRequirementsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, list[BookingRule]] = Field(default_factory=dict)
    max_lead_time_days: int | None = None
    english_booking_gaps: list[str] = Field(default_factory=list)
    closed_in_month: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# get_weather_context
# ---------------------------------------------------------------------------
class GetWeatherContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slug: str = Field(min_length=1, max_length=80)
    month: int = Field(ge=1, le=12)


class GetWeatherContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved: bool
    place_slug: str
    month: int
    typical_high_c: float | None = None
    typical_low_c: float | None = None
    rain_days: int | None = None
    snow_likely: bool = False
    summary: str = ""
    provider: ProviderStamp | None = None


# ---------------------------------------------------------------------------
# get_verification_status
# ---------------------------------------------------------------------------
class GetVerificationStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjects: list[str] = Field(default_factory=list, max_length=20)
    region_code: str | None = None
    stale_only: bool = False
    limit: int = Field(default=25, ge=1, le=100)


class VerificationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    field_name: str
    value: str
    verified_at: str | None = None
    verified_by: str = "system"
    verification_method: str = "seed"
    confidence: float = 0.0
    status: str = "verified"
    freshness: str = "unverified"
    requires_reverification: bool = False
    source_id: str | None = None


class ConflictEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    field_name: str
    values: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    open_review_task_id: str | None = None


class GetVerificationStatusOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[VerificationEntry] = Field(default_factory=list)
    conflicts: list[ConflictEntry] = Field(default_factory=list)
    stale_count: int = 0


# ---------------------------------------------------------------------------
# create_human_review_request
# ---------------------------------------------------------------------------
class CreateHumanReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    subject: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=5, max_length=2000)
    field_name: str | None = None
    candidate_values: list[str] = Field(default_factory=list, max_length=8)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    analysis_id: str | None = None
    thread_id: str | None = None
    priority: str = "normal"


class CreateHumanReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: str = "open"
    created: bool = True


# ---------------------------------------------------------------------------
# trip state
# ---------------------------------------------------------------------------
class GetTripContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip_id: str = Field(min_length=1, max_length=40)


class GetTripContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool
    trip_id: str
    visited: list[str] = Field(default_factory=list)
    candidate_region: str | None = None
    rejected_regions: dict[str, str] = Field(default_factory=dict)
    confirmed_preferences: dict[str, str] = Field(default_factory=dict)
    verified_warnings: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    arrival_city: str | None = None
    departure_city: str | None = None
    regional_nights: int | None = None


class SaveTripDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip_id: str = Field(min_length=1, max_length=40)
    decision_kind: str
    """candidate_selected | region_rejected | preference_confirmed | warning_acknowledged"""
    region_code: str | None = None
    reason: str | None = Field(default=None, max_length=500)
    preference_key: str | None = None
    preference_value: str | None = None
    note: str | None = Field(default=None, max_length=500)


class SaveTripDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved: bool
    trip_id: str
    message: str = ""


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
TOOL_CONTRACTS: dict[str, ToolContract] = {
    c.name: c
    for c in [
        ToolContract(
            name="search_verified_evidence",
            description="Hybrid (vector + full-text) search over verified travel evidence, with metadata filters, reranking and citation-preserving results.",
            permission=ToolPermission.READ,
            timeout_seconds=12.0,
            freshness_sensitive=True,
        ),
        ToolContract(
            name="get_source_evidence",
            description="Fetch specific evidence chunks and their full source text by id.",
            permission=ToolPermission.READ,
            timeout_seconds=8.0,
        ),
        ToolContract(
            name="get_place_details",
            description="Resolve a free-text Japanese place name to a catalogue entry with coordinates, region and access metadata.",
            permission=ToolPermission.READ,
            timeout_seconds=8.0,
        ),
        ToolContract(
            name="get_place_constraints",
            description="Structured booking and access constraints for one place, plus supporting evidence.",
            permission=ToolPermission.READ,
            timeout_seconds=10.0,
            freshness_sensitive=True,
        ),
        ToolContract(
            name="search_transport",
            description="Transport options between two places, from verified records where available and clearly-labelled estimates otherwise.",
            permission=ToolPermission.READ,
            timeout_seconds=12.0,
            freshness_sensitive=True,
        ),
        ToolContract(
            name="get_route_context",
            description="Resolve a whole itinerary into transport legs in one call.",
            permission=ToolPermission.READ,
            timeout_seconds=20.0,
            freshness_sensitive=True,
        ),
        ToolContract(
            name="calculate_travel_load",
            description="Deterministic travel-load metrics for an itinerary. No model involved.",
            permission=ToolPermission.READ,
            timeout_seconds=15.0,
        ),
        ToolContract(
            name="check_route_constraints",
            description="Run the deterministic route-health rules engine over an itinerary and return graded issues with the measurements that triggered them.",
            permission=ToolPermission.READ,
            timeout_seconds=20.0,
        ),
        ToolContract(
            name="get_booking_requirements",
            description="Booking lead times, language availability and closure windows for a set of places.",
            permission=ToolPermission.READ,
            timeout_seconds=10.0,
            freshness_sensitive=True,
        ),
        ToolContract(
            name="get_weather_context",
            description="Seasonal climate context for a place and month. Context only — never a constraint.",
            permission=ToolPermission.READ,
            timeout_seconds=8.0,
        ),
        ToolContract(
            name="get_verification_status",
            description="Verification records, freshness state and detected source conflicts for operational facts.",
            permission=ToolPermission.READ,
            timeout_seconds=10.0,
            freshness_sensitive=True,
        ),
        ToolContract(
            name="create_human_review_request",
            description="Escalate an unresolved or conflicting operational fact to a human reviewer.",
            permission=ToolPermission.HUMAN_REVIEW,
            timeout_seconds=8.0,
            cacheable=False,
        ),
        ToolContract(
            name="get_trip_context",
            description="Persistent trip memory: visited places, current candidate, rejected regions, confirmed preferences.",
            permission=ToolPermission.READ,
            timeout_seconds=8.0,
            cacheable=False,
        ),
        ToolContract(
            name="save_trip_decision",
            description="Record a trip decision in persistent memory so later analyses respect it.",
            permission=ToolPermission.WRITE_STATE,
            timeout_seconds=8.0,
            cacheable=False,
        ),
    ]
}

READ_TOOLS = [n for n, c in TOOL_CONTRACTS.items() if c.permission is ToolPermission.READ]
WRITE_TOOLS = [n for n, c in TOOL_CONTRACTS.items() if c.permission is ToolPermission.WRITE_STATE]
HUMAN_TOOLS = [n for n, c in TOOL_CONTRACTS.items() if c.permission is ToolPermission.HUMAN_REVIEW]
