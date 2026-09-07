"""LangGraph workflow tests: node progression, branching, budgets and recovery."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestWhereNextGraph:
    async def test_every_node_executes_in_order(self, analysis_service):
        from jst_api.agents.where_next.graph import NODE_SEQUENCE

        run = await analysis_service.run_where_next(
            {
                "regional_nights": 4,
                "arrival_city": "Tokyo",
                "interests": ["food"],
                "driving": "no_car",
            }
        )
        nodes = run.trace_summary["nodes"]
        for node in NODE_SEQUENCE:
            assert node in nodes, f"{node} did not run"
        assert nodes.index("apply_hard_constraints") < nodes.index("compare_candidates")
        assert nodes.index("grounding_check") < nodes.index("confidence_check")
        assert nodes[-1] == "answer"

    async def test_the_graph_calls_tools_through_mcp(self, analysis_service):
        run = await analysis_service.run_where_next({"regional_nights": 4, "arrival_city": "Tokyo"})
        assert run.trace_summary["tool_calls"] > 0
        assert run.trace_summary["failed_tool_calls"] == 0

    async def test_a_run_stays_inside_its_budgets(self, analysis_service, settings):
        run = await analysis_service.run_where_next({"regional_nights": 4})
        assert run.trace_summary["steps"] <= settings.agent_max_steps
        assert run.trace_summary["tool_calls"] <= settings.agent_max_tool_calls

    async def test_scores_are_reproducible_across_runs(self, analysis_service):
        payload = {
            "regional_nights": 4,
            "arrival_city": "Tokyo",
            "departure_city": "Tokyo",
            "interests": ["food", "onsen"],
            "driving": "no_car",
            "start_date": "2026-10-12",
        }
        first = await analysis_service.run_where_next(payload)
        second = await analysis_service.run_where_next(payload)
        assert (
            first.result["recommended"]["region_code"]
            == second.result["recommended"]["region_code"]
        )
        assert (
            first.result["recommended"]["deterministic_score"]
            == second.result["recommended"]["deterministic_score"]
        )

    async def test_trip_memory_is_read_into_the_analysis(self, analysis_service, session_factory):
        from jst_api.db.models import CandidateRegion, Trip

        async with session_factory() as session:
            trip = Trip(title="memory test", arrival_city="Tokyo", available_regional_nights=5)
            session.add(trip)
            await session.flush()
            session.add(
                CandidateRegion(
                    trip_id=trip.id,
                    region_code="tohoku",
                    status="rejected",
                    reason="Went last year.",
                )
            )
            await session.commit()
            trip_id = trip.id

        run = await analysis_service.run_where_next(
            {"regional_nights": 5, "arrival_city": "Tokyo"}, trip_id=trip_id
        )
        rejected = {r["region_code"] for r in run.result["rejected"]}
        assert "tohoku" in rejected, (
            "a region the traveller rejected must not be re-recommended silently"
        )
        assert run.result["recommended"]["region_code"] != "tohoku"


class TestRouteCheckGraph:
    async def test_every_node_executes(self, analysis_service):
        from jst_api.agents.route_check.graph import NODE_SEQUENCE

        run = await analysis_service.run_route_check(
            {
                "itinerary_text": "Tokyo 3 nights, Sendai 2 nights, Aomori 2 nights, then Tokyo",
                "trip_context": {},
            }
        )
        for node in NODE_SEQUENCE:
            assert node in run.trace_summary["nodes"], f"{node} did not run"
        assert run.trace_summary["nodes"][-1] == "result"

    async def test_the_model_cannot_invent_a_route(self, analysis_service, monkeypatch):
        """A revision must be one of the deterministically costed candidates.
        If the model returns something else it is discarded, not shown."""
        from jst_api.domain.results import CritiqueOutput
        from jst_api.providers import llm as llm_module

        original = llm_module.DemoLLMProvider.complete_structured

        async def hijacked(self, *, system, user, schema, **kwargs):
            obj, usage = await original(self, system=system, user=user, schema=schema, **kwargs)
            if schema is CritiqueOutput:
                obj = obj.model_copy(
                    update={
                        "revised_stops": ["Atlantis", "El Dorado"],
                        "revised_nights": [3, 3],
                        "revision_summary": "A route nobody costed.",
                    }
                )
            return obj, usage

        monkeypatch.setattr(llm_module.DemoLLMProvider, "complete_structured", hijacked)

        run = await analysis_service.run_route_check(
            {
                "itinerary_text": "Tokyo 3 nights, Sendai 1 night, Ginzan Onsen 1 night, Aomori 1 night, then Tokyo",
                "trip_context": {
                    "arrival_city": "Tokyo",
                    "departure_city": "Tokyo",
                    "driving": "no_car",
                },
            }
        )
        revised = run.result["revised_route"]
        if revised:
            assert "Atlantis" not in revised["stops"]
            assert "El Dorado" not in revised["stops"]

    async def test_extraction_failure_degrades_rather_than_crashes(
        self, analysis_service, monkeypatch
    ):
        from jst_api.domain.results import ExtractedItinerary
        from jst_api.providers import llm as llm_module

        original = llm_module.DemoLLMProvider.complete_structured

        async def failing(self, *, system, user, schema, **kwargs):
            if schema is ExtractedItinerary:
                raise RuntimeError("extraction provider is down")
            return await original(self, system=system, user=user, schema=schema, **kwargs)

        monkeypatch.setattr(llm_module.DemoLLMProvider, "complete_structured", failing)

        run = await analysis_service.run_route_check(
            {"itinerary_text": "Tokyo 3 nights, Sendai 2 nights"}
        )
        assert run.result["status"] != "failed", (
            "a provider failure must not lose the whole request"
        )
        assert run.result["unknowns"], "the failure must be disclosed to the traveller"

    async def test_analysis_and_tool_calls_are_persisted_for_replay(
        self, analysis_service, session_factory
    ):
        from sqlalchemy import select

        from jst_api.db.models import AgentRun, Analysis, ToolCall

        run = await analysis_service.run_route_check(
            {
                "stops": [{"name": "Tokyo", "nights": 2}, {"name": "Sendai", "nights": 2}],
                "trip_context": {},
            }
        )
        async with session_factory() as session:
            analysis = await session.get(Analysis, run.analysis_id)
            assert analysis is not None and analysis.kind == "route_check"

            agent_run = await session.scalar(
                select(AgentRun).where(AgentRun.analysis_id == run.analysis_id)
            )
            assert agent_run is not None
            assert agent_run.node_path, "the node path is the agent-eval signal"

            calls = list(
                (
                    await session.scalars(select(ToolCall).where(ToolCall.run_id == agent_run.id))
                ).all()
            )
            assert calls
            assert all(c.transport == "mcp" for c in calls), "tools must cross the MCP boundary"

    async def test_arguments_are_redacted_in_the_trace(self, analysis_service, session_factory):
        from sqlalchemy import select

        from jst_api.db.models import ToolCall

        await analysis_service.run_route_check(
            {
                "itinerary_text": "Tokyo 2 nights then Sendai 2 nights, email me at traveller@example.com",
                "trip_context": {},
            }
        )
        async with session_factory() as session:
            calls = list((await session.scalars(select(ToolCall))).all())
        blob = str([c.arguments for c in calls])
        assert "traveller@example.com" not in blob, "PII must not reach the trace"
