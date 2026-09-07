"""Fixed-window rate limiting.

Analysis endpoints are expensive: each one runs a graph, several tool calls and
at least one model call. Without a limit, one client can turn the LLM bill into
a denial-of-wallet attack.

Redis-backed when configured (correct across replicas), in-process otherwise
(correct for a single node, and never a hard dependency).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from jst_api.core.errors import RateLimitedError
from jst_api.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class RateLimiter:
    limit: int
    window_seconds: int = 60
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    redis: Any = None

    async def check(self, key: str, *, cost: int = 1) -> None:
        if self.redis is not None:
            try:
                await self._check_redis(key, cost)
                return
            except RateLimitedError:
                raise
            except Exception as exc:  # pragma: no cover - Redis outage
                log.warning("ratelimit.redis_degraded", error=str(exc))
        self._check_local(key, cost)

    async def _check_redis(self, key: str, cost: int) -> None:
        window = int(time.time() // self.window_seconds)
        redis_key = f"jst:rl:{key}:{window}"
        total = await self.redis.incrby(redis_key, cost)
        if total == cost:
            await self.redis.expire(redis_key, self.window_seconds * 2)
        if total > self.limit:
            raise RateLimitedError(
                f"Rate limit of {self.limit} requests per {self.window_seconds}s exceeded",
                details={"limit": self.limit, "window_seconds": self.window_seconds},
            )

    def _check_local(self, key: str, cost: int) -> None:
        now = time.time()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        if len(bucket) + cost > self.limit:
            raise RateLimitedError(
                f"Rate limit of {self.limit} requests per {self.window_seconds}s exceeded",
                details={"limit": self.limit, "window_seconds": self.window_seconds},
            )
        for _ in range(cost):
            bucket.append(now)

    def reset(self) -> None:
        self._hits.clear()
