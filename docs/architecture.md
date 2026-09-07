# Architecture

## The problem this shape exists to solve

A repeat visitor to Japan asks two questions. *Where should I go next?* and *is
this itinerary actually realistic?* Both are decision problems, not search
problems, and both have a property that shapes everything below: **being
confidently wrong is worse than being usefully uncertain.** A recommendation
that sends someone to a region their nights cannot absorb, or a critique that
misses the last bus of the day, costs them a day of a trip they may take once.

That single constraint produces the whole architecture. Every design decision
below is an answer to "what happens when this is wrong?"

## The layers, and what each is allowed to decide

```
Next.js / React frontend
          │
          ▼
      FastAPI
          │
          ▼
  LangGraph agent runtime           ← stateful workflow, branching, HITL
          │
     tool calling                   ← typed, allowlisted, budgeted
          │
          ▼
  travel-intelligence-mcp           ← the reusable capability boundary
          │
   ┌──────┴────────────────┐
   │                       │
external providers     knowledge service
                           │
                       LangChain
                           │
             SQL metadata filtering
                           │
              keyword / FTS search
                           +
                    vector search
                           │
                    hybrid fusion (RRF)
                           │
                       reranking
                           │
                   context assembly
                           │
                          RAG
                           │
                PostgreSQL + pgvector
```

Cross-cutting: guardrails · security · HITL · evals · tracing · observability ·
caching · retries · fallbacks · CI/CD · Docker · AWS.

### Deterministic code decides what is true

`domain/scoring.py` and `domain/route_rules.py` contain every judgement that
affects the answer: fit scores, hard constraints, travel load, issue severities,
route revisions. They are pure functions of structured data. Same input, same
output, every time — which is what makes the product testable, explainable and
auditable.

A traveller can open the rubric in the UI and see the arithmetic.

### Tools and verified data supply the facts

Transport durations, booking lead times, closure windows, last departures. These
come from `transport_constraints` / `booking_constraints` rows with a
`verified_at`, from a live provider, or — clearly labelled — from a geometric
estimate. **Never from a language model.** `providers/transport.py` will return
a car-only option rather than invent a train that does not run.

### Retrieval supplies the prose that resists normalisation

"Difficult without a car." "Awkward with a large suitcase." "The inn takes phone
bookings in Japanese only." These do not become columns without losing their
meaning, so they live in the evidence index and are found by hybrid search.

### The language model reads and explains

Three jobs, and only three: parse a free-text itinerary into a stop list; explain
what the deterministic layer decided; choose between deterministic revision
candidates. It cannot change a score, add an issue, or introduce a route — and
`tests/agents/test_graphs.py::test_the_model_cannot_invent_a_route` enforces the
last one by hijacking the model and asserting the invention is discarded.

### A person decides when the system cannot

Conflicting approved sources, stale critical facts, failed grounding. The system
escalates rather than picking. See "Human in the loop" below.

## Structured data vs RAG

The split is deliberate and is the reason retrieval quality is measurable at all.

| Goes in PostgreSQL columns | Goes in the evidence index |
| --- | --- |
| coordinates, distances | access caveats in prose |
| durations, transfers, frequencies | booking mechanics and etiquette |
| nights, region, prefecture | operator guidance |
| closure months, lead times | "you will regret this with a suitcase" |
| verification timestamps | human verification notes |
| deterministic thresholds | official tourism explanations |

Putting a duration in the vector index would make the fit score unreproducible.
Putting "difficult without a car" in a column would flatten the judgement it
carries. `docs/adr/0005-hybrid-search.md` goes further.

## Retrieval, in detail

```
structured hard filters       region · place · topic · trust · verified-since · season
        ↓
keyword / PostgreSQL FTS      ts_rank_cd + trigram (BM25 on the SQLite fallback)
        +
dense vector retrieval        pgvector cosine, HNSW index
        ↓
hybrid fusion                 Reciprocal Rank Fusion, k = 5, dense weight 0.5
        ↓
reranking                     optional; measured and NOT the default (see below)
        ↓
context assembly              dedupe · quarantine · token budget
        ↓
top evidence + citations
```

Every parameter here was chosen by sweep, and the sweeping found a real bug:
PostgreSQL's `plainto_tsquery` ANDs every term, so a natural-language question
scored **zero against every document in the corpus** and lexical search was
contributing nothing to an entire query class. ORing the terms took keyword MRR
from 0.665 to 0.864 and required re-sweeping everything downstream (`k` 60 → 5,
dense weight 1.5 → 0.5).

Reranking is implemented but is **not** the default: measured, it costs a case
and adds latency on a corpus this size. It is one setting away
(`RETRIEVAL_STRATEGY=hybrid_rerank`) and should be re-evaluated as the corpus
grows. Numbers and reasoning in `docs/evals/retrieval-comparison.md`.

## The two graphs

Both are real `StateGraph`s with typed state, conditional branching and a
checkpointer. Node lists live in `agents/*/graph.py` and are asserted on by the
agent eval — a node that stops running is a test failure, not a silent change.

**WhereNextGraph** — parse trip context → load memory → retrieve region
candidates → **apply hard constraints** (the ranking happens here) → call travel
tools → retrieve verified evidence → rerank → compare candidates (the one model
call) → grounding check → confidence check → answer *or* human review → answer.

**RouteCheckGraph** — parse itinerary → resolve places → load trip state →
retrieve structured facts → call transport tools → retrieve constraints → **run
deterministic checks** (severities decided here) → detect route issues →
generate candidate fixes (deterministic, then re-costed with real transport data)
→ narrate critique → grounding check → confidence check → result *or* human
review → result.

## Why MCP, and why it is not decoration

`travel-intelligence-mcp` is a real MCP server: typed input and output schemas,
protocol-level argument validation, JSON-RPC. The agents connect over in-memory
streams, so a tool call from WhereNext takes exactly the same code path as one
from Claude Desktop over stdio — same validation, same error shaping.

It has three genuine consumers with **different permissions**:

| Consumer | Tools | May write trip state |
| --- | --- | --- |
| WhereNext agent | 13 | yes — it produces the candidate and the rejections |
| RouteCheck agent | 12 | no — critiquing an itinerary is not a reason to write |
| Admin verification assistant | 7 | no — it acts for a reviewer, not a traveller |

That asymmetry is the point. It is also the capability half of the
prompt-injection defence: the model never dispatches a tool, a graph node does,
from an allowlist. A successful injection cannot reach a write tool because the
consumer does not hold the capability.

What does *not* go through MCP: ordinary internal CRUD. Routing a database read
through JSON-RPC would be architecture theatre. MCP carries reusable AI-facing
capabilities and nothing else.

## State and memory

LangGraph state holds the *active workflow*. PostgreSQL holds what survives it:
visited places, the current candidate, rejected regions **with their reasons**,
confirmed preferences, acknowledged warnings, a decision log.

No conversation transcript is stored or replayed. Trip memory is rendered into a
compact block (`TripMemory.to_prompt_block`) with a hard ceiling, so the context
budget stays predictable and the system cannot drift across sessions. A region
the traveller rejected is never silently re-proposed — asserted by
`test_trip_memory_is_read_into_the_analysis`.

## Context engineering

Every model call gets a budget, and the assembler decides what earns a place:

1. quarantine anything scanning as injection (it never reaches the prompt);
2. drop near-duplicates (5-gram Jaccard ≥ 0.82) so one repeated claim cannot
   dominate by repetition;
3. fill to the token budget best-first, truncating the *lowest*-ranked evidence;
4. render each chunk with its id, source, trust level and verification date.

Every assembly emits an audit record — included, dropped, quarantined, tokens
used — which goes into the trace.

## Human in the loop

Escalation triggers, all narrow on purpose:

- approved sources disagree **and the answer depends on the disputed fact**;
- stale critical evidence is cited **and the answer repeats an operational figure
  from it**;
- a citation does not resolve, or an unsupported operational claim survives.

Thin retrieval alone lowers confidence but does *not* escalate — a reviewer
cannot verify a fact the answer never asserted, and filling the queue with those
buries the real conflicts. That narrowing came from the agent eval: before it,
every run escalated.

Resolution writes a `VerificationRecord` (superseding the previous one, keeping
history), then **re-runs every analysis blocked on that task**. Resumption is by
re-execution rather than a held-open process, because a reviewer may answer days
later, after a deploy. LangGraph's `interrupt()` path exists too and is used by
the interactive runner where the pause and the answer share a process.

## Reliability

Every external call has a timeout, bounded exponential retries on transient
errors only, and a circuit breaker. Above that:

- `call_optional` — capabilities the graph can proceed without degrade to a
  thinner answer rather than a failed request;
- LLM fallback — a failing primary provider falls through to a secondary, tagged
  `fell_back` in the trace;
- reranker fallback — any failure returns the fusion ordering;
- schema repair — one bounded retry, then give up (an endless repair loop is a
  cost incident, not resilience);
- budgets — hard caps on steps and tool calls per run.

## Model routing

Cheap model for extraction, classification, reranking and schema repair; strong
model only for multi-constraint comparison and route critique. The policy is a
table in `providers/llm.py`, not scattered defaults. `docs/adr/0009-model-routing.md`.

## Demo mode is a first-class state

With no credentials the entire product works: deterministic embeddings,
deterministic LLM, seeded catalogue and evidence. Every affected result carries
`demo_mode`, every seeded source carries `is_demo`, and the UI says so in a
banner and per-citation badge. A product whose claim is verification cannot be
coy about the provenance of its own answers.
