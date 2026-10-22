# Implementation report

The state of the build against the original brief, as of 2026-10-22 (commit
`3501e6f`). Numbers below were measured, not estimated; where a figure was not
re-run for this report, it says so.

## Built

- **Where Next** ranks five regions with a documented, deterministic score and
  says plainly which ones to skip and why.
- **RouteCheck** reads a pasted itinerary, costs every leg, flags problems by
  severity, and offers a revised route with what it gains and what it loses.
- **Every result** opens with a short summary — verdict, next steps, caveats —
  and every source shows its last-verified date.
- **Trip memory** persists. A region the traveller rejected is never re-proposed.
- **Human review** is real: when sources disagree, a review task opens, an admin
  resolves it, and the analyses that were waiting on it re-run.
- **Admin console**: sources, ingestion, review queue, stale and changed
  sources, agent runs, evals, failed tool calls, and an assistant whose model
  chooses its own read-only tools.
- **Checkout** works end to end in demo mode, with no card and no charge.
- **Everything runs with no API keys**, on demo providers labelled as demo
  throughout.

## Architecture

- **Two LangGraph workflows** (12 and 14 nodes) with typed state, a branch to
  human review, and a durable checkpointer.
- **LangChain owns retrieval**: keyword and vector search fused by rank, then
  reranked, with source ids carried through to the citations.
- **One MCP gateway** with 14 typed tools serves three consumers — Where Next,
  RouteCheck and the admin assistant — each with its own allowlist and call
  budget.
- **Deterministic code** computes every score, duration and rule. The model
  explains results and never overrules them.
- **The traveller flows call tools in a fixed order.** Only the admin
  assistant's model picks its tools, and code validates each pick before
  anything runs ([ADR 0013](adr/0013-model-selected-tools.md)).
- **No predictive ML** ([ADR 0011](adr/0011-no-predictive-ml.md)). There are 13
  decision records in [`adr/`](adr/).

## AI engineering skills

| Skill | Real implementation | File/module | Why used |
| --- | --- | --- | --- |
| LLM APIs | Anthropic and OpenAI adapters, demo provider, fallback, model routing | `providers/llm.py` | No single provider can stop the product |
| Prompt engineering | 8 versioned prompts with a shared safety preamble | `prompts/library/*.toml` | Auditable; an eval regression maps to a prompt version |
| Context engineering | Injection quarantine, de-duplication, token budget | `knowledge/context.py` | Bounded, relevant context |
| Structured outputs | Pydantic schemas with one bounded repair | `domain/results.py`, `providers/llm.complete_with_repair` | Machine-checked model output |
| Hybrid retrieval and RAG | Full-text + pgvector, rank fusion, reranker, citations | `knowledge/*` | Place names need exact matching; intent needs meaning |
| LangGraph | Two stateful graphs with a review branch | `agents/where_next`, `agents/route_check` | Branching, resumable workflows |
| MCP and tool calling | Typed gateway, allowlists, retries, tracing, validated tool selection | `packages/travel_mcp`, `agents/common/tools.py`, `agents/common/selection.py` | One reusable capability boundary |
| Human review | Review tasks, resolution, re-run | `services/review_service.py` | Conflicting facts go to a person |
| Guardrails and security | Unsupported-claim check, injection defence, admin auth, rate limit | `agents/common/guardrails.py`, `security/*` | No evidence, no confident claim |
| Observability | OpenTelemetry, per-run tokens, cost and latency, optional Langfuse | `observability/*` | Every analysis is traceable |
| Reliability | Cache, bounded retries, fallbacks, background re-embedding | `core/*`, `knowledge/reembed.py` | Outages degrade results, not requests |

The full table, with the tests behind every row, is in
[`ai-engineering-skill-map.md`](ai-engineering-skill-map.md).

## Evals

| Suite | Result | Notes |
| --- | --- | --- |
| Retrieval | 20/20 | Hybrid selected: MRR 0.887, recall@5 0.797. Reranking did not help on this corpus, so it is off. |
| Tool | 29/29 | Tool selection 6/6 with 0% unnecessary calls, on both the demo model and gpt-4o-mini |
| RAG | 6/6 | Relevance, citations and groundedness 1.00; no unsupported claims |
| Security | 19/19 | |
| Agent | 8/8 | |
| Production | 12/12 | p50 307 ms, p95 350 ms on demo providers |

The tool, RAG, security and agent suites were re-run during the final round of
work and passed. The retrieval report was regenerated on 2026-10-07. The
production latency figures come from [`evals.md`](evals.md) and were not re-run
for this report. Methodology: [`evals.md`](evals.md); the four-way retrieval
comparison: [`evals/retrieval-comparison.md`](evals/retrieval-comparison.md).

## Tests

| Check | Result |
| --- | --- |
| Backend | 276 tests pass on PostgreSQL; on SQLite 273 pass and 3 PostgreSQL-only tests are skipped |
| Frontend | 52 tests pass: 24 component, 28 integration against a mocked API |
| End-to-end (Playwright) | 20 tests × 2 viewports (desktop and mobile), all pass |
| Lint and types | ruff, mypy and tsc clean |
| Terraform | validates |
| CI | green on GitHub for the commit above, including the Docker build and the end-to-end job |

## External integrations

| Service | Status |
| --- | --- |
| LLM | Real (OpenAI configured; Anthropic supported), with a demo fallback |
| Embeddings | Real (OpenAI) or demo |
| Weather | Real (Open-Meteo, no key needed) |
| Places and transport | Demo. The Google adapter is written but has no key. |
| Stripe | Demo checkout. The real adapter has only been tested with a mocked client. |
| Langfuse | Supported, switched off |
| AWS | Terraform written and validated, never applied |

## Known limitations

- The travel data is hand-authored demo data for five regions. Do not book from
  it.
- Durations are approximations, not timetables.
- The fit-score weights are judgement and have never been checked against real
  travellers.
- Buying unlocks nothing yet: every result is shown in full for free.
- The closing summary's wording varies from run to run. A summary that states
  anything the analysis does not support is replaced by a plain one.
- No real user has tried it.

## How to run

```bash
make setup
make dev          # web :3000, API :8000, admin /admin (token dev-admin-token)
make test         # backend
make test-web     # frontend
make e2e          # needs the stack running
make evals-ci     # the CI eval subset
```

## Next production steps

1. Connect a real transport and places source (a Google Maps key or a licensed
   timetable feed).
2. Decide what a paid plan unlocks, then test checkout with a Stripe test key.
3. Set an AWS deploy role on the repository and apply the Terraform.
4. Grow the golden eval set well beyond 20 queries, and re-measure retrieval on
   the live embedder.
5. Test the product with real repeat visitors to Japan.
