"""FastAPI integration tests against the real app, database and agent graphs.

Nothing internal is mocked: these exercise the same code path a browser hits.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestHealth:
    async def test_health_does_not_touch_the_database(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_ready_reports_seed_state_and_providers(self, client):
        body = (await client.get("/ready")).json()
        assert body["checks"]["database"] is True
        assert body["checks"]["seeded"] is True
        assert body["evidence_chunks"] > 0
        assert body["regions"] == 5
        assert body["demo_mode"] is True

    async def test_providers_disclose_demo_mode(self, client):
        body = (await client.get("/providers")).json()
        assert body["demo_mode"] is True
        assert body["providers"]["llm"]["demo"] is True

    async def test_pricing_is_configuration_driven(self, client):
        plans = (await client.get("/pricing")).json()
        assert {p["id"] for p in plans} == {"free", "verified_route", "route_check"}


class TestWhereNext:
    async def test_full_flow_returns_a_ranked_comparison(self, client):
        response = await client.post(
            "/api/v1/where-next",
            json={
                "trip": {
                    "start_date": "2026-10-12",
                    "total_nights": 12,
                    "regional_nights": 3,
                    "arrival_city": "Tokyo",
                    "departure_city": "Tokyo",
                    "visited_places": ["Tokyo", "Kyoto", "Osaka"],
                    "interests": ["food", "onsen", "nature"],
                    "driving": "no_car",
                    "pace": "balanced",
                }
            },
        )
        assert response.status_code == 201
        body = response.json()
        result = body["result"]

        assert result["recommended"] is not None
        assert result["recommended"]["deterministic_score"] > 0
        assert result["recommended"]["score_components"], "the rubric must be exposed"
        assert result["citations"], "operational claims need sources"
        assert body["demo_mode"] is True
        assert body["trip_id"] and body["trip_token"]

    async def test_short_trip_rules_kyushu_out_with_a_stated_reason(self, client):
        body = (
            await client.post(
                "/api/v1/where-next",
                json={
                    "trip": {
                        "regional_nights": 3,
                        "arrival_city": "Tokyo",
                        "departure_city": "Tokyo",
                        "interests": ["food", "onsen"],
                        "driving": "no_car",
                    }
                },
            )
        ).json()
        rejected = {r["region_code"]: r for r in body["result"]["rejected"]}
        assert "kyushu" in rejected, "Kyushu cannot work on three nights from Tokyo"
        assert rejected["kyushu"]["rejected_reasons"], "a rejection must say why"
        assert rejected["kyushu"]["fit_label"] == "not_recommended"

    async def test_sparse_input_still_produces_an_answer_with_assumptions(self, client):
        body = (
            await client.post("/api/v1/where-next", json={"trip": {"visited_places": ["Tokyo"]}})
        ).json()
        assert body["result"]["recommended"] is not None
        assert body["result"]["assumptions"], "unstated inputs must surface as assumptions"
        assert body["result"]["missing_information"]

    async def test_result_is_retrievable_by_id(self, client):
        created = (
            await client.post("/api/v1/where-next", json={"trip": {"regional_nights": 4}})
        ).json()
        fetched = (await client.get(f"/api/v1/where-next/{created['analysis_id']}")).json()
        assert fetched["result"]["analysis_id"] == created["analysis_id"]

    async def test_unknown_analysis_is_404(self, client):
        response = await client.get("/api/v1/where-next/an_does_not_exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    async def test_invalid_body_is_422_with_detail(self, client):
        response = await client.post("/api/v1/where-next", json={"trip": {"regional_nights": -5}})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"


class TestRouteCheck:
    async def test_overstuffed_itinerary_is_criticised_with_a_revision(self, client):
        body = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "itinerary_text": "Tokyo 3 nights, Sendai 1 night, Ginzan Onsen 1 night, Aomori 1 night, Hakodate 1 night, then Tokyo",
                    "trip": {
                        "arrival_city": "Tokyo",
                        "departure_city": "Tokyo",
                        "driving": "no_car",
                    },
                },
            )
        ).json()
        result = body["result"]

        assert result["health"] in {"needs_improvement", "high_risk"}
        assert result["critical_issues"], "this itinerary has a real problem"
        assert result["strengths"], "a critique must also say what works"
        assert result["revised_route"], "a better route must be offered"
        assert result["travel_load"]["total_transit_hours"] > 0

        revised_load = result["revised_route"]["travel_load"]
        assert revised_load["total_transit_hours"] < result["travel_load"]["total_transit_hours"]

    async def test_each_issue_carries_its_own_measurements(self, client):
        body = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "itinerary_text": "Tokyo 3 nights, Sendai 1 night, Ginzan Onsen 1 night, Aomori 1 night, then Tokyo",
                    "trip": {
                        "arrival_city": "Tokyo",
                        "departure_city": "Tokyo",
                        "driving": "no_car",
                    },
                },
            )
        ).json()
        issues = body["result"]["critical_issues"] + body["result"]["warnings"]
        assert issues
        for issue in issues:
            assert issue["rule_id"]
            assert issue["deterministic_signal"]

        # Two hops triggering the same rule must not share one explanation.
        burden = [i for i in issues if i["rule_id"] == "R01_travel_burden"]
        if len(burden) > 1:
            assert len({i["explanation"] for i in burden}) == len(burden)

    async def test_structured_stop_entry_skips_extraction(self, client):
        body = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "stops": [
                        {"name": "Tokyo", "nights": 3},
                        {"name": "Kanazawa", "nights": 3},
                        {"name": "Tokyo", "nights": 0},
                    ],
                    "trip": {
                        "arrival_city": "Tokyo",
                        "departure_city": "Tokyo",
                        "driving": "no_car",
                    },
                },
            )
        ).json()
        assert body["result"]["parsed_route"]["stops"][1]["display_name"] == "Kanazawa"
        assert not body["result"]["critical_issues"], "a sane route must not be criticised"

    async def test_unknown_place_is_reported_not_invented(self, client):
        body = (
            await client.post(
                "/api/v1/route-check",
                json={
                    "stops": [
                        {"name": "Tokyo", "nights": 2},
                        {"name": "Zzzq Nonexistent Town", "nights": 2},
                        {"name": "Sendai", "nights": 2},
                    ],
                    "trip": {"arrival_city": "Tokyo"},
                },
            )
        ).json()
        assert body["result"]["unresolved_places"]
        assert "Zzzq Nonexistent Town" in body["result"]["unresolved_places"]

    async def test_empty_request_is_rejected(self, client):
        response = await client.post(
            "/api/v1/route-check", json={"itinerary_text": "", "stops": []}
        )
        assert response.status_code == 422


class TestTripMemory:
    async def test_a_trip_remembers_decisions_across_analyses(self, client):
        created = (
            await client.post(
                "/api/v1/where-next",
                json={
                    "trip": {
                        "regional_nights": 3,
                        "arrival_city": "Tokyo",
                        "departure_city": "Tokyo",
                        "visited_places": ["Tokyo", "Kyoto"],
                        "interests": ["food"],
                        "driving": "no_car",
                    }
                },
            )
        ).json()
        trip_id = created["trip_id"]

        trip = (await client.get(f"/api/v1/trips/{trip_id}")).json()
        assert trip["candidate_region"], "the recommendation becomes the candidate"
        assert "kyushu" in trip["rejected_regions"], "rejections are remembered with their reason"
        assert set(trip["visited"]) >= {"Tokyo", "Kyoto"}

        # A second analysis on the same trip inherits that memory.
        await client.post(
            "/api/v1/route-check",
            json={
                "stops": [{"name": "Tokyo", "nights": 2}, {"name": "Sendai", "nights": 2}],
                "trip_id": trip_id,
            },
        )
        updated = (await client.get(f"/api/v1/trips/{trip_id}")).json()
        assert len(updated["analyses"]) == 2
        assert {a["kind"] for a in updated["analyses"]} == {"where_next", "route_check"}

    async def test_explicit_rejection_is_recorded(self, client):
        created = (
            await client.post("/api/v1/trips", json={"title": "T", "trip": {"regional_nights": 4}})
        ).json()
        trip_id = created["trip"]["id"]
        updated = (
            await client.patch(
                f"/api/v1/trips/{trip_id}",
                json={"reject_region": "tohoku", "reject_reason": "Been there in 2019."},
            )
        ).json()
        assert updated["rejected_regions"]["tohoku"] == "Been there in 2019."

    async def test_unknown_trip_is_404(self, client):
        assert (await client.get("/api/v1/trips/trip_nope")).status_code == 404


class TestEvidence:
    async def test_a_citation_resolves_to_a_readable_passage(self, client):
        body = (
            await client.post("/api/v1/where-next", json={"trip": {"regional_nights": 4}})
        ).json()
        citations = body["result"]["citations"]
        assert citations

        evidence = (await client.get(f"/api/v1/evidence/{citations[0]['evidence_id']}")).json()
        assert evidence["content"]
        assert evidence["freshness_label"]
        assert evidence["is_demo"] is True
        assert "(demo data) (demo data)" not in evidence["source_title"]

    async def test_unknown_evidence_is_404(self, client):
        assert (await client.get("/api/v1/evidence/ev_nope")).status_code == 404


class TestFeedback:
    async def test_feedback_is_recorded(self, client):
        response = await client.post(
            "/api/v1/feedback",
            json={"helpful": False, "comment": "Wrong bus time.", "reported_inaccuracy": True},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "recorded"
