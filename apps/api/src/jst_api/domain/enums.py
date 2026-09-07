"""Controlled vocabularies shared by the API, agents and database."""

from __future__ import annotations

from enum import StrEnum


class TravellerType(StrEnum):
    SOLO = "solo"
    COUPLE = "couple"
    FAMILY = "family"


class Pace(StrEnum):
    RELAXED = "relaxed"
    BALANCED = "balanced"
    FAST = "fast"


class Interest(StrEnum):
    FOOD = "food"
    ONSEN = "onsen"
    NATURE = "nature"
    CULTURE = "culture"
    HIKING = "hiking"
    CITY = "city"
    COAST = "coast"
    SNOW = "snow"
    ART = "art"
    NIGHTLIFE = "nightlife"


class BudgetLevel(StrEnum):
    BUDGET = "budget"
    MID = "mid"
    PREMIUM = "premium"


class DrivingWillingness(StrEnum):
    NO_CAR = "no_car"
    """Public transport only — a car requirement is a hard constraint failure."""
    WILLING = "willing"
    PREFERS_CAR = "prefers_car"


class TransportMode(StrEnum):
    SHINKANSEN = "shinkansen"
    LIMITED_EXPRESS = "limited_express"
    LOCAL_TRAIN = "local_train"
    HIGHWAY_BUS = "highway_bus"
    LOCAL_BUS = "local_bus"
    FERRY = "ferry"
    FLIGHT = "flight"
    CAR = "car"
    WALK = "walk"


PUBLIC_MODES: frozenset[TransportMode] = frozenset(
    {
        TransportMode.SHINKANSEN,
        TransportMode.LIMITED_EXPRESS,
        TransportMode.LOCAL_TRAIN,
        TransportMode.HIGHWAY_BUS,
        TransportMode.LOCAL_BUS,
        TransportMode.FERRY,
        TransportMode.FLIGHT,
        TransportMode.WALK,
    }
)


class FitLabel(StrEnum):
    STRONG = "strong"
    GOOD = "good"
    MARGINAL = "marginal"
    NOT_RECOMMENDED = "not_recommended"


class RouteHealth(StrEnum):
    HEALTHY = "healthy"
    NEEDS_IMPROVEMENT = "needs_improvement"
    HIGH_RISK = "high_risk"


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    GOOD = "good"


class IssueType(StrEnum):
    TRAVEL_BURDEN = "travel_burden"
    ACCOMMODATION_CHURN = "accommodation_churn"
    BACKTRACKING = "backtracking"
    DEPARTURE_RISK = "departure_risk"
    CAR_REQUIRED = "car_required"
    LAST_CONNECTION_RISK = "last_connection_risk"
    BOOKING_LEAD_TIME = "booking_lead_time"
    SEASONAL_CLOSURE = "seasonal_closure"
    PACE_MISMATCH = "pace_mismatch"
    LUGGAGE_RISK = "luggage_risk"
    STALE_EVIDENCE = "stale_evidence"
    UNRESOLVED_STOP = "unresolved_stop"
    EFFICIENT_SEGMENT = "efficient_segment"
    GOOD_STAY_LENGTH = "good_stay_length"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    FAILED = "failed"


class ConfidenceState(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    AGEING = "ageing"
    STALE = "stale"
    UNVERIFIED = "unverified"


class SourceType(StrEnum):
    OFFICIAL_TOURISM = "official_tourism"
    TRANSPORT_OPERATOR = "transport_operator"
    GOVERNMENT = "government"
    ACCOMMODATION = "accommodation"
    EDITORIAL = "editorial"
    HUMAN_VERIFIED_NOTE = "human_verified_note"
    DEMO_SEED = "demo_seed"
    """Seeded demo evidence. Always surfaced to the user as demo data."""


class TrustLevel(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNVERIFIED = "unverified"


TRUST_WEIGHT: dict[TrustLevel, float] = {
    TrustLevel.PRIMARY: 1.0,
    TrustLevel.SECONDARY: 0.75,
    TrustLevel.UNVERIFIED: 0.4,
}


class ReviewReason(StrEnum):
    CONFLICTING_SOURCES = "conflicting_sources"
    STALE_CRITICAL_EVIDENCE = "stale_critical_evidence"
    MISSING_EVIDENCE = "missing_evidence"
    GROUNDING_FAILED = "grounding_failed"
    LOW_CONFIDENCE = "low_confidence"
    SOURCE_CHANGED = "source_changed"


class ReviewStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EvidenceTopic(StrEnum):
    TRANSPORT_ACCESS = "transport_access"
    BOOKING = "booking"
    SEASONAL = "seasonal"
    LUGGAGE = "luggage"
    ACCESSIBILITY = "accessibility"
    GENERAL = "general"
    COST = "cost"
