"""Runs the agent graphs and persists everything needed to audit a run.

Responsibilities:
  * open one MCP session per analysis (the agents' only route to capabilities);
  * create the ``RunTrace`` and enforce the step/tool budgets;
  * invoke the compiled LangGraph with a recursion limit;
  * persist the ``Analysis``, the ``AgentRun`` and every ``ToolCall``;
  * turn a failure into a recorded, inspectable outcome rather than a 500.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jst_api.agents.common.checkpointing import checkpointer_for
from jst_api.agents.common.state import AgentContext
from jst_api.agents.common.tools import ToolBelt, ToolBudget
from jst_api.agents.route_check.graph import GRAPH_NAME as ROUTE_CHECK_GRAPH
from jst_api.agents.route_check.graph import build_route_check_graph
from jst_api.agents.where_next.graph import GRAPH_NAME as WHERE_NEXT_GRAPH
from jst_api.agents.where_next.graph import build_where_next_graph
from jst_api.core.config import Settings
from jst_api.core.errors import AgentBudgetExceeded
from jst_api.core.ids import new_id
from jst_api.core.logging import get_logger
from jst_api.db.models import Analysis
from jst_api.domain.enums import AnalysisStatus, ConfidenceState
from jst_api.domain.results import RouteCheckResult, WhereNextResult
from jst_api.observability.metrics import METRICS
from jst_api.observability.tracing import RunTrace
from jst_api.prompts.registry import get_prompts
from jst_api.providers.registry import ProviderRegistry
from jst_api.services.mcp_backend import JstTravelBackend
from travel_mcp.session import TravelMcpSession

log = get_logger(__name__)


@dataclass
class AnalysisRun:
    analysis_id: str
    run_id: str
    trace_summary: dict[str, Any]
    result: dict[str, Any]


class AnalysisService:
    def __init__(
        self, session_factory: Any, registry: ProviderRegistry, settings: Settings
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._settings = settings
        self._backend = JstTravelBackend(session_factory, registry, settings)

    # ---- public API -------------------------------------------------------
    async def run_where_next(
        self, payload: dict[str, Any], *, trip_id: str | None = None, interactive: bool = False
    ) -> AnalysisRun:
        analysis_id = new_id("an")
        thread_id = new_id("th")
        initial = {
            "analysis_id": analysis_id,
            "trip_id": trip_id,
            "thread_id": thread_id,
            "raw_input": payload,
            "status": AnalysisStatus.RUNNING.value,
        }
        return await self._run(
            graph_name=WHERE_NEXT_GRAPH,
            consumer="where_next",
            builder=build_where_next_graph,
            initial=initial,
            analysis_id=analysis_id,
            thread_id=thread_id,
            trip_id=trip_id,
            kind="where_next",
            input_payload=payload,
            interactive=interactive,
        )

    async def run_route_check(
        self,
        payload: dict[str, Any],
        *,
        trip_id: str | None = None,
        interactive: bool = False,
    ) -> AnalysisRun:
        analysis_id = new_id("an")
        thread_id = new_id("th")
        initial = {
            "analysis_id": analysis_id,
            "trip_id": trip_id,
            "thread_id": thread_id,
            "raw_text": payload.get("itinerary_text"),
            "raw_stops": payload.get("stops") or [],
            "trip_context": payload.get("trip_context") or {},
            "status": AnalysisStatus.RUNNING.value,
        }
        return await self._run(
            graph_name=ROUTE_CHECK_GRAPH,
            consumer="route_check",
            builder=build_route_check_graph,
            initial=initial,
            analysis_id=analysis_id,
            thread_id=thread_id,
            trip_id=trip_id,
            kind="route_check",
            input_payload=payload,
            interactive=interactive,
        )

    # ---- internals --------------------------------------------------------
    async def _run(
        self,
        *,
        graph_name: str,
        consumer: str,
        builder: Any,
        initial: dict[str, Any],
        analysis_id: str,
        thread_id: str,
        trip_id: str | None,
        kind: str,
        input_payload: dict[str, Any],
        interactive: bool,
    ) -> AnalysisRun:
        trace = RunTrace(graph_name=graph_name, thread_id=thread_id, analysis_id=analysis_id)
        prompts = get_prompts()
        error: str | None = None
        final_state: dict[str, Any] = {}

        # The analysis row is created and committed *before* the graph runs.
        # Two reasons: a human-review task raised mid-run has a real analysis to
        # point at (it is a foreign key), and a run that crashes leaves an
        # inspectable ``running``/``failed`` record instead of nothing at all.
        async with self._session_factory() as session:
            session.add(
                Analysis(
                    id=analysis_id,
                    trip_id=trip_id,
                    kind=kind,
                    status=AnalysisStatus.RUNNING.value,
                    input_payload=input_payload,
                    result_payload={},
                )
            )
            await session.commit()

        async with (
            TravelMcpSession(self._backend) as mcp,
            checkpointer_for(self._settings) as saver,
        ):
            belt = ToolBelt(
                session=mcp,
                consumer=consumer,
                trace=trace,
                budget=ToolBudget(max_calls=self._settings.agent_max_tool_calls),
            )
            ctx = AgentContext(
                tools=belt,
                registry=self._registry,
                prompts=prompts,
                settings=self._settings,
                trace=trace,
                session_factory=self._session_factory,
                interactive=interactive,
            )
            graph = builder(ctx, checkpointer=saver)
            config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": self._settings.agent_recursion_limit,
            }
            try:
                final_state = await graph.ainvoke(initial, config=config)
            except AgentBudgetExceeded as exc:
                error = str(exc)
                trace.error = error
                log.warning("analysis.budget_exceeded", analysis_id=analysis_id, error=error)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                trace.error = error
                log.exception("analysis.failed", analysis_id=analysis_id, graph=graph_name)

        result = (final_state or {}).get("result") or self._failure_result(
            kind, analysis_id, trip_id, error
        )
        status = result.get(
            "status", AnalysisStatus.FAILED.value if error else AnalysisStatus.COMPLETE.value
        )

        async with self._session_factory() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:  # pragma: no cover - only if the pre-insert was rolled back
                analysis = Analysis(
                    id=analysis_id, trip_id=trip_id, kind=kind, input_payload=input_payload
                )
                session.add(analysis)
            analysis.status = status
            analysis.confidence = result.get("confidence")
            analysis.human_review_required = bool(result.get("human_review_required"))
            analysis.result_payload = result
            analysis.evidence_ids = trace.evidence_ids
            analysis.prompt_versions = trace.prompt_versions
            analysis.error = error
            await session.flush()
            run_id = await trace.persist(session, status="failed" if error else "complete")
            await session.commit()

        summary = trace.summary()
        METRICS.record_run(summary)
        log.info(
            "analysis.complete",
            kind=kind,
            **{k: summary[k] for k in ("latency_ms", "tool_calls", "estimated_cost_usd")},
        )
        return AnalysisRun(
            analysis_id=analysis_id, run_id=run_id, trace_summary=summary, result=result
        )

    @staticmethod
    def _failure_result(
        kind: str, analysis_id: str, trip_id: str | None, error: str | None
    ) -> dict[str, Any]:
        """A failed run still returns a well-formed, honest result."""
        base = {
            "analysis_id": analysis_id,
            "trip_id": trip_id,
            "status": AnalysisStatus.FAILED.value,
            "confidence": ConfidenceState.INSUFFICIENT_EVIDENCE.value,
            "human_review_required": True,
            "human_review_task_id": None,
            "citations": [],
            "demo_mode": True,
            "unknowns": [
                "The analysis did not complete. Nothing here should be treated as verified.",
                *([error] if error else []),
            ],
        }
        if kind == "where_next":
            return {
                **base,
                "recommended": None,
                "alternatives": [],
                "rejected": [],
                "suggested_route": None,
                "assumptions": [],
                "missing_information": [],
                "conflicts": [],
                "scoring_rubric_version": "1.0.0",
                "prompt_versions": {},
            }
        return {
            **base,
            "health": "needs_improvement",
            "health_summary": "The route check did not complete.",
            "parsed_route": None,
            "travel_load": None,
            "critical_issues": [],
            "warnings": [],
            "strengths": [],
            "revised_route": None,
            "proposed_fixes": [],
            "unresolved_places": [],
            "conflicts": [],
            "rules_version": "1.0.0",
            "prompt_versions": {},
        }


def parse_where_next_result(payload: dict[str, Any]) -> WhereNextResult:
    return WhereNextResult.model_validate(payload)


def parse_route_check_result(payload: dict[str, Any]) -> RouteCheckResult:
    return RouteCheckResult.model_validate(payload)
