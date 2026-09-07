# ADR 0009 — Explicit model routing by task class

**Status:** accepted · **Date:** 2026-09-06

## Context

A single analysis makes several model calls with very different difficulty.
Pulling stop names out of "Tokyo 3 nights, Sendai 1" is not the same problem as
weighing four regions against six constraints. Using the strongest model for both
wastes money on the first; using the cheapest for both degrades the second.

## Decision

A declared policy table in `providers/llm.py`, not scattered defaults:

| Task class | Tier | Why |
| --- | --- | --- |
| extraction | fast | pattern recognition over short text |
| rerank | fast | ordering supplied candidates |
| schema repair | fast | mechanical correction against a validation error |
| grounding check | fast | matching claims to supplied evidence |
| admin triage | fast | summarising records already gathered |
| **comparison** | **reasoning** | multi-constraint trade-offs with evidence |
| **critique** | **reasoning** | explaining severities and choosing a revision |

Two model names are configured (`LLM_MODEL_REASONING`, `LLM_MODEL_FAST`) and the
router maps task class to one of them. Every call's model, tokens and estimated
cost are recorded on the run and surfaced in the admin console.

## Alternatives considered

**One model everywhere.** Simpler, and defensible at low volume. Rejected
because most calls are genuinely easy, and the cost difference between tiers is
roughly 5×.

**Dynamic routing on input complexity.** Rejected as premature: it needs a
classifier (another model call) and a signal we do not yet have. The task class
is known statically at every call site.

**Cheap model with escalation on failure.** Rejected for the reasoning tasks:
"failure" is a subtly worse explanation, which no validator detects.

## Consequences

Good: cost tracked per run against a stated policy; changing tiers is one
setting; the eval reports tokens per run so a regression is visible.

Bad: two model configurations to keep current, and the split is a judgement call
that should be revisited with production data on where quality actually differs.
