# ADR 0006 — Deterministic rules coexist with LLM reasoning

**Status:** accepted · **Date:** 2026-09-06

## Context

The product makes claims a traveller acts on: this region does not fit your
nights; this hop costs more time than it buys; you will miss the last bus. Those
must be right, consistent between runs, and explainable when challenged.

## Decision

A hard split, enforced by tests.

**Deterministic code decides.** `domain/scoring.py` is a documented weighted
rubric over explicit constraints (weights asserted to sum to 1.0 at import).
`domain/route_rules.py` is eleven rules, each a pure function producing an issue
with the measurements that triggered it. `domain/revision.py` generates route
alternatives structurally and scores them on an explicit objective.

**The model explains.** It writes the prose for issues the engine already found,
and chooses among revisions already costed with real transport data. Prompts
state that deterministic results are authoritative and must not be recomputed.

**Enforcement, not politeness.** The critique node validates that any revision
the model returns is one of the costed candidates; anything else is discarded and
an unknown is recorded. `tests/agents/test_graphs.py` proves it by hijacking the
model to return an invented route and asserting it never reaches the user.

## Alternatives considered

**Let the model judge everything.** Rejected: unreproducible, unexplainable, and
it would invent travel times. The failure mode is a confident wrong answer, which
is the exact thing this product exists to avoid.

**Deterministic only, no model.** Rejected: parsing "Tokyo 3 nights, Sendai 1,
Ginzan 1" from free text is a genuine language task, and machine-written
explanations read like a compiler.

**Model with a validation pass.** Rejected: validating a generated number
requires the deterministic computation anyway, so compute it first and skip the
generation.

## Consequences

Good: reproducible scores (asserted), auditable critiques, a rubric a user can
read, and rules that regression-test in milliseconds without a model.

Bad: rules are hand-written and need maintaining as the catalogue grows.
Thresholds are judgement calls — so they are module-level constants with stated
reasoning, and the evals sweep them. One of them (`MAX_TRANSIT_SHARE`) was
tightened from 0.42 to 0.35 because a unit test showed a 14-hour return transfer
for two nights was passing.
