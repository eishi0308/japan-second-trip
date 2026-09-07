"""MCP gateway tests.

These run against a real MCP session — JSON-RPC initialise, tools/list,
tools/call over in-memory streams. If argument validation, output schemas or
error shaping regress in the gateway, these fail.
"""

from __future__ import annotations

import pytest

from travel_mcp.session import McpToolError, TravelMcpSession

pytestmark = pytest.mark.asyncio


class TestGatewayContract:
    async def test_every_tool_publishes_input_and_output_schemas(self, backend):
        from shared_schemas.tools import TOOL_CONTRACTS

        async with TravelMcpSession(backend) as mcp:
            tools = await mcp.list_tools()
        assert {t["name"] for t in tools} == set(TOOL_CONTRACTS)
        for tool in tools:
            assert tool["input_schema"], f"{tool['name']} has no input schema"
            assert tool["output_schema"], f"{tool['name']} has no output schema"
            assert tool["description"], f"{tool['name']} has no description"

    async def test_schemas_are_flat_not_wrapped(self, backend):
        """A consumer should see `from_place`, not `args: {$ref: ...}`."""
        async with TravelMcpSession(backend) as mcp:
            tools = {t["name"]: t for t in await mcp.list_tools()}
        properties = tools["search_transport"]["input_schema"]["properties"]
        assert "from_place" in properties and "to_place" in properties
        assert "args" not in properties

    async def test_bad_arguments_are_rejected_before_dispatch(self, backend):
        async with TravelMcpSession(backend) as mcp:
            with pytest.raises(McpToolError):
                await mcp.call("search_transport", {"from_place": "Sendai"})  # missing to_place
            with pytest.raises(McpToolError):
                await mcp.call("get_weather_context", {"place_slug": "sendai", "month": 13})

    async def test_unknown_tool_is_rejected(self, backend):
        async with TravelMcpSession(backend) as mcp:
            with pytest.raises(McpToolError):
                await mcp.call("drop_all_tables", {})


class TestTransportTools:
    async def test_verified_records_are_preferred_over_estimates(self, backend):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call(
                "search_transport", {"from_place": "Tokyo", "to_place": "Sendai"}
            )
        best = result.data["best_public_option"]
        assert best["duration_minutes"] == 95
        assert best["is_estimate"] is False

    async def test_a_car_only_hop_is_never_dressed_up_as_public_transport(self, backend):
        """The seeded Aso→Takachiho hop has no public equivalent. Returning a
        geometric 'train' estimate would fabricate a service and silence R05."""
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call(
                "search_transport",
                {"from_place": "Mount Aso", "to_place": "Takachiho", "allow_car": False},
            )
        options = result.data["options"]
        assert options, "the hop must still be described"
        assert all(o["requires_car"] for o in options)
        assert result.data["best_public_option"] is None

    async def test_unresolvable_places_return_a_negative_not_a_guess(self, backend):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call(
                "search_transport", {"from_place": "Sendai", "to_place": "Qqxz Imaginary Village"}
            )
        assert result.data["resolved"] is False
        assert result.data["message"]
        assert not result.data["options"]

    async def test_route_rules_run_over_real_durations(self, backend):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call(
                "check_route_constraints",
                {
                    "place_slugs": [
                        "tokyo",
                        "sendai",
                        "ginzan-onsen",
                        "aomori",
                        "hakodate",
                        "tokyo",
                    ],
                    "nights": [3, 1, 1, 1, 1, 0],
                    "public_transport_only": True,
                },
            )
        assert result.data["health"] in {"needs_improvement", "high_risk"}
        rules = {i["rule_id"] for i in result.data["issues"]}
        assert "R01_travel_burden" in rules
        assert result.data["travel_load"]["total_nights"] == 7


class TestPlaceAndEvidenceTools:
    async def test_fuzzy_place_names_resolve(self, backend):
        async with TravelMcpSession(backend) as mcp:
            for query, expected in [
                ("ginzan", "ginzan-onsen"),
                ("Dogo Onsen", "matsuyama"),
                ("Hakata", "fukuoka"),
            ]:
                result = await mcp.call("get_place_details", {"query": query})
                assert result.data["resolved"], f"{query} did not resolve"
                assert result.data["place"]["slug"] == expected

    async def test_evidence_carries_full_provenance(self, backend):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call(
                "search_verified_evidence",
                {"query": "Kurokawa Onsen bus access without a car", "limit": 3},
            )
        assert result.data["evidence"]
        for item in result.data["evidence"]:
            assert item["evidence_id"] and item["source_id"] and item["source_title"]
            assert item["freshness"] in {"fresh", "ageing", "stale", "unverified"}
            assert isinstance(item["is_demo"], bool)

    async def test_verification_status_surfaces_the_seeded_conflict(self, backend):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call("get_verification_status", {"limit": 40})
        assert result.data["entries"]
        conflicts = result.data["conflicts"]
        assert any("ginzan" in c["subject"] for c in conflicts), (
            "the seeded conflict must be visible"
        )


class TestPermissions:
    async def test_consumers_have_least_privilege(self, backend):
        from jst_api.agents.common.tools import ToolBelt, ToolBudget
        from jst_api.observability.tracing import RunTrace

        async with TravelMcpSession(backend) as mcp:
            trace = RunTrace(graph_name="t", thread_id="t")

            route_check = ToolBelt(
                session=mcp, consumer="route_check", trace=trace, budget=ToolBudget()
            )
            where_next = ToolBelt(
                session=mcp, consumer="where_next", trace=trace, budget=ToolBudget()
            )
            admin = ToolBelt(
                session=mcp, consumer="admin_assistant", trace=trace, budget=ToolBudget()
            )

            assert not route_check.can_call("save_trip_decision")
            assert where_next.can_call("save_trip_decision")
            assert not admin.can_call("save_trip_decision")
            assert admin.can_call("create_human_review_request")
            assert admin.writes_allowed() == ["create_human_review_request"]

    async def test_a_denied_tool_raises_before_it_is_dispatched(self, backend):
        from jst_api.agents.common.tools import ToolBelt, ToolBudget
        from jst_api.core.errors import ForbiddenError
        from jst_api.observability.tracing import RunTrace

        async with TravelMcpSession(backend) as mcp:
            belt = ToolBelt(
                session=mcp,
                consumer="route_check",
                trace=RunTrace(graph_name="t", thread_id="t"),
                budget=ToolBudget(),
            )
            with pytest.raises(ForbiddenError):
                await belt.call(
                    "save_trip_decision", {"trip_id": "x", "decision_kind": "candidate_selected"}
                )

    async def test_the_tool_budget_stops_a_runaway_loop(self, backend):
        from jst_api.agents.common.tools import ToolBelt, ToolBudget
        from jst_api.core.errors import AgentBudgetExceeded
        from jst_api.observability.tracing import RunTrace

        async with TravelMcpSession(backend) as mcp:
            belt = ToolBelt(
                session=mcp,
                consumer="where_next",
                trace=RunTrace(graph_name="t", thread_id="t"),
                budget=ToolBudget(max_calls=3),
            )
            with pytest.raises(AgentBudgetExceeded):
                for _ in range(10):
                    await belt.call("get_place_details", {"query": "Sendai"})


class TestTripStateTools:
    async def test_decisions_round_trip_through_the_gateway(self, backend, session_factory):
        from jst_api.db.models import Trip

        async with session_factory() as session:
            trip = Trip(title="mcp state test")
            session.add(trip)
            await session.commit()
            trip_id = trip.id

        async with TravelMcpSession(backend) as mcp:
            saved = await mcp.call(
                "save_trip_decision",
                {
                    "trip_id": trip_id,
                    "decision_kind": "region_rejected",
                    "region_code": "kyushu",
                    "reason": "Too far.",
                },
            )
            assert saved.data["saved"] is True

            context = await mcp.call("get_trip_context", {"trip_id": trip_id})
        assert context.data["found"] is True
        assert context.data["rejected_regions"]["kyushu"] == "Too far."
        assert context.data["decisions"]

    async def test_saving_against_an_unknown_trip_fails_cleanly(self, backend):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call(
                "save_trip_decision",
                {"trip_id": "trip_nope", "decision_kind": "candidate_selected"},
            )
        assert result.data["saved"] is False
