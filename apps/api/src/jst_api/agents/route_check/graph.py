"""RouteCheckGraph — "is this itinerary actually realistic?"

   parse_itinerary            ← the only place free text meets a model
           ↓
     resolve_places           ← MCP: catalogue lookup, unknowns kept as unknowns
           ↓
    load_trip_state           ← MCP: persistent trip memory
           ↓
retrieve_structured_facts     ← MCP: booking rules, verification status
           ↓
  call_transport_tools        ← MCP: real durations for every leg
           ↓
  retrieve_constraints        ← MCP: hybrid retrieval over access/booking prose
           ↓
run_deterministic_checks      ← MCP: the rules engine. Severities decided here.
           ↓
 detect_route_issues          ← enrich with evidence, booking and freshness
           ↓
generate_candidate_fixes      ← deterministic reshapes, re-costed with real data
           ↓
  narrate_critique            ← the LLM writes prose; it cannot invent a route
           ↓
   grounding_check
           ↓
  confidence_check
      ╱          ╲
  result      human_review
                   ↓
                result
"""

from __future__ import annotations

import itertools
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from jst_api.agents.common.state import AgentContext, RouteCheckState
from jst_api.agents.route_check import nodes

GRAPH_NAME = "route_check"

NODE_SEQUENCE = [
    "parse_itinerary",
    "resolve_places",
    "load_trip_state",
    "retrieve_structured_facts",
    "call_transport_tools",
    "retrieve_constraints",
    "run_deterministic_checks",
    "detect_route_issues",
    "generate_candidate_fixes",
    "narrate_critique",
    "grounding_check",
    "confidence_check",
]


def build_route_check_graph(ctx: AgentContext, *, checkpointer: Any | None = None):
    graph = StateGraph(RouteCheckState)

    graph.add_node("parse_itinerary", nodes.make_parse_itinerary(ctx))
    graph.add_node("resolve_places", nodes.make_resolve_places(ctx))
    graph.add_node("load_trip_state", nodes.make_load_trip_state(ctx))
    graph.add_node("retrieve_structured_facts", nodes.make_retrieve_structured_facts(ctx))
    graph.add_node("call_transport_tools", nodes.make_call_transport_tools(ctx))
    graph.add_node("retrieve_constraints", nodes.make_retrieve_constraints(ctx))
    graph.add_node("run_deterministic_checks", nodes.make_run_deterministic_checks(ctx))
    graph.add_node("detect_route_issues", nodes.make_detect_route_issues(ctx))
    graph.add_node("generate_candidate_fixes", nodes.make_generate_candidate_fixes(ctx))
    graph.add_node("narrate_critique", nodes.make_narrate_critique(ctx))
    graph.add_node("grounding_check", nodes.make_grounding_check(ctx))
    graph.add_node("confidence_check", nodes.make_confidence_check(ctx))
    graph.add_node("human_review", nodes.make_human_review(ctx))
    graph.add_node("result", nodes.make_result(ctx))

    graph.add_edge(START, "parse_itinerary")
    for a, b in itertools.pairwise(NODE_SEQUENCE):
        graph.add_edge(a, b)

    graph.add_conditional_edges(
        "confidence_check",
        nodes.route_after_confidence,
        {"human_review": "human_review", "result": "result"},
    )
    graph.add_edge("human_review", "result")
    graph.add_edge("result", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
