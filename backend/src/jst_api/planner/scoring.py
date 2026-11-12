"""Deterministic fit rubric for a destination combination.

Five components add up to 100 points. Preferences (reactions, scene cards,
"what tired you") then add or take away a few points. The UI never shows the
points: it shows one of five fit levels and a plain-language breakdown such
as "Interests 3/3 matched".

Components and their maximum points:

==========  ===  ==========================================================
interests    35  share of the traveller's interests the trip covers
season       20  how good the month is at each stop, weighted by nights
travel       25  moving time against the travel budget for the nights
transport    10  car need against the traveller's transport
rhythm       10  nights per stop against each place's typical stay
==========  ===  ==========================================================

The travel budget is ``120 min x nights + 120 min``, scaled by pace (a
relaxed traveller tolerates less moving). A combination over the budget is
not scored at all: it is ruled out with a stated reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jst_api.domain.enums import Pace
from jst_api.planner.model import Place, Resolved
from jst_api.planner.preferences import Preferences
from jst_api.planner.travel import RouteTime

MAX_POINTS = {"interests": 35, "season": 20, "travel": 25, "transport": 10, "rhythm": 10}
if sum(MAX_POINTS.values()) != 100:  # not an assert: python -O must not strip it
    raise ValueError("fit rubric must total 100 points")

PACE_TRAVEL_FACTOR = {Pace.RELAXED: 0.85, Pace.BALANCED: 1.0, Pace.FAST: 1.2}
#: Most hotel stops a pace allows for a given number of nights.
MAX_STOPS = {Pace.RELAXED: (1, 2), Pace.BALANCED: (2, 3), Pace.FAST: (3, 3)}
"""Per pace: (stops allowed up to 4 nights, stops allowed from 5 nights)."""

#: (minimum points, level, label). Levels are what the UI shows.
FIT_LEVELS: tuple[tuple[float, int, str], ...] = (
    (80.0, 5, "Excellent fit"),
    (68.0, 4, "Strong fit"),
    (56.0, 3, "Good fit"),
    (44.0, 2, "Fair fit"),
    (0.0, 1, "Weak fit"),
)
SEASON_WORDS = {0: "closed or best avoided", 1: "possible", 2: "a good time", 3: "the best time"}
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


#: Themes that only count in some months: snow in July is not snow.
SEASONAL_THEMES: dict[str, frozenset[int]] = {"snow": frozenset({12, 1, 2, 3})}


def themes_in(place: Place, month: int) -> tuple[str, ...]:
    return tuple(t for t in place.themes if t not in SEASONAL_THEMES or month in SEASONAL_THEMES[t])


def travel_budget(nights: int, pace: Pace, prefs: Preferences | None = None) -> int:
    factor = PACE_TRAVEL_FACTOR[pace] * (prefs.travel_factor if prefs else 1.0)
    return int((120 * nights + 120) * factor)


def max_stops(nights: int, pace: Pace, prefs: Preferences | None = None) -> int:
    short, long = MAX_STOPS[pace]
    stops = long if nights >= 5 else short
    if prefs and prefs.fewer_stops:
        stops -= 1
    return max(1, min(stops, nights))


def fit_level(points: float) -> tuple[int, str]:
    for floor, level, label in FIT_LEVELS:
        if points >= floor:
            return level, label
    return 1, FIT_LEVELS[-1][2]


def hours(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


@dataclass(frozen=True)
class Line:
    name: str
    points: float
    max_points: int
    text: str


@dataclass(frozen=True)
class Fit:
    points: float
    level: int
    label: str
    lines: tuple[Line, ...]
    adjustments: tuple[str, ...]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(
    stops: Sequence[Place],
    nights: Sequence[int],
    route: RouteTime,
    resolved: Resolved,
    prefs: Preferences,
) -> Fit:
    c = resolved.conditions
    month = resolved.month
    total_nights = sum(nights)
    lines: list[Line] = []

    # interests ----------------------------------------------------------
    themes = {t for p in stops for t in themes_in(p, month)}
    if c.interests:
        matched = [i for i in c.interests if i in themes]
        per_stop = sum(len(set(c.interests) & set(themes_in(p, month))) for p in stops) / (
            len(stops) * len(c.interests)
        )
        value = 0.75 * len(matched) / len(c.interests) + 0.25 * per_stop
        text = f"Interests {len(matched)}/{len(c.interests)} matched"
        if matched:
            text += f" ({', '.join(matched)})"
    else:
        value, text = 0.6, "No interests given: judged on season and travel"
    lines.append(Line("interests", value * 35, 35, text))

    # season -------------------------------------------------------------
    weighted = sum(p.season(month) * n for p, n in zip(stops, nights, strict=True)) / total_nights
    worst = min(stops, key=lambda p: p.season(month))
    text = f"{MONTH_NAMES[month - 1]} is {SEASON_WORDS[round(weighted)]}"
    if worst.season(month) < round(weighted):
        text += f"; {worst.name} is {SEASON_WORDS[worst.season(month)]}"
    lines.append(Line("season", weighted / 3 * 20, 20, text))

    # travel -------------------------------------------------------------
    budget = travel_budget(total_nights, c.pace, prefs)
    value = _clamp(1 - route.minutes / (budget * 1.25))
    text = (
        f"{hours(route.minutes)} moving over {total_nights} nights ({travel_load(route, budget)})"
    )
    lines.append(Line("travel", value * 25, 25, text))

    # transport ----------------------------------------------------------
    if resolved.can_drive:
        value, text = 1.0, "Car or public transport both work"
    else:
        helpful = [p.name for p in stops if p.car_need == "helpful"]
        value = 1.0 - 0.5 * len(helpful) / len(stops)
        text = (
            "No car needed"
            if not helpful
            else f"No car needed; a car would help at {', '.join(helpful)}"
        )
    lines.append(Line("transport", value * 10, 10, text))

    # rhythm -------------------------------------------------------------
    short = [p.name for p, n in zip(stops, nights, strict=True) if n < min(p.typical_nights, 2)]
    changes = len(stops) - 1
    value = 1.0 - 0.3 * len(short) - (0.15 * changes if c.pace is Pace.RELAXED else 0.0)
    if c.big_luggage:
        value -= 0.1 * changes
    text = (
        "One hotel for the whole stay"
        if not changes
        else f"{changes} hotel change{'s' if changes > 1 else ''}"
    )
    if short:
        text += f"; short stay at {', '.join(short)}"
    lines.append(Line("rhythm", _clamp(value) * 10, 10, text))

    points = sum(line.points for line in lines)
    bonus, adjustments = _preference_points(stops, resolved, prefs)
    points = max(0.0, min(100.0, points + bonus))
    level, label = fit_level(points)
    return Fit(round(points, 2), level, label, tuple(lines), tuple(adjustments))


def travel_load(route: RouteTime, budget: int) -> str:
    share = route.minutes / budget if budget else 1.0
    if share <= 0.55:
        return "light"
    if share <= 0.85:
        return "moderate"
    return "heavy"


def _preference_points(
    stops: Sequence[Place], resolved: Resolved, prefs: Preferences
) -> tuple[float, list[str]]:
    c = resolved.conditions
    bonus = 0.0
    notes: list[str] = []
    n = len(stops)
    tiers = [p.tier for p in stops]
    if prefs.quiet:
        delta = prefs.quiet * (3.0 * tiers.count("hidden") - 4.0 * tiers.count("classic")) / n
        bonus += delta
        notes.append("Quieter places preferred")
    if prefs.unexpected:
        delta = prefs.unexpected * (4.0 * tiers.count("hidden") - 3.0 * tiers.count("classic")) / n
        bonus += delta
        notes.append("Less-known places preferred")
    if prefs.seen:
        bonus -= 10.0 * sum(p.slug in prefs.seen for p in stops) / n
    if prefs.liked_areas:
        bonus += 3.0 * sum(p.area in prefs.liked_areas for p in stops) / n
    if prefs.theme_boost:
        boost = sum(prefs.theme_boost.get(t, 0.0) for p in stops for t in p.themes) / n
        bonus += min(6.0, 2.0 * boost)
        notes.append("Closer to the trips you liked")
    if prefs.avoid_cities and any("city" in p.themes for p in stops):
        bonus -= 5.0
    if c.limited_walking:
        bonus -= 5.0 * sum("hiking" in p.themes for p in stops) / n
    if c.kids:
        bonus -= 3.0 * sum(p.themes[:1] == ("hiking",) for p in stops) / n
    return bonus, notes
