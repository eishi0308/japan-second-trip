"""M5: "Being checked" → a reviewer resolves it → the saved trip is updated.

The whole loop through the real API on the seeded Ginzan Onsen conflict (three
reported last-bus times). The test restores the record afterwards, because the
session database is shared with the other tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from jst_api.db.models import FragileLink

pytestmark = pytest.mark.asyncio(loop_scope="session")

GINZAN_TRIP = {
    "title": "Ginzan in the snow",
    "check": {
        "stops": [
            {"name": "Tokyo", "nights": 1},
            {"name": "Ginzan Onsen", "nights": 2, "pinned": True},
            {"name": "Tokyo", "nights": 0},
        ],
        "month": 1,
        "arrival_city": "Tokyo",
        "departure_city": "Tokyo",
    },
}


@pytest.fixture
async def ginzan_restored(session):
    link = await session.scalar(
        select(FragileLink).where(
            FragileLink.destination_slug == "ginzan-onsen", FragileLink.kind == "last_connection"
        )
    )
    saved = {
        k: getattr(link, k)
        for k in (
            "status",
            "conflicting_values",
            "last_departure_local",
            "verified_at",
            "source_id",
        )
    }
    yield link.id
    await session.refresh(link)
    for k, v in saved.items():
        setattr(link, k, v)
    await session.commit()


def _ginzan_issue(trip: dict) -> dict | None:
    return next(
        (
            i
            for i in trip["result"]["check"]["issues"]
            if i["stop"] == "ginzan-onsen" and i["kind"] == "last_connection"
        ),
        None,
    )


async def test_the_full_review_loop(client, admin_headers, ginzan_restored) -> None:
    fact_id = ginzan_restored

    # 1. The traveller saves a trip; the disputed last bus shows as being checked.
    saved = (await client.post("/api/v1/saved-trips", json=GINZAN_TRIP)).json()
    trip, token = saved["trip"], saved["token"]
    owner = {"Authorization": f"Bearer {token}"}
    issue = _ginzan_issue(trip)
    assert issue and issue["needs_review"] and issue["fact_id"] == fact_id
    assert issue["evidence"][0]["fact_state"] == "being_checked"

    # 2. A review task is open for that fact, and the queue knows the trip depends on it.
    queue = (await client.get("/api/v1/admin/facts/queue", headers=admin_headers)).json()
    item = next(i for i in queue["items"] if i["fact_id"] == fact_id)
    assert item["state"] == "being_checked"
    assert item["task_id"] is not None
    assert item["trips_affected"] >= 1
    assert set(item["candidate_values"]) >= {"17:00", "16:30"}
    assert item["current_value"] is None  # a disputed value is never shown as current

    # 3. Saving again does not open a second task for the same fact.
    await client.post("/api/v1/saved-trips", json=GINZAN_TRIP)
    again = (await client.get("/api/v1/admin/facts/queue", headers=admin_headers)).json()
    assert next(i for i in again["items"] if i["fact_id"] == fact_id)["task_id"] == item["task_id"]

    # 4. The reviewer resolves it with a source.
    resolved = await client.post(
        f"/api/v1/admin/facts/{fact_id}/resolve",
        json={
            "value": "17:00",
            "source_url": "https://example.org/ginzan-bus-timetable",
            "note": "Checked the winter timetable.",
            "reviewer": "ops@jst",
        },
        headers=admin_headers,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["tasks_closed"] == 1
    assert trip["id"] in {t["trip_id"] for t in body["trips_updated"]}

    # 5. The saved trip shows what changed, and the fact is now a dated, checked fact.
    after = (await client.get(f"/api/v1/saved-trips/{trip['id']}", headers=owner)).json()
    notice = after["notices"][-1]
    assert "confirmed as 17:00" in notice["text"]
    assert "We re-checked your trip" in notice["text"]
    assert notice["seen"] is False
    issue = _ginzan_issue(after)
    assert issue is None or not issue["needs_review"]
    evidence = [
        e
        for i in after["result"]["check"]["issues"]
        if i["fact_id"] == fact_id
        for e in i["evidence"]
    ]
    assert all(e["fact_state"] == "verified" and e["verified_at"] for e in evidence)

    # 6. The fact has left the queue.
    final = (await client.get("/api/v1/admin/facts/queue", headers=admin_headers)).json()
    assert fact_id not in {i["fact_id"] for i in final["items"]}

    # 7. The share link shows the update too; the owner can mark it seen.
    shared = (await client.get(f"/api/v1/shared/{trip['share_id']}")).json()
    assert shared["notices"][-1]["text"] == notice["text"]
    seen = (
        await client.post(f"/api/v1/saved-trips/{trip['id']}/notices/seen", headers=owner)
    ).json()
    assert all(n["seen"] for n in seen["notices"])


async def test_a_disputed_time_needs_a_real_time(client, admin_headers, ginzan_restored) -> None:
    response = await client.post(
        f"/api/v1/admin/facts/{ginzan_restored}/resolve",
        json={"value": "about five"},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "HH:MM" in response.text


async def test_only_admins_see_or_resolve_the_queue(client, ginzan_restored) -> None:
    assert (await client.get("/api/v1/admin/facts/queue")).status_code in (401, 403)
    response = await client.post(
        f"/api/v1/admin/facts/{ginzan_restored}/resolve", json={"value": "17:00"}
    )
    assert response.status_code in (401, 403)
