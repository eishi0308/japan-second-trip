"""What a traveller is told about a critical fact (PRODUCT_AMENDMENTS.md §2.3, §7).

Four states, decided by code from the stored status and dates:

* ``verified`` — shown with its date. Never shown as "Verified" without one.
* ``stale`` — older than its TTL: shown with its date and a re-check warning.
* ``unverified`` — "No verified info yet". Nothing is asserted.
* ``being_checked`` — sources conflict, a human review is open. No single
  value is asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from jst_api.domain.enums import FactStatus


class FactState(StrEnum):
    VERIFIED = "verified"
    STALE = "stale"
    UNVERIFIED = "unverified"
    BEING_CHECKED = "being_checked"


def fact_state(
    status: str,
    verified_at: datetime | None,
    ttl_days: int,
    *,
    now: datetime | None = None,
) -> FactState:
    if status == FactStatus.CONFLICTING:
        return FactState.BEING_CHECKED
    if status == FactStatus.UNVERIFIED or verified_at is None:
        return FactState.UNVERIFIED
    now = now or datetime.now(UTC)
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    if now - verified_at > timedelta(days=ttl_days):
        return FactState.STALE
    return FactState.VERIFIED


def can_assert(state: FactState) -> bool:
    """Whether the fact's value may be stated as current. Stale facts are shown with a warning."""
    return state in (FactState.VERIFIED, FactState.STALE)
