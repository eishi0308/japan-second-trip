"""Typed LangGraph state.

State is plain, serialisable data — no sessions, no providers, no clients. The
runtime dependencies live in ``AgentContext``, which nodes close over. That
separation is what makes the state checkpointable and the graphs testable node
by node.

List fields that several nodes contribute to use ``operator.add`` reducers so a
node returns only its own contribution rather than having to read-modify-write
the whole list.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from jst_api.agents.common.tools import ToolBelt
from jst_api.core.config import Settings
from jst_api.observability.tracing import RunTrace
from jst_api.prompts.registry import PromptRegistry
from jst_api.providers.registry import ProviderRegistry


@dataclass
class AgentContext:
    """Everything a node needs that is not state."""

    tools: ToolBelt
    registry: ProviderRegistry
    prompts: PromptRegistry
    settings: Settings
    trace: RunTrace
    session_factory: Any
    interactive: bool = False
    """When True the human-review node uses LangGraph ``interrupt()``. The API
    runs non-interactive and instead persists a review task, because a reviewer
    may answer days later and in a different process."""

    def model_for(self, task: str) -> str:
        return self.registry.router.model_for(task)


class WhereNextState(TypedDict, total=False):
    # --- inputs
    analysis_id: str
    trip_id: str | None
    thread_id: str
    raw_input: dict[str, Any]
    trip_context: dict[str, Any]

    # --- memory
    visited_places: list[str]
    memory: dict[str, Any]
    previously_rejected: dict[str, str]

    # --- candidates
    candidate_regions: list[dict[str, Any]]
    rejected_regions: list[dict[str, Any]]
    hard_constraint_failures: dict[str, list[dict[str, Any]]]

    # --- facts and tools
    structured_facts: dict[str, Any]
    tool_results: dict[str, Any]

    # --- evidence
    retrieved_evidence: list[dict[str, Any]]
    reranked_evidence: list[dict[str, Any]]
    evidence_block: str
    quarantined_evidence: list[dict[str, Any]]
    context_audit: dict[str, Any]

    # --- outputs
    explanations: list[dict[str, Any]]
    suggested_route: dict[str, Any] | None
    constraints: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    missing_information: Annotated[list[str], operator.add]
    assumptions: Annotated[list[str], operator.add]
    unknowns: Annotated[list[str], operator.add]
    node_errors: Annotated[list[str], operator.add]
    #: Checks that could not be performed at all — distinct from ``unknowns``
    #: (things the answer does not know) and ``node_errors`` (crashes). A gap
    #: here means the analysis skipped part of its own job, so guardrail G7 caps
    #: confidence: a verdict on a route that was never costed is not a
    #: high-confidence verdict, however good the evidence behind it looks.
    analysis_gaps: Annotated[list[str], operator.add]

    # --- control
    guardrail_report: dict[str, Any]
    conflicts: list[dict[str, Any]]
    confidence: str
    status: str
    human_review_required: bool
    human_review_task_id: str | None
    human_resolution: dict[str, Any] | None
    result: dict[str, Any] | None


class RouteCheckState(TypedDict, total=False):
    # --- inputs
    analysis_id: str
    trip_id: str | None
    thread_id: str
    raw_text: str | None
    raw_stops: list[dict[str, Any]]
    trip_context: dict[str, Any]

    # --- parsing / resolution
    extracted: dict[str, Any]
    resolved_stops: list[dict[str, Any]]
    unresolved_places: Annotated[list[str], operator.add]

    # --- facts and tools
    memory: dict[str, Any]
    structured_facts: dict[str, Any]
    route: dict[str, Any]
    travel_load: dict[str, Any]
    tool_results: dict[str, Any]

    # --- evidence
    retrieved_evidence: list[dict[str, Any]]
    evidence_block: str
    quarantined_evidence: list[dict[str, Any]]
    context_audit: dict[str, Any]

    # --- analysis
    issues: list[dict[str, Any]]
    health: str
    candidate_revisions: list[dict[str, Any]]
    chosen_revision: dict[str, Any] | None
    critique: dict[str, Any]

    # --- accumulators
    unknowns: Annotated[list[str], operator.add]
    node_errors: Annotated[list[str], operator.add]
    #: Checks that could not be performed at all — distinct from ``unknowns``
    #: (things the answer does not know) and ``node_errors`` (crashes). A gap
    #: here means the analysis skipped part of its own job, so guardrail G7 caps
    #: confidence: a verdict on a route that was never costed is not a
    #: high-confidence verdict, however good the evidence behind it looks.
    analysis_gaps: Annotated[list[str], operator.add]

    # --- control
    guardrail_report: dict[str, Any]
    conflicts: list[dict[str, Any]]
    confidence: str
    status: str
    human_review_required: bool
    human_review_task_id: str | None
    human_resolution: dict[str, Any] | None
    result: dict[str, Any] | None


@dataclass
class NodeOutcome:
    """Small helper for nodes that can partially fail without stopping the graph."""

    updates: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def merged(self) -> dict[str, Any]:
        if self.error:
            return {**self.updates, "node_errors": [self.error]}
        return self.updates
