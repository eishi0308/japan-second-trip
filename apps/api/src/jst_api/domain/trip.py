"""Trip context — everything the system knows about *this* trip."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jst_api.domain.enums import (
    BudgetLevel,
    DrivingWillingness,
    Interest,
    Pace,
    TravellerType,
)


class MobilityConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_free_required: bool = False
    limited_walking: bool = False
    notes: str | None = Field(default=None, max_length=500)


class TripContext(BaseModel):
    """Deliberately permissive: almost every field is optional.

    Missing fields are recorded in ``missing_information`` by the agents rather
    than blocking the analysis, because a repeat visitor rarely knows every
    detail up front.
    """

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
    interests: list[Interest] = Field(default_factory=list)
    driving: DrivingWillingness | None = None
    budget: BudgetLevel | None = None
    pace: Pace | None = None

    large_luggage: bool | None = None
    mobility: MobilityConstraints | None = None
    free_text: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _coherent_dates(self) -> TripContext:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.start_date and self.end_date and self.total_nights is None:
            object.__setattr__(self, "total_nights", (self.end_date - self.start_date).days or 1)
        if self.total_nights and self.regional_nights and self.regional_nights > self.total_nights:
            raise ValueError("regional_nights cannot exceed total_nights")
        return self

    # ---- derived helpers ---------------------------------------------------
    @property
    def month(self) -> int | None:
        return self.start_date.month if self.start_date else None

    @property
    def public_transport_only(self) -> bool:
        return self.driving == DrivingWillingness.NO_CAR

    @property
    def effective_regional_nights(self) -> int:
        """Nights available for the regional leg, with a documented default.

        If the traveller gave no explicit regional allowance we assume roughly
        one third of the trip (min 2, max 7) — enough to produce an analysis,
        and always reported back as an assumption.
        """
        if self.regional_nights:
            return self.regional_nights
        if self.total_nights:
            return max(2, min(7, self.total_nights // 3))
        return 3

    @property
    def visited_normalised(self) -> set[str]:
        return {p.strip().lower() for p in self.visited_places if p.strip()}

    def missing_fields(self) -> list[str]:
        checks = {
            "start_date": self.start_date,
            "regional_nights": self.regional_nights,
            "arrival_city": self.arrival_city,
            "departure_city": self.departure_city,
            "interests": self.interests or None,
            "driving": self.driving,
            "pace": self.pace,
        }
        return sorted(k for k, v in checks.items() if v in (None, [], ""))

    def digest_payload(self) -> dict[str, object]:
        """Stable dict used as a cache key. Free text is excluded on purpose:
        it is user PII and does not change the deterministic constraint set."""
        return {
            "month": self.month,
            "regional_nights": self.effective_regional_nights,
            "arrival": (self.arrival_city or "").lower(),
            "departure": (self.departure_city or "").lower(),
            "visited": sorted(self.visited_normalised),
            "interests": sorted(i.value for i in self.interests),
            "driving": self.driving.value if self.driving else None,
            "pace": self.pace.value if self.pace else None,
            "traveller": self.traveller_type.value if self.traveller_type else None,
            "budget": self.budget.value if self.budget else None,
            "luggage": self.large_luggage,
        }


class TripMemory(BaseModel):
    """Durable, structured trip memory. Not a chat transcript.

    Only these fields are ever replayed into a model prompt, which keeps the
    context budget predictable and stops conversation drift.
    """

    model_config = ConfigDict(extra="forbid")

    trip_id: str
    visited: list[str] = Field(default_factory=list)
    candidate_region: str | None = None
    rejected_regions: dict[str, str] = Field(default_factory=dict)
    """region_code -> short reason, so the system never re-proposes a region the
    traveller already ruled out without acknowledging why."""
    confirmed_preferences: dict[str, str] = Field(default_factory=dict)
    verified_warnings: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)

    def to_prompt_block(self, max_items: int = 6) -> str:
        parts: list[str] = []
        if self.visited:
            parts.append("Already visited: " + ", ".join(self.visited[:max_items]))
        if self.candidate_region:
            parts.append(f"Current candidate region: {self.candidate_region}")
        if self.rejected_regions:
            rejected = "; ".join(
                f"{k} ({v})" for k, v in list(self.rejected_regions.items())[:max_items]
            )
            parts.append(f"Previously rejected: {rejected}")
        if self.confirmed_preferences:
            prefs = ", ".join(
                f"{k}={v}" for k, v in list(self.confirmed_preferences.items())[:max_items]
            )
            parts.append(f"Confirmed preferences: {prefs}")
        if self.verified_warnings:
            parts.append("Verified warnings: " + " | ".join(self.verified_warnings[:max_items]))
        return "\n".join(parts) if parts else "No prior trip memory."
