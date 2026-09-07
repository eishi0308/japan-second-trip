# ADR 0002 — LangGraph for stateful agent orchestration

**Status:** accepted · **Date:** 2026-09-06

## Context

Both flows are multi-step, and both need to branch on something the system
learns partway through: *is this answer confident enough to show, or does it need
a person?* They also need to be inspectable after the fact — when a critique is
wrong, "which nodes ran and what did each produce" has to be answerable.

## Decision

Both workflows are `StateGraph`s with typed `TypedDict` state, `operator.add`
reducers on accumulating fields, a conditional edge at `confidence_check`, and a
checkpointer keyed by `thread_id`.

Runtime dependencies (tool belt, providers, prompts, trace) live in an
`AgentContext` the nodes close over; state stays plain serialisable data. That
separation is what makes state checkpointable and nodes testable individually.

## Alternatives considered

**A plain async function per flow.** Honestly viable — the graphs are mostly
linear. Rejected for three things a function does not give: the executed node
path recorded for free (the agent eval asserts on it), a first-class branch to
human review, and interrupt/resume semantics.

**A multi-agent swarm.** Explicitly rejected. There is no task here that
benefits from agents negotiating; it would multiply cost, latency and failure
modes to look sophisticated. One well-orchestrated graph with explicit nodes and
deterministic rules beats a swarm, and `docs/README` says so out loud.

**ReAct-style autonomous loop.** Rejected. An open loop over a tool set is
unbounded in cost and unpredictable in behaviour. The steps are known; encoding
them is a feature.

## Consequences

Good: explicit control flow, recorded node path, branching to HITL, bounded
recursion, individually testable nodes.

Bad: more ceremony than a function for the linear stretches, and a hard rule the
codebase has to keep — nothing runtime may enter graph state, or checkpointing
breaks.

Checkpointing uses `AsyncPostgresSaver` when the database is PostgreSQL, so a
graph paused on `interrupt()` can be resumed by a different process — and falls
back to `MemorySaver` on SQLite, when durable checkpoints are switched off, or if
the saver cannot start, because a checkpointer outage must not take an analysis
down with it (`agents/common/checkpointing.py`).

The application *also* resumes blocked analyses by re-execution with the resolved
fact injected (ADR 0007). That path works regardless of checkpoint state and does
not depend on a checkpoint surviving a library schema change, so it stays the
primary mechanism; the checkpointer is what makes the interrupt path viable
alongside it. Both are tested (`tests/agents/test_interrupt_resume.py`).
