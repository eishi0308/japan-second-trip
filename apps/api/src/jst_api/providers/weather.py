"""Seasonal weather context.

Weather is *context*, not a constraint: it nudges the seasonal component of the
fit score's explanation and warns about snow closures. It never overrides a
deterministic rule.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from jst_api.core.cache import Cache, cache_key
from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.core.resilience import CircuitBreaker, RetryPolicy, call_with_resilience
from jst_api.db.models import Place
from jst_api.providers.base import ProviderMeta, WeatherContext

log = get_logger(__name__)

#: Coarse climate normals by latitude band and month. Enough to say "expect
#: snow" or "expect a wet, humid week" without pretending to be a forecast.
_MONTH_BASE: dict[int, tuple[float, float, int]] = {
    1: (8.0, -1.0, 9),
    2: (9.0, -1.0, 8),
    3: (13.0, 3.0, 10),
    4: (19.0, 9.0, 10),
    5: (23.0, 14.0, 10),
    6: (26.0, 19.0, 13),
    7: (30.0, 23.0, 12),
    8: (32.0, 24.0, 10),
    9: (28.0, 21.0, 12),
    10: (22.0, 15.0, 10),
    11: (16.0, 8.0, 8),
    12: (11.0, 2.0, 8),
}


class DemoWeatherProvider:
    name = "demo-climate"
    is_demo = True

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def get_weather_context(self, place_slug: str, month: int) -> WeatherContext | None:
        async with self._session_factory() as session:
            place = await session.scalar(select(Place).where(Place.slug == place_slug))
        if place is None:
            return None
        high, low, rain = _MONTH_BASE.get(month, _MONTH_BASE[4])
        # ~0.65 °C per degree of latitude above Tokyo (35.7°N)
        adj = (place.lat - 35.7) * 0.65
        high -= adj
        low -= adj
        snow = low <= 1.0 and month in (12, 1, 2, 3)
        summary = f"Typical {month:02d}: {low:.0f}–{high:.0f} °C, about {rain} days with rain." + (
            " Snow cover is likely; some roads and trails close." if snow else ""
        )
        return WeatherContext(
            place_slug=place_slug,
            month=month,
            typical_high_c=round(high, 1),
            typical_low_c=round(low, 1),
            rain_days=rain,
            snow_likely=snow,
            summary=summary,
            meta=ProviderMeta(provider=self.name, is_demo=True),
        )


class OpenMeteoWeatherProvider:
    """Open-Meteo climate normals. No API key required, generous free tier."""

    name = "open-meteo"
    is_demo = False

    def __init__(
        self, settings: Settings, fallback: DemoWeatherProvider, cache: Cache | None = None
    ) -> None:
        self._fallback = fallback
        self._cache = cache
        self._timeout = settings.external_timeout_seconds
        self._policy = RetryPolicy(max_attempts=settings.external_max_retries + 1)
        self._breaker = CircuitBreaker("open-meteo")
        self._session_factory = fallback._session_factory

    async def get_weather_context(self, place_slug: str, month: int) -> WeatherContext | None:
        key = cache_key("weather", {"p": place_slug, "m": month})
        if self._cache:
            hit = await self._cache.get(key)
            if hit is not None:
                return WeatherContext.model_validate(hit)

        async with self._session_factory() as session:
            place = await session.scalar(select(Place).where(Place.slug == place_slug))
        if place is None:
            return None

        async def _call() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    "https://climate-api.open-meteo.com/v1/climate",
                    params={
                        "latitude": place.lat,
                        "longitude": place.lon,
                        "start_date": "1991-01-01",
                        "end_date": "2020-12-31",
                        "models": "MRI_AGCM3_2_S",
                        "monthly": "temperature_2m_max,temperature_2m_min",
                    },
                )
                resp.raise_for_status()
                return resp.json()

        try:
            data = await call_with_resilience(
                _call,
                name="open-meteo",
                timeout=self._timeout,
                policy=self._policy,
                breaker=self._breaker,
            )
            monthly = data.get("monthly", {})
            highs = monthly.get("temperature_2m_max") or []
            lows = monthly.get("temperature_2m_min") or []
            idx = month - 1
            high = float(highs[idx]) if idx < len(highs) else 0.0
            low = float(lows[idx]) if idx < len(lows) else 0.0
        except Exception as exc:
            log.warning("weather.openmeteo_failed_using_normals", error=str(exc))
            return await self._fallback.get_weather_context(place_slug, month)

        snow = low <= 1.0 and month in (12, 1, 2, 3)
        result = WeatherContext(
            place_slug=place_slug,
            month=month,
            typical_high_c=round(high, 1),
            typical_low_c=round(low, 1),
            rain_days=_MONTH_BASE.get(month, _MONTH_BASE[4])[2],
            snow_likely=snow,
            summary=f"Climate normal {month:02d}: {low:.0f}–{high:.0f} °C."
            + (" Snow cover is likely." if snow else ""),
            meta=ProviderMeta(provider=self.name, is_demo=False),
        )
        if self._cache:
            await self._cache.set(key, result.model_dump(mode="json"), ttl=86400 * 7)
        return result
