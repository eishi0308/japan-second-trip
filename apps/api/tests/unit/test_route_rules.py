"""Deterministic route-health rules.

Each rule is tested for both firing and *not* firing. A rules engine that only
ever says yes is a rubber stamp, and false positives are how a critique loses
the traveller's trust.
"""

from __future__ import annotations

import pytest

from jst_api.domain.enums import IssueType, Pace, RouteHealth, Severity, TransportMode
from jst_api.domain.route import Route, RouteSegment, RouteStop, compute_travel_load
from jst_api.domain.route_rules import (
    TRAVEL_DAY_START,
    grade_health,
    registered_rule_ids,
    run_rules,
)
from jst_api.domain.trip import TripContext


def stop(order: int, name: str, nights: int, lat: float = 38.0, lon: float = 140.0) -> RouteStop:
    return RouteStop(
        order=order,
        raw_name=name,
        place_slug=name.lower(),
        display_name=name,
        nights=nights,
        lat=lat,
        lon=lon,
        resolved=True,
    )


def seg(a: RouteStop, b: RouteStop, minutes: int, **kw) -> RouteSegment:
    return RouteSegment(
        from_order=a.order,
        to_order=b.order,
        from_name=a.name,
        to_name=b.name,
        mode=kw.pop("mode", TransportMode.SHINKANSEN),
        duration_minutes=minutes,
        **kw,
    )


def fired(issues, rule_id: str):
    return [i for i in issues if i.rule_id == rule_id]


def test_all_rules_are_registered():
    ids = registered_rule_ids()
    assert len(ids) == len(set(ids)), "rule ids must be unique"
    assert "R01_travel_burden" in ids


class TestTravelBurden:
    def test_long_hop_to_a_single_night_is_critical(self):
        a, b = stop(0, "Ginzan", 1), stop(1, "Aomori", 1)
        route = Route(stops=[a, b], segments=[seg(a, b, 330)])
        issues, _ = run_rules(route, TripContext())
        found = fired(issues, "R01_travel_burden")
        assert found and found[0].severity is Severity.CRITICAL
        assert found[0].deterministic_signal["segment_hours"] == pytest.approx(5.5)

    def test_short_hop_to_a_multi_night_stay_does_not_fire(self):
        a, b = stop(0, "Tokyo", 3), stop(1, "Sendai", 3)
        route = Route(stops=[a, b], segments=[seg(a, b, 95)])
        issues, _ = run_rules(route, TripContext())
        assert not fired(issues, "R01_travel_burden")

    def test_a_pass_through_stop_is_not_penalised(self):
        a, b = stop(0, "Tokyo", 3), stop(1, "Tokyo", 0)
        route = Route(stops=[a, b], segments=[seg(a, b, 400)])
        issues, _ = run_rules(route, TripContext())
        assert not fired(issues, "R01_travel_burden")


class TestAccommodationChurn:
    def test_four_single_nights_is_a_warning_not_a_blocker(self):
        stops = [stop(0, "Tokyo", 3), *(stop(i, f"S{i}", 1) for i in range(1, 5))]
        segments = [seg(stops[i], stops[i + 1], 90) for i in range(len(stops) - 1)]
        issues, _ = run_rules(Route(stops=stops, segments=segments), TripContext())
        found = fired(issues, "R02_accommodation_churn")
        assert found and found[0].severity is Severity.WARNING

    def test_two_solid_bases_do_not_fire(self):
        stops = [stop(0, "Tokyo", 3), stop(1, "Sendai", 3)]
        issues, _ = run_rules(
            Route(stops=stops, segments=[seg(stops[0], stops[1], 95)]), TripContext()
        )
        assert not fired(issues, "R02_accommodation_churn")


class TestBacktracking:
    def test_a_closed_loop_is_not_a_detour(self):
        """Returning to where you started is a legitimate shape, not backtracking."""
        stops = [
            stop(0, "Tokyo", 2, 35.68, 139.77),
            stop(1, "Sendai", 2, 38.27, 140.87),
            stop(2, "Tokyo", 0, 35.68, 139.77),
        ]
        segments = [seg(stops[0], stops[1], 95), seg(stops[1], stops[2], 95)]
        issues, load = run_rules(Route(stops=stops, segments=segments), TripContext())
        assert load.detour_ratio == 1.0
        assert not fired(issues, "R03_backtracking")

    def test_zigzag_fires(self):
        stops = [
            stop(0, "Tokyo", 2, 35.68, 139.77),
            stop(1, "Aomori", 2, 40.82, 140.74),
            stop(2, "Sendai", 2, 38.27, 140.87),
            stop(3, "Hakodate", 2, 41.77, 140.73),
        ]
        segments = [seg(stops[i], stops[i + 1], 120) for i in range(3)]
        issues, _ = run_rules(Route(stops=stops, segments=segments), TripContext())
        assert fired(issues, "R03_backtracking")


class TestCarRequired:
    def test_car_only_hop_is_critical_for_a_public_transport_trip(self):
        a, b = stop(0, "Aso", 2), stop(1, "Takachiho", 2)
        route = Route(
            stops=[a, b], segments=[seg(a, b, 75, mode=TransportMode.CAR, requires_car=True)]
        )
        issues, _ = run_rules(route, TripContext(driving="no_car"))
        found = fired(issues, "R05_car_required")
        assert found and found[0].severity is Severity.CRITICAL

    def test_same_hop_is_fine_when_the_traveller_will_drive(self):
        a, b = stop(0, "Aso", 2), stop(1, "Takachiho", 2)
        route = Route(
            stops=[a, b], segments=[seg(a, b, 75, mode=TransportMode.CAR, requires_car=True)]
        )
        issues, _ = run_rules(route, TripContext(driving="willing"))
        assert not fired(issues, "R05_car_required")


class TestLastConnection:
    def test_missing_the_last_local_service_is_critical(self):
        a, b = stop(0, "Sendai", 1), stop(1, "Ginzan", 1)
        route = Route(
            stops=[a, b],
            segments=[seg(a, b, 600, last_departure_local="17:00", final_leg_minutes=40)],
        )
        issues, _ = run_rules(route, TripContext())
        found = fired(issues, "R06_last_connection")
        assert found and found[0].severity is Severity.CRITICAL
        assert found[0].deterministic_signal["assumed_day_start"] == TRAVEL_DAY_START.strftime(
            "%H:%M"
        )

    def test_comfortable_margin_does_not_fire(self):
        a, b = stop(0, "Sendai", 1), stop(1, "Ginzan", 1)
        route = Route(
            stops=[a, b],
            segments=[seg(a, b, 120, last_departure_local="18:10", final_leg_minutes=40)],
        )
        issues, _ = run_rules(route, TripContext())
        assert not fired(issues, "R06_last_connection")


class TestPaceAndLuggage:
    def test_relaxed_pace_flags_a_busy_route(self):
        stops = [stop(0, "A", 1), stop(1, "B", 1), stop(2, "C", 1)]
        segments = [seg(stops[0], stops[1], 200), seg(stops[1], stops[2], 200)]
        issues, _ = run_rules(Route(stops=stops, segments=segments), TripContext(pace=Pace.RELAXED))
        assert fired(issues, "R08_pace_mismatch")

    def test_luggage_rule_needs_the_luggage_flag(self):
        a, b = stop(0, "A", 2), stop(1, "B", 2)
        route = Route(stops=[a, b], segments=[seg(a, b, 200, transfers=4)])
        assert not fired(run_rules(route, TripContext())[0], "R09_luggage_risk")
        assert fired(run_rules(route, TripContext(large_luggage=True))[0], "R09_luggage_risk")


class TestPositiveSignals:
    def test_an_efficient_hop_is_reported(self):
        a, b = stop(0, "Tokyo", 3), stop(1, "Kanazawa", 3)
        issues, _ = run_rules(Route(stops=[a, b], segments=[seg(a, b, 155)]), TripContext())
        good = fired(issues, "R50_efficient_segments")
        assert good and good[0].severity is Severity.GOOD
        assert good[0].issue_type is IssueType.EFFICIENT_SEGMENT


class TestGrading:
    @pytest.mark.parametrize(
        ("criticals", "warnings", "expected"),
        [
            (0, 0, RouteHealth.HEALTHY),
            (0, 1, RouteHealth.NEEDS_IMPROVEMENT),
            (1, 0, RouteHealth.NEEDS_IMPROVEMENT),
            (2, 0, RouteHealth.HIGH_RISK),
        ],
    )
    def test_health_grades(self, criticals, warnings, expected):
        from jst_api.domain.results import RouteIssue

        issues = [
            RouteIssue(
                issue_type=IssueType.TRAVEL_BURDEN,
                severity=Severity.CRITICAL,
                title="c",
                explanation="c",
            )
            for _ in range(criticals)
        ] + [
            RouteIssue(
                issue_type=IssueType.TRAVEL_BURDEN,
                severity=Severity.WARNING,
                title="w",
                explanation="w",
            )
            for _ in range(warnings)
        ]
        assert grade_health(issues) is expected


def test_travel_load_is_arithmetic_not_opinion():
    stops = [stop(0, "A", 3), stop(1, "B", 1), stop(2, "C", 2)]
    segments = [seg(stops[0], stops[1], 120), seg(stops[1], stops[2], 60)]
    load = compute_travel_load(Route(stops=stops, segments=segments))
    assert load.total_nights == 6
    assert load.total_transit_hours == pytest.approx(3.0)
    assert load.one_night_stays == 1
    assert load.accommodation_changes == 2
    assert load.longest_segment_hours == pytest.approx(2.0)


def test_every_issue_carries_its_measurements():
    """A critique without numbers is an opinion; the UI shows these."""
    stops = [stop(0, "Tokyo", 3), *(stop(i, f"S{i}", 1) for i in range(1, 5))]
    segments = [seg(stops[i], stops[i + 1], 260) for i in range(len(stops) - 1)]
    issues, _ = run_rules(Route(stops=stops, segments=segments), TripContext(pace=Pace.RELAXED))
    for issue in issues:
        assert issue.rule_id
        assert issue.deterministic_signal, f"{issue.rule_id} reported no measurements"
