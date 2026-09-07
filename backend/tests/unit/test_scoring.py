"""Deterministic fit scoring.

These lock down the property the whole product rests on: the same trip and the
same region always produce the same number, and that number moves in the
direction a traveller would expect when a constraint changes.
"""

from __future__ import annotations

from datetime import date

import pytest

from jst_api.domain.enums import DrivingWillingness, FitLabel, Interest, Pace
from jst_api.domain.geo import LatLon
from jst_api.domain.region import GatewayAccess, RegionProfile, SeasonalProfile
from jst_api.domain.scoring import (
    WEIGHTS,
    evaluate_hard_constraints,
    label_for,
    rank_regions,
    score_region,
)
from jst_api.domain.trip import TripContext


def build_region(**overrides) -> RegionProfile:
    base = {
        "code": "test",
        "name": "Test Region",
        "tagline": "t",
        "prefectures": ["X"],
        "hub_place_slug": "hub",
        "centroid": LatLon(38.0, 140.0),
        "gateways": {
            "Tokyo": GatewayAccess(
                gateway="Tokyo", hours_one_way=2.0, primary_mode="shinkansen", transfers=0
            )
        },
        "min_recommended_nights": 3,
        "ideal_nights": 5,
        "max_useful_nights": 9,
        "public_transport_score": 0.8,
        "car_free_possible": True,
        "car_recommended": False,
        "interest_strength": {Interest.FOOD: 0.9, Interest.ONSEN: 0.9, Interest.ART: 0.2},
        "seasonal": SeasonalProfile(month_scores=dict.fromkeys(range(1, 13), 0.8)),
        "booking_complexity": 0.3,
    }
    base.update(overrides)
    return RegionProfile(**base)


def trip(**overrides) -> TripContext:
    base = {
        "start_date": date(2026, 10, 12),
        "total_nights": 12,
        "regional_nights": 4,
        "arrival_city": "Tokyo",
        "departure_city": "Tokyo",
        "interests": [Interest.FOOD, Interest.ONSEN],
        "driving": DrivingWillingness.NO_CAR,
        "pace": Pace.BALANCED,
    }
    base.update(overrides)
    return TripContext(**base)


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_scoring_is_deterministic():
    region, context = build_region(), trip()
    scores = {score_region(region, context).score for _ in range(20)}
    assert len(scores) == 1, "the same inputs must always produce the same score"


def test_score_is_the_sum_of_its_components():
    result = score_region(build_region(), trip())
    assert result.score == pytest.approx(sum(c.contribution for c in result.components), abs=0.01)


def test_too_few_nights_eliminates_rather_than_merely_lowers():
    region = build_region(min_recommended_nights=6)
    result = score_region(region, trip(regional_nights=3))
    assert result.eliminated
    assert result.label is FitLabel.NOT_RECOMMENDED
    assert any(f.code == "min_nights" for f in result.hard_failures)
    assert "at least 6 nights" in result.hard_failures[0].explanation


def test_car_only_region_is_eliminated_for_a_public_transport_trip():
    region = build_region(car_free_possible=False)
    assert score_region(region, trip(driving=DrivingWillingness.NO_CAR)).eliminated
    assert not score_region(region, trip(driving=DrivingWillingness.WILLING)).eliminated


def test_distant_region_on_a_short_leg_fails_the_transit_share_constraint():
    far = build_region(
        gateways={
            "Tokyo": GatewayAccess(
                gateway="Tokyo", hours_one_way=7.0, primary_mode="flight", transfers=2
            )
        },
        min_recommended_nights=1,
    )
    failures = evaluate_hard_constraints(far, trip(regional_nights=2))
    assert any(f.code == "transit_share" and not f.passed for f in failures)


def test_more_nights_improves_a_distant_region():
    far = build_region(
        gateways={
            "Tokyo": GatewayAccess(
                gateway="Tokyo", hours_one_way=5.0, primary_mode="shinkansen", transfers=1
            )
        },
        min_recommended_nights=2,
    )
    short = score_region(far, trip(regional_nights=3, total_nights=12))
    long = score_region(far, trip(regional_nights=8, total_nights=16))
    assert long.score > short.score


def test_interest_fit_penalises_a_region_weak_at_a_stated_interest():
    """The blend of mean and minimum is what stops a region that is superb at two
    interests and poor at a third from outranking one that is good at all three."""
    generalist = build_region(
        code="generalist",
        interest_strength={Interest.FOOD: 0.8, Interest.ONSEN: 0.8, Interest.ART: 0.8},
    )
    lopsided = build_region(
        code="lopsided",
        interest_strength={Interest.FOOD: 1.0, Interest.ONSEN: 1.0, Interest.ART: 0.2},
    )
    context = trip(interests=[Interest.FOOD, Interest.ONSEN, Interest.ART])
    assert score_region(generalist, context).score > score_region(lopsided, context).score


def test_visiting_the_region_before_reduces_novelty():
    region = build_region(name="Tohoku")
    fresh = score_region(region, trip(visited_places=["Tokyo"]))
    repeat = score_region(region, trip(visited_places=["Tokyo", "Tohoku"]))
    assert repeat.score < fresh.score


def test_ranking_is_stable_and_ordered():
    regions = [build_region(code=f"r{i}", booking_complexity=i / 10) for i in range(5)]
    first = rank_regions(regions, trip())
    second = rank_regions(list(reversed(regions)), trip())
    assert [s.region_code for s in first] == [s.region_code for s in second]
    assert [s.score for s in first] == sorted((s.score for s in first), reverse=True)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (95, FitLabel.STRONG),
        (72, FitLabel.STRONG),
        (60, FitLabel.GOOD),
        (45, FitLabel.MARGINAL),
        (10, FitLabel.NOT_RECOMMENDED),
    ],
)
def test_label_thresholds(score, expected):
    assert label_for(score) is expected


def test_every_component_carries_a_human_explanation():
    for component in score_region(build_region(), trip()).components:
        assert component.explanation.strip(), f"{component.name} has no explanation"
        assert 0.0 <= component.value <= 1.0
