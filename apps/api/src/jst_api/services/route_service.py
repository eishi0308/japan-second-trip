"""Turning a list of place names into a costed, checkable route.

This is the join between the place catalogue, the transport provider and the
deterministic rules engine. It is the only place that constructs
``domain.route.Route`` objects, so every route in the system has real durations
attached to it, sourced the same way and labelled the same way.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date
from typing import Any

from jst_api.core.logging import get_logger
from jst_api.domain.enums import PUBLIC_MODES, TransportMode
from jst_api.domain.route import Route, RouteSegment, RouteStop
from jst_api.providers.base import TransportOption

log = get_logger(__name__)


@dataclass
class ResolvedStop:
    raw_name: str
    slug: str | None
    display_name: str
    lat: float | None
    lon: float | None
    region_code: str | None
    confidence: float
    resolved: bool
    note: str | None = None


class RouteService:
    def __init__(self, places: Any, transport: Any) -> None:
        self._places = places
        self._transport = transport

    async def resolve_stops(self, names: list[str]) -> list[ResolvedStop]:
        resolved: list[ResolvedStop] = []
        for name in names:
            place = await self._places.resolve_place(name)
            if place is None:
                resolved.append(
                    ResolvedStop(
                        raw_name=name,
                        slug=None,
                        display_name=name,
                        lat=None,
                        lon=None,
                        region_code=None,
                        confidence=0.0,
                        resolved=False,
                        note="Not found in the place catalogue — excluded from transport and rule checks.",
                    )
                )
                continue
            resolved.append(
                ResolvedStop(
                    raw_name=name,
                    slug=place.slug,
                    display_name=place.name,
                    lat=place.lat,
                    lon=place.lon,
                    region_code=place.region_code,
                    confidence=place.confidence,
                    resolved=True,
                    note=None
                    if place.confidence >= 0.95
                    else f"Matched '{name}' to {place.name} ({place.confidence:.0%} confidence).",
                )
            )
        return resolved

    @staticmethod
    def _pick_option(options: list[TransportOption], *, allow_car: bool) -> TransportOption | None:
        if not options:
            return None
        public = [o for o in options if o.mode in PUBLIC_MODES and not o.requires_car]
        if public:
            # Prefer a verified record over an estimate even if it is slower —
            # a real number that is worse is more useful than a fast guess.
            verified = [o for o in public if not o.is_estimate]
            pool = verified or public
            return min(pool, key=lambda o: o.duration_minutes)
        if allow_car:
            return min(options, key=lambda o: o.duration_minutes)
        return min(options, key=lambda o: o.duration_minutes)

    async def build_route(
        self,
        names: list[str],
        nights: list[int],
        *,
        allow_car: bool = True,
        arrival_city: str | None = None,
        departure_city: str | None = None,
        travel_date: date | None = None,
    ) -> tuple[Route, list[ResolvedStop]]:
        resolved = await self.resolve_stops(names)
        padded_nights = list(nights) + [0] * max(0, len(names) - len(nights))

        stops = [
            RouteStop(
                order=i,
                raw_name=r.raw_name,
                place_slug=r.slug,
                display_name=r.display_name,
                nights=int(padded_nights[i]) if i < len(padded_nights) else 0,
                region_code=r.region_code,
                lat=r.lat,
                lon=r.lon,
                resolved=r.resolved,
                resolution_note=r.note,
            )
            for i, r in enumerate(resolved)
        ]

        segments: list[RouteSegment] = []
        for a, b in itertools.pairwise(stops):
            if not (a.place_slug and b.place_slug):
                continue
            options = await self._transport.search_transport(
                a.place_slug, b.place_slug, travel_date=travel_date, allow_car=allow_car
            )
            option = self._pick_option(options, allow_car=allow_car)
            if option is None:
                log.warning("route.no_transport_option", frm=a.place_slug, to=b.place_slug)
                continue
            segments.append(
                RouteSegment(
                    from_order=a.order,
                    to_order=b.order,
                    from_name=a.name,
                    to_name=b.name,
                    mode=TransportMode(option.mode),
                    duration_minutes=option.duration_minutes,
                    transfers=option.transfers,
                    distance_km=option.distance_km,
                    requires_car=option.requires_car,
                    last_departure_local=option.last_departure_local
                    if not option.is_estimate
                    else None,
                    final_leg_minutes=option.final_leg_minutes if not option.is_estimate else None,
                    provider=option.meta.provider,
                    is_estimate=option.is_estimate,
                    notes=option.notes,
                )
            )

        route = Route(
            stops=stops,
            segments=segments,
            arrival_city=arrival_city or (stops[0].name if stops else None),
            departure_city=departure_city or (stops[-1].name if stops else None),
        )
        return route, resolved

    async def cost_candidate(
        self,
        stops: list[str],
        nights: list[int],
        *,
        allow_car: bool,
        arrival_city: str | None,
        departure_city: str | None,
    ) -> Route:
        route, _ = await self.build_route(
            stops,
            nights,
            allow_car=allow_car,
            arrival_city=arrival_city,
            departure_city=departure_city,
        )
        return route
