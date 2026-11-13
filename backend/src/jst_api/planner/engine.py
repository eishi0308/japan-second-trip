"""Where Next engine: conditions in, three options and the bad news out.

Steps, all deterministic:

1. **Resolve** undecided inputs. Cities default to Tokyo in/out, labelled
   "Assumed". An undecided month returns a season choice; undecided nights
   return a 3-night versus 5-night choice.
2. **Funnel** the catalogue with real counts: not visited, open in the month,
   realistic for the transport, within reach for the nights. Every place that
   drops out keeps the reason it dropped out.
3. **Combine** the survivors into 1 to 3 stop trips, in the fastest order,
   with nights split by each place's typical stay. Pinned places are in every
   combination.
4. **Score** each combination with the rubric in ``scoring.py``.
5. **Pick** three options with different characters: Classic, Unexpected and
   Slow-paced. Apart from pinned stops they share no destination.
6. **Explain** what is left out: each area with no option says why, and
   which single change would bring it back ("If you can fly out of Fukuoka,
   Kyushu becomes a strong option"). The counterfactual is computed by
   re-running the check with that change, not written by hand.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from jst_api.domain.enums import Area, Pace
from jst_api.domain.fact_state import FactState, fact_state
from jst_api.planner.feasibility import Assumptions, Checker, Itinerary, StopSpec
from jst_api.planner.model import (
    DEFAULT_HUB,
    DEFAULT_NIGHTS,
    Assumption,
    Catalogue,
    Conditions,
    FragileNote,
    Place,
    Resolved,
    Transport,
)
from jst_api.planner.preferences import Preferences, preferences_from
from jst_api.planner.results import (
    CHARACTER_LABELS,
    AssumptionOut,
    FitLine,
    FitOut,
    FunnelStep,
    HardItem,
    LegOut,
    NightsChoice,
    NoticeOut,
    OptionOut,
    OptionSet,
    PlanResult,
    RejectionOut,
    SeasonChoice,
    StopOut,
    SuggestionOut,
    TravelOut,
    VerificationOut,
)
from jst_api.planner.scoring import (
    MONTH_NAMES,
    SEASON_WORDS,
    SEASONAL_THEMES,
    Fit,
    hours,
    max_stops,
    score,
    themes_in,
    travel_budget,
    travel_load,
)
from jst_api.planner.travel import RouteTime, TravelModel

AREA_LABELS = {
    Area.HOKKAIDO: "Hokkaido",
    Area.TOHOKU: "Tohoku",
    Area.KANTO: "Kanto",
    Area.CHUBU: "Chubu and the Japan Alps",
    Area.HOKURIKU: "Hokuriku",
    Area.KANSAI: "Kansai",
    Area.CHUGOKU: "Chugoku",
    Area.SHIKOKU: "Shikoku",
    Area.KYUSHU: "Kyushu",
    Area.OKINAWA: "Okinawa",
}
SEASONS: tuple[tuple[str, str, int], ...] = (
    ("winter", "Winter (January)", 1),
    ("spring", "Spring (April)", 4),
    ("summer", "Summer (July)", 7),
    ("autumn", "Autumn (October)", 10),
)
NIGHTS_CHOICES = (3, 5)
#: Single-stop candidates kept for combining, after ranking. Pins are added on top.
CANDIDATES_FOR_PAIRS = 36
CANDIDATES_FOR_TRIPLES = 22
#: A hop between two stops longer than this is two trips, not one.
MAX_HOP_MINUTES = 300
MAX_REJECTIONS = 6
CATALOGUE_TTL_DAYS = 365
_STATE_ORDER = (
    FactState.VERIFIED,
    FactState.STALE,
    FactState.UNVERIFIED,
    FactState.BEING_CHECKED,
)


@dataclass(frozen=True)
class Combo:
    stops: tuple[Place, ...]
    nights: tuple[int, ...]
    route: RouteTime
    fit: Fit

    @property
    def slugs(self) -> frozenset[str]:
        return frozenset(p.slug for p in self.stops)


@dataclass
class Funnel:
    survivors: list[Place]
    dropped: dict[str, tuple[str, str]]
    steps: list[FunnelStep]


class Planner:
    def __init__(self, catalogue: Catalogue, *, now: datetime | None = None) -> None:
        self.catalogue = catalogue
        self.travel = TravelModel(catalogue)
        self.now = now or datetime.now(UTC)
        self.checker = Checker(catalogue, now=self.now)

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------
    def plan(self, conditions: Conditions) -> PlanResult:
        notices = self._pin_notices(conditions)
        conditions = conditions.with_(
            must_include=tuple(
                p.slug for name in conditions.must_include if (p := self.catalogue.find(name))
            ),
            visited=self._visited_slugs(conditions.visited),
        )
        assumptions = list(self._city_assumptions(conditions))
        interests = list(conditions.interests)

        if conditions.month is None:
            nights = conditions.regional_nights or DEFAULT_NIGHTS
            if conditions.regional_nights is None:
                assumptions.append(
                    Assumption("regional_nights", str(nights), f"Assumed: {nights} nights")
                )
            seasons = [
                SeasonChoice(
                    season=key,
                    label=label,
                    month=month,
                    result=self.option_set(self.resolve(conditions, month, nights)),
                )
                for key, label, month in SEASONS
            ]
            return self._result("season_choice", assumptions, interests, notices, seasons=seasons)

        if conditions.regional_nights is None:
            choices = [
                NightsChoice(
                    nights=n,
                    label=f"With {n} nights",
                    result=self.option_set(self.resolve(conditions, conditions.month, n)),
                )
                for n in NIGHTS_CHOICES
            ]
            return self._result(
                "nights_choice", assumptions, interests, notices, nights_options=choices
            )

        resolved = self.resolve(conditions, conditions.month, conditions.regional_nights)
        return self._result(
            "options", assumptions, interests, notices, result=self.option_set(resolved)
        )

    def _result(
        self,
        kind: str,
        assumptions: list[Assumption],
        interests: list[str],
        notices: list[NoticeOut],
        **parts: object,
    ) -> PlanResult:
        return PlanResult(
            kind=kind,  # type: ignore[arg-type]
            assumptions=[
                AssumptionOut(field=a.field, value=a.value, label=a.label) for a in assumptions
            ],
            interests=interests,
            notices=[
                *notices,
                NoticeOut(
                    code="demo_data",
                    text="Destination details are DEMO data: hand-authored, not yet checked "
                    "against operators.",
                ),
            ],
            **parts,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    # resolving undecided inputs
    # ------------------------------------------------------------------
    def resolve(self, conditions: Conditions, month: int, nights: int) -> Resolved:
        arrival = conditions.arrival_hub or conditions.departure_hub or DEFAULT_HUB
        departure = conditions.departure_hub or arrival
        return Resolved(
            conditions=conditions,
            month=month,
            nights=nights,
            arrival=arrival,
            departure=departure,
            assumptions=tuple(self._city_assumptions(conditions)),
        )

    def _city_assumptions(self, c: Conditions) -> list[Assumption]:
        if c.arrival_hub is None and c.departure_hub is None:
            name = self.travel.hub_name(DEFAULT_HUB)
            return [Assumption("cities", DEFAULT_HUB, f"Assumed: {name} in/out")]
        if c.arrival_hub is None:
            name = self.travel.hub_name(c.departure_hub or DEFAULT_HUB)
            return [Assumption("arrival_hub", c.departure_hub or "", f"Assumed: arriving {name}")]
        if c.departure_hub is None:
            name = self.travel.hub_name(c.arrival_hub)
            return [Assumption("departure_hub", c.arrival_hub, f"Assumed: leaving from {name}")]
        return []

    def _visited_slugs(self, visited: Sequence[str]) -> tuple[str, ...]:
        return tuple(p.slug for name in visited if (p := self.catalogue.find(name)))

    def _pin_notices(self, c: Conditions) -> list[NoticeOut]:
        return [
            NoticeOut(
                code="not_in_database",
                text=f"{name}: No verified info yet. It is not in our destination database, "
                "so only travel between major cities can be checked.",
            )
            for name in c.must_include
            if self.catalogue.find(name) is None
        ]

    # ------------------------------------------------------------------
    # one month + nights: the three options
    # ------------------------------------------------------------------
    def option_set(
        self, resolved: Resolved, *, explain: bool = True, check: bool | None = None
    ) -> OptionSet:
        """``explain`` adds rejections and zero-result suggestions; ``check`` runs the
        feasibility engine on each option (defaults to ``explain``)."""
        check = explain if check is None else check
        prefs = preferences_from(resolved.conditions, self.catalogue.places)
        funnel = self.funnel(resolved, prefs)
        combos = self.combos(resolved, prefs, funnel)
        picked = pick_characters(combos, set(resolved.conditions.must_include))
        options = [
            self._option(character, combo, resolved, check=check) for character, combo in picked
        ]
        used_areas = {p.area for _, combo in picked for p in combo.stops}
        return OptionSet(
            month=resolved.month,
            nights=resolved.nights,
            options=options,
            not_for_this_trip=self.rejections(resolved, prefs, funnel, used_areas)
            if explain
            else [],
            funnel=funnel.steps,
            zero_results_suggestions=self.suggestions(resolved) if explain and not options else [],
        )

    def funnel(self, resolved: Resolved, prefs: Preferences) -> Funnel:
        c = resolved.conditions
        month_name = MONTH_NAMES[resolved.month - 1]
        budget = travel_budget(resolved.nights, c.pace, prefs)
        arrival = self.travel.hub_name(resolved.arrival)
        places = sorted(self.catalogue.places.values(), key=lambda p: p.slug)
        dropped: dict[str, tuple[str, str]] = {}
        steps = [FunnelStep(label="places in the database", count=len(places))]

        def keep(label: str, code: str, why: Callable[[Place], str | None]) -> None:
            nonlocal places
            survivors = []
            for place in places:
                reason = why(place)
                if reason is None:
                    survivors.append(place)
                else:
                    dropped[place.slug] = (code, reason)
            places = survivors
            steps.append(FunnelStep(label=label, count=len(places)))

        if c.visited or prefs.excluded:
            keep(
                "not visited or ruled out",
                "visited",
                lambda p: "visited" if p.slug in c.visited or p.slug in prefs.excluded else None,
            )
        keep(
            f"open in {month_name}",
            "season",
            lambda p: (
                None if p.season(resolved.month) >= 1 else f"{month_name} is closed or best avoided"
            ),
        )
        if not resolved.can_drive:
            keep(
                "realistic without a car",
                "car",
                lambda p: None if p.car_need != "required" else "needs a car",
            )
        if c.limited_walking:
            keep(
                "suit limited walking",
                "walking",
                lambda p: None if p.themes[:1] != ("hiking",) else "needs a lot of walking",
            )

        def reach(p: Place) -> str | None:
            route = self.travel.route(resolved.arrival, [p], resolved.departure)
            if route is None:
                return "no public route in our data"
            if route.minutes > budget:
                return f"about {hours(route.minutes)} of travel for {resolved.nights} nights"
            return None

        keep(f"within reach of {arrival} for {resolved.nights} nights", "reach", reach)
        return Funnel(places, dropped, steps)

    def combos(self, resolved: Resolved, prefs: Preferences, funnel: Funnel) -> list[Combo]:
        c = resolved.conditions
        pins = [self.catalogue.places[s] for s in c.must_include if s in self.catalogue.places]
        pin_slugs = {p.slug for p in pins}
        singles = [self._best_combo((p,), resolved, prefs) for p in funnel.survivors]
        ranked = [
            combo.stops[0]
            for combo in sorted(
                (s for s in singles if s is not None),
                key=lambda s: (-s.fit.points, s.stops[0].slug),
            )
            if combo.stops[0].slug not in pin_slugs
        ]
        top_stops = min(max(max_stops(resolved.nights, c.pace, prefs), len(pins)), resolved.nights)
        out: list[Combo] = []
        seen: set[frozenset[str]] = set()
        for k in range(max(1, len(pins)), top_stops + 1):
            free = k - len(pins)
            pool = ranked[: CANDIDATES_FOR_TRIPLES if free >= 2 else CANDIDATES_FOR_PAIRS]
            for extra in itertools.combinations(pool, free):
                stops = (*pins, *extra)
                key = frozenset(p.slug for p in stops)
                if key in seen:
                    continue
                seen.add(key)
                combo = self._best_combo(stops, resolved, prefs, enforce_budget=True)
                if combo is not None:
                    out.append(combo)
        out.sort(key=lambda combo: (-combo.fit.points, sorted(combo.slugs)))
        return out

    def _best_combo(
        self,
        stops: Sequence[Place],
        resolved: Resolved,
        prefs: Preferences,
        *,
        enforce_budget: bool = False,
    ) -> Combo | None:
        if len(stops) > resolved.nights:
            return None
        best: tuple[int, tuple[Place, ...], RouteTime] | None = None
        for order in itertools.permutations(stops):
            route = self.travel.route(resolved.arrival, order, resolved.departure)
            if route is None:
                continue
            if any(leg.minutes > MAX_HOP_MINUTES for leg in route.legs[1:-1]):
                continue
            key = (route.minutes, tuple(p.slug for p in order))
            if best is None or key < (best[0], tuple(p.slug for p in best[1])):
                best = (route.minutes, tuple(order), route)
        if best is None:
            return None
        _, order, route = best
        budget = travel_budget(resolved.nights, resolved.conditions.pace, prefs)
        if enforce_budget and route.minutes > budget:
            return None
        nights = split_nights(order, resolved.nights)
        return Combo(order, nights, route, score(order, nights, route, resolved, prefs))

    # ------------------------------------------------------------------
    # presenting one option
    # ------------------------------------------------------------------
    def _option(
        self, character: str, combo: Combo, resolved: Resolved, *, check: bool = True
    ) -> OptionOut:
        month = resolved.month
        pins = set(resolved.conditions.must_include)
        budget = travel_budget(resolved.nights, resolved.conditions.pace)
        stops = [
            StopOut(
                slug=p.slug,
                name=p.name,
                area=p.area,
                prefecture=p.prefecture,
                nights=n,
                tier=p.tier,
                summary=p.summary,
                pinned=p.slug in pins,
                is_demo=p.is_demo,
                lat=p.lat,
                lon=p.lon,
            )
            for p, n in zip(combo.stops, combo.nights, strict=True)
        ]
        legs = [
            LegOut(
                origin=self._label(leg.origin),
                destination=self._label(leg.destination),
                minutes=leg.minutes,
                transfers=leg.transfers,
            )
            for leg in combo.route.legs
        ]
        longest = max(legs, key=lambda leg: leg.minutes)
        season = min(p.season(month) for p in combo.stops)
        car = "none"
        if any(p.car_need == "required" for p in combo.stops):
            car = "required"
        elif any(p.car_need == "helpful" for p in combo.stops):
            car = "helpful"
        return OptionOut(
            character=character,  # type: ignore[arg-type]
            character_label=CHARACTER_LABELS[character],
            title=" + ".join(p.name for p in combo.stops),
            nights_label=" + ".join(f"{n}N" for n in combo.nights),
            description=" ".join(p.summary for p in combo.stops),
            stops=stops,
            fit=FitOut(
                level=combo.fit.level,
                label=combo.fit.label,
                breakdown=[FitLine(name=line.name, text=line.text) for line in combo.fit.lines],
                adjusted_for=list(combo.fit.adjustments),
            ),
            travel=TravelOut(
                moving_minutes=combo.route.minutes,
                moving_label=f"{hours(combo.route.minutes)} moving in total",
                load=travel_load(combo.route, budget),  # type: ignore[arg-type]
                hotel_changes=len(combo.stops) - 1,
                longest_leg=longest,
                legs=legs,
            ),
            car=car,
            car_label={
                "none": "No car needed",
                "helpful": "No car needed (a car helps)",
                "required": "Car needed",
            }[car],
            season=season,
            season_label=f"{MONTH_NAMES[month - 1]}: {SEASON_WORDS[season]}",
            whats_hard=self._whats_hard(combo, resolved, longest),
            verification=self._verification(combo),
            check=self.checker.check(self.itinerary_of(combo, resolved)) if check else None,
        )

    def itinerary_of(self, combo: Combo, resolved: Resolved) -> Itinerary:
        """The option as an itinerary the feasibility engine can check (and the UI can edit)."""
        c = resolved.conditions
        pins = set(c.must_include)
        return Itinerary(
            stops=tuple(
                StopSpec(p.slug, n, pinned=p.slug in pins)
                for p, n in zip(combo.stops, combo.nights, strict=True)
            ),
            month=resolved.month,
            arrival=resolved.arrival,
            departure=resolved.departure,
            transport=c.transport,
            pace=c.pace,
            big_luggage=c.big_luggage,
            assumptions=Assumptions(whole_trip=False),
        )

    def _label(self, slug: str) -> str:
        place = self.catalogue.places.get(slug)
        return place.name if place else self.travel.hub_name(slug)

    def _relevant_notes(self, place: Place, month: int) -> list[FragileNote]:
        """Notes that matter in this month: a winter closure is not news in July."""

        def relevant(note: FragileNote) -> bool:
            if note.kind == "seasonal_closure":
                return month in note.closed_months
            if note.kind == "weather_cancellation" and "snow" in note.title.lower():
                return month in SEASONAL_THEMES["snow"]
            return True

        return [note for note in place.fragile if relevant(note)]

    def _whats_hard(self, combo: Combo, resolved: Resolved, longest: LegOut) -> list[HardItem]:
        month = resolved.month
        pins = set(resolved.conditions.must_include)
        items: list[HardItem] = []
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        notes = sorted(
            ((p, n) for p in combo.stops for n in self._relevant_notes(p, month)),
            key=lambda pn: (severity_rank.get(pn[1].severity, 3), pn[0].slug, pn[1].kind),
        )
        state_words = {
            FactState.BEING_CHECKED: " (being checked)",
            FactState.UNVERIFIED: " (no verified info yet)",
            FactState.STALE: " (may be out of date)",
            FactState.VERIFIED: "",
        }
        for place, note in notes[:2]:
            items.append(
                HardItem(
                    text=f"{place.name}: {note.title}{state_words[note.state]}",
                    kind=note.kind,
                    fact_state=note.state.value,
                    verified_at=note.verified_at,
                    source_id=note.source_id,
                )
            )
        for place in combo.stops:
            if place.slug in pins and place.season(month) == 0:
                items.insert(
                    0,
                    HardItem(
                        text=f"{place.name} (pinned): {MONTH_NAMES[month - 1]} is closed or best avoided",
                        kind="pinned_out_of_season",
                    ),
                )
        derived: list[HardItem] = []
        if longest.minutes >= 150:
            derived.append(
                HardItem(
                    text=f"Longest travel day: {hours(longest.minutes)}, "
                    f"{longest.origin} to {longest.destination}",
                    kind="travel_burden",
                )
            )
        helpful = [p.name for p in combo.stops if p.car_need == "helpful"]
        if helpful and not resolved.can_drive:
            derived.append(
                HardItem(
                    text=f"Some sights around {', '.join(helpful)} are easier by car",
                    kind="car_helpful",
                )
            )
        for place in combo.stops:
            if place.season(month) == 1:
                derived.append(
                    HardItem(
                        text=f"{place.name}: {MONTH_NAMES[month - 1]} is possible, not ideal",
                        kind="season",
                    )
                )
        items.extend(derived)
        # Always-true fill-ins, so every card shows at least two honest items.
        if len(combo.stops) > 1:
            day = combo.nights[0] + 1
            items.append(
                HardItem(text=f"Hotel change on day {day}: pack up and move", kind="hotel_change")
            )
        for place in combo.stops:
            if not place.fragile:
                items.append(
                    HardItem(
                        text=f"{place.name}: no verified info yet on last buses or closures",
                        kind="no_verified_info",
                        fact_state=FactState.UNVERIFIED.value,
                    )
                )
        items.append(
            HardItem(
                text=f"Longest travel day: {hours(longest.minutes)}, "
                f"{longest.origin} to {longest.destination}",
                kind="travel_burden",
            )
        )
        unique: dict[str, HardItem] = {}
        for item in items:
            unique.setdefault(item.text, item)
        return list(unique.values())[:3]

    def _verification(self, combo: Combo) -> VerificationOut:
        states: list[FactState] = []
        dates: list[datetime] = []
        for place in combo.stops:
            states.append(
                fact_state("verified", place.verified_at, CATALOGUE_TTL_DAYS, now=self.now)
            )
            if place.verified_at:
                dates.append(place.verified_at)
            for note in place.fragile:
                states.append(note.state)
                if note.verified_at:
                    dates.append(note.verified_at)
        worst = max(states, key=_STATE_ORDER.index)
        oldest = min(dates) if dates else None
        date_text = f"{oldest:%d %b %Y}" if oldest else ""
        label = {
            FactState.VERIFIED: f"DEMO data, last checked {date_text}",
            FactState.STALE: f"DEMO data, some details last checked {date_text} and may be out of date",
            FactState.UNVERIFIED: "DEMO data, some details have no verified info yet",
            FactState.BEING_CHECKED: "DEMO data, a detail is being checked",
        }[worst]
        return VerificationOut(state=worst.value, label=label, oldest_verified_at=oldest)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # "Not for this trip"
    # ------------------------------------------------------------------
    def rejections(
        self, resolved: Resolved, prefs: Preferences, funnel: Funnel, used_areas: set[str]
    ) -> list[RejectionOut]:
        """One entry per area with no option, with the reason and what would change it.

        An area whose every place dropped out of the funnel takes the reason of
        its most relevant place. An area that passed the funnel but still lost
        is listed only for a reason the traveller can act on (heavy travel, a
        weak month, nothing matching their interests); an area that simply came
        fourth is not "bad news" and is left out.
        """
        c = resolved.conditions
        budget = travel_budget(resolved.nights, c.pace, prefs)
        survivors_by_area: dict[str, list[Place]] = {}
        for place in funnel.survivors:
            survivors_by_area.setdefault(place.area, []).append(place)
        out: list[tuple[tuple[int, int], RejectionOut]] = []
        for area in Area:
            if area.value in used_areas:
                continue
            label = AREA_LABELS[area]
            in_area = survivors_by_area.get(area.value, [])
            if in_area:
                singles = [
                    combo
                    for p in in_area
                    if (combo := self._best_combo((p,), resolved, prefs)) is not None
                ]
                if not singles:
                    continue
                best = max(singles, key=lambda x: (x.fit.points, x.stops[0].slug))
                rep = best.stops[0]
                if travel_load(best.route, budget) == "heavy":
                    code = "heavy"
                    reason = (
                        f"Heavy travel from {self.travel.hub_name(resolved.arrival)}: even "
                        f"{rep.name} means about {hours(best.route.minutes)} of moving "
                        f"for {resolved.nights} nights."
                    )
                elif c.interests and not set(c.interests) & {
                    t for p in in_area for t in themes_in(p, resolved.month)
                }:
                    code, reason = "interests", f"Little here for {', '.join(c.interests)}."
                elif rep.season(resolved.month) <= 1:
                    code = "season"
                    reason = (
                        f"{MONTH_NAMES[resolved.month - 1]} is possible but not ideal "
                        f"at {rep.name}."
                    )
                else:
                    continue
                current = best.fit.level
            else:
                candidates = [
                    p
                    for p in self.catalogue.places.values()
                    if p.area == area.value and funnel.dropped.get(p.slug, ("",))[0] != "visited"
                ]
                if not candidates:
                    continue
                rep = max(
                    candidates,
                    key=lambda p: (
                        len(set(c.interests) & set(themes_in(p, resolved.month))),
                        p.season(resolved.month),
                        p.tier == "classic",
                        p.slug,
                    ),
                )
                code, why = funnel.dropped.get(rep.slug, ("", ""))
                reason = self._reason_text(code, why, rep, resolved)
                current = 0
            out.append(
                (
                    (
                        -len(set(c.interests) & set(themes_in(rep, resolved.month))),
                        list(Area).index(area),
                    ),
                    RejectionOut(
                        area=area.value,
                        area_label=label,
                        example=rep.name,
                        reason=reason,
                        if_you_change=self._counterfactual(code, rep, label, resolved, current),
                    ),
                )
            )
        out.sort(key=lambda item: item[0])
        return [rejection for _, rejection in out[:MAX_REJECTIONS]]

    def _reason_text(self, code: str, reason: str, rep: Place, resolved: Resolved) -> str:
        arrival = self.travel.hub_name(resolved.arrival)
        if code == "reach":
            return f"Too much travel from {arrival}: {rep.name} is {reason}."
        if code == "season":
            return f"Out of season: at {rep.name}, {reason}."
        if code == "car":
            return f"Hard without a car: {rep.name} {reason}."
        if code == "walking":
            return f"{rep.name} {reason}."
        return f"{rep.name} does not fit these conditions."

    def _counterfactual(
        self, code: str, rep: Place, area_label: str, resolved: Resolved, current: int = 0
    ) -> str | None:
        """The single change that makes ``rep`` fit better than ``current``, re-checked."""
        c = resolved.conditions

        def works(changed: Conditions, nights: int | None = None, month: int | None = None) -> int:
            r = self.resolve(changed, month or resolved.month, nights or resolved.nights)
            prefs = preferences_from(changed, self.catalogue.places)
            if rep.season(r.month) == 0 or (not r.can_drive and rep.car_need == "required"):
                return 0
            combo = self._best_combo((rep,), r, prefs, enforce_budget=True)
            if combo is None:
                return 0
            lighter = code == "heavy" and (
                travel_load(combo.route, travel_budget(r.nights, changed.pace, prefs)) != "heavy"
            )
            return combo.fit.level if combo.fit.level > current or lighter else 0

        def becomes(level: int) -> str:
            return f"{area_label} becomes a {'strong' if level >= 4 else 'possible'} option"

        if code in ("reach", "heavy"):
            for gateway in self.catalogue.gateways_in(rep.area):
                if gateway.slug == resolved.departure:
                    continue
                if level := works(
                    c.with_(arrival_hub=resolved.arrival, departure_hub=gateway.slug)
                ):
                    return f"If you can fly out of {gateway.name}, {becomes(level)}."
            for extra in (2, 3):
                if level := works(c, nights=resolved.nights + extra):
                    return f"With {resolved.nights + extra} regional nights, {becomes(level)}."
            for gateway in self.catalogue.gateways_in(rep.area):
                if level := works(c.with_(arrival_hub=gateway.slug, departure_hub=gateway.slug)):
                    return f"If you fly into and out of {gateway.name}, {becomes(level)}."
            return None
        if code == "car":
            if level := works(c.with_(transport=Transport.CAN_DRIVE)):
                return f"If you can drive, {becomes(level)}."
            return None
        if code == "season":
            good = [m for m in range(1, 13) if rep.season(m) >= 2]
            if current and good:
                good = [m for m in range(1, 13) if rep.season(m) == 3] or good
            if good:
                return f"In {_month_span(good)}, {rep.name} is a good choice."
            return None
        return None

    # ------------------------------------------------------------------
    # zero results
    # ------------------------------------------------------------------
    def suggestions(self, resolved: Resolved) -> list[SuggestionOut]:
        c = resolved.conditions
        tries: list[tuple[str, str, Conditions, int, int]] = []
        m, n = resolved.month, resolved.nights
        if c.transport is Transport.NO_CAR:
            tries.append(
                ("can_drive", "If you can drive", c.with_(transport=Transport.EITHER), m, n)
            )
        tries.append(("nights_plus_1", f"With {n + 1} nights", c, m, n + 1))
        tries.append(("nights_plus_2", f"With {n + 2} nights", c, m, n + 2))
        for delta in (-1, 1):
            month = (m - 1 + delta) % 12 + 1
            tries.append((f"month_{month}", f"In {MONTH_NAMES[month - 1]}", c, month, n))
        if c.pace is not Pace.FAST:
            tries.append(("pace_fast", "With a faster pace", c.with_(pace=Pace.FAST), m, n))
        if c.limited_walking:
            tries.append(
                (
                    "walking",
                    "Including places with more walking",
                    c.with_(limited_walking=False),
                    m,
                    n,
                )
            )
        for slug in c.must_include:
            name = self._label(slug)
            rest = tuple(s for s in c.must_include if s != slug)
            tries.append(
                (f"unpin_{slug}", f"Without {name} pinned", c.with_(must_include=rest), m, n)
            )
        if c.reactions:
            tries.append(
                ("reset_reactions", "Clearing your reactions", c.with_(reactions=()), m, n)
            )
        out: list[SuggestionOut] = []
        for code, label, changed, month, nights in tries:
            found = len(
                self.option_set(self.resolve(changed, month, nights), explain=False).options
            )
            if found:
                out.append(SuggestionOut(change=code, label=label, options_found=found))
        return out[:4]


def split_nights(stops: Sequence[Place], nights: int) -> tuple[int, ...]:
    """At least one night each; the rest to whoever is furthest below their typical stay,
    then to the place that is usually stayed in longest."""
    alloc = [1] * len(stops)
    for _ in range(nights - len(stops)):
        i = max(
            range(len(stops)),
            key=lambda j: (stops[j].typical_nights - alloc[j], stops[j].typical_nights, -j),
        )
        alloc[i] += 1
    return tuple(alloc)


def pick_characters(combos: Sequence[Combo], pins: set[str]) -> list[tuple[str, Combo]]:
    """Classic, Unexpected and Slow-paced, sharing no unpinned stop where possible."""
    if not combos:
        return []

    def overlap(a: Combo, chosen: Sequence[Combo]) -> int:
        return max((len((a.slugs & b.slugs) - pins) for b in chosen), default=0)

    def first(
        candidates: Sequence[Combo], chosen: Sequence[Combo], key: Callable[[Combo], tuple]
    ) -> Combo | None:
        for allowed in (0, 1):
            pool = [
                x
                for x in candidates
                if overlap(x, chosen) <= allowed and all(x.slugs != y.slugs for y in chosen)
            ]
            if pool:
                return min(pool, key=key)
        return None

    picked: list[tuple[str, Combo]] = []
    chosen: list[Combo] = []

    def by_points(x: Combo) -> tuple:
        return (-x.fit.points, sorted(x.slugs))

    classic = first(
        [x for x in combos if any(p.tier == "classic" for p in x.stops)] or combos,
        chosen,
        by_points,
    )
    if classic:
        picked.append(("classic", classic))
        chosen.append(classic)

    classic_areas = {p.area for p in classic.stops} if classic else set()
    unexpected = first(
        [x for x in combos if any(p.tier == "hidden" for p in x.stops)] or combos,
        chosen,
        lambda x: (
            -(x.fit.points + (4.0 if not {p.area for p in x.stops} & classic_areas else 0.0)),
            sorted(x.slugs),
        ),
    )
    if unexpected:
        picked.append(("unexpected", unexpected))
        chosen.append(unexpected)

    slow = first(
        combos,
        chosen,
        lambda x: (len(x.stops), -(x.fit.points - x.route.minutes / 60), sorted(x.slugs)),
    )
    if slow:
        picked.append(("slow_paced", slow))
    return picked


def _month_span(months: list[int]) -> str:
    """[4, 5, 6, 10, 11] -> "April–June and October–November"."""
    runs: list[list[int]] = []
    for m in months:
        if runs and m == runs[-1][-1] + 1:
            runs[-1].append(m)
        else:
            runs.append([m])
    if len(runs) > 1 and runs[0][0] == 1 and runs[-1][-1] == 12:
        runs[0] = runs.pop() + runs[0]
    parts = [
        MONTH_NAMES[r[0] - 1]
        if len(r) == 1
        else f"{MONTH_NAMES[r[0] - 1]}–{MONTH_NAMES[r[-1] - 1]}"
        for r in runs
    ]
    return " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 1 else parts)
