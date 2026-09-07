# Japan Second Trip

**Choose the right next Japan — and make sure the trip actually works.**

Verified regional travel intelligence for people who have already done Tokyo,
Kyoto and Osaka.

---

## The problem

A repeat visitor to Japan asks two questions that existing tools answer badly.

**"Where should I go next?"** The difficulty is not discovering that Tohoku,
Nagano, Hokuriku, Shikoku and Kyushu exist. It is knowing which one fits *this*
trip — these dates, this many nights, flying in and out of here, with or without
a car. Kyushu is superb, and it is the wrong answer for three regional nights out
of Tokyo. Nothing about Kyushu changes; the trip does.

**"Is this itinerary actually realistic?"** Someone with a drafted route wants to
know whether it survives contact with the last bus of the day — before they book
it.

Both are decision problems, and both share one property that shapes the entire
system: **being confidently wrong is worse than being usefully uncertain.**
Someone takes this trip once.

## What it does

### Where Next

Scores every region against your actual constraints using a documented,
deterministic rubric, then explains the result against retrieved evidence.

```
BEST FIT   Nagano & the Japan Alps          86/100  strong fit

  + 3.0h return transfer from Tokyo by shinkansen, no transfer —
    7% of the leg in transit
  + 3N sits inside the 2–4N sweet spot
  + Strong for food, onsen, nature
  − Kamikochi's valley lodges book out for autumn nearly a year ahead

ALTERNATIVES   Tohoku 83 · Hokuriku 81 · Shikoku 67

NOT RECOMMENDED FOR THIS TRIP
  Kyushu 38  → Kyushu needs at least 4 nights to be worth the transfer;
                this trip allows 3.
```

The product is willing to say *do not go here on this trip*, and to say why.

### RouteCheck

```
ROUTE HEALTH   Needs improvement

CRITICAL  Ginzan Onsen → Aomori costs more time than it buys
          5.5h hop; with 1 night at Aomori that leaves ~3.5h of usable time.

WARNING   Sendai → Ginzan Onsen costs more time than it buys
WARNING   You are changing accommodation almost every night
WARNING   Something here needs booking about 120 days ahead

GOOD      Tokyo → Sendai is efficient
GOOD      You have a proper base

RECOMMENDED CHANGE
  Tokyo 3N → Sendai 2N → Aomori 2N → Tokyo
  transit 16.9h → 6.9h · hotel changes 4 → 2 · single nights 4 → 0
  Lost: you no longer visit Ginzan Onsen or Hakodate.
```

Every issue exposes the measurements that triggered it. The revised route is
generated deterministically and **re-costed with real transport data** before it
is offered — a route with invented travel times is worse than no route.

## What is actually agentic here

Not "an LLM in a loop". Specifically:

- **Stateful workflows.** Two LangGraph `StateGraph`s (12 and 14 nodes) with
  typed state, reducers and a durable PostgreSQL checkpointer. The executed node path is recorded
  and asserted on by the eval suite.
- **Conditional branching.** `confidence_check` routes to `answer` or to
  `human_review` based on what the guardrails found — a real decision the system
  makes at runtime.
- **Tool selection and invocation.** 14 typed tools behind an MCP gateway, with
  per-consumer allowlists, argument validation at the protocol layer, budgets,
  bounded retries and full tracing.
- **Retrieval.** Hybrid dense + lexical search with rank fusion and reranking,
  tuned by measurement.
- **State and memory.** Trip decisions persist and constrain later analyses. A
  region the traveller rejected is never silently re-proposed.
- **Degradation.** A provider outage produces a thinner answer, not a failed
  request. A failing LLM falls through to a secondary, tagged in the trace.
- **Human escalation.** When approved sources disagree, the system stops and asks
  a person — then re-runs every analysis that was waiting.
- **Evaluation.** Six suites, versioned datasets, and eight defects that these
  evals found and that were fixed as a result.

**What is deliberately not agentic:** the scoring, the rules, the severities and
the route revisions. Those are deterministic code. The model reads free text and
explains findings; it cannot change a score or invent a route, and there is a
test that hijacks the model to prove it.

## Architecture

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
  travel-intelligence-mcp           ← reusable capability boundary, 3 consumers
          │
   ┌──────┴────────────────┐
   │                       │
external providers     knowledge service
                           │
                       LangChain
                           │
             SQL metadata filtering
                           │
              keyword / FTS search  +  vector search
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

### Who decides what

| Layer | Decides | Example |
| --- | --- | --- |
| **Deterministic code** | what is true | fit scores, travel load, issue severities, route revisions |
| **Tools & verified data** | the facts | durations, booking lead times, last departures |
| **Retrieval** | the nuance | "difficult without a car", "book in Japanese only" |
| **The model** | the words | parses itineraries, explains findings, picks between costed options |
| **A person** | the unresolvable | conflicting sources, stale critical facts |

Full detail in [`docs/architecture.md`](docs/architecture.md).

## Running it

```bash
git clone <repo> && cd japan-second-trip
make setup
make dev
```

- web — http://localhost:3000
- api — http://localhost:8000/docs
- ready — http://localhost:8000/ready
- admin — http://localhost:3000/admin (token: `dev-admin-token`)

Or the whole stack in Docker:

```bash
docker compose up --build
```

**No API keys are needed.** With none configured the system runs on demo
providers and seeded evidence, and every affected result says so — a banner, a
`demo_mode` flag, and a badge on every citation. See
[`docs/adr/0008-provider-abstraction.md`](docs/adr/0008-provider-abstraction.md).

### Demo flow

1. `/where-next` → 12 nights, 3 regional, Tokyo in/out, food + onsen + nature,
   public transport only → Kyushu is ruled out with a stated reason; open the
   rubric on any card to see the arithmetic.
2. `/route-check` → "Use the example" → the over-stuffed Tohoku itinerary is
   criticised, with a costed alternative and what it costs you.
3. Any citation → expand for the passage, its type and its last-verified date.
4. `/admin` → the seeded source conflict about the last bus into Ginzan Onsen is
   waiting for a human. Resolve it and the blocked analysis re-runs.

### Environment

Every variable is documented in [`.env.example`](.env.example). The ones that
matter for a real deployment are listed in
[`docs/deployment.md`](docs/deployment.md).

## Technologies

**Backend** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2
**AI** LangChain · LangGraph · MCP · Anthropic / OpenAI adapters · pgvector
**Data** PostgreSQL 16 + pgvector · Redis
**Frontend** Next.js 15 · React 19 · TypeScript (strict) · Tailwind
**Quality** pytest · Vitest · Playwright · ruff · mypy · pre-commit
**Ops** Docker · GitHub Actions · Terraform · AWS ECS Fargate · OpenTelemetry

## Evals

Built **before** the AI logic was called finished, and they changed it.

```
retrieval    20/20   hybrid: recall@5 0.797  MRR 0.887  NDCG@8 0.813
tool         23/23   p50 20ms
security     19/19
rag           6/6    relevance 1.00  citations 1.00  grounded 1.00  unsupported 0
agent         8/8    p50 381ms  p95 570ms
production   12/12   p50 307ms  p95 350ms  5209 tokens/run
```

### The retrieval decision was measured, not assumed

| Strategy | Recall@5 | Precision@5 | MRR | NDCG@8 | Primary in top-5 |
| --- | --- | --- | --- | --- | --- |
| keyword only | 0.806 | 0.370 | 0.864 | 0.813 | 20/20 |
| vector only | 0.684 | 0.310 | 0.785 | 0.694 | 18/20 |
| **hybrid** | 0.797 | 0.370 | **0.887** | 0.813 | **20/20** |
| hybrid + reranking | 0.737 | 0.360 | 0.873 | 0.811 | 19/20 |

Three things came out of measuring rather than assuming, and all three changed
the code:

1. **Lexical search was silently broken.** PostgreSQL's `plainto_tsquery` ANDs
   every term, so "should I buy a rail pass for a single region" scored **zero
   against every document in the corpus**. ORing the terms took keyword MRR from
   0.665 to 0.864 and fixed all three previously-failing golden queries.
2. **The fusion weights were tuned against that broken retriever.** Re-sweeping
   moved `rrf_k` 60 → 5 and the dense weight 1.5 → 0.5.
3. **Reranking does not earn its place here.** It costs a case and adds latency
   for no gain. It stays implemented and configurable, but `hybrid` is the
   default. Reranking adds precision over a large candidate set; a few dozen
   chunks is not that.

Full report, including per-case ranks and where each retriever loses:
[`docs/evals/retrieval-comparison.md`](docs/evals/retrieval-comparison.md).

### What the evals caught

| Finding | Fix |
| --- | --- |
| `plainto_tsquery` ANDs terms — lexical search scored 0 on whole query classes | ORed terms; keyword MRR 0.665 → 0.864, 3 failing queries fixed |
| Fusion weights were tuned against the broken lexical retriever | re-swept: `rrf_k` 60 → 5, dense weight 1.5 → 0.5 |
| Reranking cost a case for no measurable gain | default strategy changed to `hybrid`; reranking kept configurable |
| The eval harness measured a different config from the sweep | `dense_weight` passed explicitly everywhere |
| A region weak at a stated interest outranked a balanced one | interest fit blends mean with minimum |
| A car-only hop was returned as an estimated train | provider returns the car option instead of inventing a service |
| Every analysis escalated to human review | escalation narrowed to what the answer depends on |
| A bare delimiter spoof passed the injection scan | critical patterns quarantine on a single match |
| A 14h return transfer for 2 nights passed | `MAX_TRANSIT_SHARE` 0.42 → 0.35 |
| Two hops firing one rule shared an explanation | narratives keyed per issue |

### What the dual-dialect and live-flow verification caught

The eval suites are green on things they measure. These are defects they did
*not* measure, found by running the whole suite against PostgreSQL and then
driving the real endpoints by hand.

| Finding | Fix |
| --- | --- |
| The suite had never actually run on PostgreSQL: a session-scoped asyncpg engine against pytest-asyncio's per-test loop failed 52 tests. SQLite has no socket, so it never showed | one session-scoped loop for fixtures *and* tests |
| Tests built their own engine, so SQLite skipped `PRAGMA foreign_keys` — the default leg silently accepted rows PostgreSQL rejects | tests use the application's `build_engine` |
| Free-text itinerary parsing understood only `Place N nights`. `2 nights Ginzan Onsen` and `Day 1-2 Sendai` extracted **zero stops**, so RouteCheck's headline input path silently produced nothing | leading-night and day-range forms; day→night inference is disclosed, not hidden |
| `fly home` became a stop, failed catalogue lookup, and dragged the itinerary below the two-stop floor | bare non-place words are dropped |
| **A route could report `high` confidence having checked nothing.** Under two resolvable stops nothing is costed and no rule runs, but the evidence was clean, so every guardrail passed | new guardrail **G7**: a check that could not run caps confidence at `low` |
| `Narnia` fuzzy-matched Tokyo's alias `narita` at 0.833 and was silently costed as a **Tokyo** stop | see below — the score cannot decide this, so the match *kind* does |
| An unresolved stop was reported as a staleness problem | its own `unresolved_stop` issue type |
| `unknowns` showed the same line twice — the critique prompt is handed them, and the model echoes them back | order-preserving dedupe on the way out |
| The E2E config defaulted to port 3010 while `scripts/dev.sh`, `.env.example`, the docs and CI all use 3000 — so the documented local flow (`dev.sh` then `make e2e`) hit an empty port, and CORS blocked the browser. CI passed only because it sets `E2E_BASE_URL` explicitly | Playwright defaults to 3000 like everything else |
| 30 browser tests back to back exceed the API's own 60-requests-per-minute limit, failing whichever test crossed the line — it read as a mobile-only bug and is latent flakiness in CI's E2E job | the E2E environment raises the limit; the limiter keeps its own unit tests |
| **The web container could never become healthy.** Docker sets `HOSTNAME` to the container id and Next's standalone server binds to whatever `HOSTNAME` says, so it listened on eth0 only and refused loopback. Every page served correctly through the published port, which is what hides it — anything gating on health (compose `depends_on`, an ECS/ALB target group) would have waited forever | `HOSTNAME=0.0.0.0` in the runtime stage |
| `docker-compose.yml` allowed only `http://localhost:3000` as a CORS origin while `.env.example` lists both spellings — reaching the compose stack on `127.0.0.1` failed every client-side call with nothing logged server-side | both origins, as in `.env.example` |

#### Why place matching gates on *kind*, not score

Measured on this catalogue, `Sendia`→`Sendai` (a typo that should be accepted)
and `Narnia`→`narita` (a different place entirely) **both score 0.833**. No
threshold separates them, so tuning the number cannot fix it.

Name equality and substring containment are trusted. An edit-distance-only match
is never a resolution — it is returned as a suggestion ("did you mean Tokyo?"),
the stop is excluded from costing exactly as an unknown name would be, and
confidence drops. The traveller decides, not the matcher.

```bash
make evals        # all suites
make evals-ci     # the fast subset CI runs
make sweep        # retrieval hyper-parameter sweep
```

## Testing

```bash
make test         # 231 backend tests, 80% coverage
make test-web     # 21 frontend unit tests
make e2e          # 15 end-to-end tests × 2 viewports
make lint         # ruff, mypy, tsc
```

Nothing internal is mocked. Tests run against a real database, real graphs and a
real MCP session; only outbound HTTP is faked. CI runs the whole backend suite
against **both** SQLite and PostgreSQL, because the offline path and the
production path must both keep working.

Both legs have now actually been run: 231 pass on PostgreSQL, 228 on SQLite
(3 durable-checkpoint tests need a real PostgreSQL and skip). That is worth
stating precisely, because for most of this project's life the PostgreSQL leg
had never executed — a session-scoped asyncpg engine against pytest-asyncio's
per-test event loop failed 52 tests the moment it did, and two real defects were
hiding behind that failure.

## Security

Four layers, because a prompt instruction is a mitigation and not a control:

1. **Ingestion allowlist** — https only, approved domains, no lookalikes, no
   private addresses, no crawling.
2. **Detection and neutralisation** — nine pattern families, four of which
   quarantine on a single match.
3. **Structural separation** — retrieved content only appears inside an explicit
   untrusted-data fence.
4. **Capability control** — the model never dispatches a tool. A graph node does,
   from a per-consumer allowlist. A successful injection during a RouteCheck
   cannot reach a write tool, because that consumer does not hold it.

The seeded corpus contains a **live injection canary** so the defence is
continuously exercised rather than assumed.

Full threat model, including what is *not* covered:
[`docs/security.md`](docs/security.md).

## Deployment

Docker for local; Terraform for AWS (ECS Fargate, RDS with pgvector,
ElastiCache, S3, Secrets Manager, CloudWatch). `terraform validate` passes.
Deliberately not Kubernetes — see
[`docs/adr/0010-aws-deployment.md`](docs/adr/0010-aws-deployment.md).

[`docs/deployment.md`](docs/deployment.md) covers configuration, migrations, the
deploy safety model, and how to switch from demo to live providers one capability
at a time.

## Repository layout

```
japan-second-trip/
├── backend/                FastAPI service — the whole product API
│   ├── src/jst_api/
│   │   ├── agents/         LangGraph graphs, nodes, state, guardrails
│   │   ├── knowledge/      retrieval, RAG, reranking, embeddings
│   │   ├── domain/         scoring, route rules, revisions — no I/O
│   │   ├── db/             models, migrations, repositories
│   │   ├── providers/      LLM, embeddings, places, transport adapters
│   │   ├── api/            routers and schemas
│   │   ├── security/       auth, rate limiting, injection defence
│   │   └── observability/  tracing, cost and latency
│   └── tests/              unit · integration · agents · security
├── frontend/               Next.js app — the two flows and the admin console
│   ├── src/app/            routes
│   ├── src/components/
│   └── tests/              unit (vitest) · e2e (playwright)
├── packages/               code both apps import
│   ├── shared_schemas/     the MCP tool contracts, one source of truth
│   └── travel_mcp/         the MCP server and session
├── docs/                   architecture, security, evals, 12 ADRs
├── evals/                  datasets, runners and reports
├── infra/                  Terraform for the AWS deployment
├── scripts/                dev.sh, check.sh, seed.py, deploy.sh
└── docker-compose.yml      db · redis · backend · frontend
```

`backend/` and `frontend/` are separate deployables that share only
`packages/`. The frontend never imports backend code, and the contracts between
them live in one place rather than being restated on each side.

## Documentation

| | |
| --- | --- |
| [architecture.md](docs/architecture.md) | how it fits together and why |
| [ai-engineering-skill-map.md](docs/ai-engineering-skill-map.md) | every capability, where it lives, how it is verified |
| [evals.md](docs/evals.md) | methodology and results |
| [evals/retrieval-comparison.md](docs/evals/retrieval-comparison.md) | the four-way comparison, generated |
| [security.md](docs/security.md) | threat model and defences |
| [data-model.md](docs/data-model.md) | 22 tables and the structured/RAG split |
| [mcp.md](docs/mcp.md) | the gateway and its three consumers |
| [deployment.md](docs/deployment.md) | local, Docker, AWS |
| [product-decisions.md](docs/product-decisions.md) | who it is for and what was left out |
| [adr/](docs/adr/) | 12 architecture decision records |

## Limitations

Stated plainly, because a portfolio project that claims completeness is not
credible.

- **The travel data is demo data.** Five regions, 50 places, 61 transport records,
  29 evidence documents — hand-authored approximations, labelled as such
  everywhere. Plausible, not verified. Do not book from it.
- **Durations are approximations, not timetables.** Real deployment needs a
  transport API or a licensed timetable feed.
- **Fit-score weights are judgement**, not fitted to satisfaction data. They are
  documented and swept, but nobody has validated them against a real traveller.
- **The demo embedder is a hashing vectoriser**, not a neural model. It gives
  genuine cosine separation and makes the offline eval meaningful, but a live
  embedder will change retrieval numbers — re-run the eval after switching.
- **Never tested with a real user.** Every product claim here is a hypothesis.
- **A genuine typo now needs confirming.** Refusing edit-distance matches means
  `Sendia` is offered back as "did you mean Sendai?" rather than corrected
  silently. That is the deliberate trade: no threshold separates that typo from
  `Narnia`→Tokyo, and silently costing a route through the wrong city is the
  worse failure. A real deployment should replace this with a geocoder that
  returns calibrated confidence.
- **Terraform has not been applied** against a live AWS account — it validates
  and plans, but no infrastructure has ever been created from it.
- **Retrieval numbers flatter lexical search.** The corpus is small and
  hand-authored, so its vocabulary overlaps the golden queries more than a
  scraped corpus would. Re-measure after switching to a real embedding provider.

## Roadmap

**Next** — a real transport data source; expand the golden set well beyond 20
queries so the comparison is not decided by noise; Stripe in test mode.

**Then** — more regions, added one at a time with verified evidence; a learned
reranker over retrieval, where relevance labels can genuinely come from
click-through; multi-language ingestion (the best sources are in Japanese).

**Not planned** — a chat interface, hotel and flight search, or a trained
destination ranker. Reasons in
[`docs/adr/0011-no-predictive-ml.md`](docs/adr/0011-no-predictive-ml.md) and
[`docs/product-decisions.md`](docs/product-decisions.md).
