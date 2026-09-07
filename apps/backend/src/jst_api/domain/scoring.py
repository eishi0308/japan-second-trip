"""Deterministic region fit scoring.

This is *not* an LLM judgement and *not* a trained model. It is a documented,
reproducible weighted rubric over explicit travel constraints. The same input
always yields the same score, which is what makes the recommendation auditable
and testable (see ``tests/unit/test_scoring.py`` and
``docs/adr/0006-deterministic-rules.md``).

Pipeline
--------
1. **Hard constraints** run first and can *eliminate* a region outright.
   Elimination is never a low score — it is a stated reason.
2. **Component scores** each produce a value in ``[0, 1]``.
3. **Weighted sum** produces ``0..100``. Weights are declared in ``WEIGHTS`` and
   sum to 1.0 (asserted at import time).
4. **Label** is derived from the score by fixed thresholds.

The LLM is given the resulting numbers and asked to *explain* them. It is never
asked to produce them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jst_api.domain.enums import (
    DrivingWillingness,
    FitLabel,
    Interest,
    Pace,
    TravellerType,
)
from jst_api.domain.region import RegionProfile
from jst_api.domain.trip import TripContext

WEIGHTS: dict[str, float] = {
    "nights_fit": 0.24,
    "access_efficiency": 0.22,
    "transport_compatibility": 0.16,
    "interest_match": 0.16,
    "season_fit": 0.12,
    "novelty": 0.06,
    "practicality": 0.04,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "fit-score weights must sum to 1.0"

#: score -> label thresholds (inclusive lower bound)
LABEL_THRESHOLDS: list[tuple[float, FitLabel]] = [
    (72.0, FitLabel.STRONG),
    (58.0, FitLabel.GOOD),
    (42.0, FitLabel.MARGINAL),
    (0.0, FitLabel.NOT_RECOMMENDED),
]

#: A regional leg where more than this share of usable hours goes to the return
#: transfer is travel-dominated: a travel day at each end wrapped around a short
#: stay. Set to match ``route.TRAVEL_DOMINATED_SHARE`` — the same judgement
#: applied to a region's access overhead and to a whole route's transit load.
#: 0.42 was too permissive: a 14h return transfer for two nights (41%) slipped
#: through, and that is not a trip anyone should be sold.
MAX_TRANSIT_SHARE = 0.35

PACE_TOLERANCE: dict[Pace, float] = {Pace.RELAXED: 0.8, Pace.BALANCED: 1.0, Pace.FAST: 1.25}

#: Interest fit blends the average match with the worst match, so a region that
#: is superb at two of three stated interests and poor at the third does not
#: outrank one that is good at all three.
INTEREST_MEAN_WEIGHT = 0.7
INTEREST_MIN_WEIGHT = 0.3


@dataclass
class ComponentScore:
    name: str
    value: float
    weight: float
    explanation: str

    @property
    def contribution(self) -> float:
        return self.value * self.weight * 100.0


@dataclass
class HardConstraintResult:
    passed: bool
    code: str
    explanation: str


@dataclass
class FitScore:
    region_code: str
    score: float
    label: FitLabel
    components: list[ComponentScore] = field(default_factory=list)
    hard_failures: list[HardConstraintResult] = field(default_factory=list)
    eliminated: bool = False
    transit_share: float = 0.0
    round_trip_hours: float = 0.0

    def breakdown(self) -> dict[str, float]:
        return {c.name: round(c.contribution, 2) for c in self.components}

    def rationale_lines(self) -> list[str]:
        return [
            f"{c.name}: {c.value:.2f} × weight {c.weight:.2f} — {c.explanation}"
            for c in self.components
        ]


# ---------------------------------------------------------------------------
# hard constraints
# ---------------------------------------------------------------------------
def evaluate_hard_constraints(
    region: RegionProfile, trip: TripContext
) -> list[HardConstraintResult]:
    """Constraints that disqualify a region regardless of how appealing it is."""
    results: list[HardConstraintResult] = []
    nights = trip.effective_regional_nights

    results.append(
        HardConstraintResult(
            passed=nights >= region.min_recommended_nights,
            code="min_nights",
            explanation=(
                f"{region.name} needs at least {region.min_recommended_nights} nights to be worth the "
                f"transfer; this trip allows {nights}."
            ),
        )
    )

    if trip.public_transport_only:
        results.append(
            HardConstraintResult(
                passed=region.car_free_possible,
                code="car_free_required",
                explanation=(
                    f"A worthwhile {region.name} itinerary effectively requires a car, but this trip is "
                    "public-transport only."
                ),
            )
        )

    access = region.access_from(trip.arrival_city) or region.best_gateway()
    round_trip = access.hours_one_way * 2
    usable_hours = max(nights, 1) * 10.0  # ~10 usable sightseeing hours per night of stay
    transit_share = round_trip / (round_trip + usable_hours)
    tolerance = PACE_TOLERANCE.get(trip.pace or Pace.BALANCED, 1.0)
    results.append(
        HardConstraintResult(
            passed=transit_share <= MAX_TRANSIT_SHARE * tolerance,
            code="transit_share",
            explanation=(
                f"Round-trip transfer from {access.gateway} is {round_trip:.1f}h against roughly "
                f"{usable_hours:.0f}h of usable time — {transit_share:.0%} of the leg would be spent travelling."
            ),
        )
    )

    if trip.mobility and trip.mobility.step_free_required:
        results.append(
            HardConstraintResult(
                passed=region.step_free_score >= 0.5,
                code="step_free",
                explanation=f"{region.name}'s core sights are not reliably step-free.",
            )
        )

    return results


# ---------------------------------------------------------------------------
# component scores
# ---------------------------------------------------------------------------
def _nights_fit(region: RegionProfile, nights: int) -> ComponentScore:
    if nights < region.min_recommended_nights:
        value = max(0.0, nights / max(region.min_recommended_nights, 1) * 0.5)
        expl = f"{nights}N is below the {region.min_recommended_nights}N minimum for this region."
    elif nights <= region.ideal_nights:
        span = max(region.ideal_nights - region.min_recommended_nights, 1)
        value = 0.7 + 0.3 * ((nights - region.min_recommended_nights) / span)
        expl = f"{nights}N sits inside the {region.min_recommended_nights}–{region.ideal_nights}N sweet spot."
    elif nights <= region.max_useful_nights:
        span = max(region.max_useful_nights - region.ideal_nights, 1)
        value = 1.0 - 0.25 * ((nights - region.ideal_nights) / span)
        expl = f"{nights}N is generous but still productive here (ideal {region.ideal_nights}N)."
    else:
        value = 0.6
        expl = f"{nights}N exceeds what this region needs ({region.max_useful_nights}N of distinct content)."
    return ComponentScore(
        "nights_fit", round(min(1.0, max(0.0, value)), 4), WEIGHTS["nights_fit"], expl
    )


def _access_efficiency(
    region: RegionProfile, trip: TripContext
) -> tuple[ComponentScore, float, float]:
    nights = trip.effective_regional_nights
    inbound = region.access_from(trip.arrival_city) or region.best_gateway()
    outbound = region.access_from(trip.departure_city) or inbound
    round_trip = inbound.hours_one_way + outbound.hours_one_way
    usable_hours = max(nights, 1) * 10.0
    transit_share = round_trip / (round_trip + usable_hours)
    # map 10% share -> 1.0, 45% share -> 0.0, linear
    value = (0.45 - transit_share) / 0.35
    expl = (
        f"{round_trip:.1f}h return transfer ({inbound.gateway} → {region.name} by "
        f"{inbound.primary_mode.value.replace('_', ' ')}, {inbound.transfers} transfer(s)) against {nights}N on the "
        f"ground = {transit_share:.0%} of the leg in transit."
    )
    score = ComponentScore(
        "access_efficiency", round(min(1.0, max(0.0, value)), 4), WEIGHTS["access_efficiency"], expl
    )
    return score, transit_share, round_trip


def _transport_compatibility(region: RegionProfile, trip: TripContext) -> ComponentScore:
    driving = trip.driving
    pts = region.public_transport_score
    if driving == DrivingWillingness.NO_CAR:
        value = pts
        expl = f"Public-transport-only trip; region scores {pts:.2f} for car-free feasibility."
        if region.car_required_highlights:
            expl += f" Off-limits without a car: {', '.join(region.car_required_highlights[:3])}."
    elif driving in (DrivingWillingness.WILLING, DrivingWillingness.PREFERS_CAR):
        value = max(pts, 0.85 if region.car_recommended else 0.75)
        expl = "Traveller will drive, which unlocks this region's dispersed sights."
    else:
        value = 0.5 + pts * 0.5
        expl = f"Driving preference unknown; assuming mixed use (car-free score {pts:.2f})."
    if trip.large_luggage:
        value *= 0.85 + 0.15 * region.luggage_friendliness
        expl += " Large luggage discounts regions with frequent local-train/bus changes."
    return ComponentScore(
        "transport_compatibility",
        round(min(1.0, max(0.0, value)), 4),
        WEIGHTS["transport_compatibility"],
        expl,
    )


def _interest_match(region: RegionProfile, interests: list[Interest]) -> ComponentScore:
    if not interests:
        strengths = sorted(region.interest_strength.values(), reverse=True)[:3]
        value = sum(strengths) / max(len(strengths), 1) if strengths else 0.6
        return ComponentScore(
            "interest_match",
            round(value, 4),
            WEIGHTS["interest_match"],
            "No interests supplied — scored on the region's own strongest themes.",
        )
    scores = [region.interest_strength.get(i, 0.25) for i in interests]
    # A plain mean lets one excellent theme paper over a stated interest the
    # region is poor at — "I want art" answered with 0.45 is a real miss, not an
    # average. Blending the mean with the weakest match rewards regions that
    # satisfy *all* of what the traveller asked for.
    value = INTEREST_MEAN_WEIGHT * (sum(scores) / len(scores)) + INTEREST_MIN_WEIGHT * min(scores)
    matched = [i.value for i in interests if region.interest_strength.get(i, 0) >= 0.7]
    weak = [i.value for i in interests if region.interest_strength.get(i, 0) < 0.5]
    expl = f"Strong for {', '.join(matched) or 'none of the stated interests'}"
    if weak:
        expl += f"; weak for {', '.join(weak)}"
    return ComponentScore("interest_match", round(value, 4), WEIGHTS["interest_match"], expl + ".")


def _season_fit(region: RegionProfile, trip: TripContext) -> ComponentScore:
    month = trip.month
    value = region.seasonal.score_for(month)
    note = region.seasonal.note_for(month)
    if month is None:
        expl = "No travel dates supplied — neutral seasonal prior applied."
    else:
        expl = f"Month {month:02d} seasonal suitability {value:.2f}." + (f" {note}" if note else "")
    return ComponentScore("season_fit", round(value, 4), WEIGHTS["season_fit"], expl)


def _novelty(region: RegionProfile, trip: TripContext) -> ComponentScore:
    visited = trip.visited_normalised
    if not visited:
        return ComponentScore("novelty", 0.8, WEIGHTS["novelty"], "No travel history supplied.")
    overlaps = {o.lower() for o in region.overlaps_with_visited}
    hits = len(overlaps & visited)
    already_here = any(
        p in visited for p in [region.name.lower(), *(pref.lower() for pref in region.prefectures)]
    )
    if already_here:
        return ComponentScore(
            "novelty", 0.15, WEIGHTS["novelty"], f"Traveller has already been to {region.name}."
        )
    value = max(0.3, 1.0 - 0.25 * hits)
    expl = (
        f"Feels materially different from the {len(visited)} place(s) already visited."
        if hits == 0
        else f"Shares {hits} theme(s) with places already visited ({', '.join(sorted(overlaps & visited))})."
    )
    return ComponentScore("novelty", round(value, 4), WEIGHTS["novelty"], expl)


def _practicality(region: RegionProfile, trip: TripContext) -> ComponentScore:
    value = 1.0 - region.booking_complexity
    expl = f"Booking complexity {region.booking_complexity:.2f} (0 = walk-up friendly, 1 = advance/Japanese-only)."
    if trip.traveller_type == TravellerType.FAMILY:
        value *= 0.8 + 0.2 * region.luggage_friendliness
        expl += " Family travel weights luggage/pram friendliness."
    if trip.mobility and trip.mobility.limited_walking:
        value *= 0.6 + 0.4 * region.step_free_score
        expl += " Limited-walking constraint weights step-free access."
    return ComponentScore(
        "practicality", round(min(1.0, max(0.0, value)), 4), WEIGHTS["practicality"], expl
    )


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def label_for(score: float) -> FitLabel:
    for threshold, label in LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return FitLabel.NOT_RECOMMENDED


def score_region(region: RegionProfile, trip: TripContext) -> FitScore:
    """Deterministic fit score for one region against one trip context."""
    hard = evaluate_hard_constraints(region, trip)
    failures = [h for h in hard if not h.passed]

    access_score, transit_share, round_trip = _access_efficiency(region, trip)
    components = [
        _nights_fit(region, trip.effective_regional_nights),
        access_score,
        _transport_compatibility(region, trip),
        _interest_match(region, trip.interests),
        _season_fit(region, trip),
        _novelty(region, trip),
        _practicality(region, trip),
    ]
    raw = sum(c.contribution for c in components)

    # A hard failure caps the score rather than silently blending away: the
    # region is reported as rejected, with the failing constraint as the reason.
    eliminated = bool(failures)
    score = min(raw, 38.0) if eliminated else raw

    return FitScore(
        region_code=region.code,
        score=round(score, 2),
        label=FitLabel.NOT_RECOMMENDED if eliminated else label_for(score),
        components=components,
        hard_failures=failures,
        eliminated=eliminated,
        transit_share=round(transit_share, 4),
        round_trip_hours=round(round_trip, 2),
    )


def rank_regions(regions: list[RegionProfile], trip: TripContext) -> list[FitScore]:
    """Stable ranking: score descending, then region code for determinism."""
    scored = [score_region(r, trip) for r in regions]
    return sorted(scored, key=lambda s: (-s.score, s.region_code))
