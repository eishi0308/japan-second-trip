"""M3: RouteCheck and option checks on the real seeded catalogue, through the API.

Includes the RouteCheck hero demo from PRODUCT_AMENDMENTS.md §10: "Tokyo 3N,
Sendai 1N, Ginzan Onsen 1N, Aomori 1N, Hakodate 1N, Tokyo" with Ginzan
pinned must not remove Ginzan.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HERO_TEXT = "Tokyo 3N, Sendai 1N, Ginzan Onsen 1N, Aomori 1N, Hakodate 1N, Tokyo"
HERO_STOPS = [
    {"name": "Tokyo", "nights": 3},
    {"name": "Sendai", "nights": 1},
    {"name": "Ginzan Onsen", "nights": 1, "pinned": True},
    {"name": "Aomori", "nights": 1},
    {"name": "Hakodate", "nights": 1},
    {"name": "Tokyo", "nights": 0},
]
HERO_CHECK = {
    "stops": HERO_STOPS,
    "month": 1,
    "arrival_city": "Tokyo",
    "departure_city": "Tokyo",
}


async def _check(client, body: dict) -> dict:
    response = await client.post("/api/v1/checks", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def test_parse_turns_text_into_a_table_to_confirm(client) -> None:
    response = await client.post("/api/v1/checks/parse", json={"text": HERO_TEXT})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert [r["name"] for r in rows][:5] == [
        "Tokyo",
        "Sendai",
        "Ginzan Onsen",
        "Aomori",
        "Hakodate",
    ]
    assert [r["nights"] for r in rows][:5] == [3, 1, 1, 1, 1]
    assert {r["status"] for r in rows} <= {"known", "city"}


async def test_parse_highlights_what_it_cannot_match(client) -> None:
    body = (
        await client.post("/api/v1/checks/parse", json={"text": "Tokyo 2N, Atlantis 2N, Tokyo"})
    ).json()
    atlantis = next(r for r in body["rows"] if r["name"] == "Atlantis")
    assert atlantis["status"] == "unknown"
    assert any("Atlantis" in line for line in body["to_confirm"])


async def test_hero_route_check_is_day_by_day(client) -> None:
    check = (await _check(client, HERO_CHECK))["check"]
    assert len(check["days"]) == 7 + 1
    assert check["verdict_label"] in ("Needs attention", "Will not work")
    for day in check["days"]:
        assert day["moving_label"] and day["staying_label"]
    assert any(a["label"].startswith("Assumed: leave the hotel") for a in check["assumptions"])


async def test_hero_route_check_never_removes_pinned_ginzan(client) -> None:
    check = (await _check(client, HERO_CHECK))["check"]
    fixes = [f for i in check["issues"] for f in i["fixes"]]
    assert fixes
    for fix in fixes:
        pinned = [s for s in fix["stops"] if s["pinned"]]
        assert [s["slug"] for s in pinned] == ["ginzan-onsen"], fix["label"]


async def test_hero_ginzan_last_bus_is_being_checked(client) -> None:
    check = (await _check(client, HERO_CHECK))["check"]
    ginzan = next(
        i for i in check["issues"] if i["stop"] == "ginzan-onsen" and i["kind"] == "last_connection"
    )
    assert ginzan["needs_review"] is True
    assert "being checked" in ginzan["title"]
    assert ginzan["evidence"][0]["fact_state"] == "being_checked"
    text = json.dumps(check)
    for value in ("16:30", "18:10"):
        assert value not in text


async def test_every_issue_has_problem_why_and_dated_evidence(client) -> None:
    check = (await _check(client, HERO_CHECK))["check"]
    for issue in check["issues"]:
        assert issue["title"] and issue["why"]
        if issue["severity"] != "info":
            assert issue["evidence"], issue["title"]
            assert issue["fixes"], issue["title"]
            assert len(issue["fixes"]) <= 2


async def test_booking_list_is_backed_by_evidence(client) -> None:
    check = (await _check(client, {**HERO_CHECK, "start_date": "2027-01-10"}))["check"]
    assert check["booking"]
    for item in check["booking"]:
        assert item["evidence"]["source_id"]


async def test_applying_a_fix_re_runs_the_check(client) -> None:
    first = (await _check(client, HERO_CHECK))["check"]
    fix = next(f for i in first["issues"] for f in i["fixes"])
    stops = [
        {"name": s["slug"] or s["name"], "nights": s["nights"], "pinned": s["pinned"]}
        for s in fix["stops"]
    ]
    again = (await _check(client, {**HERO_CHECK, "stops": stops}))["check"]
    assert again["verdict"] == fix["verdict_after"]


async def test_after_route_check_you_could_also_consider(client) -> None:
    body = await _check(client, HERO_CHECK)
    assert 1 <= len(body["also_consider"]) <= 3
    assert all(o["title"] for o in body["also_consider"])


async def test_swap_alternatives_come_from_the_database(client) -> None:
    response = await client.post("/api/v1/checks/alternatives", json={**HERO_CHECK, "index": 3})
    assert response.status_code == 200, response.text
    alts = response.json()
    assert alts and all(a["is_demo"] for a in alts)
    assert "aomori" not in {a["slug"] for a in alts}
    pinned = await client.post("/api/v1/checks/alternatives", json={**HERO_CHECK, "index": 2})
    assert pinned.json() == []


async def test_a_month_is_required(client) -> None:
    response = await client.post("/api/v1/checks", json={"stops": HERO_STOPS})
    assert response.status_code == 422


async def test_where_next_options_carry_their_check(client) -> None:
    response = await client.post(
        "/api/v1/plans",
        json={
            "month": 1,
            "regional_nights": 4,
            "arrival_city": "Tokyo",
            "departure_city": "Tokyo",
            "interests": ["onsen", "snow", "food"],
        },
    )
    options = response.json()["plan"]["result"]["options"]
    for option in options:
        assert len(option["check"]["days"]) == 5
    dated = [
        e
        for o in options
        for i in o["check"]["issues"]
        for e in i["evidence"]
        if e["verified_at"] and e["source_id"]
    ]
    assert dated, "at least one fragile-link check backed by dated evidence"
