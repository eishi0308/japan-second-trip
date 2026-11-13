"""Feasibility engine: does this itinerary actually work, day by day?

Shared by Where Next (every option is checked) and RouteCheck (the traveller's
own itinerary). Pure and deterministic: no I/O, no model call.

What it does
------------
1. **Resolves** each stop against the catalogue: a destination (with its
   fragile links), a hub city, or unknown ("No verified info yet": only
   travel between known places is checked).
2. **Lays out days.** Each day shows moving time and time at the
   destination. Clock times come from default assumptions the traveller can
   edit, and each one is labelled: leave the hotel at 09:30, sightseeing ends
   at 18:30, land at 14:00, be at the departure city by 15:00 for a flight.
3. **Runs rules** on the days: last connections against estimated arrival
   times, seasonal and weekly closures, car-only places, long travel days,
   late arrivals, one-night churn, travel share, departure-day risk,
   backtracking. A fact that is being checked (sources disagree) is never
   asserted. The issue says so and is flagged for human review.
4. **Grades** the trip: Will not work (any critical issue), Needs attention
   (any warning), or Works.
5. **Proposes fixes.** Each candidate is a concrete change to the itinerary:
   reorder, leave earlier, move a night, swap a stop, skip a stop. Each one
   is re-checked, and a fix is offered for an issue only if it really
   resolves it. **A pinned stop is never removed or swapped.** Each fix
   carries a before/after diff of what is gained and what is lost.

Estimated times are estimates: the last stretch is modelled as hub time, and
the connection point is assumed to be halfway along it. The UI labels them
"estimated" and shows the assumptions they rest on.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from jst_api.domain.backbone import CHANGE_MINUTES
from jst_api.domain.enums import Pace
from jst_api.domain.fact_state import FactState, fact_state
from jst_api.planner.model import Catalogue, FragileNote, HubInfo, Place, Transport
from jst_api.planner.results import (
    VERDICT_LABELS,
    AssumptionOut,
    BookingOut,
    CheckResult,
    CheckStopOut,
    DayOut,
    DiffOut,
    EvidenceOut,
    FixOut,
    IssueOut,
    MoveOut,
)
from jst_api.planner.scoring import MONTH_NAMES, SEASONAL_THEMES, hours
from jst_api.planner.travel import TravelModel

PACE_DAY_LIMIT = {Pace.RELAXED: 240, Pace.BALANCED: 300, Pace.FAST: 390}
"""Most moving minutes a day can take before it is a travel day, by pace."""
TIGHT_MARGIN = 45
TRAVEL_SHARE_LIMIT = 0.35
CHURN_LIMIT = 2
"""Consecutive one-night stops tolerated before it is a packing trip."""
BACKTRACK_SAVING = 90
LATE_REGIONAL_RETURN = 21 * 60
EARLIEST_LEAVE = 6 * 60 + 30
CATALOGUE_TTL_DAYS = 365
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_VERDICT_RANK = {"works": 0, "needs_attention": 1, "will_not_work": 2}


def clock(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_clock(value: str | None) -> int | None:
    if not value or ":" not in value:
        return None
    h, _, m = value.strip().partition(":")
    try:
        return int(h) * 60 + int(m[:2])
    except ValueError:
        return None


@dataclass(frozen=True)
class Assumptions:
    """Default clock times. Editable; always shown as "Assumed"."""

    leave_hotel: int = 9 * 60 + 30
    day_end: int = 18 * 60 + 30
    landing: int = 14 * 60
    flight_cutoff: int = 15 * 60
    whole_trip: bool = True
    """True for RouteCheck: arrival is landing in Japan and departure is a
    flight out. False for a Where Next regional leg, which starts from the
    arrival city in the morning and returns to the departure city."""

    def describe(self) -> list[AssumptionOut]:
        out = [
            AssumptionOut(
                field="leave_hotel",
                value=clock(self.leave_hotel),
                label=f"Assumed: leave the hotel at {clock(self.leave_hotel)}",
            ),
            AssumptionOut(
                field="day_end",
                value=clock(self.day_end),
                label=f"Assumed: sightseeing ends at {clock(self.day_end)}",
            ),
        ]
        if self.whole_trip:
            out += [
                AssumptionOut(
                    field="landing",
                    value=clock(self.landing),
                    label=f"Assumed: you land and reach the first city by {clock(self.landing)}",
                ),
                AssumptionOut(
                    field="flight_cutoff",
                    value=clock(self.flight_cutoff),
                    label=f"Assumed: be at the departure city by {clock(self.flight_cutoff)} "
                    "for your flight",
                ),
            ]
        return out


@dataclass(frozen=True)
class StopSpec:
    name: str
    nights: int
    pinned: bool = False
    leave_at: int | None = None
    """Override for the time you leave this stop (a fix can set it)."""


@dataclass(frozen=True)
class Itinerary:
    stops: tuple[StopSpec, ...]
    month: int
    arrival: str | None = None
    departure: str | None = None
    start_date: date | None = None
    transport: Transport = Transport.NO_CAR
    pace: Pace = Pace.BALANCED
    big_luggage: bool = False
    assumptions: Assumptions = field(default_factory=Assumptions)

    def with_stops(self, stops: Sequence[StopSpec]) -> Itinerary:
        return replace(self, stops=tuple(stops))


@dataclass(frozen=True)
class Stop:
    spec: StopSpec
    kind: str  # "place" | "city" | "unknown"
    place: Place | None

    @property
    def name(self) -> str:
        return self.place.name if self.place else self.spec.name

    @property
    def slug(self) -> str | None:
        return self.place.slug if self.place else None


@dataclass
class Issue:
    kind: str
    severity: str
    title: str
    why: str
    stop: str | None = None
    day: int | None = None
    needs_review: bool = False
    evidence: list[EvidenceOut] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.stop or "")

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.stop or 'trip'}:{self.day or 0}"


@dataclass
class Analysis:
    itinerary: Itinerary
    stops: list[Stop]
    days: list[DayOut]
    issues: list[Issue]
    booking: list[BookingOut]
    moving: int

    @property
    def verdict(self) -> str:
        severities = {i.severity for i in self.issues}
        if "critical" in severities:
            return "will_not_work"
        if "warning" in severities:
            return "needs_attention"
        return "works"

    def blocking(self) -> dict[tuple[str, str], Issue]:
        return {i.key: i for i in self.issues if i.severity != "info"}


def _city_place(hub: HubInfo) -> Place:
    return Place(
        slug=hub.slug,
        name=hub.name,
        area=hub.area,
        prefecture="",
        hub_slug=hub.slug,
        hub_minutes=0,
        hub_transfers=0,
        access_mode="walk",
        car_need="none",
        season_fit=(2,) * 12,
        themes=("city",),
        tier="classic",
        typical_nights=1,
        summary="",
        verified_at=None,
    )


class Checker:
    def __init__(self, catalogue: Catalogue, *, now: datetime | None = None) -> None:
        self.catalogue = catalogue
        self.travel = TravelModel(catalogue)
        self.now = now or datetime.now(UTC)

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------
    def resolve_stop(self, spec: StopSpec) -> Stop:
        place = self.catalogue.find(spec.name)
        if place is not None:
            return Stop(spec, "place", place)
        key = spec.name.strip().lower()
        for hub in self.catalogue.hubs.values():
            if key in (hub.slug, hub.name.lower()):
                return Stop(spec, "city", _city_place(hub))
        return Stop(spec, "unknown", None)

    def _endpoint(self, hub_slug: str | None, fallback: Stop) -> Place | None:
        if hub_slug and hub_slug in self.catalogue.hubs:
            return _city_place(self.catalogue.hubs[hub_slug])
        if fallback.place is not None:
            return _city_place(self.catalogue.hubs[fallback.place.hub_slug])
        return None

    def _move(self, a: Place | None, b: Place | None) -> tuple[int, int] | None:
        if a is None or b is None:
            return None
        if a.slug == b.slug:
            return (0, 0)
        if a.access_mode == "walk" and a.hub_minutes == 0 and a.slug == a.hub_slug:
            return self.travel.hub_to_place(a.slug, b)
        if b.access_mode == "walk" and b.hub_minutes == 0 and b.slug == b.hub_slug:
            return self.travel.hub_to_place(b.slug, a)
        return self.travel.between(a, b)

    # ------------------------------------------------------------------
    # analysis
    # ------------------------------------------------------------------
    def analyse(self, itin: Itinerary) -> Analysis:
        a = itin.assumptions
        stops = [self.resolve_stop(s) for s in itin.stops]
        if not stops:
            return Analysis(itin, [], [], [], [], 0)
        start = self._endpoint(itin.arrival, stops[0])
        end = self._endpoint(itin.departure, stops[-1])
        issues: list[Issue] = []
        days: list[DayOut] = []
        booking: list[BookingOut] = []

        def date_of(day: int) -> date | None:
            return itin.start_date + timedelta(days=day - 1) if itin.start_date else None

        def day_out(
            day: int, title: str, overnight: str | None, moves: list[MoveOut], staying: int
        ) -> DayOut:
            moving = sum(m.minutes for m in moves)
            d = date_of(day)
            return DayOut(
                day=day,
                date=d.isoformat() if d else None,
                title=title,
                overnight=overnight,
                moving_minutes=moving,
                staying_minutes=max(0, staying),
                moving_label="No travel" if not moving else f"{hours(moving)} moving",
                staying_label=f"{hours(max(0, staying))} at the destination"
                if staying > 0
                else "No time to look around",
                moves=moves,
            )

        loc: Place | None = start
        loc_name = start.name if start else "arrival"
        day_no = 1
        now_clock = a.landing if a.whole_trip else a.leave_hotel
        pending: list[MoveOut] = []
        total_moving = 0
        for i, stop in enumerate(stops):
            landing_here = (
                i == 0
                and loc is not None
                and stop.place is not None
                and (stop.place.slug == loc.slug)
            )
            if not landing_here:
                hop = self._move(loc, stop.place)
                depart = now_clock
                if hop is None:
                    pending.append(
                        MoveOut(
                            origin=loc_name,
                            destination=stop.name,
                            depart=clock(depart),
                            arrive="unknown",
                            minutes=0,
                            transfers=0,
                        )
                    )
                else:
                    minutes, transfers = hop
                    arrive = depart + minutes
                    pending.append(
                        MoveOut(
                            origin=loc_name,
                            destination=stop.name,
                            depart=clock(depart),
                            arrive=clock(arrive),
                            minutes=minutes,
                            transfers=transfers,
                        )
                    )
                    total_moving += minutes
                    if stop.place is not None and stop.kind == "place":
                        issues += self._connection_issues(stop, depart, minutes, day_no, itin)
                    now_clock = arrive
            loc, loc_name = stop.place, stop.name
            if stop.spec.nights == 0:
                continue  # a waypoint: keep moving the same day
            moving_today = sum(m.minutes for m in pending)
            if pending:
                title = " → ".join([pending[0].origin, *(m.destination for m in pending)])
            else:
                title = f"Arrive in {stop.name}"
            days.append(day_out(day_no, title, stop.name, pending, a.day_end - now_clock))
            limit = PACE_DAY_LIMIT[itin.pace]
            if moving_today > limit:
                issues.append(
                    Issue(
                        "long_travel_day",
                        "critical" if moving_today > limit + 150 else "warning",
                        f"Day {day_no} is {hours(moving_today)} of travel",
                        f"That is more than a {itin.pace.value} pace allows in one day "
                        f"({hours(limit)}), so the day goes to trains and buses.",
                        stop=stop.slug or stop.name,
                        day=day_no,
                        evidence=self._travel_evidence(stop),
                    )
                )
            if pending and now_clock > a.day_end:
                issues.append(
                    Issue(
                        "late_arrival",
                        "warning",
                        f"You reach {stop.name} around {clock(now_clock)} (estimated)",
                        f"That is after {clock(a.day_end)}, so day {day_no} has no time there, "
                        "and late check-in can be a problem at small inns.",
                        stop=stop.slug or stop.name,
                        day=day_no,
                        evidence=self._travel_evidence(stop),
                    )
                )
            issues += self._stay_issues(stop, day_no, itin, date_of)
            booking += self._booking(stop, date_of(day_no))
            for extra in range(1, stop.spec.nights):
                days.append(
                    day_out(day_no + extra, stop.name, stop.name, [], a.day_end - a.leave_hotel)
                )
            day_no += stop.spec.nights
            now_clock = stop.spec.leave_at if stop.spec.leave_at is not None else a.leave_hotel
            pending = []

        # final day: to the departure city
        final_moves = list(pending)
        if end is not None and loc is not None and loc.slug != end.slug:
            hop = self._move(loc, end)
            if hop is not None:
                minutes, transfers = hop
                final_moves.append(
                    MoveOut(
                        origin=loc_name,
                        destination=end.name,
                        depart=clock(now_clock),
                        arrive=clock(now_clock + minutes),
                        minutes=minutes,
                        transfers=transfers,
                    )
                )
                total_moving += minutes
                now_clock += minutes
        end_name = end.name if end else loc_name
        cutoff = a.flight_cutoff if a.whole_trip else a.day_end
        days.append(
            day_out(
                day_no,
                " → ".join([final_moves[0].origin, *(m.destination for m in final_moves)])
                if final_moves
                else f"Leave from {end_name}",
                None,
                final_moves,
                cutoff - now_clock,
            )
        )
        if a.whole_trip and now_clock > a.flight_cutoff and final_moves:
            issues.append(
                Issue(
                    "departure_risk",
                    "critical",
                    f"Departure day: you reach {end_name} around {clock(now_clock)} (estimated)",
                    f"For a flight you should be there by {clock(a.flight_cutoff)}; the "
                    f"{hours(sum(m.minutes for m in final_moves))} transfer leaves no margin "
                    "for a delay.",
                    stop=end.slug if end else None,
                    day=day_no,
                    evidence=self._travel_evidence(stops[-1]),
                )
            )
        elif not a.whole_trip and now_clock > LATE_REGIONAL_RETURN:
            issues.append(
                Issue(
                    "late_return",
                    "warning",
                    f"You get back to {end_name} around {clock(now_clock)} (estimated)",
                    "The last day is mostly travel and ends late.",
                    stop=end.slug if end else None,
                    day=day_no,
                    evidence=self._travel_evidence(stops[-1]),
                )
            )

        issues += self._trip_issues(stops, days, total_moving, itin, start, end)
        issues.sort(key=lambda i: (_SEVERITY_RANK[i.severity], i.day or 0, i.kind))
        for day in days:
            day.issue_ids = [i.id for i in issues if i.day == day.day]
        return Analysis(itin, stops, days, issues, booking, total_moving)

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------
    def _evidence(self, note: FragileNote) -> EvidenceOut:
        when = f"{note.verified_at:%d %b %Y}" if note.verified_at else ""
        label = {
            FactState.VERIFIED: f"DEMO record, checked {when}",
            FactState.STALE: f"DEMO record, checked {when}, may be out of date",
            FactState.UNVERIFIED: "DEMO record, no verified info yet",
            FactState.BEING_CHECKED: "DEMO record, sources disagree, being checked",
        }[note.state]
        return EvidenceOut(
            source_id=note.source_id,
            label=label,
            fact_state=note.state.value,  # type: ignore[arg-type]
            verified_at=note.verified_at,
        )

    def _travel_evidence(self, stop: Stop) -> list[EvidenceOut]:
        place = stop.place
        if place is None or place.verified_at is None:
            return []
        state = fact_state("verified", place.verified_at, CATALOGUE_TTL_DAYS, now=self.now)
        return [
            EvidenceOut(
                source_id=place.source_id,
                label=f"DEMO travel times, checked {place.verified_at:%d %b %Y}",
                fact_state=state.value,  # type: ignore[arg-type]
                verified_at=place.verified_at,
            )
        ]

    def _connection_issues(
        self, stop: Stop, depart: int, minutes: int, day: int, itin: Itinerary
    ) -> list[Issue]:
        place = stop.place
        assert place is not None
        change = (
            CHANGE_MINUTES if place.access_mode != "walk" and minutes > place.hub_minutes else 0
        )
        at_hub = depart + max(0, minutes - place.hub_minutes - change)
        at_connection = at_hub + change + place.hub_minutes // 2
        out: list[Issue] = []
        for note in place.fragile:
            if note.kind not in ("last_connection", "ryokan_shuttle"):
                continue
            evidence = [self._evidence(note)]
            if note.state is FactState.BEING_CHECKED:
                times = [t for v in note.conflicting_values if (t := parse_clock(v)) is not None]
                safe = bool(times) and at_connection + TIGHT_MARGIN <= min(times)
                out.append(
                    Issue(
                        note.kind,
                        "info" if safe else "warning",
                        f"{note.title}: being checked",
                        (
                            "Sources disagree on this detail, so we cannot confirm it. You "
                            f"would reach the connection around {clock(at_connection)} "
                            "(estimated), well ahead of every reported time."
                        )
                        if safe
                        else (
                            "Sources disagree on this detail, so we cannot confirm you make it. "
                            f"You would reach the connection around {clock(at_connection)} "
                            "(estimated). A reviewer has been asked to check."
                        ),
                        stop=place.slug,
                        day=day,
                        needs_review=True,
                        evidence=evidence,
                    )
                )
                continue
            last = parse_clock(note.last_departure_local)
            if note.state is FactState.UNVERIFIED or last is None:
                out.append(
                    Issue(
                        note.kind,
                        "warning",
                        f"{note.title}: no verified info yet",
                        f"We hold no verified time for this at {place.name}, so we cannot "
                        "check that you make it. Confirm it before you book.",
                        stop=place.slug,
                        day=day,
                        evidence=evidence,
                    )
                )
                continue
            stale = " The time was last checked a while ago and may be out of date." * (
                note.state is FactState.STALE
            )
            if at_connection > last:
                out.append(
                    Issue(
                        note.kind,
                        "critical",
                        f"You miss the {note.title.lower()} at {place.name}",
                        f"You would reach the connection around {clock(at_connection)} "
                        f"(estimated), after the last departure at {clock(last)}.{stale}",
                        stop=place.slug,
                        day=day,
                        evidence=evidence,
                    )
                )
            elif at_connection + TIGHT_MARGIN > last:
                out.append(
                    Issue(
                        note.kind,
                        "warning",
                        f"Tight connection: {note.title.lower()} at {place.name}",
                        f"You would reach the connection around {clock(at_connection)} "
                        f"(estimated) for the last departure at {clock(last)}; one delay and "
                        f"you miss it.{stale}",
                        stop=place.slug,
                        day=day,
                        evidence=evidence,
                    )
                )
        return out

    def _stay_issues(self, stop: Stop, day: int, itin: Itinerary, date_of) -> list[Issue]:
        if stop.kind == "unknown":
            return [
                Issue(
                    "not_in_database",
                    "warning",
                    f"{stop.name}: no verified info yet",
                    "It is not in our destination database, so travel to and from it, last "
                    "connections and closures are not checked.",
                    stop=stop.name,
                    day=day,
                )
            ]
        place = stop.place
        assert place is not None
        out: list[Issue] = []
        month = itin.month
        month_name = MONTH_NAMES[month - 1]
        closure = [
            n for n in place.fragile if n.kind == "seasonal_closure" and month in n.closed_months
        ]
        if closure or place.season(month) == 0:
            note = closure[0] if closure else None
            out.append(
                Issue(
                    "seasonal_closure",
                    "critical",
                    f"{place.name} is closed or best avoided in {month_name}",
                    note.title
                    if note
                    else "Our season data marks this month as closed or best avoided.",
                    stop=place.slug,
                    day=day,
                    evidence=[self._evidence(note)] if note else self._travel_evidence(stop),
                )
            )
        if place.car_need == "required" and itin.transport is Transport.NO_CAR:
            out.append(
                Issue(
                    "car_required",
                    "critical",
                    f"{place.name} needs a car",
                    "Public transport does not reach it in a way that works for a stay.",
                    stop=place.slug,
                    day=day,
                    evidence=self._travel_evidence(stop),
                )
            )
        for note in place.fragile:
            if note.kind == "weekly_closure" and note.closed_weekdays:
                closed = ", ".join(WEEKDAYS[d] + "s" for d in note.closed_weekdays if 0 <= d < 7)
                stay = [date_of(day + k) for k in range(stop.spec.nights)]
                hit = [d for d in stay if d and d.weekday() in note.closed_weekdays]
                if hit:
                    out.append(
                        Issue(
                            "weekly_closure",
                            "warning",
                            f"{note.title} on {hit[0]:%a %d %b}",
                            f"It is closed on {closed}, and you are there that day.",
                            stop=place.slug,
                            day=day,
                            evidence=[self._evidence(note)],
                        )
                    )
                elif itin.start_date is None:
                    out.append(
                        Issue(
                            "weekly_closure",
                            "info",
                            f"{note.title}",
                            f"Closed on {closed}. Add your dates to check your stay.",
                            stop=place.slug,
                            day=day,
                            evidence=[self._evidence(note)],
                        )
                    )
            elif note.kind == "access_disruption":
                out.append(
                    Issue(
                        "access_disruption",
                        "warning",
                        f"{place.name}: {note.title}",
                        note.detail,
                        stop=place.slug,
                        day=day,
                        evidence=[self._evidence(note)],
                    )
                )
            elif note.kind == "weather_cancellation" and (
                "snow" not in note.title.lower() or month in SEASONAL_THEMES["snow"]
            ):
                out.append(
                    Issue(
                        "weather",
                        "info",
                        f"{place.name}: {note.title}",
                        note.detail,
                        stop=place.slug,
                        day=day,
                        evidence=[self._evidence(note)],
                    )
                )
            elif note.kind == "low_frequency":
                per_day = (
                    f" (about {note.frequency_per_day} a day)" if note.frequency_per_day else ""
                )
                out.append(
                    Issue(
                        "low_frequency",
                        "info",
                        f"{place.name}: {note.title}{per_day}",
                        note.detail,
                        stop=place.slug,
                        day=day,
                        evidence=[self._evidence(note)],
                    )
                )
        return out

    def _booking(self, stop: Stop, arrival_date: date | None) -> list[BookingOut]:
        if stop.place is None:
            return []
        out = []
        for note in stop.place.fragile:
            if (
                note.kind not in ("booking_difficulty", "ryokan_shuttle")
                and not note.lead_time_days
            ):
                continue
            book_by = None
            if arrival_date and note.lead_time_days:
                book_by = (arrival_date - timedelta(days=note.lead_time_days)).isoformat()
            out.append(
                BookingOut(
                    stop=stop.place.name,
                    text=f"{stop.place.name}: {note.title}",
                    lead_time_days=note.lead_time_days,
                    book_by=book_by,
                    evidence=self._evidence(note),
                )
            )
        return out

    def _trip_issues(
        self,
        stops: list[Stop],
        days: list[DayOut],
        moving: int,
        itin: Itinerary,
        start: Place | None,
        end: Place | None,
    ) -> list[Issue]:
        out: list[Issue] = []
        first_known = next((s for s in stops if s.place is not None and s.kind == "place"), None)
        evidence = self._travel_evidence(first_known) if first_known else []
        run: list[Stop] = []
        runs: list[list[Stop]] = []
        for stop in stops:
            if stop.spec.nights == 1:
                run.append(stop)
            elif stop.spec.nights > 1:
                if len(run) > CHURN_LIMIT:
                    runs.append(run)
                run = []
        if len(run) > CHURN_LIMIT:
            runs.append(run)
        for r in runs:
            out.append(
                Issue(
                    "hotel_churn",
                    "critical" if len(r) >= 5 else "warning",
                    f"{len(r)} one-night stays in a row",
                    f"{', '.join(s.name for s in r)}: you pack up and move every morning, and "
                    "each stay is mostly arriving and leaving.",
                    evidence=self._travel_evidence(r[0]),
                )
            )
        usable = sum(itin.assumptions.day_end - itin.assumptions.leave_hotel for _ in days)
        if usable and moving / usable > TRAVEL_SHARE_LIMIT:
            out.append(
                Issue(
                    "travel_share",
                    "warning",
                    f"{hours(moving)} of travel in {len(days)} days",
                    "More than a third of your waking sightseeing time goes to moving between "
                    "places.",
                    evidence=evidence,
                )
            )
        known = [s for s in stops if s.place is not None]
        if 3 <= len(known) <= 7 and len(known) == len(stops):
            best = self._best_order_minutes(stops, start, end)
            if best is not None and moving - best >= BACKTRACK_SAVING:
                out.append(
                    Issue(
                        "backtracking",
                        "warning",
                        "The order of stops costs extra travel",
                        f"Visiting the same places in a different order saves about "
                        f"{hours(moving - best)} of moving.",
                        evidence=evidence,
                    )
                )
        return out

    def _route_minutes(
        self, places: Sequence[Place], start: Place | None, end: Place | None
    ) -> int | None:
        seq = [p for p in [start, *places, end] if p is not None]
        total = 0
        for a, b in itertools.pairwise(seq):
            hop = self._move(a, b)
            if hop is None:
                return None
            total += hop[0]
        return total

    def _fixed_ends(self, stops: Sequence[Stop], itin: Itinerary) -> tuple[bool, bool]:
        """A first stop in the arrival city and a last stop in the departure city stay put."""
        first = bool(stops) and stops[0].kind == "city" and (itin.arrival in (None, stops[0].slug))
        last = (
            len(stops) > 1
            and stops[-1].kind == "city"
            and (itin.departure in (None, stops[-1].slug))
        )
        return first, last

    def _best_order_minutes(
        self, stops: list[Stop], start: Place | None, end: Place | None
    ) -> int | None:
        order = self._best_order(stops, (start, end))
        if order is None:
            return None
        return self._route_minutes([s.place for s in order if s.place], start, end)

    def _best_order(self, stops: list[Stop], ends) -> list[Stop] | None:
        start, end = ends
        head = 1 if stops and start is not None and stops[0].slug == start.slug else 0
        tail = 1 if len(stops) > head and end is not None and stops[-1].slug == end.slug else 0
        middle = stops[head : len(stops) - tail]
        if len(middle) > 6:
            return None
        best: tuple[int, list[Stop]] | None = None
        for perm in itertools.permutations(middle):
            order = [*stops[:head], *perm, *stops[len(stops) - tail :]]
            minutes = self._route_minutes([s.place for s in order if s.place], start, end)
            if minutes is not None and (best is None or minutes < best[0]):
                best = (minutes, order)
        return best[1] if best else None

    # ------------------------------------------------------------------
    # fixes
    # ------------------------------------------------------------------
    def check(self, itin: Itinerary) -> CheckResult:
        before = self.analyse(itin)
        candidates = self._candidates(before)
        evaluated = [(label, cost, self.analyse(after)) for label, cost, after in candidates]
        issues_out: list[IssueOut] = []
        for issue in before.issues:
            fixes: list[FixOut] = []
            if issue.severity != "info":
                fixes = self._fixes_for(issue, before, evaluated)
            issues_out.append(
                IssueOut(
                    id=issue.id,
                    kind=issue.kind,
                    severity=issue.severity,  # type: ignore[arg-type]
                    title=issue.title,
                    why=issue.why,
                    day=issue.day,
                    stop=issue.stop,
                    needs_review=issue.needs_review,
                    fixes=fixes,
                    evidence=issue.evidence,
                )
            )
        verdict = before.verdict
        counts = {s: sum(i.severity == s for i in before.issues) for s in ("critical", "warning")}
        if verdict == "works":
            summary = "Every day works on these assumptions."
        else:
            parts = []
            if counts["critical"]:
                parts.append(
                    f"{counts['critical']} problem{'s' * (counts['critical'] > 1)} "
                    "that break the trip"
                )
            if counts["warning"]:
                parts.append(f"{counts['warning']} thing{'s' * (counts['warning'] > 1)} to look at")
            summary = " and ".join(parts).capitalize() + "."
        return CheckResult(
            verdict=verdict,  # type: ignore[arg-type]
            verdict_label=VERDICT_LABELS[verdict],
            summary=summary,
            stops=self._stops_out(before.stops),
            assumptions=itin.assumptions.describe(),
            days=before.days,
            issues=issues_out,
            booking=before.booking,
            moving_minutes=before.moving,
            hotel_changes=max(0, sum(1 for s in before.stops if s.spec.nights > 0) - 1),
        )

    def _stops_out(self, stops: Sequence[Stop]) -> list[CheckStopOut]:
        return [
            CheckStopOut(
                name=s.name,
                slug=s.slug,
                kind=s.kind,  # type: ignore[arg-type]
                nights=s.spec.nights,
                pinned=s.spec.pinned,
                area=s.place.area if s.place else None,
            )
            for s in stops
        ]

    def _candidates(self, before: Analysis) -> list[tuple[str, int, Itinerary]]:
        itin = before.itinerary
        stops = before.stops
        specs = list(itin.stops)
        first_fixed, last_fixed = self._fixed_ends(stops, itin)
        movable = [
            i
            for i in range(len(stops))
            if not (i == 0 and first_fixed) and not (i == len(stops) - 1 and last_fixed)
        ]
        out: list[tuple[str, int, Itinerary]] = []

        # reorder
        start = self._endpoint(itin.arrival, stops[0]) if stops else None
        end = self._endpoint(itin.departure, stops[-1]) if stops else None
        if all(s.place for s in stops):
            order = self._best_order(stops, (start, end))
            if order is not None and [s.spec for s in order] != specs:
                out.append(
                    (
                        "Change the order: " + " → ".join(s.name for s in order),
                        1,
                        itin.with_stops([s.spec for s in order]),
                    )
                )

        # leave earlier from the stop before each timed connection
        for i in range(len(stops) - 1):
            for leave in (8 * 60 + 30, 7 * 60 + 30, EARLIEST_LEAVE):
                if leave >= (specs[i].leave_at or itin.assumptions.leave_hotel):
                    continue
                new = list(specs)
                new[i] = replace(specs[i], leave_at=leave)
                out.append(
                    (
                        f"Leave {stops[i].name} at {clock(leave)} instead of "
                        f"{clock(specs[i].leave_at or itin.assumptions.leave_hotel)}",
                        1 if leave >= 8 * 60 else 2,
                        itin.with_stops(new),
                    )
                )

        # move a night between stops (pinned stops keep at least one night)
        for i, j in itertools.permutations(range(len(specs)), 2):
            if specs[i].nights >= 2 and specs[j].nights >= 1:
                new = list(specs)
                new[i] = replace(specs[i], nights=specs[i].nights - 1)
                new[j] = replace(specs[j], nights=specs[j].nights + 1)
                out.append(
                    (
                        f"One night less in {stops[i].name}, one more in {stops[j].name}",
                        2,
                        itin.with_stops(new),
                    )
                )

        # skip an unpinned stop, giving its nights to a neighbour
        for i in movable:
            if specs[i].pinned or len(specs) < 2:
                continue
            for j in (i - 1, i + 1):
                if not 0 <= j < len(specs) or specs[j].nights == 0:
                    continue
                new = list(specs)
                new[j] = replace(specs[j], nights=specs[j].nights + specs[i].nights)
                del new[i]
                nights = specs[i].nights
                out.append(
                    (
                        f"Skip {stops[i].name} and spend {'the night' if nights == 1 else f'those {nights} nights'} "
                        f"in {stops[j].name}",
                        4 + nights,
                        itin.with_stops(new),
                    )
                )

        # swap an unpinned destination for a nearby alternative
        for i in movable:
            if specs[i].pinned or stops[i].kind != "place":
                continue
            for alt in self.alternatives(before, i, limit=2):
                new = list(specs)
                new[i] = replace(specs[i], name=alt.slug)
                out.append((f"Swap {stops[i].name} for {alt.name}", 3, itin.with_stops(new)))
        return out

    def alternatives(self, analysis: Analysis, index: int, *, limit: int = 5) -> list[Place]:
        """Places that could take this stop's slot: same area, open, reachable, not on the trip."""
        itin = analysis.itinerary
        stop = analysis.stops[index]
        if stop.place is None:
            return []
        used = {s.slug for s in analysis.stops}
        prev = analysis.stops[index - 1].place if index > 0 else self._endpoint(itin.arrival, stop)
        nxt = (
            analysis.stops[index + 1].place
            if index + 1 < len(analysis.stops)
            else self._endpoint(itin.departure, stop)
        )
        scored: list[tuple[int, str, Place]] = []
        for place in self.catalogue.places.values():
            if place.slug in used or place.area != stop.place.area:
                continue
            if place.season(itin.month) < 2:
                continue
            if place.car_need == "required" and itin.transport is Transport.NO_CAR:
                continue
            legs = [self._move(prev, place), self._move(place, nxt)]
            if any(leg is None for leg in legs):
                continue
            shared = len(set(place.themes) & set(stop.place.themes))
            scored.append((sum(leg[0] for leg in legs if leg) - 30 * shared, place.slug, place))
        scored.sort(key=lambda x: (x[0], x[1]))
        return [p for _, _, p in scored[:limit]]

    def _fixes_for(
        self,
        issue: Issue,
        before: Analysis,
        evaluated: list[tuple[str, int, Analysis]],
    ) -> list[FixOut]:
        before_blocking = before.blocking()
        pinned = {s.slug or s.name for s in before.stops if s.spec.pinned}
        ranked = []
        for label, cost, after in evaluated:
            kept = {s.slug or s.name for s in after.stops}
            if not pinned <= kept:
                continue  # never remove a pinned stop
            blocking = after.blocking()
            if issue.key in blocking:
                continue
            new = [i for k, i in blocking.items() if k not in before_blocking]
            if any(i.severity == "critical" for i in new):
                continue
            if _VERDICT_RANK[after.verdict] > _VERDICT_RANK[before.verdict]:
                continue
            ranked.append(
                (
                    (_VERDICT_RANK[after.verdict], len(new), cost, after.moving, label),
                    label,
                    after,
                )
            )
        ranked.sort(key=lambda r: r[0])
        out: list[FixOut] = []
        for n, (_, label, after) in enumerate(ranked[:2], start=1):
            out.append(
                FixOut(
                    id=f"{issue.id}#fix{n}",
                    label=label,
                    stops=self._stops_out(after.stops),
                    diff=self._diff(before, after),
                    verdict_after=after.verdict,  # type: ignore[arg-type]
                    verdict_after_label=VERDICT_LABELS[after.verdict],
                )
            )
        return out

    def _diff(self, before: Analysis, after: Analysis) -> DiffOut:
        gained: list[str] = []
        lost: list[str] = []
        delta = before.moving - after.moving
        if delta >= 10:
            gained.append(f"{hours(delta)} less moving")
        elif delta <= -10:
            lost.append(f"{hours(-delta)} more moving")
        b_nights = {s.slug or s.name: (s.name, s.spec.nights) for s in before.stops}
        a_nights = {s.slug or s.name: (s.name, s.spec.nights) for s in after.stops}
        for key, (name, n) in b_nights.items():
            if key not in a_nights:
                lost.append(f"Drops {name}")
            elif a_nights[key][1] > n:
                gained.append(f"{name}: {n} → {a_nights[key][1]} nights")
            elif a_nights[key][1] < n:
                lost.append(f"{name}: {n} → {a_nights[key][1]} nights")
        for key, (name, _) in a_nights.items():
            if key not in b_nights:
                gained.append(f"Adds {name}")
        b_changes = sum(1 for s in before.stops if s.spec.nights) - 1
        a_changes = sum(1 for s in after.stops if s.spec.nights) - 1
        if a_changes < b_changes:
            gained.append(
                f"{b_changes - a_changes} hotel change{'s' * (b_changes - a_changes > 1)} fewer"
            )
        for b_spec, a_spec in zip(before.itinerary.stops, after.itinerary.stops, strict=False):
            if (
                a_spec.leave_at is not None
                and a_spec.leave_at != b_spec.leave_at
                and a_spec.name == b_spec.name
            ):
                lost.append(
                    f"Earlier start: leave {self.resolve_stop(a_spec).name} at {clock(a_spec.leave_at)}"
                )
        b_block, a_block = before.blocking(), after.blocking()
        gained += [f"Fixes: {i.title}" for k, i in b_block.items() if k not in a_block]
        lost += [f"New: {i.title}" for k, i in a_block.items() if k not in b_block]
        return DiffOut(gained=gained, lost=lost)
