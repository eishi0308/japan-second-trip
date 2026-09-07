"""WhereNextGraph — the stateful workflow behind "where should I go next?".

    parse_trip_context
            ↓
      load_memory
            ↓
  retrieve_region_candidates
            ↓
   apply_hard_constraints          ← deterministic ranking happens here
            ↓
    call_travel_tools              ← MCP: transport, weather, booking
            ↓
 retrieve_verified_evidence        ← MCP: hybrid retrieval + rerank
            ↓
     rerank_evidence               ← dedupe, quarantine, token budget
            ↓
   compare_candidates              ← the single LLM call
            ↓
    grounding_check                ← guardrails over the draft
            ↓
   confidence_check
       ╱          ╲
   answer      human_review
                    ↓
                 answer

The graph is compiled with a checkpointer so a run is addressable by
``thread_id`` and can be resumed after human review.
"""

from __future__ import annotations

import itertools
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from jst_api.agents.common.state import AgentContext, WhereNextState
from jst_api.agents.where_next import nodes

GRAPH_NAME = "where_next"

NODE_SEQUENCE = [
    "parse_trip_context",
    "load_memory",
    "retrieve_region_candidates",
    "apply_hard_constraints",
    "call_travel_tools",
    "retrieve_verified_evidence",
    "rerank_evidence",
    "compare_candidates",
    "grounding_check",
    "confidence_check",
]


def build_where_next_graph(ctx: AgentContext, *, checkpointer: Any | None = None):
    graph = StateGraph(WhereNextState)

    graph.add_node("parse_trip_context", nodes.make_parse_trip_context(ctx))
    graph.add_node("load_memory", nodes.make_load_memory(ctx))
    graph.add_node("retrieve_region_candidates", nodes.make_retrieve_region_candidates(ctx))
    graph.add_node("apply_hard_constraints", nodes.make_apply_hard_constraints(ctx))
    graph.add_node("call_travel_tools", nodes.make_call_travel_tools(ctx))
    graph.add_node("retrieve_verified_evidence", nodes.make_retrieve_verified_evidence(ctx))
    graph.add_node("rerank_evidence", nodes.make_rerank_evidence(ctx))
    graph.add_node("compare_candidates", nodes.make_compare_candidates(ctx))
    graph.add_node("grounding_check", nodes.make_grounding_check(ctx))
    graph.add_node("confidence_check", nodes.make_confidence_check(ctx))
    graph.add_node("human_review", nodes.make_human_review(ctx))
    graph.add_node("answer", nodes.make_answer(ctx))

    graph.add_edge(START, "parse_trip_context")
    for a, b in itertools.pairwise(NODE_SEQUENCE):
        graph.add_edge(a, b)

    graph.add_conditional_edges(
        "confidence_check",
        nodes.route_after_confidence,
        {"human_review": "human_review", "answer": "answer"},
    )
    graph.add_edge("human_review", "answer")
    graph.add_edge("answer", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
