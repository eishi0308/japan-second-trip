"""Intercity backbone: deterministic travel time between hubs and to destinations.

Pure code, no I/O. The repository builds a ``Backbone`` from ``hub_links``,
and Where Next and RouteCheck ask it how far a destination really is from the
traveller's arrival and departure cities. No LLM is involved: it is a
shortest-path search over a few dozen hubs, and the answer must be
reproducible.

Journey time = the sum of leg times + ``CHANGE_MINUTES`` for each change
between legs. Leg times already include the transfers inside them
(``HubLink.transfers``). The search minimises journey time, and breaks ties on
fewer transfers.
"""

from __future__ import annotations

import heapq
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

CHANGE_MINUTES = 20
"""Time allowed for each change between two backbone legs."""


@dataclass(frozen=True)
class Leg:
    from_hub: str
    to_hub: str
    mode: str
    minutes: int
    transfers: int = 0


@dataclass(frozen=True)
class Journey:
    """A hub-to-hub journey. A journey from a hub to itself has no legs."""

    origin: str
    destination: str
    legs: tuple[Leg, ...] = ()

    @property
    def minutes(self) -> int:
        changes = max(len(self.legs) - 1, 0)
        return sum(leg.minutes for leg in self.legs) + CHANGE_MINUTES * changes

    @property
    def transfers(self) -> int:
        changes = max(len(self.legs) - 1, 0)
        return sum(leg.transfers for leg in self.legs) + changes

    @property
    def modes(self) -> tuple[str, ...]:
        return tuple(leg.mode for leg in self.legs)


@dataclass(frozen=True)
class DestinationAccess:
    """The last stretch from a destination's hub, as stored on ``destinations``."""

    slug: str
    hub_slug: str
    hub_minutes: int
    hub_transfers: int = 0
    access_mode: str = "local_train"


@dataclass(frozen=True)
class AccessTime:
    """From a hub to a destination: backbone journey plus the last stretch."""

    journey: Journey
    destination: DestinationAccess
    minutes: int
    transfers: int


@dataclass
class Backbone:
    legs: Iterable[Leg]
    _adjacency: dict[str, list[Leg]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for leg in self.legs:
            self._adjacency.setdefault(leg.from_hub, []).append(leg)
            self._adjacency.setdefault(leg.to_hub, [])

    @property
    def hubs(self) -> frozenset[str]:
        return frozenset(self._adjacency)

    def journey(
        self, origin: str, destination: str, *, modes: Collection[str] | None = None
    ) -> Journey | None:
        """Fastest journey between two hubs, or ``None`` if none exists.

        ``modes`` restricts the legs used, for example to leave out flights.
        """
        if origin not in self._adjacency or destination not in self._adjacency:
            return None
        if origin == destination:
            return Journey(origin, destination)

        # (minutes, transfers, tie-break counter, hub, legs so far)
        counter = 0
        frontier: list[tuple[int, int, int, str, tuple[Leg, ...]]] = [(0, 0, counter, origin, ())]
        best: dict[str, tuple[int, int]] = {origin: (0, 0)}
        while frontier:
            minutes, transfers, _, hub, legs = heapq.heappop(frontier)
            if hub == destination:
                return Journey(origin, destination, legs)
            if best.get(hub, (minutes, transfers)) < (minutes, transfers):
                continue
            for leg in self._adjacency[hub]:
                if modes is not None and leg.mode not in modes:
                    continue
                change = 1 if legs else 0
                cost = (
                    minutes + leg.minutes + CHANGE_MINUTES * change,
                    transfers + leg.transfers + change,
                )
                if cost < best.get(leg.to_hub, (10**9, 10**9)):
                    best[leg.to_hub] = cost
                    counter += 1
                    heapq.heappush(frontier, (*cost, counter, leg.to_hub, (*legs, leg)))
        return None

    def access(
        self,
        origin_hub: str,
        destination: DestinationAccess,
        *,
        modes: Collection[str] | None = None,
    ) -> AccessTime | None:
        """Time from ``origin_hub`` to a destination, via the destination's own hub."""
        journey = self.journey(origin_hub, destination.hub_slug, modes=modes)
        if journey is None:
            return None
        last_stretch_change = 1 if journey.legs and destination.access_mode != "walk" else 0
        return AccessTime(
            journey=journey,
            destination=destination,
            minutes=journey.minutes
            + destination.hub_minutes
            + CHANGE_MINUTES * last_stretch_change,
            transfers=journey.transfers + destination.hub_transfers + last_stretch_change,
        )
