"""Human-in-the-loop: escalation, resolution, resumption.

The full cycle, because each half is useless alone — escalating without a
resume path just strands the traveller, and resolving without escalation means
nothing was ever caught.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _reopen_seeded_conflict(session_factory) -> str:
    """Restore the fixture. Earlier tests may have resolved it."""
    from sqlalchemy import select

    from jst_api.db.models import HumanReviewTask, VerificationRecord

    async with session_factory() as session:
        task = await session.scalar(
            select(HumanReviewTask).where(HumanReviewTask.reason == "conflicting_sources")
        )
        assert task is not None, "the seed must provide a conflicting fact"
        task.status = "open"
        task.resolved_value = None
        task.resolved_at = None
        task.resolved_by = None
        task.resumed = False
        task.analysis_id = None
        for record in (
            await session.scalars(
                select(VerificationRecord).where(
                    VerificationRecord.verification_method == "human_review"
                )
            )
        ).all():
            await session.delete(record)
        await session.commit()
        return task.id


class TestEscalation:
    async def test_a_route_through_a_disputed_fact_escalates(self, client, session_factory):
        await _reopen_seeded_conflict(session_factory)
        body = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "stops": [
                        {"name": "Sendai", "nights": 2},
                        {"name": "Ginzan Onsen", "nights": 2},
                        {"name": "Sendai", "nights": 0},
                    ],
                    "trip": {
                        "arrival_city": "Tokyo",
                        "departure_city": "Tokyo",
                        "driving": "no_car",
                    },
                },
            )
        ).json()
        result = body["result"]
        assert result["human_review_required"] is True
        assert result["human_review_task_id"]
        assert result["conflicts"], "the disputed values must be shown, not hidden"
        assert len(result["conflicts"][0]["values"]) >= 2

    async def test_the_system_never_picks_between_conflicting_values(self, client, session_factory):
        await _reopen_seeded_conflict(session_factory)
        body = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "stops": [
                        {"name": "Sendai", "nights": 2},
                        {"name": "Ginzan Onsen", "nights": 2},
                    ],
                    "trip": {"driving": "no_car"},
                },
            )
        ).json()
        conflict = body["result"]["conflicts"][0]
        assert set(conflict["values"]) == {"17:00", "16:30"}, (
            "both candidates must survive to the user"
        )

    async def test_an_unrelated_analysis_is_not_blocked_by_the_conflict(
        self, client, session_factory
    ):
        """A dispute about one onsen's bus must not hold up a region comparison
        that never asserts a bus time."""
        await _reopen_seeded_conflict(session_factory)
        body = (
            await client.post(
                "/api/v1/where-next",
                json={
                    "trip": {
                        "regional_nights": 5,
                        "arrival_city": "Osaka",
                        "interests": ["art", "coast"],
                    }
                },
            )
        ).json()
        assert body["result"]["human_review_required"] is False


class TestResolution:
    async def test_resolving_writes_a_verification_record_and_resumes(
        self, client, admin_headers, session_factory
    ):
        task_id = await _reopen_seeded_conflict(session_factory)

        created = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "stops": [
                        {"name": "Sendai", "nights": 2},
                        {"name": "Ginzan Onsen", "nights": 2},
                    ],
                    "trip": {"driving": "no_car", "arrival_city": "Tokyo"},
                },
            )
        ).json()
        assert created["result"]["human_review_required"] is True
        analysis_id = created["analysis_id"]

        queue = (await client.get("/api/v1/admin/reviews", headers=admin_headers)).json()
        assert any(r["id"] == task_id for r in queue["reviews"])

        resolved = (
            await client.post(
                f"/api/v1/admin/reviews/{task_id}/resolve",
                headers=admin_headers,
                json={
                    "resolved_value": "17:00",
                    "resolution_note": "Confirmed by phone with the operator.",
                    "reviewer": "tester",
                },
            )
        ).json()
        assert resolved["status"] == "resolved"
        assert resolved["verification_id"], "the verified value must be recorded with a date"
        assert resolved["resumed"] is True, "the blocked analysis must be re-run"
        assert resolved["resumed_analysis_id"]

        original = (await client.get(f"/api/v1/route-check/{analysis_id}")).json()["result"]
        assert original["status"] == "complete"
        assert original["human_review_required"] is False
        assert original["resolved_facts"], "the traveller must see what was confirmed and by whom"
        assert original["resolved_facts"][0]["value"] == "17:00"
        assert original["resolved_facts"][0]["verified_by"] == "tester"
        assert original["superseded_by"]

        rerun = (await client.get(f"/api/v1/route-check/{resolved['resumed_analysis_id']}")).json()[
            "result"
        ]
        assert rerun["human_review_required"] is False
        assert not rerun["conflicts"], "the conflict is settled, so it must not re-escalate"

    async def test_resolution_supersedes_the_previous_record(
        self, client, admin_headers, session_factory
    ):
        from sqlalchemy import select

        from jst_api.db.models import VerificationRecord

        task_id = await _reopen_seeded_conflict(session_factory)
        await client.post(
            f"/api/v1/admin/reviews/{task_id}/resolve",
            headers=admin_headers,
            json={"resolved_value": "16:30", "reviewer": "tester"},
        )
        async with session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(VerificationRecord).where(
                            VerificationRecord.subject == "ginzan-onsen:oishida_last_bus"
                        )
                    )
                ).all()
            )
        verified = [r for r in records if r.status == "verified"]
        assert len(verified) == 1, "exactly one value may be current"
        assert verified[0].value == "16:30"
        assert verified[0].verification_method == "human_review"
        assert any(r.status == "superseded" for r in records), (
            "history must be kept, not overwritten"
        )

    async def test_a_task_cannot_be_resolved_twice(self, client, admin_headers, session_factory):
        task_id = await _reopen_seeded_conflict(session_factory)
        first = await client.post(
            f"/api/v1/admin/reviews/{task_id}/resolve",
            headers=admin_headers,
            json={"resolved_value": "17:00", "reviewer": "a"},
        )
        assert first.status_code == 200
        second = await client.post(
            f"/api/v1/admin/reviews/{task_id}/resolve",
            headers=admin_headers,
            json={"resolved_value": "16:30", "reviewer": "b"},
        )
        assert second.status_code == 409

    async def test_resolving_requires_admin(self, client, session_factory):
        task_id = await _reopen_seeded_conflict(session_factory)
        response = await client.post(
            f"/api/v1/admin/reviews/{task_id}/resolve", json={"resolved_value": "17:00"}
        )
        assert response.status_code == 401


class TestAdminAssistant:
    async def test_it_triages_through_the_same_mcp_gateway(
        self, client, admin_headers, session_factory
    ):
        await _reopen_seeded_conflict(session_factory)
        body = (
            await client.post(
                "/api/v1/admin/assistant",
                headers=admin_headers,
                json={"request": "Show me evidence that is stale or conflicting"},
            )
        ).json()
        assert body["summary"]
        assert body["findings"], "the seeded conflict and stale fact must be found"
        assert body["trace"]["tool_calls"] > 0, "it must actually use the gateway"

    async def test_it_cannot_write_trip_state(self, client, admin_headers):
        body = (
            await client.post(
                "/api/v1/admin/assistant", headers=admin_headers, json={"request": "anything"}
            )
        ).json()
        assert body["can_write_trip_state"] is False
        assert "save_trip_decision" not in body["tools_available"]

    async def test_it_presents_conflicts_without_choosing(
        self, client, admin_headers, session_factory
    ):
        await _reopen_seeded_conflict(session_factory)
        body = (
            await client.post(
                "/api/v1/admin/assistant",
                headers=admin_headers,
                json={"request": "conflicting evidence", "region_code": "tohoku"},
            )
        ).json()
        conflicts = [f for f in body["findings"] if f["severity"] == "critical"]
        assert conflicts
        assert len(conflicts[0]["values"]) >= 2, "both values must be presented neutrally"
