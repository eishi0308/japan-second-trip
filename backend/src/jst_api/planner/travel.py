"""Moving time for a sequence of stops, from the M1 backbone.

Between two destinations the model goes via their hubs: the last stretch out
of the first, the backbone journey, the last stretch into the second, with a
change at each hub. Where two places share a hub that over-counts a little
(the real local hop can be shorter). That is the conservative direction: the
planner may call a trip slightly heavier than it is, never lighter.

Hub links are stored in both directions with the same time, so the journey
back to the departure hub is the same as the journey out of it.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from jst_api.domain.backbone import CHANGE_MINUTES, Backbone
from jst_api.planner.model import Catalogue, Place


@dataclass(frozen=True)
class MoveLeg:
    origin: str
    destination: str
    minutes: int
    transfers: int


@dataclass(frozen=True)
class RouteTime:
    legs: tuple[MoveLeg, ...]

    @property
    def minutes(self) -> int:
        return sum(leg.minutes for leg in self.legs)

    @property
    def transfers(self) -> int:
        return sum(leg.transfers for leg in self.legs)

    @property
    def longest_leg(self) -> MoveLeg:
        return max(self.legs, key=lambda leg: leg.minutes)


class TravelModel:
    """Cached travel times over one catalogue."""

    def __init__(self, catalogue: Catalogue) -> None:
        self._catalogue = catalogue
        self._backbone: Backbone = catalogue.backbone
        self._hub_cache: dict[tuple[str, str], tuple[int, int] | None] = {}

    def _hubs(self, a: str, b: str) -> tuple[int, int] | None:
        key = (a, b) if a <= b else (b, a)
        if key not in self._hub_cache:
            journey = self._backbone.journey(*key)
            self._hub_cache[key] = None if journey is None else (journey.minutes, journey.transfers)
        return self._hub_cache[key]

    def hub_to_place(self, hub: str, place: Place) -> tuple[int, int] | None:
        """Minutes and transfers from a hub to a destination (or back)."""
        base = self._hubs(hub, place.hub_slug)
        if base is None:
            return None
        minutes, transfers = base
        change = 1 if hub != place.hub_slug and place.access_mode != "walk" else 0
        return (
            minutes + place.hub_minutes + CHANGE_MINUTES * change,
            transfers + place.hub_transfers + change,
        )

    def between(self, a: Place, b: Place) -> tuple[int, int] | None:
        if a.slug == b.slug:
            return (0, 0)
        base = self._hubs(a.hub_slug, b.hub_slug)
        if base is None:
            return None
        minutes, transfers = base
        changes = 1 if a.hub_slug == b.hub_slug else 2
        return (
            minutes + a.hub_minutes + b.hub_minutes + CHANGE_MINUTES * changes,
            transfers + a.hub_transfers + b.hub_transfers + changes,
        )

    def route(self, arrival: str, stops: Sequence[Place], departure: str) -> RouteTime | None:
        """Arrival hub -> each stop in order -> departure hub."""
        if not stops:
            return None
        legs: list[MoveLeg] = []
        first = self.hub_to_place(arrival, stops[0])
        if first is None:
            return None
        legs.append(MoveLeg(arrival, stops[0].slug, *first))
        for a, b in itertools.pairwise(stops):
            hop = self.between(a, b)
            if hop is None:
                return None
            legs.append(MoveLeg(a.slug, b.slug, *hop))
        last = self.hub_to_place(departure, stops[-1])
        if last is None:
            return None
        legs.append(MoveLeg(stops[-1].slug, departure, *last))
        return RouteTime(tuple(legs))

    def hub_name(self, slug: str) -> str:
        hub = self._catalogue.hubs.get(slug)
        return hub.name if hub else slug.replace("-", " ").title()
