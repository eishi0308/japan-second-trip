"""A critical fact is never shown as verified without a date, or forever."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jst_api.domain.fact_state import FactState, can_assert, fact_state

NOW = datetime(2026, 11, 12, tzinfo=UTC)


def test_recent_verified_fact_is_verified() -> None:
    assert fact_state("verified", NOW - timedelta(days=10), 180, now=NOW) is FactState.VERIFIED


def test_fact_older_than_its_ttl_is_stale() -> None:
    assert fact_state("verified", NOW - timedelta(days=181), 180, now=NOW) is FactState.STALE


def test_verified_status_without_a_date_is_unverified() -> None:
    assert fact_state("verified", None, 180, now=NOW) is FactState.UNVERIFIED


def test_conflicting_fact_is_being_checked_even_if_recent() -> None:
    state = fact_state("conflicting", NOW - timedelta(days=1), 180, now=NOW)
    assert state is FactState.BEING_CHECKED
    assert not can_assert(state)


def test_naive_datetimes_are_treated_as_utc() -> None:
    naive = (NOW - timedelta(days=5)).replace(tzinfo=None)
    assert fact_state("verified", naive, 180, now=NOW) is FactState.VERIFIED


def test_only_dated_facts_can_be_asserted() -> None:
    assert can_assert(FactState.VERIFIED)
    assert can_assert(FactState.STALE)
    assert not can_assert(FactState.UNVERIFIED)
