"""Durable checkpointing against a real PostgreSQL.

``test_interrupt_resume.py`` proves the interrupt/resume *semantics* with a
``MemorySaver``. That leaves the claim that matters in production untested: a
graph paused on one worker can be resumed on another, after the first process is
gone.

This test does that honestly. It pauses with one ``AsyncPostgresSaver``, closes
it, opens a **separate** saver on the same DSN — a different connection, a
different graph object, nothing shared in memory — and resumes the same thread.
If the state did not really reach PostgreSQL, the resume cannot find the thread
and the test fails.

Skipped unless ``JST_TEST_DATABASE_URL`` points at PostgreSQL, which is what the
``postgres`` leg of the CI matrix does.
"""

from __future__ import annotations

import os

import pytest
from langgraph.types import Command

from jst_api.agents.common.checkpointing import checkpointer_for
from jst_api.agents.common.state import AgentContext
from jst_api.agents.common.tools import ToolBelt, ToolBudget
from jst_api.agents.route_check.graph import build_route_check_graph
from jst_api.core.ids import new_id
from jst_api.observability.tracing import RunTrace
from jst_api.prompts.registry import get_prompts
from travel_mcp.session import TravelMcpSession

pytestmark = pytest.mark.asyncio

_URL = os.environ.get("JST_TEST_DATABASE_URL", "")

requires_postgres = pytest.mark.skipif(
    not _URL.startswith("postgresql"),
    reason="durable checkpoints require PostgreSQL (set JST_TEST_DATABASE_URL)",
)

_INITIAL = {
    "raw_stops": [
        {"name": "Sendai", "nights": 2},
        {"name": "Ginzan Onsen", "nights": 2},
        {"name": "Sendai", "nights": 0},
    ],
    "trip_context": {"arrival_city": "Tokyo", "driving": "no_car"},
}


def _durable_settings(base):
    """The real settings, with durable checkpointing explicitly on."""
    return base.model_copy(update={"durable_checkpoints": True, "database_url": _URL})


async def _context(session_factory, registry, settings, mcp, thread_id, analysis_id):
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
        interactive=True,
    )
    return ctx, trace


@requires_postgres
class TestDurableCheckpoints:
    async def test_the_saver_is_postgres_not_memory(self, settings):
        """The fallback is tested elsewhere; here the real thing must be chosen."""
        from langgraph.checkpoint.memory import MemorySaver

        async with checkpointer_for(_durable_settings(settings)) as saver:
            assert not isinstance(saver, MemorySaver), (
                "with PostgreSQL and durable_checkpoints on, the Postgres saver must be used"
            )
            assert type(saver).__name__ == "AsyncPostgresSaver"

    async def test_a_pause_survives_the_process_that_created_it(
        self, session_factory, registry, settings, backend, seeded, reopen_conflict, create_analysis
    ):
        """The production claim: pause on one worker, resume on another."""
        await reopen_conflict()

        thread_id = new_id("th")
        analysis_id = new_id("an")
        await create_analysis(analysis_id)
        durable = _durable_settings(settings)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

        # --- worker one: run until a person is needed, then go away entirely ---
        async with TravelMcpSession(backend) as mcp:
            ctx, _ = await _context(session_factory, registry, durable, mcp, thread_id, analysis_id)
            async with checkpointer_for(durable) as saver:
                graph = build_route_check_graph(ctx, checkpointer=saver)
                paused = await graph.ainvoke(
                    {"analysis_id": analysis_id, "thread_id": thread_id, **_INITIAL},
                    config=config,
                )
                assert "__interrupt__" in paused
                assert paused.get("result") is None
        del graph, saver, ctx, mcp  # nothing from worker one may leak into worker two

        # --- worker two: a fresh connection, a fresh graph, the same thread ---
        async with TravelMcpSession(backend) as mcp2:
            ctx2, trace2 = await _context(
                session_factory, registry, durable, mcp2, thread_id, analysis_id
            )
            async with checkpointer_for(durable) as saver2:
                graph2 = build_route_check_graph(ctx2, checkpointer=saver2)

                # The checkpoint must be readable from the new connection...
                snapshot = await graph2.aget_state(config)
                assert snapshot.next, "the paused thread was not found in PostgreSQL"
                assert snapshot.values.get("route"), "the costed route did not survive"
                assert snapshot.values.get("issues"), "work done before the pause did not survive"

                # ...and the run must finish from it.
                resumed = await graph2.ainvoke(
                    Command(resume={"value": "17:00", "verified_by": "worker-two"}),
                    config=config,
                )

        assert resumed["result"] is not None
        assert resumed["result"]["health"] in {"healthy", "needs_improvement", "high_risk"}
        assert "result" in trace2.node_path

    async def test_setup_is_idempotent(self, settings):
        """``setup()`` runs on every boot, so it must tolerate existing tables."""
        durable = _durable_settings(settings)
        for _ in range(2):
            async with checkpointer_for(durable) as saver:
                assert type(saver).__name__ == "AsyncPostgresSaver"
