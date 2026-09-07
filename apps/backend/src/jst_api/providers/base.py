"""Provider interfaces.

Every external capability is behind a Protocol with:
  * a real adapter used when credentials are configured,
  * a ``Demo*`` adapter used otherwise,
  * a timeout, bounded retries and a circuit breaker (``core/resilience.py``),
  * cache-ability declared by the caller,
  * a ``name`` and ``is_demo`` flag that propagate into results so the UI can
    label demo data honestly.

The application must never hard-depend on one proprietary provider being
reachable — see docs/adr/0008-provider-abstraction.md.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from jst_api.domain.enums import TransportMode


class ProviderMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    is_demo: bool = True
    cached: bool = False
    latency_ms: int = 0
    fetched_at: str | None = None


class PlaceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    name_ja: str | None = None
    lat: float
    lon: float
    region_code: str | None = None
    prefecture: str | None = None
    place_kind: str = "town"
    nearest_station: str | None = None
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    car_recommended: bool = False
    confidence: float = 1.0
    #: How the name was matched: ``exact`` (name/slug/alias equality),
    #: ``contains`` (one name inside the other, e.g. "Kanazawa city"), or
    #: ``fuzzy`` (edit-distance only). The score alone cannot be trusted to
    #: separate a typo from a different place — "Sendia"→"Sendai" and
    #: "Narnia"→"narita" both score 0.833 — so the *kind* of match is what
    #: callers gate on.
    match_kind: Literal["exact", "contains", "fuzzy"] = "exact"
    meta: ProviderMeta


class TransportOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TransportMode
    duration_minutes: int
    transfers: int = 0
    distance_km: float | None = None
    requires_car: bool = False
    last_departure_local: str | None = None
    final_leg_minutes: int | None = None
    frequency_per_day: int | None = None
    operator: str | None = None
    is_estimate: bool = False
    notes: str | None = None
    meta: ProviderMeta


class WeatherContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_slug: str
    month: int
    typical_high_c: float
    typical_low_c: float
    rain_days: int
    snow_likely: bool = False
    summary: str = ""
    meta: ProviderMeta


class LLMUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    fell_back: bool = False


class LLMResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    parsed: dict[str, Any] | None = None
    usage: LLMUsage


@runtime_checkable
class PlaceProvider(Protocol):
    name: str
    is_demo: bool

    async def resolve_place(self, query: str) -> PlaceResult | None: ...
    async def get_place_details(self, slug: str) -> PlaceResult | None: ...


@runtime_checkable
class TransportProvider(Protocol):
    name: str
    is_demo: bool

    async def search_transport(
        self,
        from_slug: str,
        to_slug: str,
        *,
        travel_date: date | None = None,
        allow_car: bool = True,
    ) -> list[TransportOption]: ...


@runtime_checkable
class WeatherProvider(Protocol):
    name: str
    is_demo: bool

    async def get_weather_context(self, place_slug: str, month: int) -> WeatherContext | None: ...


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    is_demo: bool

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[BaseModel, LLMUsage]: ...

    async def complete_text(
        self, *, system: str, user: str, model: str | None = None, max_tokens: int | None = None
    ) -> LLMResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    is_demo: bool
    dim: int
    model: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
