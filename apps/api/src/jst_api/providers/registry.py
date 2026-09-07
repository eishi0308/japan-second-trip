"""Provider container.

One object assembled at startup and injected everywhere. It records, for each
capability, whether the live adapter or the demo adapter is in use — that flag
propagates all the way to the ``demo_mode`` badge in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jst_api.core.cache import Cache, build_cache
from jst_api.core.config import Settings, get_settings
from jst_api.core.logging import get_logger
from jst_api.providers.embeddings import build_embedding_provider
from jst_api.providers.llm import DemoLLMProvider, ModelRouter, build_llm_provider
from jst_api.providers.places import DemoPlaceProvider, GooglePlacesProvider
from jst_api.providers.transport import DemoTransportProvider, GoogleDirectionsProvider
from jst_api.providers.weather import DemoWeatherProvider, OpenMeteoWeatherProvider

log = get_logger(__name__)


@dataclass
class ProviderRegistry:
    settings: Settings
    cache: Cache
    llm: Any
    embeddings: Any
    places: Any
    transport: Any
    weather: Any
    router: ModelRouter

    @property
    def demo_flags(self) -> dict[str, bool]:
        return {
            "llm": bool(getattr(self.llm, "is_demo", True)),
            "embeddings": bool(getattr(self.embeddings, "is_demo", True)),
            "places": bool(getattr(self.places, "is_demo", True)),
            "transport": bool(getattr(self.transport, "is_demo", True)),
            "weather": bool(getattr(self.weather, "is_demo", True)),
        }

    @property
    def any_demo(self) -> bool:
        return any(self.demo_flags.values())

    def describe(self) -> dict[str, dict[str, Any]]:
        return {
            "llm": {"provider": getattr(self.llm, "name", "?"), "demo": self.demo_flags["llm"]},
            "embeddings": {
                "provider": getattr(self.embeddings, "name", "?"),
                "model": getattr(self.embeddings, "model", "?"),
                "demo": self.demo_flags["embeddings"],
            },
            "places": {
                "provider": getattr(self.places, "name", "?"),
                "demo": self.demo_flags["places"],
            },
            "transport": {
                "provider": getattr(self.transport, "name", "?"),
                "demo": self.demo_flags["transport"],
            },
            "weather": {
                "provider": getattr(self.weather, "name", "?"),
                "demo": self.demo_flags["weather"],
            },
        }


def build_registry(session_factory: Any, settings: Settings | None = None) -> ProviderRegistry:
    settings = settings or get_settings()
    cache = build_cache(settings.redis_url, settings.cache_ttl_seconds, settings.cache_max_entries)

    demo_places = DemoPlaceProvider(session_factory, cache)
    demo_transport = DemoTransportProvider(session_factory, cache)
    demo_weather = DemoWeatherProvider(session_factory)

    places: Any = demo_places
    if settings.place_provider == "google":
        try:
            places = GooglePlacesProvider(settings, demo_places, cache)
        except Exception as exc:
            log.warning("providers.google_places_unavailable", error=str(exc))

    transport: Any = demo_transport
    if settings.transport_provider == "google":
        try:
            transport = GoogleDirectionsProvider(settings, demo_transport, cache)
        except Exception as exc:
            log.warning("providers.google_directions_unavailable", error=str(exc))

    weather: Any = demo_weather
    if settings.weather_provider == "openmeteo":
        try:
            weather = OpenMeteoWeatherProvider(settings, demo_weather, cache)
        except Exception as exc:
            log.warning("providers.openmeteo_unavailable", error=str(exc))

    registry = ProviderRegistry(
        settings=settings,
        cache=cache,
        llm=build_llm_provider(settings),
        embeddings=build_embedding_provider(settings, cache),
        places=places,
        transport=transport,
        weather=weather,
        router=ModelRouter(settings),
    )
    log.info("providers.ready", **{k: v["provider"] for k, v in registry.describe().items()})
    return registry


def build_demo_registry(session_factory: Any, settings: Settings | None = None) -> ProviderRegistry:
    """Force every capability onto its demo adapter. Used by tests and evals so
    results are reproducible regardless of what credentials happen to be set."""
    settings = settings or get_settings()
    cache = build_cache(None, settings.cache_ttl_seconds, settings.cache_max_entries)
    from jst_api.providers.embeddings import DemoEmbeddingProvider

    return ProviderRegistry(
        settings=settings,
        cache=cache,
        llm=DemoLLMProvider(settings),
        embeddings=DemoEmbeddingProvider(dim=settings.embedding_dim),
        places=DemoPlaceProvider(session_factory, cache),
        transport=DemoTransportProvider(session_factory, cache),
        weather=DemoWeatherProvider(session_factory),
        router=ModelRouter(settings),
    )
