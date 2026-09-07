"""Cache abstraction: Redis when configured, bounded in-process TTL map otherwise.

Cached surfaces (see docs/architecture.md):
  * embedding vectors            — keyed by (model, sha256(text)); content-addressed
  * evidence retrieval results   — keyed by (query, filters, k)
  * external provider responses  — keyed by provider + normalised args
  * region comparison payloads   — keyed by deterministic trip-context digest

Nothing that carries a *freshness-critical* verified fact is served from cache
past its TTL; freshness policy lives in ``domain/freshness.py`` and is applied
after the cache returns.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Protocol, TypeVar

from jst_api.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T")


def cache_key(namespace: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return f"jst:{namespace}:{digest}"


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...


class InMemoryCache:
    """Bounded LRU + TTL cache. Safe default for local dev, tests and single-node."""

    def __init__(self, max_entries: int = 2048, default_ttl: int = 900) -> None:
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entries
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at < time.time():
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        async with self._lock:
            self._data[key] = (time.time() + (ttl or self._default_ttl), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._data)}


class RedisCache:
    """Redis-backed cache that degrades to a local cache when Redis is unreachable."""

    def __init__(self, url: str, default_ttl: int = 900, fallback: Cache | None = None) -> None:
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(url, decode_responses=True)
        self._default_ttl = default_ttl
        self._fallback = fallback or InMemoryCache(default_ttl=default_ttl)
        self._degraded = False

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(key)
            self._degraded = False
        except Exception as exc:  # pragma: no cover - requires a broken Redis
            self._note_degradation(exc)
            return await self._fallback.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl or self._default_ttl)
        except Exception as exc:  # pragma: no cover
            self._note_degradation(exc)
            await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:  # pragma: no cover
            self._note_degradation(exc)
            await self._fallback.delete(key)

    async def clear(self) -> None:  # pragma: no cover - destructive, admin only
        try:
            await self._client.flushdb()
        except Exception as exc:
            self._note_degradation(exc)
            await self._fallback.clear()

    def _note_degradation(self, exc: Exception) -> None:
        if not self._degraded:
            log.warning("cache.redis_degraded", error=str(exc))
            self._degraded = True


def build_cache(redis_url: str | None, ttl: int, max_entries: int) -> Cache:
    if redis_url:
        try:
            return RedisCache(redis_url, default_ttl=ttl)
        except Exception as exc:  # pragma: no cover
            log.warning("cache.redis_init_failed", error=str(exc))
    return InMemoryCache(max_entries=max_entries, default_ttl=ttl)
