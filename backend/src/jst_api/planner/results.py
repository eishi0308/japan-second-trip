"""What the planner returns. Pydantic so the API can serve it as is.

Words, not machinery: every field a screen shows is already a phrase
("Strong fit", "Interests 3/3 matched", "Being checked"). There are no
percentages and no internal scores in this shape, apart from ``level``,
which is one of five steps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Character = Literal["classic", "unexpected", "slow_paced"]
CHARACTER_LABELS: dict[str, str] = {
    "classic": "Classic",
    "unexpected": "Unexpected",
    "slow_paced": "Slow-paced",
}


class AssumptionOut(BaseModel):
    field: str
    value: str
    label: str


class FunnelStep(BaseModel):
    label: str
    count: int


class StopOut(BaseModel):
    slug: str
    name: str
    area: str
    prefecture: str
    nights: int
    tier: str
    summary: str
    pinned: bool = False
    is_demo: bool = True


class FitLine(BaseModel):
    name: str
    text: str


class FitOut(BaseModel):
    level: int = Field(ge=1, le=5)
    label: str
    breakdown: list[FitLine]
    adjusted_for: list[str] = Field(default_factory=list)


class LegOut(BaseModel):
    origin: str
    destination: str
    minutes: int
    transfers: int


class TravelOut(BaseModel):
    moving_minutes: int
    moving_label: str
    load: Literal["light", "moderate", "heavy"]
    hotel_changes: int
    longest_leg: LegOut
    legs: list[LegOut]


class HardItem(BaseModel):
    text: str
    kind: str
    fact_state: str | None = None
    verified_at: datetime | None = None
    source_id: str | None = None
    is_demo: bool = True


class VerificationOut(BaseModel):
    state: Literal["verified", "stale", "unverified", "being_checked"]
    label: str
    oldest_verified_at: datetime | None = None
    is_demo: bool = True


class OptionOut(BaseModel):
    character: Character
    character_label: str
    title: str
    nights_label: str
    description: str
    stops: list[StopOut]
    fit: FitOut
    travel: TravelOut
    car: str
    car_label: str
    season: int = Field(ge=0, le=3)
    season_label: str
    whats_hard: list[HardItem]
    verification: VerificationOut


class RejectionOut(BaseModel):
    area: str
    area_label: str
    example: str
    reason: str
    if_you_change: str | None = None


class SuggestionOut(BaseModel):
    change: str
    label: str
    options_found: int


class NoticeOut(BaseModel):
    code: str
    text: str


class OptionSet(BaseModel):
    month: int
    nights: int
    options: list[OptionOut]
    not_for_this_trip: list[RejectionOut]
    funnel: list[FunnelStep]
    zero_results_suggestions: list[SuggestionOut] = Field(default_factory=list)


class SeasonChoice(BaseModel):
    season: str
    label: str
    month: int
    result: OptionSet


class NightsChoice(BaseModel):
    nights: int
    label: str
    result: OptionSet


class PlanResult(BaseModel):
    kind: Literal["options", "season_choice", "nights_choice"]
    assumptions: list[AssumptionOut] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    notices: list[NoticeOut] = Field(default_factory=list)
    result: OptionSet | None = None
    seasons: list[SeasonChoice] = Field(default_factory=list)
    nights_options: list[NightsChoice] = Field(default_factory=list)
    is_demo: bool = True
