"""Transport search.

Durations are the single most safety-critical number in this product, so they
are only ever produced in one of three ways, in priority order:

1. a **verified structured record** in ``transport_constraints`` (seeded or
   admin-verified, with ``verified_at``);
2. a **live provider** response (Google Directions), when a key is configured;
3. a **clearly-labelled geometric estimate** (``is_estimate=True``) derived from
   great-circle distance and a mode-specific effective speed.

The language model never produces one. Estimates are surfaced to the user as
estimates and never used to assert a last-connection time.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx
from sqlalchemy import or_, select

from jst_api.core.cache import Cache, cache_key
from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.core.resilience import CircuitBreaker, RetryPolicy, call_with_resilience
from jst_api.db.models import Place, TransportConstraint
from jst_api.domain.enums import TransportMode
from jst_api.domain.geo import LatLon, haversine_km
from jst_api.providers.base import ProviderMeta, TransportOption

log = get_logger(__name__)

#: Effective door-to-door speed in km/h including access, waiting and transfers.
#: Deliberately conservative — an estimate that flatters the itinerary is worse
#: than one that is slightly pessimistic.
MODE_EFFECTIVE_KMH: dict[TransportMode, float] = {
    TransportMode.SHINKANSEN: 140.0,
    TransportMode.LIMITED_EXPRESS: 75.0,
    TransportMode.LOCAL_TRAIN: 45.0,
    TransportMode.HIGHWAY_BUS: 55.0,
    TransportMode.LOCAL_BUS: 28.0,
    TransportMode.FERRY: 32.0,
    TransportMode.FLIGHT: 260.0,
    TransportMode.CAR: 58.0,
}
#: Fixed overhead per mode in minutes (check-in, access, typical wait).
MODE_OVERHEAD_MIN: dict[TransportMode, int] = {
    TransportMode.SHINKANSEN: 35,
    TransportMode.LIMITED_EXPRESS: 30,
    TransportMode.LOCAL_TRAIN: 20,
    TransportMode.HIGHWAY_BUS: 30,
    TransportMode.LOCAL_BUS: 20,
    TransportMode.FERRY: 60,
    TransportMode.FLIGHT: 180,
    TransportMode.CAR: 15,
}


def estimate_option(distance_km: float, mode: TransportMode, provider: str) -> TransportOption:
    speed = MODE_EFFECTIVE_KMH[mode]
    minutes = round(distance_km / speed * 60) + MODE_OVERHEAD_MIN[mode]
    transfers = (
        0 if mode in (TransportMode.CAR, TransportMode.FLIGHT) else max(0, int(distance_km // 220))
    )
    return TransportOption(
        mode=mode,
        duration_minutes=minutes,
        transfers=transfers,
        distance_km=round(distance_km, 1),
        requires_car=mode is TransportMode.CAR,
        is_estimate=True,
        notes="Geometric estimate — not a timetabled journey. Confirm before booking.",
        meta=ProviderMeta(provider=provider, is_demo=True),
    )


def _plausible_modes(distance_km: float) -> list[TransportMode]:
    if distance_km < 25:
        return [TransportMode.LOCAL_TRAIN, TransportMode.LOCAL_BUS, TransportMode.CAR]
    if distance_km < 120:
        return [TransportMode.LIMITED_EXPRESS, TransportMode.LOCAL_TRAIN, TransportMode.CAR]
    if distance_km < 600:
        return [TransportMode.SHINKANSEN, TransportMode.HIGHWAY_BUS, TransportMode.CAR]
    return [TransportMode.FLIGHT, TransportMode.SHINKANSEN]


class DemoTransportProvider:
    """Seeded verified records first, geometric estimate as a labelled fallback."""

    name = "demo-transport"
    is_demo = True

    def __init__(self, session_factory: Any, cache: Cache | None = None) -> None:
        self._session_factory = session_factory
        self._cache = cache

    async def search_transport(
        self,
        from_slug: str,
        to_slug: str,
        *,
        travel_date: date | None = None,
        allow_car: bool = True,
    ) -> list[TransportOption]:
        key = cache_key("transport", {"f": from_slug, "t": to_slug, "car": allow_car})
        if self._cache:
            hit = await self._cache.get(key)
            if hit is not None:
                return [TransportOption.model_validate(o) for o in hit]

        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(TransportConstraint).where(
                            or_(
                                (TransportConstraint.from_slug == from_slug)
                                & (TransportConstraint.to_slug == to_slug),
                                (TransportConstraint.from_slug == to_slug)
                                & (TransportConstraint.to_slug == from_slug),
                            )
                        )
                    )
                ).all()
            )
            places = list(
                (
                    await session.scalars(select(Place).where(Place.slug.in_([from_slug, to_slug])))
                ).all()
            )

        options: list[TransportOption] = []
        car_only_rows: list[TransportConstraint] = []
        for row in rows:
            mode = TransportMode(row.mode)
            if mode is TransportMode.CAR and not allow_car:
                # Keep it aside: a hop we KNOW is car-only must surface as
                # car-required, not be replaced by an invented public estimate.
                car_only_rows.append(row)
                continue
            options.append(
                TransportOption(
                    mode=mode,
                    duration_minutes=row.duration_minutes,
                    transfers=row.transfers,
                    distance_km=row.distance_km,
                    requires_car=row.requires_car,
                    last_departure_local=row.last_departure_local,
                    final_leg_minutes=row.final_leg_minutes,
                    frequency_per_day=row.frequency_per_day,
                    operator=row.operator,
                    is_estimate=False,
                    notes=row.seasonal_note,
                    meta=ProviderMeta(
                        provider=self.name,
                        is_demo=row.is_demo,
                        fetched_at=row.verified_at.isoformat() if row.verified_at else None,
                    ),
                )
            )

        if not options and car_only_rows:
            # We have verified knowledge of this pair and every option needs a
            # car. Returning a geometric "train" estimate here would fabricate a
            # service that does not exist and silence rule R05_car_required.
            row = min(car_only_rows, key=lambda r: r.duration_minutes)
            options.append(
                TransportOption(
                    mode=TransportMode.CAR,
                    duration_minutes=row.duration_minutes,
                    transfers=row.transfers,
                    distance_km=row.distance_km,
                    requires_car=True,
                    frequency_per_day=row.frequency_per_day,
                    operator=row.operator,
                    is_estimate=False,
                    notes=row.seasonal_note
                    or "No practical public-transport equivalent on this hop.",
                    meta=ProviderMeta(
                        provider=self.name,
                        is_demo=row.is_demo,
                        fetched_at=row.verified_at.isoformat() if row.verified_at else None,
                    ),
                )
            )
        elif not options:
            # No knowledge of this pair at all — a labelled geometric estimate is
            # the honest fallback.
            by_slug = {p.slug: p for p in places}
            a, b = by_slug.get(from_slug), by_slug.get(to_slug)
            if a and b:
                distance = haversine_km(LatLon(a.lat, a.lon), LatLon(b.lat, b.lon))
                for mode in _plausible_modes(distance):
                    if mode is TransportMode.CAR and not allow_car:
                        continue
                    options.append(estimate_option(distance, mode, self.name))

        options.sort(key=lambda o: (o.requires_car and not allow_car, o.duration_minutes))
        if self._cache:
            await self._cache.set(key, [o.model_dump(mode="json") for o in options], ttl=1800)
        return options


class GoogleDirectionsProvider:
    """Live transit routing. Verified seeded records still win when present."""

    name = "google-directions"
    is_demo = False

    def __init__(
        self, settings: Settings, fallback: DemoTransportProvider, cache: Cache | None = None
    ) -> None:
        if not settings.google_maps_api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is required for the Google transport provider")
        self._key = settings.google_maps_api_key
        self._fallback = fallback
        self._cache = cache
        self._timeout = settings.external_timeout_seconds
        self._policy = RetryPolicy(max_attempts=settings.external_max_retries + 1)
        self._breaker = CircuitBreaker("google-directions")

    async def search_transport(
        self,
        from_slug: str,
        to_slug: str,
        *,
        travel_date: date | None = None,
        allow_car: bool = True,
    ) -> list[TransportOption]:
        seeded = await self._fallback.search_transport(
            from_slug, to_slug, travel_date=travel_date, allow_car=allow_car
        )
        verified = [o for o in seeded if not o.is_estimate]
        if verified:
            return seeded

        key = cache_key("gdir", {"f": from_slug, "t": to_slug, "d": str(travel_date)})
        if self._cache:
            hit = await self._cache.get(key)
            if hit is not None:
                return [TransportOption.model_validate(o) for o in hit]

        started = time.perf_counter()

        async def _call() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/directions/json",
                    params={
                        "origin": f"{from_slug}, Japan",
                        "destination": f"{to_slug}, Japan",
                        "mode": "transit",
                        "key": self._key,
                    },
                )
                resp.raise_for_status()
                return resp.json()

        try:
            data = await call_with_resilience(
                _call,
                name="google-directions",
                timeout=self._timeout,
                policy=self._policy,
                breaker=self._breaker,
            )
        except Exception as exc:
            log.warning("transport.google_failed_using_estimates", error=str(exc))
            return seeded

        routes = data.get("routes") or []
        if not routes:
            return seeded
        leg = routes[0]["legs"][0]
        steps = leg.get("steps", [])
        transit_steps = [s for s in steps if s.get("travel_mode") == "TRANSIT"]
        option = TransportOption(
            mode=TransportMode.LOCAL_TRAIN,
            duration_minutes=int(leg["duration"]["value"] / 60),
            transfers=max(0, len(transit_steps) - 1),
            distance_km=round(leg["distance"]["value"] / 1000, 1),
            is_estimate=False,
            operator="Google Directions (transit)",
            meta=ProviderMeta(
                provider=self.name,
                is_demo=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        result = [option, *[o for o in seeded if o.mode is TransportMode.CAR and allow_car]]
        if self._cache:
            await self._cache.set(key, [o.model_dump(mode="json") for o in result], ttl=3600)
        return result
