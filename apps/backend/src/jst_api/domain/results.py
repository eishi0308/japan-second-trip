"""Structured analysis results.

Every model-consumed and API-returned result is a strict Pydantic schema. The
LLM is asked for these shapes directly (structured output); anything that fails
validation is repaired once, then rejected — never passed through loosely.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from jst_api.domain.enums import (
    AnalysisStatus,
    ConfidenceState,
    FitLabel,
    IssueType,
    RouteHealth,
    Severity,
)
from jst_api.domain.evidence import Citation, ConflictingEvidence
from jst_api.domain.route import Route, TravelLoad


class ResolvedFact(BaseModel):
    """A fact a human reviewer confirmed after this analysis was blocked on it."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    field: str | None = None
    value: str
    verified_by: str
    verified_at: str


# ---------------------------------------------------------------------------
# Where Next
# ---------------------------------------------------------------------------
class ScoreComponentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    weight: float
    contribution: float
    explanation: str


class RegionRecommendation(BaseModel):
    """One region, ranked, with the deterministic score it earned and the
    LLM-written explanation of what that score means for this traveller."""

    model_config = ConfigDict(extra="forbid")

    region_code: str
    region_name: str
    rank: int = Field(ge=1)
    fit_label: FitLabel
    deterministic_score: float = Field(ge=0, le=100)
    score_components: list[ScoreComponentOut] = Field(default_factory=list)

    headline: str = Field(max_length=240)
    reasons: list[str] = Field(default_factory=list, max_length=8)
    tradeoffs: list[str] = Field(default_factory=list, max_length=8)
    rejected_reasons: list[str] = Field(default_factory=list, max_length=8)

    round_trip_transfer_hours: float = 0.0
    transit_share: float = 0.0
    car_required: bool = False
    public_transport_viable: bool = True
    booking_complexity: float = 0.0
    seasonal_note: str | None = None

    evidence_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: ConfidenceState = ConfidenceState.MEDIUM
    is_demo_data: bool = True


class SuggestedRegionalRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_code: str
    summary: str
    stops: list[str] = Field(default_factory=list)
    nights: list[int] = Field(default_factory=list)
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class WhereNextResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    trip_id: str | None = None
    status: AnalysisStatus = AnalysisStatus.COMPLETE
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    recommended: RegionRecommendation | None = None
    alternatives: list[RegionRecommendation] = Field(default_factory=list)
    rejected: list[RegionRecommendation] = Field(default_factory=list)

    suggested_route: SuggestedRegionalRoute | None = None
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    conflicts: list[ConflictingEvidence] = Field(default_factory=list)

    confidence: ConfidenceState = ConfidenceState.MEDIUM
    human_review_required: bool = False
    human_review_task_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    resolved_facts: list[ResolvedFact] = Field(default_factory=list)
    """Populated when a human reviewer unblocked this analysis."""
    superseded_by: str | None = None
    """The re-run produced after human review. Read that one instead."""
    demo_mode: bool = True
    scoring_rubric_version: str = "1.0.0"
    prompt_versions: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# RouteCheck
# ---------------------------------------------------------------------------
class ProposedFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    changed: list[str] = Field(default_factory=list)
    gained: list[str] = Field(default_factory=list)
    lost: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class RouteIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: IssueType
    severity: Severity
    segment: str | None = None
    """Human-readable segment or stop the issue attaches to, e.g. "Ginzan Onsen → Aomori"."""
    title: str = Field(max_length=160)
    explanation: str
    deterministic_signal: dict[str, float | int | str | bool] = Field(default_factory=dict)
    """The measured numbers that triggered the rule. Always present for
    non-LLM-originated issues, so the critique is auditable."""
    rule_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    proposed_fix: str | None = None


class RevisedRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stops: list[str]
    nights: list[int]
    summary: str
    travel_load: TravelLoad | None = None
    rationale: str = ""


class RouteCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    trip_id: str | None = None
    status: AnalysisStatus = AnalysisStatus.COMPLETE
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    health: RouteHealth = RouteHealth.HEALTHY
    health_summary: str = ""
    parsed_route: Route | None = None
    travel_load: TravelLoad | None = None

    critical_issues: list[RouteIssue] = Field(default_factory=list)
    warnings: list[RouteIssue] = Field(default_factory=list)
    strengths: list[RouteIssue] = Field(default_factory=list)

    revised_route: RevisedRoute | None = None
    proposed_fixes: list[ProposedFix] = Field(default_factory=list)

    unknowns: list[str] = Field(default_factory=list)
    unresolved_places: list[str] = Field(default_factory=list)
    conflicts: list[ConflictingEvidence] = Field(default_factory=list)

    confidence: ConfidenceState = ConfidenceState.MEDIUM
    human_review_required: bool = False
    human_review_task_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    resolved_facts: list[ResolvedFact] = Field(default_factory=list)
    """Populated when a human reviewer unblocked this analysis."""
    superseded_by: str | None = None
    """The re-run produced after human review. Read that one instead."""
    demo_mode: bool = True
    rules_version: str = "1.0.0"
    prompt_versions: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LLM-facing structured output schemas (narrow on purpose)
# ---------------------------------------------------------------------------
class ExtractedStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=100)
    nights: int = Field(ge=0, le=30)
    note: str | None = Field(default=None, max_length=200)


class ExtractedItinerary(BaseModel):
    """What the extraction model is allowed to return. Nothing operational —
    no durations, no times, no prices. Those come from tools and structured data."""

    model_config = ConfigDict(extra="forbid")

    stops: list[ExtractedStop] = Field(default_factory=list, max_length=30)
    arrival_city: str | None = Field(default=None, max_length=80)
    departure_city: str | None = Field(default=None, max_length=80)
    total_nights: int | None = Field(default=None, ge=0, le=120)
    ambiguities: list[str] = Field(default_factory=list, max_length=10)


class RegionExplanation(BaseModel):
    """LLM output for one candidate: prose only, bound to supplied evidence ids."""

    model_config = ConfigDict(extra="forbid")

    region_code: str
    headline: str = Field(max_length=240)
    reasons: list[str] = Field(default_factory=list, max_length=6)
    tradeoffs: list[str] = Field(default_factory=list, max_length=6)
    rejected_reasons: list[str] = Field(default_factory=list, max_length=6)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)


class ComparisonOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanations: list[RegionExplanation] = Field(default_factory=list, max_length=8)
    suggested_route_summary: str | None = Field(default=None, max_length=600)
    suggested_route_stops: list[str] = Field(default_factory=list, max_length=10)
    suggested_route_nights: list[int] = Field(default_factory=list, max_length=10)
    unknowns: list[str] = Field(default_factory=list, max_length=8)


class CritiqueOutput(BaseModel):
    """LLM output for RouteCheck: explanation and a proposed reshape.

    Deterministic issues are supplied to the model; the model may add *narrative*
    but may not add or remove severities — the service reconciles both.
    """

    model_config = ConfigDict(extra="forbid")

    health_summary: str = Field(max_length=600)
    issue_narratives: dict[str, str] = Field(default_factory=dict)
    """rule_id -> traveller-facing explanation."""
    revised_stops: list[str] = Field(default_factory=list, max_length=15)
    revised_nights: list[int] = Field(default_factory=list, max_length=15)
    revision_summary: str = Field(default="", max_length=600)
    gained: list[str] = Field(default_factory=list, max_length=6)
    lost: list[str] = Field(default_factory=list, max_length=6)
    unknowns: list[str] = Field(default_factory=list, max_length=8)
    evidence_ids: list[str] = Field(default_factory=list, max_length=15)


class GroundingVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grounded: bool
    unsupported_claims: list[str] = Field(default_factory=list, max_length=10)
    missing_citations: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=600)


class RerankVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ranked_evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    reasoning: str | None = Field(default=None, max_length=400)
