"""Deterministic route revision.

The product promises a *better route*, not a plausible-sounding one. A language
model cannot supply one safely: it has no access to real travel times, so any
route it invents carries invented durations.

So revisions are generated here, deterministically, by structural
transformations of the route the traveller actually gave us. Each candidate is
then re-costed with real transport data and scored on an explicit objective. The
model's job is to choose between the candidates and explain the trade-off — it
cannot introduce a stop, and it cannot change a number.

Transformations:
  T1  drop the worst burden-ratio stop and give its nights to the best-scoring
      remaining neighbour;
  T2  drop the two worst;
  T3  consolidate consecutive one-night stays into the strongest base;
  T4  reorder to reduce backtracking (only when the detour rule fired).

Objective (lower is better):

    transit_hours / total_nights  +  DROP_PENALTY × stops_dropped

The first term is what the traveller feels. The penalty stops the optimiser from
"improving" the trip by deleting it — a route with everything removed has zero
transit and is not an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jst_api.domain.geo import LatLon, haversine_km, path_length_km
from jst_api.domain.route import Route, RouteStop, TravelLoad, compute_travel_load

DROP_PENALTY = 0.35
MIN_KEPT_STOPS = 2
MAX_CANDIDATES = 8

#: At most half the overnight stops may be removed. Without this the optimiser
#: "fixes" a trip by deleting it — a single base with no travel scores brilliantly
#: on transit-per-night and is not an answer to "improve my itinerary".
MAX_DROP_FRACTION = 0.5

#: Effective door-to-door speed used only to estimate the *bypass* leg when
#: ranking which stop to drop. Distance-banded, because a flat speed badly
#: misprices Japan: a 600 km shinkansen corridor and a 40 km valley bus are not
#: the same journey. This estimate never reaches the user — every surviving
#: candidate is re-costed with real transport data first.
BYPASS_SPEED_BANDS: tuple[tuple[float, float], ...] = (
    (120.0, 60.0),
    (600.0, 120.0),
    (float("inf"), 150.0),
)
BYPASS_OVERHEAD_MIN = 35

#: How many stops feed the pairwise search. Wide enough that the ranking
#: heuristic only has to be roughly right; the objective does the real work.
TOP_N_FOR_PAIRS = 4


@dataclass
class RevisionCandidate:
    strategy: str
    stops: list[str]
    nights: list[int]
    dropped: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    reordered: bool = False
    objective: float = 0.0
    load: TravelLoad | None = None

    @property
    def is_change(self) -> bool:
        return bool(self.dropped or self.merged or self.reordered)

    def describe(self) -> str:
        parts: list[str] = []
        if self.dropped:
            parts.append(f"removed {', '.join(self.dropped)}")
        if self.merged:
            parts.append(f"consolidated nights into {', '.join(self.merged)}")
        if self.reordered:
            parts.append("re-ordered to run in one direction")
        return "; ".join(parts) or "unchanged"


def _burden_ratio(route: Route, order: int) -> float:
    """(inbound hours + outbound hours) / nights at this stop.

    High means the stop costs a lot of travel per night of value.
    """
    inbound = next((s.duration_minutes for s in route.segments if s.to_order == order), 0)
    outbound = next((s.duration_minutes for s in route.segments if s.from_order == order), 0)
    nights = next((s.nights for s in route.stops if s.order == order), 0)
    return ((inbound + outbound) / 60.0) / max(nights, 1)


def _marginal_saving_minutes(route: Route, index: int) -> float:
    """Minutes of transit actually saved by removing the stop at ``index``.

    Burden ratio alone is misleading: a stop can look expensive only because its
    *neighbour* is remote. What matters is the travel removed minus the travel
    the resulting bypass leg adds. The bypass is estimated geometrically here —
    good enough to rank candidates, and every surviving candidate is re-costed
    with real transport data before it is offered.
    """
    stops = route.stops
    if index <= 0 or index >= len(stops) - 1:
        return 0.0
    removed = 0.0
    for segment in route.segments:
        if segment.to_order == stops[index].order or segment.from_order == stops[index].order:
            removed += segment.duration_minutes

    before, after = stops[index - 1], stops[index + 1]
    if before.coords is None or after.coords is None:
        return removed * 0.5  # unknown geometry: assume the bypass costs half
    distance = haversine_km(before.coords, after.coords)
    speed = next(kmh for limit, kmh in BYPASS_SPEED_BANDS if distance <= limit)
    bypass = distance / speed * 60.0 + BYPASS_OVERHEAD_MIN
    return removed - bypass


def _overnight_indices(route: Route) -> list[int]:
    """Indices of stops that can be dropped: overnight, not first, not last."""
    return [i for i, s in enumerate(route.stops) if s.nights > 0 and 0 < i < len(route.stops) - 1]


def max_droppable(route: Route) -> int:
    return max(0, int(len(_overnight_indices(route)) * MAX_DROP_FRACTION))


def _drop_stops(route: Route, drop_indices: set[int]) -> tuple[list[str], list[int], list[str]]:
    """Remove stops and redistribute their nights to the best remaining neighbour."""
    stops = list(route.stops)
    keep = [s for i, s in enumerate(stops) if i not in drop_indices]
    dropped_names = [stops[i].name for i in sorted(drop_indices)]
    if len(keep) < MIN_KEPT_STOPS:
        return [], [], []

    nights = {s.order: s.nights for s in keep}
    endpoint_orders = {stops[0].order, stops[-1].order}
    orphan_nights = sum(stops[i].nights for i in drop_indices)

    # Nights freed by dropping a regional stop belong to another regional stop.
    # Handing them back to the arrival city would "improve" the trip by
    # cancelling it, which is not what the traveller asked for.
    interior = [s for s in keep if s.nights > 0 and s.order not in endpoint_orders]
    recipients = interior or [s for s in keep if s.nights > 0]

    # Spread one night at a time to whichever recipient currently has the fewest,
    # tie-broken by which is cheapest to reach. Dumping every freed night on one
    # stop turns a four-stop trip into a two-stop trip and overshoots the fix.
    for _ in range(orphan_nights):
        if not recipients:
            break
        target = min(
            recipients,
            key=lambda s: (nights.get(s.order, 0), _burden_ratio(route, s.order), s.order),
        )
        nights[target.order] = nights.get(target.order, 0) + 1

    return [s.name for s in keep], [nights.get(s.order, s.nights) for s in keep], dropped_names


def _consolidate_one_nighters(route: Route) -> tuple[list[str], list[int], list[str], list[str]]:
    """Fold runs of consecutive single nights into the best base in that run."""
    stops = list(route.stops)
    runs: list[list[int]] = []
    current: list[int] = []
    for i, stop in enumerate(stops):
        if stop.nights == 1 and 0 < i < len(stops) - 1:
            current.append(i)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)

    if not runs:
        return [], [], [], []

    drop: set[int] = set()
    merged_into: list[str] = []
    extra: dict[int, int] = {}
    for run in runs:
        base_index = min(run, key=lambda i: (_burden_ratio(route, stops[i].order), i))
        merged_into.append(stops[base_index].name)
        for i in run:
            if i != base_index:
                drop.add(i)
                extra[base_index] = extra.get(base_index, 0) + stops[i].nights

    keep = [s for i, s in enumerate(stops) if i not in drop]
    nights = []
    for i, stop in enumerate(stops):
        if i in drop:
            continue
        nights.append(stop.nights + extra.get(i, 0))
    dropped_names = [stops[i].name for i in sorted(drop)]
    return [s.name for s in keep], nights, dropped_names, merged_into


def _reorder_for_efficiency(route: Route) -> tuple[list[str], list[int]] | None:
    """Nearest-neighbour reordering of the interior stops, endpoints pinned.

    Only useful when the route backtracks; the caller decides whether to offer it.
    """
    stops = list(route.stops)
    if len(stops) < 4:
        return None
    if any(s.coords is None for s in stops):
        return None

    start, end = stops[0], stops[-1]
    interior = stops[1:-1]
    ordered: list[RouteStop] = []
    current: LatLon = start.coords  # type: ignore[assignment]
    remaining = list(interior)
    while remaining:
        # Coordinates were checked non-None above; mypy cannot narrow through the lambda.
        nxt = min(remaining, key=lambda s: path_length_km([current, s.coords]))  # type: ignore[list-item]
        ordered.append(nxt)
        current = nxt.coords  # type: ignore[assignment]
        remaining.remove(nxt)

    new_stops = [start, *ordered, end]
    if [s.order for s in new_stops] == [s.order for s in stops]:
        return None
    return [s.name for s in new_stops], [s.nights for s in new_stops]


def generate_candidates(route: Route, *, backtracking: bool = False) -> list[RevisionCandidate]:
    """Structural revision candidates.

    Single drops and pairwise drops among the three highest-saving stops are all
    offered, rather than only "the two worst". Which stop is worst changes once
    another is removed, so the objective — evaluated after real re-costing —
    decides, not the initial ranking.
    """
    candidates: list[RevisionCandidate] = []
    droppable = _overnight_indices(route)
    limit = max_droppable(route)

    if droppable and limit >= 1:
        ranked = sorted(droppable, key=lambda i: (-_marginal_saving_minutes(route, i), i))
        top = ranked[:TOP_N_FOR_PAIRS]

        for index in top:
            stops, nights, dropped = _drop_stops(route, {index})
            if stops:
                candidates.append(
                    RevisionCandidate(
                        f"drop_{_slug(route.stops[index].name)}", stops, nights, dropped=dropped
                    )
                )

        if limit >= 2:
            for i, first in enumerate(top):
                for second in top[i + 1 :]:
                    stops, nights, dropped = _drop_stops(route, {first, second})
                    if stops:
                        candidates.append(
                            RevisionCandidate(
                                f"drop_{_slug(route.stops[first].name)}_and_{_slug(route.stops[second].name)}",
                                stops,
                                nights,
                                dropped=dropped,
                            )
                        )

    stops, nights, dropped, merged = _consolidate_one_nighters(route)
    if stops and len(dropped) <= limit:
        candidates.append(
            RevisionCandidate(
                "consolidate_one_night_stays", stops, nights, dropped=dropped, merged=merged
            )
        )

    if backtracking:
        reordered = _reorder_for_efficiency(route)
        if reordered:
            candidates.append(
                RevisionCandidate(
                    "reorder_for_efficiency", reordered[0], reordered[1], reordered=True
                )
            )

    # Deduplicate structurally identical candidates, keeping the first strategy.
    seen: set[tuple[tuple[str, ...], tuple[int, ...]]] = set()
    unique: list[RevisionCandidate] = []
    for candidate in candidates:
        key = (tuple(candidate.stops), tuple(candidate.nights))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique[:MAX_CANDIDATES]


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")[:24]


def score_candidate(candidate: RevisionCandidate, route: Route) -> float:
    """Objective value. Requires ``candidate.load`` to have been computed."""
    if candidate.load is None:
        return float("inf")
    base = candidate.load.transit_hours_per_night
    penalty = DROP_PENALTY * len(candidate.dropped)
    candidate.objective = round(base + penalty, 4)
    return candidate.objective


def choose_best(candidates: list[RevisionCandidate], original: Route) -> RevisionCandidate | None:
    """Best candidate, or None when nothing beats the original."""
    original_load = compute_travel_load(original)
    baseline = original_load.transit_hours_per_night
    scored = [c for c in candidates if c.load is not None]
    if not scored:
        return None
    best = min(scored, key=lambda c: (score_candidate(c, original), len(c.dropped), c.strategy))
    # A revision must actually be better by a meaningful margin, otherwise the
    # honest answer is "your route is fine".
    if best.objective >= baseline - 0.05:
        return None
    return best
