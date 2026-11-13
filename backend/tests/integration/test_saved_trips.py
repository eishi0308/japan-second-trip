"""M4 backend: saved plans re-open, saved trips are owner-edited and share read-only."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HERO_PLAN = {
    "month": 1,
    "regional_nights": 4,
    "arrival_city": "Tokyo",
    "departure_city": "Tokyo",
    "interests": ["onsen", "snow", "food"],
}
CHECK = {
    "stops": [
        {"name": "Tokyo", "nights": 2},
        {"name": "nyuto-onsen", "nights": 2, "pinned": True},
        {"name": "Tokyo", "nights": 0},
    ],
    "month": 1,
    "arrival_city": "Tokyo",
    "departure_city": "Tokyo",
}


async def test_a_saved_plan_reopens_with_the_same_options(client) -> None:
    created = (await client.post("/api/v1/plans", json=HERO_PLAN)).json()
    assert created["plan_id"]
    reopened = (await client.get(f"/api/v1/plans/{created['plan_id']}")).json()
    assert reopened["plan"] == created["plan"]
    assert reopened["request"]["month"] == 1


async def test_what_if_plans_are_not_saved(client) -> None:
    body = (await client.post("/api/v1/plans", json={**HERO_PLAN, "save": False})).json()
    assert body["plan_id"] is None


async def test_unknown_plan_is_404(client) -> None:
    assert (await client.get("/api/v1/plans/plan_nope")).status_code == 404


async def test_save_edit_and_share_a_trip(client) -> None:
    saved = await client.post(
        "/api/v1/saved-trips",
        json={"title": "Snow and onsen", "email": "traveller@example.com", "check": CHECK},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    trip, token = body["trip"], body["token"]
    assert trip["has_email"] is True
    assert trip["result"]["check"]["days"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get(f"/api/v1/saved-trips/{trip['id']}")).status_code == 403
    mine = await client.get(f"/api/v1/saved-trips/{trip['id']}", headers=headers)
    assert mine.status_code == 200

    longer = {**CHECK, "stops": [{**s} for s in CHECK["stops"]]}
    longer["stops"][1]["nights"] = 3
    updated = await client.put(
        f"/api/v1/saved-trips/{trip['id']}", json={"check": longer}, headers=headers
    )
    assert updated.status_code == 200
    assert (
        len(updated.json()["result"]["check"]["days"]) == len(trip["result"]["check"]["days"]) + 1
    )

    shared = (await client.get(f"/api/v1/shared/{trip['share_id']}")).json()
    assert shared["read_only"] is True
    assert shared["id"] is None and shared["has_email"] is None
    assert "traveller@example.com" not in str(shared)


async def test_editing_without_the_owner_token_is_refused(client) -> None:
    trip = (await client.post("/api/v1/saved-trips", json={"check": CHECK})).json()["trip"]
    response = await client.put(f"/api/v1/saved-trips/{trip['id']}", json={"title": "Mine now"})
    assert response.status_code == 403


async def test_full_report_click_is_recorded(client) -> None:
    response = await client.post("/api/v1/demand", json={"kind": "full_report", "option": 1})
    assert response.status_code == 201
    assert response.json()["status"] == "recorded"


async def test_option_stops_carry_coordinates_for_the_map(client) -> None:
    options = (await client.post("/api/v1/plans", json=HERO_PLAN)).json()["plan"]["result"][
        "options"
    ]
    for stop in options[0]["stops"]:
        assert stop["lat"] and stop["lon"]
