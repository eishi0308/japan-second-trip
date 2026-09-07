"""Timeouts, bounded retries and circuit breaking for every external call.

Rules enforced here (see docs/architecture.md "Reliability"):
  * every outbound call has an explicit timeout;
  * retries are bounded, exponential, jittered, and only for transient errors;
  * a repeatedly failing dependency is short-circuited rather than retried
    forever, so one broken provider cannot stall the whole request.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from jst_api.core.errors import ProviderError, ProviderTimeoutError
from jst_api.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T")

TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    asyncio.TimeoutError,
    ConnectionError,
    ProviderTimeoutError,
)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 4.0
    jitter: float = 0.25

    def delay_for(self, attempt: int) -> float:
        raw = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return raw + random.uniform(0, self.jitter)  # noqa: S311 - jitter, not crypto


@dataclass
class CircuitBreaker:
    """Trip after ``failure_threshold`` consecutive failures; probe after cooldown."""

    name: str
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            log.warning("circuit.open", breaker=self.name, failures=self._failures)


async def call_with_resilience(
    fn: Callable[[], Awaitable[T]],
    *,
    name: str,
    timeout: float,
    policy: RetryPolicy | None = None,
    breaker: CircuitBreaker | None = None,
    retry_on: tuple[type[BaseException], ...] = TRANSIENT_EXCEPTIONS,
) -> T:
    policy = policy or RetryPolicy()
    if breaker is not None and breaker.is_open:
        raise ProviderError(
            f"{name} is temporarily unavailable (circuit open)", details={"provider": name}
        )

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(fn(), timeout=timeout)
        except TimeoutError as exc:
            last_exc = ProviderTimeoutError(
                f"{name} timed out after {timeout}s", details={"provider": name}
            )
            log.warning("external.timeout", provider=name, attempt=attempt, timeout=timeout)
            if breaker:
                breaker.record_failure()
            if attempt == policy.max_attempts:
                raise last_exc from exc
        except retry_on as exc:
            last_exc = exc
            log.warning("external.transient_error", provider=name, attempt=attempt, error=str(exc))
            if breaker:
                breaker.record_failure()
            if attempt == policy.max_attempts:
                raise ProviderError(
                    f"{name} failed after {attempt} attempts: {exc}", details={"provider": name}
                ) from exc
        except Exception:
            if breaker:
                breaker.record_failure()
            raise
        else:
            if breaker:
                breaker.record_success()
            log.debug(
                "external.ok",
                provider=name,
                attempt=attempt,
                ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return result
        await asyncio.sleep(policy.delay_for(attempt))

    raise ProviderError(
        f"{name} exhausted retries", details={"provider": name, "cause": str(last_exc)}
    )
