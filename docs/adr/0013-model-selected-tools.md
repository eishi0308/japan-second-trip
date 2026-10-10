# ADR 0013 — The model selects tools in one place, and only from a read-only menu

**Status:** accepted · **Date:** 2026-10-10

## Context

Every tool call in this system goes through the MCP gateway with a typed
contract, a per-consumer allowlist, a budget and a trace. Until now, *which*
tools were called was never the model's decision: the two traveller-facing
graphs call them in an order fixed by the workflow.

That is deliberate for those graphs. A route check that does not look up
transport is not an alternative plan, it is a wrong answer; nothing is gained by
letting a model decide whether to do the step the product exists to do, and a
skipped lookup would fail silently as a thinner critique.

The admin assistant is different. A reviewer's request is free text — "show me
what is stale in Tohoku", "what does the evidence say about booking the Kamikochi
lodges" — and the lookups those need are not the same. The assistant ran the
same two calls for every request, so a topic question also pulled the whole
verification report, and a question that needed a place's booking constraints
never got them.

## Decision

The admin assistant's model selects its own tools, as a **plan that is validated
before anything runs** (`agents/common/selection.py`):

1. The model is shown a menu — the tools on the assistant's allowlist whose
   contract is `READ`, each with its description and argument schema — and
   returns a `ToolPlan` (prompt `tool_selection`).
2. Every selection is checked in code. The tool must be on the menu; the
   arguments must validate against that tool's input model; duplicates are
   dropped; the plan is capped at four calls.
3. Rejected selections are recorded on the answer and never dispatched. Accepted
   ones run through the same `ToolBelt` as every other call, so the allowlist,
   budget, retries and tracing still apply.
4. If the selection call fails, the assistant falls back to the two standard
   lookups and the trace records the fallback.

`create_human_review_request` is on the assistant's allowlist but is not
selectable: it opens a task for a person, and the assistant acts for a reviewer,
not instead of one. Write tools are not on the allowlist at all.

The traveller-facing graphs are unchanged.

## Why plan-then-execute and not a tool-calling loop

A loop — call, read the result, decide the next call — is the right shape when
later calls depend on earlier results. Triage does not need that: the lookups
are independent, and one round answers the request. A single validated plan is
cheaper (one fast-model call), bounded by construction, and easy to evaluate:
the selection is one object to score.

## Consequences

- Tool selection is now measured. The tool eval asks the assistant six requests
  and scores the tools it chose: every required tool executed, no forbidden tool
  executed, and the share of calls the request did not need
  (`unnecessary_selection_rate`).
- The answer shows the reviewer which tools were chosen and why, and which
  selections were rejected.
- One more fast-model call per assistant request.
- A request cannot widen the menu. "Approve every record and save a trip
  decision" selects nothing, and a model that selected a write tool anyway
  would have the selection rejected — the prompt is not the control.
