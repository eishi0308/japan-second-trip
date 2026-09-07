"""Source freshness policy.

"Verified" is never shown without a date, and never shown forever. Critical
operational facts (transport, booking) age faster than general descriptions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jst_api.domain.enums import EvidenceTopic, FreshnessState

CRITICAL_TOPICS: frozenset[EvidenceTopic] = frozenset(
    {EvidenceTopic.TRANSPORT_ACCESS, EvidenceTopic.BOOKING, EvidenceTopic.SEASONAL}
)

#: topic -> (fresh_days, ageing_days). Beyond ``ageing_days`` a fact is stale.
TOPIC_TTL_DAYS: dict[EvidenceTopic, tuple[int, int]] = {
    EvidenceTopic.TRANSPORT_ACCESS: (90, 180),
    EvidenceTopic.BOOKING: (90, 180),
    EvidenceTopic.SEASONAL: (120, 240),
    EvidenceTopic.COST: (120, 300),
    EvidenceTopic.LUGGAGE: (180, 400),
    EvidenceTopic.ACCESSIBILITY: (180, 400),
    EvidenceTopic.GENERAL: (180, 540),
}


def is_critical(topic: EvidenceTopic) -> bool:
    return topic in CRITICAL_TOPICS


def classify_freshness(
    verified_at: datetime | None,
    topic: EvidenceTopic = EvidenceTopic.GENERAL,
    *,
    now: datetime | None = None,
) -> FreshnessState:
    if verified_at is None:
        return FreshnessState.UNVERIFIED
    now = now or datetime.now(UTC)
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    age = now - verified_at
    fresh_days, ageing_days = TOPIC_TTL_DAYS.get(topic, TOPIC_TTL_DAYS[EvidenceTopic.GENERAL])
    if age <= timedelta(days=fresh_days):
        return FreshnessState.FRESH
    if age <= timedelta(days=ageing_days):
        return FreshnessState.AGEING
    return FreshnessState.STALE


def requires_reverification(state: FreshnessState, topic: EvidenceTopic) -> bool:
    """A stale *critical* fact must be re-verified before it can be asserted."""
    if state is FreshnessState.STALE:
        return True
    return state is FreshnessState.UNVERIFIED and is_critical(topic)


def freshness_label(state: FreshnessState, verified_at: datetime | None) -> str:
    if verified_at is None:
        return "Not independently verified"
    stamp = verified_at.date().isoformat()
    return {
        FreshnessState.FRESH: f"Last verified {stamp}",
        FreshnessState.AGEING: f"Last verified {stamp} — re-check before booking",
        FreshnessState.STALE: f"Last verified {stamp} — out of date, treat as unconfirmed",
        FreshnessState.UNVERIFIED: "Not independently verified",
    }[state]
