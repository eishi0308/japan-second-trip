"""The feasibility engine on the same small hand-built catalogue as the planner tests.

Every rule is checked against numbers that can be worked out by hand. The
fixes are checked for the two product rules that matter most: a fix really
resolves its issue, and a fix never removes a pinned stop.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

from test_planner import HERO, NOW, catalogue, planner

from jst_api.domain.fact_state import FactState
from jst_api.planner.feasibility import Assumptions, Checker, Itinerary, StopSpec
from jst_api.planner.model import Catalogue, FragileNote, Transport


def _note(kind: str, **kw) -> FragileNote:
    return FragileNote(
        kind=kind,
        severity=kw.pop("severity", "critical"),
        title=kw.pop("title", "Last bus up the valley"),
        detail=kw.pop("detail", "Detail."),
        state=kw.pop("state", FactState.VERIFIED),
        verified_at=kw.pop("verified_at", NOW - timedelta(days=20)),
        source_id=kw.pop("source_id", "src_demo_note"),
        **kw,
    )


def _with_notes(slug: str, *notes: FragileNote) -> Catalogue:
    cat = catalogue()
    cat.places[slug] = replace(cat.places[slug], fragile=notes)
    return cat


def _itin(*stops: StopSpec, **kw) -> Itinerary:
    return Itinerary(
        stops=stops,
        month=kw.pop("month", 1),
        arrival=kw.pop("arrival", "tokyo"),
        departure=kw.pop("departure", "tokyo"),
        **kw,
    )


def test_one_day_per_night_plus_the_last_day() -> None:
    result = Checker(catalogue(), now=NOW).check(
        _itin(StopSpec("Tokyo", 2), StopSpec("nyuto", 2), StopSpec("Tokyo", 0))
    )
    assert len(result.days) == 5
    assert result.days[0].title == "Arrive in Tokyo"
    assert result.days[0].moving_minutes == 0
    travel_day = result.days[2]
    assert travel_day.moves[0].depart == "09:30"
    assert travel_day.moving_minutes > 0
    assert travel_day.staying_minutes == (18 * 60 + 30) - (9 * 60 + 30) - travel_day.moving_minutes
    assert result.days[-1].overnight is None


def test_assumptions_are_listed_and_labelled() -> None:
    result = Checker(catalogue(), now=NOW).check(_itin(StopSpec("nyuto", 2)))
    labels = [a.label for a in result.assumptions]
    assert "Assumed: leave the hotel at 09:30" in labels
    assert all(label.startswith("Assumed:") for label in labels)


def test_a_missed_last_bus_will_not_work_and_leaving_earlier_fixes_it() -> None:
    cat = _with_notes("nyuto", _note("last_connection", last_departure_local="16:45"))
    late = _itin(StopSpec("Tokyo", 1, leave_at=15 * 60), StopSpec("nyuto", 2))
    result = Checker(cat, now=NOW).check(late)
    assert result.verdict == "will_not_work"
    issue = next(i for i in result.issues if i.kind == "last_connection")
    assert issue.severity == "critical" and "16:45" in issue.why
    assert issue.evidence[0].source_id == "src_demo_note" and issue.evidence[0].verified_at
    assert 1 <= len(issue.fixes) <= 2
    assert any(f.label.startswith("Leave Tokyo at") for f in issue.fixes)
    assert all(f.verdict_after != "will_not_work" for f in issue.fixes)


def test_a_conflicting_fact_is_being_checked_and_never_asserted() -> None:
    note = _note(
        "last_connection",
        state=FactState.BEING_CHECKED,
        conflicting_values=("17:00", "16:30", "18:10"),
    )
    cat = _with_notes("nyuto", note)
    result = Checker(cat, now=NOW).check(
        _itin(StopSpec("Tokyo", 1, leave_at=13 * 60), StopSpec("nyuto", 2))
    )
    issue = next(i for i in result.issues if i.kind == "last_connection")
    assert issue.title.endswith("being checked")
    assert issue.needs_review
    text = json.dumps(result.model_dump(mode="json"))
    for value in ("17:00", "16:30", "18:10"):
        assert value not in text


def test_a_pinned_stop_is_never_removed_by_any_fix() -> None:
    churn = _itin(
        StopSpec("matsushima", 1),
        StopSpec("nyuto", 1, pinned=True),
        StopSpec("kakunodate", 1),
        StopSpec("shibu", 1),
        StopSpec("obuse", 1),
    )
    result = Checker(catalogue(), now=NOW).check(churn)
    fixes = [f for i in result.issues for f in i.fixes]
    assert fixes, "a five-stop one-night trip should get fixes"
    for fix in fixes:
        assert "nyuto" in {s.slug for s in fix.stops if s.pinned}


def test_fixes_carry_a_before_after_diff() -> None:
    churn = _itin(
        StopSpec("matsushima", 1),
        StopSpec("nyuto", 1),
        StopSpec("kakunodate", 1),
        StopSpec("shibu", 2),
    )
    result = Checker(catalogue(), now=NOW).check(churn)
    issue = next(i for i in result.issues if i.kind == "hotel_churn")
    assert issue.fixes
    for fix in issue.fixes:
        assert fix.diff.gained, fix.label
        assert any(g.startswith("Fixes:") for g in fix.diff.gained)


def test_closed_in_the_month_will_not_work() -> None:
    result = Checker(catalogue(), now=NOW).check(_itin(StopSpec("alpine", 2)))
    assert result.verdict == "will_not_work"
    assert any(i.kind == "seasonal_closure" for i in result.issues)


def test_a_car_only_place_without_a_car_will_not_work() -> None:
    checker = Checker(catalogue(), now=NOW)
    assert checker.check(_itin(StopSpec("farm", 2))).verdict == "will_not_work"
    driving = checker.check(_itin(StopSpec("farm", 2), transport=Transport.CAN_DRIVE))
    assert not any(i.kind == "car_required" for i in driving.issues)


def test_a_place_outside_the_database_says_no_verified_info() -> None:
    result = Checker(catalogue(), now=NOW).check(_itin(StopSpec("Atlantis", 2)))
    issue = next(i for i in result.issues if i.kind == "not_in_database")
    assert "no verified info yet" in issue.title
    assert result.verdict != "works"
    assert result.stops[0].kind == "unknown"


def test_weekly_closure_is_checked_against_real_dates() -> None:
    monday = date(2027, 1, 4)
    cat = _with_notes(
        "obuse",
        _note("weekly_closure", severity="warning", title="Museum closed", closed_weekdays=(1,)),
    )
    checker = Checker(cat, now=NOW)
    hit = checker.check(_itin(StopSpec("obuse", 2), start_date=monday))
    assert any(i.kind == "weekly_closure" and i.severity == "warning" for i in hit.issues)
    undated = checker.check(_itin(StopSpec("obuse", 2)))
    assert any(i.kind == "weekly_closure" and i.severity == "info" for i in undated.issues)


def test_booking_items_come_only_from_dated_evidence() -> None:
    cat = _with_notes(
        "nyuto",
        _note("booking_difficulty", severity="warning", title="Book the ryokan", lead_time_days=60),
    )
    result = Checker(cat, now=NOW).check(_itin(StopSpec("nyuto", 2), start_date=date(2027, 1, 10)))
    assert len(result.booking) == 1
    item = result.booking[0]
    assert item.evidence.source_id and item.evidence.verified_at
    assert item.book_by == "2026-11-11"


def test_a_long_departure_transfer_risks_the_flight() -> None:
    result = Checker(catalogue(), now=NOW).check(
        _itin(StopSpec("beppu", 2), assumptions=Assumptions(flight_cutoff=11 * 60))
    )
    assert any(i.kind == "departure_risk" and i.severity == "critical" for i in result.issues)


def test_every_blocking_issue_has_evidence_or_is_about_an_unknown_place() -> None:
    churn = _itin(
        StopSpec("matsushima", 1),
        StopSpec("nyuto", 1),
        StopSpec("kakunodate", 1),
        StopSpec("beppu", 1),
    )
    result = Checker(catalogue(), now=NOW).check(churn)
    for issue in result.issues:
        if issue.severity != "info" and issue.kind != "not_in_database":
            assert issue.evidence, issue.title


def test_the_same_itinerary_always_gives_the_same_check() -> None:
    itin = _itin(StopSpec("matsushima", 1), StopSpec("nyuto", 2), StopSpec("shibu", 1))
    a = Checker(catalogue(), now=NOW).check(itin).model_dump(mode="json")
    b = Checker(catalogue(), now=NOW).check(itin).model_dump(mode="json")
    assert a == b


def test_every_where_next_option_is_checked_day_by_day() -> None:
    result = planner().plan(HERO).result
    assert result is not None
    for option in result.options:
        assert option.check is not None
        assert len(option.check.days) == 4 + 1
        assert option.check.verdict_label in ("Works", "Needs attention", "Will not work")
        pinned = {s.slug for s in option.stops if s.pinned}
        assert pinned == {s.slug for s in option.check.stops if s.pinned}
