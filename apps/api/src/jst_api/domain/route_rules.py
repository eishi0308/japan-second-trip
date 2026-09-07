"""Deterministic route-health rules engine.

Every rule here is a pure function of structured data (durations from transport
providers, nights from the parsed itinerary, coordinates from the place
registry). No rule calls a language model, and no language model may add,
remove or re-grade a rule's severity — the LLM only writes the prose for issues
this engine has already found. That split is what makes the critique auditable
and regression-testable (``tests/unit/test_route_rules.py``).

Rule ids are stable and versioned; ``RULES_VERSION`` is stamped into every
result so an eval regression can be traced to a rules change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time

from jst_api.domain.enums import IssueType, Pace, RouteHealth, Severity
from jst_api.domain.results import RouteIssue
from jst_api.domain.route import Route, RouteSegment, TravelLoad, compute_travel_load
from jst_api.domain.trip import TripContext

RULES_VERSION = "1.0.0"

#: Modelled start of a travel day. Checkout is 10:00 across most Japanese
#: accommodation, so this is the earliest a traveller realistically moves with
#: luggage. Documented rather than hidden because several rules depend on it.
TRAVEL_DAY_START = time(hour=10, minute=0)

#: Thresholds. Deliberately module-level constants so evals can sweep them.
LONG_HOP_HOURS = 4.0
MEDIUM_HOP_HOURS = 3.0
CHURN_ONE_NIGHT_LIMIT = 2
CHURN_CRITICAL_LIMIT = 5
"""Churn is a warning until it dominates the trip; at five single nights the
traveller is packing every morning and it becomes a blocking problem."""
CHURN_RATIO_LIMIT = 0.6
DETOUR_RATIO_LIMIT = 1.6
TRANSIT_SHARE_LIMIT = 0.35
DEPARTURE_DAY_HOURS_LIMIT = 5.0
TIGHT_CONNECTION_MINUTES = 45
HEAVY_TRANSFER_COUNT = 3
EFFICIENT_HOP_HOURS = 3.0
"""A direct hop under three hours that buys a night or more is efficient by any
traveller's reckoning — Tokyo to Kanazawa is 2h35 and nobody calls it a slog."""

PACE_TRANSIT_LIMIT: dict[Pace, float] = {
    Pace.RELAXED: 2.0,
    Pace.BALANCED: 3.0,
    Pace.FAST: 4.5,
}


@dataclass
class RuleContext:
    route: Route
    trip: TripContext
    load: TravelLoad


Rule = Callable[[RuleContext], list[RouteIssue]]
_REGISTRY: list[tuple[str, Rule]] = []


def rule(rule_id: str) -> Callable[[Rule], Rule]:
    def decorate(fn: Rule) -> Rule:
        _REGISTRY.append((rule_id, fn))
        return fn

    return decorate


def _minutes_from_time(t: time) -> int:
    return t.hour * 60 + t.minute


def _parse_hhmm(value: str) -> int | None:
    try:
        hh, mm = value.split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None


def _nights_at(route: Route, order: int) -> int:
    for stop in route.stops:
        if stop.order == order:
            return stop.nights
    return 0


def _segment_label(seg: RouteSegment) -> str:
    return f"{seg.from_name} → {seg.to_name}"


# ---------------------------------------------------------------------------
# R01 — travel burden relative to time on the ground
# ---------------------------------------------------------------------------
@rule("R01_travel_burden")
def _travel_burden(ctx: RuleContext) -> list[RouteIssue]:
    issues: list[RouteIssue] = []
    for seg in ctx.route.segments:
        hours = seg.duration_hours
        nights = _nights_at(ctx.route, seg.to_order)
        if nights == 0:
            continue
        # usable hours at the destination on arrival day + full days after
        usable = (
            max(0.0, (19.0 - (_minutes_from_time(TRAVEL_DAY_START) / 60.0) - hours))
            + (nights - 1) * 10.0
        )
        if hours >= LONG_HOP_HOURS and nights <= 1:
            severity = Severity.CRITICAL
        elif (hours >= MEDIUM_HOP_HOURS and nights <= 1) or usable < hours:
            severity = Severity.WARNING
        else:
            continue
        issues.append(
            RouteIssue(
                issue_type=IssueType.TRAVEL_BURDEN,
                severity=severity,
                segment=_segment_label(seg),
                title=f"{_segment_label(seg)} costs more time than it buys",
                explanation=(
                    f"The hop takes about {hours:.1f}h. With {nights} night(s) at {seg.to_name} that leaves "
                    f"roughly {usable:.1f}h of usable time there."
                ),
                deterministic_signal={
                    "segment_hours": hours,
                    "nights_at_destination": nights,
                    "usable_hours": round(usable, 2),
                    "transfers": seg.transfers,
                },
                rule_id="R01_travel_burden",
                evidence_ids=list(seg.evidence_ids),
                proposed_fix=f"Give {seg.to_name} a second night, or drop it and extend the previous stop.",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# R02 — accommodation churn
# ---------------------------------------------------------------------------
@rule("R02_accommodation_churn")
def _accommodation_churn(ctx: RuleContext) -> list[RouteIssue]:
    load = ctx.load
    if load.total_nights == 0:
        return []
    ratio = load.accommodation_changes / load.total_nights
    triggered = load.one_night_stays > CHURN_ONE_NIGHT_LIMIT or ratio > CHURN_RATIO_LIMIT
    if not triggered:
        return []
    severity = (
        Severity.CRITICAL if load.one_night_stays >= CHURN_CRITICAL_LIMIT else Severity.WARNING
    )
    return [
        RouteIssue(
            issue_type=IssueType.ACCOMMODATION_CHURN,
            severity=severity,
            segment=None,
            title="You are changing accommodation almost every night",
            explanation=(
                f"{load.one_night_stays} of your stops are single nights and you change beds "
                f"{load.accommodation_changes} times across {load.total_nights} nights. Packing, checkout and "
                "check-in windows eat the middle of each day."
            ),
            deterministic_signal={
                "one_night_stays": load.one_night_stays,
                "accommodation_changes": load.accommodation_changes,
                "total_nights": load.total_nights,
                "change_ratio": round(ratio, 3),
            },
            rule_id="R02_accommodation_churn",
            proposed_fix="Consolidate into two or three bases and day-trip outward.",
        )
    ]


# ---------------------------------------------------------------------------
# R03 — backtracking
# ---------------------------------------------------------------------------
@rule("R03_backtracking")
def _backtracking(ctx: RuleContext) -> list[RouteIssue]:
    if ctx.load.detour_ratio <= DETOUR_RATIO_LIMIT:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.BACKTRACKING,
            severity=Severity.WARNING,
            segment=None,
            title="The route doubles back on itself",
            explanation=(
                f"Your stops cover {ctx.load.detour_ratio:.2f}× the straight-line distance between first and last "
                "stop. Re-ordering the same places would remove travel time without removing anything you see."
            ),
            deterministic_signal={
                "detour_ratio": ctx.load.detour_ratio,
                "limit": DETOUR_RATIO_LIMIT,
            },
            rule_id="R03_backtracking",
            proposed_fix="Re-order the stops so the route runs in one geographic direction.",
        )
    ]


# ---------------------------------------------------------------------------
# R04 — departure-day risk
# ---------------------------------------------------------------------------
@rule("R04_departure_risk")
def _departure_risk(ctx: RuleContext) -> list[RouteIssue]:
    if not ctx.route.segments:
        return []
    final = ctx.route.segments[-1]
    if not ctx.route.departure_city:
        return []
    if final.duration_hours < DEPARTURE_DAY_HOURS_LIMIT:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.DEPARTURE_RISK,
            severity=Severity.CRITICAL if final.duration_hours >= 6.5 else Severity.WARNING,
            segment=_segment_label(final),
            title=f"Getting back to {ctx.route.departure_city} is a whole travel day",
            explanation=(
                f"The final hop is about {final.duration_hours:.1f}h with {final.transfers} transfer(s). On an "
                "international departure day that leaves no margin for a delay."
            ),
            deterministic_signal={
                "final_hop_hours": final.duration_hours,
                "transfers": final.transfers,
                "limit_hours": DEPARTURE_DAY_HOURS_LIMIT,
            },
            rule_id="R04_departure_risk",
            evidence_ids=list(final.evidence_ids),
            proposed_fix=f"Add a night nearer {ctx.route.departure_city} before flying out.",
        )
    ]


# ---------------------------------------------------------------------------
# R05 — car required but unavailable
# ---------------------------------------------------------------------------
@rule("R05_car_required")
def _car_required(ctx: RuleContext) -> list[RouteIssue]:
    if not ctx.trip.public_transport_only:
        return []
    offenders = [s for s in ctx.route.segments if s.requires_car]
    if not offenders:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.CAR_REQUIRED,
            severity=Severity.CRITICAL,
            segment=", ".join(_segment_label(s) for s in offenders[:3]),
            title="Part of this route effectively requires a car",
            explanation=(
                f"{len(offenders)} hop(s) have no practical public-transport equivalent, but this trip is "
                "public-transport only."
            ),
            deterministic_signal={"segments_requiring_car": len(offenders)},
            rule_id="R05_car_required",
            evidence_ids=[e for s in offenders for e in s.evidence_ids],
            proposed_fix="Replace those stops with rail-served alternatives, or hire a car for that leg only.",
        )
    ]


# ---------------------------------------------------------------------------
# R06 — last local connection of the day
# ---------------------------------------------------------------------------
@rule("R06_last_connection")
def _last_connection(ctx: RuleContext) -> list[RouteIssue]:
    issues: list[RouteIssue] = []
    start = _minutes_from_time(TRAVEL_DAY_START)
    for seg in ctx.route.segments:
        if not seg.last_departure_local:
            continue
        cutoff = _parse_hhmm(seg.last_departure_local)
        if cutoff is None:
            continue
        final_leg = seg.final_leg_minutes or 0
        transfer_arrival = start + max(seg.duration_minutes - final_leg, 0)
        margin = cutoff - transfer_arrival
        if margin >= TIGHT_CONNECTION_MINUTES:
            continue
        severity = Severity.CRITICAL if margin < 0 else Severity.WARNING
        arrive_hhmm = f"{transfer_arrival // 60:02d}:{transfer_arrival % 60:02d}"
        issues.append(
            RouteIssue(
                issue_type=IssueType.LAST_CONNECTION_RISK,
                severity=severity,
                segment=_segment_label(seg),
                title=(
                    f"You miss the last connection into {seg.to_name}"
                    if margin < 0
                    else f"Only {margin} min of margin on the last connection into {seg.to_name}"
                ),
                explanation=(
                    f"Leaving at {TRAVEL_DAY_START.strftime('%H:%M')} puts you at the final transfer around "
                    f"{arrive_hhmm}. The last service on that leg departs {seg.last_departure_local}."
                ),
                deterministic_signal={
                    "modelled_transfer_arrival": arrive_hhmm,
                    "last_departure": seg.last_departure_local,
                    "margin_minutes": margin,
                    "assumed_day_start": TRAVEL_DAY_START.strftime("%H:%M"),
                },
                rule_id="R06_last_connection",
                evidence_ids=list(seg.evidence_ids),
                proposed_fix=f"Start earlier, or break the journey short of {seg.to_name}.",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# R07 — overall transit share
# ---------------------------------------------------------------------------
@rule("R07_transit_share")
def _transit_share(ctx: RuleContext) -> list[RouteIssue]:
    share = ctx.load.transit_share_of_daylight
    if share <= TRANSIT_SHARE_LIMIT:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.TRAVEL_BURDEN,
            severity=Severity.CRITICAL if share > 0.45 else Severity.WARNING,
            segment=None,
            title="Most of this trip is spent moving",
            explanation=(
                f"About {share:.0%} of your usable hours go to transit "
                f"({ctx.load.total_transit_hours:.1f}h across {ctx.load.total_nights} nights)."
            ),
            deterministic_signal={
                "transit_share": share,
                "total_transit_hours": ctx.load.total_transit_hours,
                "limit": TRANSIT_SHARE_LIMIT,
            },
            rule_id="R07_transit_share",
            proposed_fix="Remove the stop with the worst hours-per-night ratio.",
        )
    ]


# ---------------------------------------------------------------------------
# R08 — pace mismatch
# ---------------------------------------------------------------------------
@rule("R08_pace_mismatch")
def _pace_mismatch(ctx: RuleContext) -> list[RouteIssue]:
    pace = ctx.trip.pace
    if pace is None:
        return []
    limit = PACE_TRANSIT_LIMIT[pace]
    actual = ctx.load.transit_hours_per_night
    if actual <= limit:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.PACE_MISMATCH,
            severity=Severity.WARNING,
            segment=None,
            title=f"This is not a {pace.value} itinerary",
            explanation=(
                f"You asked for a {pace.value} pace, which we treat as up to {limit:.1f}h of transit per night. "
                f"This route averages {actual:.1f}h."
            ),
            deterministic_signal={
                "pace": pace.value,
                "limit_hours_per_night": limit,
                "actual": actual,
            },
            rule_id="R08_pace_mismatch",
            proposed_fix="Drop one stop and redistribute its nights.",
        )
    ]


# ---------------------------------------------------------------------------
# R09 — luggage-heavy transfers
# ---------------------------------------------------------------------------
@rule("R09_luggage_risk")
def _luggage_risk(ctx: RuleContext) -> list[RouteIssue]:
    if not ctx.trip.large_luggage:
        return []
    offenders = [s for s in ctx.route.segments if s.transfers >= HEAVY_TRANSFER_COUNT]
    if not offenders:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.LUGGAGE_RISK,
            severity=Severity.WARNING,
            segment=", ".join(_segment_label(s) for s in offenders[:3]),
            title="Several transfers with large luggage",
            explanation=(
                f"{len(offenders)} hop(s) need {HEAVY_TRANSFER_COUNT}+ changes. Regional trains and buses often have "
                "no luggage space and stations may have stairs only."
            ),
            deterministic_signal={
                "heavy_transfer_segments": len(offenders),
                "threshold": HEAVY_TRANSFER_COUNT,
            },
            rule_id="R09_luggage_risk",
            proposed_fix="Forward the big bags (takkyubin) to your next multi-night base.",
        )
    ]


# ---------------------------------------------------------------------------
# Positive signals — the product must also say what is working
# ---------------------------------------------------------------------------
@rule("R50_efficient_segments")
def _efficient_segments(ctx: RuleContext) -> list[RouteIssue]:
    issues: list[RouteIssue] = []
    for seg in ctx.route.segments:
        nights = _nights_at(ctx.route, seg.to_order)
        if seg.duration_hours <= EFFICIENT_HOP_HOURS and seg.transfers <= 1 and nights >= 1:
            issues.append(
                RouteIssue(
                    issue_type=IssueType.EFFICIENT_SEGMENT,
                    severity=Severity.GOOD,
                    segment=_segment_label(seg),
                    title=f"{_segment_label(seg)} is efficient",
                    explanation=(
                        f"{seg.duration_hours:.1f}h with {seg.transfers} transfer(s), then {nights} nights on the "
                        "ground — the transfer pays for itself."
                    ),
                    deterministic_signal={
                        "segment_hours": seg.duration_hours,
                        "transfers": seg.transfers,
                        "nights_at_destination": nights,
                    },
                    rule_id="R50_efficient_segments",
                    evidence_ids=list(seg.evidence_ids),
                )
            )
    return issues[:4]


@rule("R51_good_stay_length")
def _good_stay_length(ctx: RuleContext) -> list[RouteIssue]:
    solid = [s for s in ctx.route.overnight_stops if s.nights >= 3]
    if not solid:
        return []
    return [
        RouteIssue(
            issue_type=IssueType.GOOD_STAY_LENGTH,
            severity=Severity.GOOD,
            segment=None,
            title="You have a proper base",
            explanation=(
                f"{', '.join(f'{s.name} ({s.nights}N)' for s in solid[:3])} gives you somewhere to unpack and "
                "day-trip from."
            ),
            deterministic_signal={"long_stays": len(solid)},
            rule_id="R51_good_stay_length",
        )
    ]


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------
def run_rules(route: Route, trip: TripContext) -> tuple[list[RouteIssue], TravelLoad]:
    load = compute_travel_load(route)
    ctx = RuleContext(route=route, trip=trip, load=load)
    issues: list[RouteIssue] = []
    for _rule_id, fn in _REGISTRY:
        issues.extend(fn(ctx))
    return issues, load


def grade_health(issues: list[RouteIssue]) -> RouteHealth:
    criticals = sum(1 for i in issues if i.severity is Severity.CRITICAL)
    warnings = sum(1 for i in issues if i.severity is Severity.WARNING)
    if criticals >= 2:
        return RouteHealth.HIGH_RISK
    if criticals == 1 or warnings >= 2:
        return RouteHealth.NEEDS_IMPROVEMENT
    if warnings == 1:
        return RouteHealth.NEEDS_IMPROVEMENT
    return RouteHealth.HEALTHY


def registered_rule_ids() -> list[str]:
    return [rid for rid, _ in _REGISTRY]
