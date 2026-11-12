"""The Where Next planner on a small hand-built catalogue.

Pure: no database. A dozen places across three areas is enough to check every
product rule in PRODUCT_AMENDMENTS.md §3 and §4b, with numbers small enough to
work out by hand.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from jst_api.domain.backbone import Backbone, Leg
from jst_api.domain.enums import Pace
from jst_api.domain.fact_state import FactState
from jst_api.planner.engine import Planner, pick_characters, split_nights
from jst_api.planner.model import (
    Avoid,
    Catalogue,
    Conditions,
    FragileNote,
    HubInfo,
    Place,
    Reaction,
    ReactionKind,
    Transport,
)
from jst_api.planner.preferences import interests_from, keyword_past_trip
from jst_api.planner.scoring import travel_budget

NOW = datetime(2026, 11, 13, tzinfo=UTC)
ALL_GOOD = (2,) * 12
WINTER_CLOSED = (0, 0, 0, 1, 3, 3, 3, 3, 3, 3, 1, 0)


def _both(a: str, b: str, mode: str, minutes: int) -> list[Leg]:
    return [Leg(a, b, mode, minutes), Leg(b, a, mode, minutes)]


def _place(
    slug: str, area: str, hub: str, minutes: int, themes: tuple[str, ...], tier: str, **kw
) -> Place:
    return Place(
        slug=slug,
        name=kw.pop("name", slug.replace("-", " ").title()),
        area=area,
        prefecture="Test",
        hub_slug=hub,
        hub_minutes=minutes,
        hub_transfers=kw.pop("transfers", 0),
        access_mode=kw.pop("access_mode", "local_bus"),
        car_need=kw.pop("car_need", "none"),
        season_fit=kw.pop("season_fit", ALL_GOOD),
        themes=themes,
        tier=tier,
        typical_nights=kw.pop("typical_nights", 2),
        summary=f"{slug} summary.",
        verified_at=NOW - timedelta(days=30),
        fragile=kw.pop("fragile", ()),
    )


LAST_BUS = FragileNote(
    kind="last_connection",
    severity="critical",
    title="Last bus 16:50",
    detail="",
    state=FactState.VERIFIED,
    verified_at=NOW - timedelta(days=20),
    source_id="src_demo_1",
)


def catalogue() -> Catalogue:
    hubs = {
        "tokyo": HubInfo("tokyo", "Tokyo", "kanto", True),
        "sendai": HubInfo("sendai", "Sendai", "tohoku", True),
        "morioka": HubInfo("morioka", "Morioka", "tohoku", False),
        "nagano": HubInfo("nagano", "Nagano", "chubu", False),
        "fukuoka": HubInfo("fukuoka", "Fukuoka", "kyushu", True),
    }
    backbone = Backbone(
        [
            *_both("tokyo", "sendai", "shinkansen", 95),
            *_both("sendai", "morioka", "shinkansen", 40),
            *_both("tokyo", "morioka", "shinkansen", 135),
            *_both("tokyo", "nagano", "shinkansen", 80),
            *_both("tokyo", "fukuoka", "flight", 240),
        ]
    )
    places = [
        _place("nyuto", "tohoku", "morioka", 90, ("onsen", "snow"), "hidden", fragile=(LAST_BUS,)),
        _place("kakunodate", "tohoku", "morioka", 50, ("culture", "snow"), "middle"),
        _place("matsushima", "tohoku", "sendai", 40, ("coast", "food"), "classic", typical_nights=1),
        _place("shibu", "chubu", "nagano", 45, ("onsen", "snow"), "classic"),
        _place("obuse", "chubu", "nagano", 30, ("food", "culture"), "hidden", typical_nights=1),
        _place("nozawa", "chubu", "nagano", 75, ("snow", "onsen", "food"), "middle"),
        _place("alpine", "chubu", "nagano", 100, ("hiking", "nature"), "hidden", season_fit=WINTER_CLOSED),
        _place("beppu", "kyushu", "fukuoka", 120, ("onsen", "food"), "classic"),
        _place("farm", "tohoku", "sendai", 60, ("nature", "food"), "hidden", car_need="required", access_mode="car"),
    ]  # fmt: skip
    return Catalogue({p.slug: p for p in places}, hubs, backbone)


HERO = Conditions(
    month=1,
    regional_nights=4,
    arrival_hub="tokyo",
    departure_hub="tokyo",
    interests=("onsen", "snow", "food"),
)


def planner() -> Planner:
    return Planner(catalogue(), now=NOW)


def test_three_options_with_different_characters_and_no_shared_stop() -> None:
    result = planner().plan(HERO).result
    assert result is not None
    assert [o.character for o in result.options] == ["classic", "unexpected", "slow_paced"]
    stop_sets = [{s.slug for s in o.stops} for o in result.options]
    for i, a in enumerate(stop_sets):
        for b in stop_sets[i + 1 :]:
            assert not a & b


def test_options_are_combinations_with_nights_that_add_up() -> None:
    result = planner().plan(HERO).result
    assert result is not None
    for option in result.options:
        assert sum(s.nights for s in option.stops) == 4
        assert option.nights_label == " + ".join(f"{s.nights}N" for s in option.stops)
        assert option.title == " + ".join(s.name for s in option.stops)


def test_the_same_conditions_give_the_same_plan() -> None:
    a = planner().plan(HERO).model_dump(mode="json")
    b = planner().plan(HERO).model_dump(mode="json")
    assert a == b


def test_fit_is_five_levels_with_words_and_no_percentages() -> None:
    plan = planner().plan(HERO)
    assert plan.result is not None
    for option in plan.result.options:
        assert 1 <= option.fit.level <= 5
        assert option.fit.breakdown[0].text.startswith("Interests ")
        assert "/3 matched" in option.fit.breakdown[0].text
    assert "%" not in json.dumps(plan.model_dump(mode="json"))


def test_every_option_shows_whats_hard_and_a_dated_verification() -> None:
    result = planner().plan(HERO).result
    assert result is not None
    for option in result.options:
        assert 2 <= len(option.whats_hard) <= 3
        assert option.verification.oldest_verified_at is not None
        assert "DEMO" in option.verification.label


def test_fragile_link_appears_in_whats_hard_with_its_source_and_date() -> None:
    result = planner().plan(HERO.with_(must_include=("nyuto",))).result
    assert result is not None
    item = next(h for h in result.options[0].whats_hard if h.kind == "last_connection")
    assert item.source_id == "src_demo_1" and item.verified_at is not None


def test_far_area_is_rejected_with_a_recomputed_if_you_change() -> None:
    result = planner().plan(HERO).result
    assert result is not None
    kyushu = next(r for r in result.not_for_this_trip if r.area == "kyushu")
    assert "Too much travel" in kyushu.reason
    assert kyushu.if_you_change is not None
    assert kyushu.if_you_change.startswith("If you can fly out of Fukuoka, Kyushu becomes")


def test_flying_out_of_fukuoka_really_does_bring_kyushu_back() -> None:
    open_jaw = HERO.with_(departure_hub="fukuoka", must_include=("beppu",))
    result = planner().plan(open_jaw).result
    assert result is not None and result.options
    assert all("beppu" in {s.slug for s in o.stops} for o in result.options)


def test_car_only_place_drops_out_without_a_car_and_returns_with_one() -> None:
    p = planner()
    funnel = p.funnel(p.resolve(HERO, 1, 4), _prefs(HERO))
    assert funnel.dropped["farm"][0] == "car"
    driving = HERO.with_(transport=Transport.CAN_DRIVE)
    assert "farm" in {x.slug for x in p.funnel(p.resolve(driving, 1, 4), _prefs(driving)).survivors}


def test_funnel_counts_never_go_up() -> None:
    result = planner().plan(HERO).result
    assert result is not None
    counts = [step.count for step in result.funnel]
    assert counts[0] == len(catalogue().places)
    assert counts == sorted(counts, reverse=True)
    assert result.funnel[1].label == "open in January"


def test_pinned_stop_is_in_every_option_even_when_out_of_season() -> None:
    result = planner().plan(HERO.with_(must_include=("alpine",))).result
    assert result is not None and result.options
    for option in result.options:
        assert "alpine" in {s.slug for s in option.stops if s.pinned}
    assert result.options[0].whats_hard[0].kind == "pinned_out_of_season"


def test_unknown_must_include_says_no_verified_info() -> None:
    plan = planner().plan(HERO.with_(must_include=("Atlantis",)))
    assert any(
        n.code == "not_in_database" and "No verified info yet" in n.text for n in plan.notices
    )


def test_undecided_cities_are_assumed_tokyo_and_labelled() -> None:
    plan = planner().plan(HERO.with_(arrival_hub=None, departure_hub=None))
    assert [a.label for a in plan.assumptions] == ["Assumed: Tokyo in/out"]
    assert plan.result is not None and plan.result.options


def test_undecided_month_offers_a_season_choice() -> None:
    plan = planner().plan(HERO.with_(month=None, regional_nights=None))
    assert plan.kind == "season_choice"
    assert [s.month for s in plan.seasons] == [1, 4, 7, 10]
    assert "Assumed: 4 nights" in [a.label for a in plan.assumptions]
    assert all(len(s.result.options) <= 3 for s in plan.seasons)


def test_undecided_nights_offers_three_versus_five() -> None:
    plan = planner().plan(HERO.with_(regional_nights=None))
    assert plan.kind == "nights_choice"
    assert [n.nights for n in plan.nights_options] == [3, 5]


def test_snow_does_not_count_in_july() -> None:
    result = planner().plan(HERO.with_(month=7, interests=("snow",))).result
    assert result is not None
    for option in result.options:
        assert option.fit.breakdown[0].text.startswith("Interests 0/1")


def test_not_for_me_removes_those_stops() -> None:
    first = planner().plan(HERO).result
    assert first is not None
    stops = tuple(s.slug for s in first.options[0].stops)
    again = planner().plan(HERO.with_(reactions=(Reaction(ReactionKind.NOT_FOR_ME, stops),)))
    assert again.result is not None
    shown = {s.slug for o in again.result.options for s in o.stops}
    assert not shown & set(stops)


def test_quieter_moves_away_from_classic_places() -> None:
    first = planner().plan(HERO).result
    assert first is not None
    quieter = (
        planner().plan(HERO.with_(reactions=(Reaction(ReactionKind.QUIETER, ("shibu",)),))).result
    )
    assert quieter is not None

    def classic_stops(r) -> int:
        return sum(s.tier == "classic" for o in r.options for s in o.stops)

    assert classic_stops(quieter) <= classic_stops(first)


def test_zero_results_suggest_the_smallest_changes() -> None:
    stuck = HERO.with_(regional_nights=2, must_include=("beppu",))
    result = planner().plan(stuck).result
    assert result is not None
    assert result.options == []
    labels = [s.label for s in result.zero_results_suggestions]
    assert "Without Beppu pinned" in labels
    assert all(s.options_found > 0 for s in result.zero_results_suggestions)


def test_relaxed_pace_lowers_the_travel_budget() -> None:
    assert (
        travel_budget(4, Pace.RELAXED)
        < travel_budget(4, Pace.BALANCED)
        < travel_budget(4, Pace.FAST)
    )


def test_split_nights_follows_typical_stay() -> None:
    cat = catalogue()
    assert split_nights([cat.places["nyuto"], cat.places["matsushima"]], 4) == (3, 1)
    assert split_nights([cat.places["nyuto"], cat.places["kakunodate"]], 4) == (2, 2)


def test_pick_characters_handles_no_combinations() -> None:
    assert pick_characters([], set()) == []


def test_past_trip_keywords_for_the_vague_hero() -> None:
    prefs = keyword_past_trip("Loved Nishiki Market food walks, tired of crowds", None)
    assert [i.value for i in prefs.liked] == ["food"]
    assert prefs.avoid == [Avoid.CROWDS]


def test_interests_prefer_explicit_chips_then_own_words_then_cards() -> None:
    assert interests_from(["art"], ["snowy-onsen-town"], ["food"]) == ("art",)
    assert interests_from([], ["snowy-onsen-town", "fishing-village"], ["food"]) == (
        "food",
        "onsen",
        "snow",
    )


def _prefs(c: Conditions):
    from jst_api.planner.preferences import preferences_from

    return preferences_from(c, catalogue().places)
