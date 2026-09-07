# ADR 0007 — Human review, and resumption by re-execution

**Status:** accepted · **Date:** 2026-09-06

## Context

Approved sources disagree. The seeded corpus contains a real example: the last
bus from Oishida into Ginzan Onsen is 18:10 on the tourism page, 17:00 on the
operator timetable, and 16:30 in a traveller's winter report. A traveller who
believes the wrong one is stranded.

No amount of model quality resolves this. The information required is not in the
corpus.

## Decision

**Escalate rather than choose**, on narrow triggers:

- sources disagree **and the answer depends on the disputed fact**;
- stale critical evidence is cited **and the answer repeats an operational figure
  from it**;
- a citation does not resolve, or an unsupported operational claim survives.

Thin retrieval alone lowers confidence but does not escalate. A reviewer cannot
verify a fact the answer never asserted, and filling the queue with those buries
the real conflicts. Both narrowings came from the agent eval, which initially
failed because *every* run escalated.

**Resume by re-execution.** Resolution writes a `VerificationRecord` (superseding
the previous one — history is kept, not overwritten), then re-runs every analysis
blocked on that task. The reviewer's decision is committed *before* the re-run,
or the re-run re-detects the conflict it was meant to settle.

LangGraph's `interrupt()` path is also real, backed by a durable PostgreSQL
checkpointer, and is used by the interactive runner. It is tested end to end:
the graph pauses at `human_review`, surfaces the disputed values, preserves the
work done before the pause, and continues to a complete result when resumed with
`Command(resume=...)`.

## Alternatives considered

**Trust the most authoritative source.** Tempting, and wrong here: the operator
page and the tourism page are both official and they disagree. Trust level does
not encode "which one was updated for the winter timetable".

**Show the traveller both and let them decide.** Partly adopted — both values are
always shown. But an unresolved conflict must also generate work for someone,
otherwise it is never fixed for the next traveller.

**Hold the graph open on `interrupt()` until a human answers.** Rejected as the
primary path. A reviewer may answer days later, after a restart or a deploy.
Holding a process is not a design, it is a leak.

## Consequences

Good: the system never fabricates a value it cannot verify; resolution is durable
across restarts; one resolution releases every analysis waiting on it; the
verified value, the reviewer and the date are shown to the traveller.

Bad: re-running costs another analysis (cheap here, would matter with an
expensive model), and the traveller sees a "pending verification" state rather
than an answer. That is the honest state, and saying so is the product.
