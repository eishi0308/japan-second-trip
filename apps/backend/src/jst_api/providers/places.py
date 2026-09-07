"""Place resolution.

``DemoPlaceProvider`` resolves against the seeded ``places`` table (exact slug,
exact name, alias, then trigram-ish fuzzy match). ``GooglePlacesProvider`` is
the live adapter; it is only constructed when a key is present and it still
prefers a local match first, because the local catalogue carries the region and
transport metadata the rules engine needs and an external geocoder does not.
"""

from __future__ import annotations

import difflib
import time
from typing import Any

import httpx
from sqlalchemy import func, or_, select

from jst_api.core.cache import Cache, cache_key
from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.core.resilience import CircuitBreaker, RetryPolicy, call_with_resilience
from jst_api.db.models import Place
from jst_api.providers.base import PlaceResult, ProviderMeta

log = get_logger(__name__)

#: Common English/romaji noise that should not defeat a name match.
_STOPWORDS = {"the", "city", "station", "onsen", "town", "prefecture", "japan"}


def _norm(text: str) -> str:
    return " ".join(w for w in text.lower().replace("-", " ").replace("_", " ").split() if w)


def _place_to_result(
    place: Place,
    provider: str,
    is_demo: bool,
    confidence: float = 1.0,
    match_kind: str = "exact",
) -> PlaceResult:
    return PlaceResult(
        slug=place.slug,
        name=place.name,
        name_ja=place.name_ja,
        lat=place.lat,
        lon=place.lon,
        region_code=place.region_code,
        prefecture=place.prefecture,
        place_kind=place.place_kind,
        nearest_station=place.nearest_station,
        summary=place.summary,
        tags=list(place.tags or []),
        car_recommended=place.car_recommended,
        confidence=confidence,
        match_kind=match_kind,  # type: ignore[arg-type]
        meta=ProviderMeta(provider=provider, is_demo=is_demo),
    )


#: Trusted match kinds outrank edit distance, whatever the numbers say.
_KIND_RANK = {"exact": 2, "contains": 1, "fuzzy": 0}


class DemoPlaceProvider:
    name = "demo-catalogue"
    is_demo = True

    def __init__(self, session_factory: Any, cache: Cache | None = None) -> None:
        self._session_factory = session_factory
        self._cache = cache

    async def _all_places(self) -> list[Place]:
        async with self._session_factory() as session:
            return list((await session.scalars(select(Place))).all())

    async def resolve_place(self, query: str) -> PlaceResult | None:
        if not query or not query.strip():
            return None
        key = cache_key("place-resolve", {"q": query.strip().lower()})
        if self._cache:
            hit = await self._cache.get(key)
            if hit is not None:
                return PlaceResult.model_validate(hit)

        normalised = _norm(query)
        async with self._session_factory() as session:
            exact = await session.scalar(
                select(Place).where(
                    or_(
                        Place.slug == normalised.replace(" ", "-"),
                        func.lower(Place.name) == normalised,
                    )
                )
            )
        result: PlaceResult | None = None
        if exact is not None:
            result = _place_to_result(exact, self.name, self.is_demo, 1.0)
        else:
            places = await self._all_places()
            best: tuple[float, Place, str] | None = None
            for place in places:
                candidates = [
                    _norm(place.name),
                    _norm(place.slug),
                    *(_norm(a) for a in (place.aliases or [])),
                ]
                if place.name_ja:
                    candidates.append(place.name_ja)
                for cand in candidates:
                    if not cand:
                        continue
                    kind = "fuzzy"
                    if normalised == cand:
                        score, kind = 1.0, "exact"
                    elif normalised in cand or cand in normalised:
                        score, kind = 0.9, "contains"
                    else:
                        stripped_q = " ".join(w for w in normalised.split() if w not in _STOPWORDS)
                        stripped_c = " ".join(w for w in cand.split() if w not in _STOPWORDS)
                        score = difflib.SequenceMatcher(
                            None, stripped_q or normalised, stripped_c or cand
                        ).ratio()
                    # Rank by *kind* first, then score. Otherwise a trusted
                    # substring match on the right place (0.9) could be shadowed
                    # by a higher-scoring edit-distance match on a different one,
                    # and then refused for being fuzzy — losing a good answer to
                    # a worse candidate.
                    if best is None or (_KIND_RANK[kind], score) > (_KIND_RANK[best[2]], best[0]):
                        best = (score, place, kind)
            if best and best[0] >= 0.72:
                result = _place_to_result(
                    best[1], self.name, self.is_demo, round(best[0], 3), best[2]
                )

        if result and self._cache:
            await self._cache.set(key, result.model_dump(mode="json"), ttl=3600)
        return result

    async def get_place_details(self, slug: str) -> PlaceResult | None:
        async with self._session_factory() as session:
            place = await session.scalar(select(Place).where(Place.slug == slug))
        return _place_to_result(place, self.name, self.is_demo) if place else None


class GooglePlacesProvider:
    """Live geocoding. Falls back to the local catalogue on any failure."""

    name = "google-places"
    is_demo = False

    def __init__(
        self, settings: Settings, fallback: DemoPlaceProvider, cache: Cache | None = None
    ) -> None:
        if not settings.google_maps_api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is required for the Google place provider")
        self._key = settings.google_maps_api_key
        self._fallback = fallback
        self._cache = cache
        self._timeout = settings.external_timeout_seconds
        self._policy = RetryPolicy(max_attempts=settings.external_max_retries + 1)
        self._breaker = CircuitBreaker("google-places")

    async def resolve_place(self, query: str) -> PlaceResult | None:
        # The local catalogue wins when it knows the place: it carries region,
        # transport and constraint metadata the geocoder cannot supply.
        local = await self._fallback.resolve_place(query)
        if local and local.confidence >= 0.9:
            return local

        key = cache_key("google-place", {"q": query.lower()})
        if self._cache:
            hit = await self._cache.get(key)
            if hit is not None:
                return PlaceResult.model_validate(hit)

        started = time.perf_counter()

        async def _call() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/textsearch/json",
                    params={"query": f"{query} Japan", "key": self._key, "region": "jp"},
                )
                resp.raise_for_status()
                return resp.json()

        try:
            data = await call_with_resilience(
                _call,
                name="google-places",
                timeout=self._timeout,
                policy=self._policy,
                breaker=self._breaker,
            )
        except Exception as exc:
            log.warning("places.google_failed_using_catalogue", error=str(exc))
            return local

        results = data.get("results") or []
        if not results:
            return local
        top = results[0]
        loc = top["geometry"]["location"]
        result = PlaceResult(
            slug=_norm(top["name"]).replace(" ", "-"),
            name=top["name"],
            lat=loc["lat"],
            lon=loc["lng"],
            place_kind="poi",
            summary=top.get("formatted_address", ""),
            confidence=0.85,
            meta=ProviderMeta(
                provider=self.name,
                is_demo=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        if self._cache:
            await self._cache.set(key, result.model_dump(mode="json"), ttl=86400)
        return result

    async def get_place_details(self, slug: str) -> PlaceResult | None:
        return await self._fallback.get_place_details(slug)
