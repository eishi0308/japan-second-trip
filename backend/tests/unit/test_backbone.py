"""The intercity backbone search is deterministic and honest about changes."""

from __future__ import annotations

from jst_api.domain.backbone import CHANGE_MINUTES, Backbone, DestinationAccess, Leg


def _both(a: str, b: str, mode: str, minutes: int, transfers: int = 0) -> list[Leg]:
    return [Leg(a, b, mode, minutes, transfers), Leg(b, a, mode, minutes, transfers)]


def _net() -> Backbone:
    return Backbone(
        [
            *_both("tokyo", "sendai", "shinkansen", 95),
            *_both("sendai", "morioka", "shinkansen", 40),
            *_both("tokyo", "morioka", "shinkansen", 135),
            *_both("morioka", "akita", "shinkansen", 95),
            *_both("tokyo", "fukuoka", "flight", 240),
            *_both("tokyo", "osaka", "shinkansen", 150),
            *_both("osaka", "fukuoka", "shinkansen", 150),
        ]
    )


def test_direct_through_service_beats_changing_trains() -> None:
    journey = _net().journey("tokyo", "morioka")
    assert journey is not None
    assert journey.minutes == 135
    assert journey.transfers == 0


def test_each_change_adds_a_transfer_and_change_time() -> None:
    journey = _net().journey("sendai", "akita")
    assert journey is not None
    assert [leg.to_hub for leg in journey.legs] == ["morioka", "akita"]
    assert journey.minutes == 40 + 95 + CHANGE_MINUTES
    assert journey.transfers == 1


def test_mode_filter_can_leave_out_flights() -> None:
    net = _net()
    fastest = net.journey("tokyo", "fukuoka")
    rail_only = net.journey("tokyo", "fukuoka", modes={"shinkansen"})
    assert fastest is not None and fastest.modes == ("flight",)
    assert rail_only is not None and rail_only.modes == ("shinkansen", "shinkansen")
    assert rail_only.minutes == 150 + 150 + CHANGE_MINUTES


def test_same_hub_is_a_zero_length_journey() -> None:
    journey = _net().journey("tokyo", "tokyo")
    assert journey is not None
    assert journey.minutes == 0 and journey.transfers == 0


def test_unknown_or_unreachable_hub_returns_none() -> None:
    net = Backbone([*_both("a", "b", "shinkansen", 10), Leg("c", "d", "ferry", 30)])
    assert net.journey("a", "nowhere") is None
    assert net.journey("a", "c") is None


def test_access_adds_the_last_stretch_and_one_change() -> None:
    nyuto = DestinationAccess("nyuto-onsen", "akita", 110, 1, "local_bus")
    access = _net().access("tokyo", nyuto)
    assert access is not None
    # tokyo -> morioka (135) -> akita (95) + change, then the bus stretch + a change
    assert access.minutes == 135 + 95 + CHANGE_MINUTES + 110 + CHANGE_MINUTES
    assert access.transfers == 1 + 1 + 1


def test_access_from_the_destinations_own_hub_has_no_backbone_legs() -> None:
    walkable = DestinationAccess("sendai", "sendai", 5, 0, "walk")
    access = _net().access("sendai", walkable)
    assert access is not None
    assert access.minutes == 5 and access.transfers == 0
