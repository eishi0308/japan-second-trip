"""Value types the planner works on. No I/O, no ORM."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from jst_api.domain.backbone import Backbone, DestinationAccess
from jst_api.domain.enums import Pace
from jst_api.domain.fact_state import FactState

DEFAULT_HUB = "tokyo"
#: Nights assumed when the traveller has not decided, for the season preview.
DEFAULT_NIGHTS = 4
MAX_INTERESTS = 3


class Transport(StrEnum):
    NO_CAR = "no_car"
    CAN_DRIVE = "can_drive"
    EITHER = "either"


class ReactionKind(StrEnum):
    MORE_LIKE_THIS = "more_like_this"
    QUIETER = "quieter"
    MORE_UNEXPECTED = "more_unexpected"
    NOT_FOR_ME = "not_for_me"


class Avoid(StrEnum):
    """Things a traveller wants less of, inferred from "what tired you?"."""

    CROWDS = "crowds"
    LONG_TRANSFERS = "long_transfers"
    HOTEL_CHANGES = "hotel_changes"
    CITIES = "cities"
    EARLY_STARTS = "early_starts"


@dataclass(frozen=True)
class FragileNote:
    kind: str
    severity: str
    title: str
    detail: str
    state: FactState
    verified_at: datetime | None
    source_id: str
    closed_months: tuple[int, ...] = ()
    lead_time_days: int | None = None
    last_departure_local: str | None = None
    closed_weekdays: tuple[int, ...] = ()
    frequency_per_day: int | None = None
    conflicting_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Place:
    slug: str
    name: str
    area: str
    prefecture: str
    hub_slug: str
    hub_minutes: int
    hub_transfers: int
    access_mode: str
    car_need: str
    season_fit: tuple[int, ...]
    themes: tuple[str, ...]
    tier: str
    typical_nights: int
    summary: str
    verified_at: datetime | None
    is_demo: bool = True
    fragile: tuple[FragileNote, ...] = ()
    source_id: str | None = None

    @property
    def access(self) -> DestinationAccess:
        return DestinationAccess(
            self.slug, self.hub_slug, self.hub_minutes, self.hub_transfers, self.access_mode
        )

    def season(self, month: int) -> int:
        if any(month in note.closed_months for note in self.fragile):
            return 0
        return self.season_fit[month - 1]


@dataclass(frozen=True)
class HubInfo:
    slug: str
    name: str
    area: str
    is_gateway: bool


@dataclass
class Catalogue:
    places: dict[str, Place]
    hubs: dict[str, HubInfo]
    backbone: Backbone

    def gateways_in(self, area: str) -> list[HubInfo]:
        return [h for h in self.hubs.values() if h.is_gateway and h.area == area]

    def find(self, name_or_slug: str) -> Place | None:
        key = name_or_slug.strip().lower()
        if key in self.places:
            return self.places[key]
        for place in self.places.values():
            if place.name.lower() == key or place.slug.replace("-", " ") == key:
                return place
        return None


@dataclass(frozen=True)
class Reaction:
    kind: ReactionKind
    stops: tuple[str, ...]


@dataclass(frozen=True)
class Conditions:
    """What the traveller told us. ``None`` means "Not decided yet"."""

    month: int | None = None
    regional_nights: int | None = None
    arrival_hub: str | None = None
    departure_hub: str | None = None
    interests: tuple[str, ...] = ()
    visited: tuple[str, ...] = ()
    transport: Transport = Transport.NO_CAR
    pace: Pace = Pace.BALANCED
    big_luggage: bool = False
    kids: bool = False
    limited_walking: bool = False
    must_include: tuple[str, ...] = ()
    avoid: tuple[Avoid, ...] = ()
    reactions: tuple[Reaction, ...] = ()

    def with_(self, **changes: object) -> Conditions:
        return replace(self, **changes)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Assumption:
    field: str
    value: str
    label: str


@dataclass(frozen=True)
class Resolved:
    """Conditions with every undecided value filled in, and the fill-ins listed."""

    conditions: Conditions
    month: int
    nights: int
    arrival: str
    departure: str
    assumptions: tuple[Assumption, ...] = field(default_factory=tuple)

    @property
    def can_drive(self) -> bool:
        return self.conditions.transport is not Transport.NO_CAR
