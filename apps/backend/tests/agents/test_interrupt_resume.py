"""LangGraph interrupt/resume semantics.

The API resumes a blocked analysis by re-execution (see ADR 0007), because a
reviewer may answer days later in a different process. But the interrupt path is
real and is used by the interactive runner, so it is tested here rather than
merely claimed: the graph must genuinely pause at ``human_review``, surface the
question, and continue to a complete result when resumed.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from jst_api.agents.common.state import AgentContext
from jst_api.agents.common.tools import ToolBelt, ToolBudget
from jst_api.agents.route_check.graph import build_route_check_graph
from jst_api.core.ids import new_id
from jst_api.observability.tracing import RunTrace
from jst_api.prompts.registry import get_prompts
from travel_mcp.session import TravelMcpSession

pytestmark = pytest.mark.asyncio


class TestInterruptResume:
    async def test_the_graph_pauses_then_completes_when_resumed(
        self, session_factory, registry, settings, backend, seeded, reopen_conflict, create_analysis
    ):
        await reopen_conflict()

        thread_id = new_id("th")
        analysis_id = new_id("an")
        await create_analysis(analysis_id)
        checkpointer = MemorySaver()
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

        initial = {
            "analysis_id": analysis_id,
            "thread_id": thread_id,
            "raw_stops": [
                {"name": "Sendai", "nights": 2},
                {"name": "Ginzan Onsen", "nights": 2},
                {"name": "Sendai", "nights": 0},
            ],
            "trip_context": {"arrival_city": "Tokyo", "driving": "no_car"},
        }

        async with TravelMcpSession(backend) as mcp:
            trace = RunTrace(graph_name="route_check", thread_id=thread_id, analysis_id=analysis_id)
            ctx = AgentContext(
                tools=ToolBelt(
                    session=mcp,
                    consumer="route_check",
                    trace=trace,
                    budget=ToolBudget(max_calls=settings.agent_max_tool_calls),
                ),
                registry=registry,
                prompts=get_prompts(),
                settings=settings,
                trace=trace,
                session_factory=session_factory,
                interactive=True,  # the path under test
            )
            graph = build_route_check_graph(ctx, checkpointer=checkpointer)

            # 1. the graph runs until it needs a person, then stops
            paused = await graph.ainvoke(initial, config=config)
            assert "__interrupt__" in paused, "the graph should have paused for human review"

            payload = paused["__interrupt__"][0].value
            assert payload["reason"] == "conflicting_sources"
            assert "ginzan" in payload["subject"]
            assert set(payload["candidate_values"]) == {"17:00", "16:30"}
            assert payload["question"]

            # 2. nothing is finished while it waits
            assert paused.get("result") is None

            # 3. a reviewer answers, and the same thread continues
            resumed = await graph.ainvoke(
                Command(resume={"value": "17:00", "verified_by": "tester"}), config=config
            )

        assert resumed["result"] is not None
        assert resumed["result"]["health"] in {"healthy", "needs_improvement", "high_risk"}
        assert resumed["result"]["human_review_task_id"]
        assert "result" in trace.node_path, "the graph must run to the terminal node"

    async def test_the_checkpoint_holds_the_paused_state(
        self, session_factory, registry, settings, backend, seeded, reopen_conflict, create_analysis
    ):
        """A pause is only useful if the state survives it."""
        await reopen_conflict()

        thread_id = new_id("th")
        analysis_id = new_id("an")
        await create_analysis(analysis_id)
        checkpointer = MemorySaver()
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

        async with TravelMcpSession(backend) as mcp:
            trace = RunTrace(graph_name="route_check", thread_id=thread_id)
            ctx = AgentContext(
                tools=ToolBelt(
                    session=mcp,
                    consumer="route_check",
                    trace=trace,
                    budget=ToolBudget(max_calls=40),
                ),
                registry=registry,
                prompts=get_prompts(),
                settings=settings,
                trace=trace,
                session_factory=session_factory,
                interactive=True,
            )
            graph = build_route_check_graph(ctx, checkpointer=checkpointer)
            await graph.ainvoke(
                {
                    "analysis_id": analysis_id,
                    "thread_id": thread_id,
                    "raw_stops": [
                        {"name": "Sendai", "nights": 2},
                        {"name": "Ginzan Onsen", "nights": 2},
                    ],
                    "trip_context": {"driving": "no_car"},
                },
                config=config,
            )

            snapshot = await graph.aget_state(config)

        assert snapshot.next, "a paused graph must have a pending next node"
        assert snapshot.values.get("issues"), "work done before the pause must be preserved"
        assert snapshot.values.get("route"), "the costed route must survive the pause"


class TestCheckpointerSelection:
    async def test_sqlite_falls_back_to_an_in_process_saver(self):
        """Durable checkpoints need PostgreSQL; SQLite must still work."""
        from jst_api.agents.common.checkpointing import checkpointer_for
        from jst_api.core.config import Settings

        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        async with checkpointer_for(settings) as saver:
            assert isinstance(saver, MemorySaver)

    async def test_durable_checkpoints_can_be_switched_off(self):
        from jst_api.agents.common.checkpointing import checkpointer_for
        from jst_api.core.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://x@localhost/y", durable_checkpoints=False
        )
        async with checkpointer_for(settings) as saver:
            assert isinstance(saver, MemorySaver)

    async def test_an_unreachable_database_degrades_instead_of_failing(self):
        """A checkpointer outage must not take an analysis down with it."""
        from jst_api.agents.common.checkpointing import checkpointer_for
        from jst_api.core.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://nobody@127.0.0.1:1/nothing",
            durable_checkpoints=True,
        )
        async with checkpointer_for(settings) as saver:
            assert isinstance(saver, MemorySaver)

    async def test_dsn_translation(self):
        """The app uses asyncpg; the checkpointer uses psycopg."""
        from jst_api.agents.common.checkpointing import to_psycopg_dsn

        assert (
            to_psycopg_dsn("postgresql+asyncpg://u:p@host:5432/db")
            == "postgresql://u:p@host:5432/db"
        )
        assert to_psycopg_dsn("postgresql://u@host/db") == "postgresql://u@host/db"
