# AI engineering skill map

Where each capability is actually implemented, what product problem it solves,
why it was chosen, and how it is verified. No row says "library installed".

Every file path is real; every test name runs.

---

## Core software / AI backend

| Skill | Implementation | File / module | Product problem | Why this way | Verified by |
| --- | --- | --- | --- | --- | --- |
| **Python** | Async throughout, strict typing, domain/infra/API separation | `backend/src/jst_api/**` | — | 3.12 for `StrEnum`, `tomllib`, better generics | `ruff`, `mypy`, 165 tests |
| **FastAPI** | 26 endpoints, DI via `Depends`, typed error envelope, lifespan-built singletons | `api/v1/*.py`, `api/deps.py`, `api/errors.py`, `main.py` | Serve analyses, trips, evidence, admin | Async-native, Pydantic-native, OpenAPI for free | `tests/integration/test_api.py` (21 tests) |
| **Backend API design** | Resource-shaped REST, correct status codes, one error envelope, capability-token trip access | `api/v1/analyses.py`, `api/schemas.py` | A frontend and future clients | Wire contract separate from domain so each can change | `test_unknown_analysis_is_404`, `test_invalid_body_is_422_with_detail` |
| **LLM APIs** | Anthropic (`messages.parse`) and OpenAI adapters, plus a working demo provider; fallback wrapper | `providers/llm.py` | Parse itineraries, explain rankings | Two vendors so no single unavailable provider stops the product | `test_a_failing_primary_falls_back_and_is_flagged` |
| **Prompt engineering** | 6 versioned TOML prompts, shared safety preamble, versions stamped on every result | `prompts/registry.py`, `prompts/library/*.toml` | Consistent, auditable model behaviour | Files under version control so an eval regression maps to a prompt change | `GET /admin/prompts`; versions in every result payload |
| **Context engineering** | Injection quarantine → near-duplicate removal → token budget → audit record | `knowledge/context.py` | Fit the right evidence in a bounded window | Budget is scarce; duplicates bias by repetition | `TestContextAssembly` (6 tests) |
| **Structured outputs** | Every model-consumed result is a strict Pydantic schema; bounded repair | `domain/results.py`, `providers/llm.complete_with_repair` | Machine-usable model output | `extra="forbid"` catches drift at the boundary | `test_repair_is_attempted_once_then_gives_up` |

## Retrieval engineering

| Skill | Implementation | File / module | Product problem | Why this way | Verified by |
| --- | --- | --- | --- | --- | --- |
| **Embeddings** | Provider abstraction; deterministic hashing vectoriser + concept lexicon for demo, OpenAI live, cached by content hash | `providers/embeddings.py`, `knowledge/embeddings.py` | Semantic recall over travel prose | Demo embedder gives real cosine separation (0.33 vs 0.02), so offline evals mean something | `TestEmbeddings` (3 tests) |
| **PostgreSQL** | 22 tables, Alembic migrations, dialect-aware types, purposeful indexes | `db/models/*.py`, `db/migrations/versions/0001_initial_schema.py` | Trips, catalogue, evidence, runs, evals | One database, one transaction boundary | CI runs the suite on PostgreSQL and SQLite |
| **pgvector** | `vector(384)` column, HNSW cosine index, `CREATE EXTENSION` in the migration | `db/types.py`, `db/models/knowledge.py`, migration | Vector search beside relational data | Filter and search in one `WHERE` clause | verified on live PostgreSQL; `Vector.Comparator` |
| **Vector search** | `DenseRetriever` over pgvector `<=>`; NumPy cosine on SQLite | `knowledge/retrievers.py`, `db/repositories/evidence_repo.py` | "Effectively impossible without a car" | Semantic queries never match lexically | eval variant `vector`: MRR 0.785 |
| **Keyword / FTS search** | OR-composed `to_tsquery` scored by `ts_rank_cd` over a GIN `tsvector`, unioned with trigram; Okapi BM25 on SQLite | `evidence_repo._or_tsquery_text`, `_keyword_pg`, `_keyword_bm25` | "Ginzan Onsen", "Hanagasa Bus", "Kagayaki" | Proper nouns the English dictionary does not know; OR because `plainto_tsquery`'s AND scored 0 on whole query classes | eval variant `keyword`: MRR 0.864; `tests/unit/test_keyword_query.py` |
| **Hybrid retrieval** | RRF with swept `k` and dense weight, provenance preserved per document | `knowledge/fusion.py`, `HybridRetriever` | Both query shapes in one pipeline | Ranks only — the two score scales are incomparable | `TestFusion` (5 tests); production default, MRR 0.887, 20/20 |
| **Reranking** | `Reranker` protocol; heuristic (swept weights) and LLM, always with a fallback | `knowledge/rerank.py` | Precision on the handful that enter context | Implemented and configurable, but **measured and rejected as the default** — it costs a case on this corpus | eval: NDCG 0.813 → 0.811, 20/20 → 19/20 |
| **RAG** | LCEL pipeline: retrieve → assemble → prompt → structured output, citations preserved | `knowledge/rag.py` | Grounded operational answers | One pipeline for agents, evals and admin | `evals/runners/rag.py`: relevance 1.00, citations 1.00, grounded 1.00 |

## Agent engineering

| Skill | Implementation | File / module | Product problem | Why this way | Verified by |
| --- | --- | --- | --- | --- | --- |
| **LangChain** | Owns ingestion, chunking, embeddings, retrievers, LCEL composition | `knowledge/**` | The whole knowledge layer | Metadata propagation to citation is the hard part | `TestChunking`, `TestFusion`, RAG eval |
| **LangGraph** | Two `StateGraph`s, 12 and 14 nodes, typed state, conditional HITL branch, durable PostgreSQL checkpointer | `agents/*/graph.py`, `agents/common/checkpointing.py` | Stateful, inspectable, resumable workflows | Recorded node path; a first-class branch to human review; `interrupt()` survives a process boundary | `tests/agents/test_graphs.py`, `test_interrupt_resume.py`; agent eval asserts node progression |
| **MCP** | Real server, 14 typed tools, in-memory + stdio transports, `TravelBackend` port | `packages/travel_mcp/**`, `services/mcp_backend.py` | One capability definition for three consumers | Same code path in-process and over stdio | `tests/integration/test_mcp.py` (16 tests) |
| **Tool calling** | Typed schemas, per-consumer allowlist, budget, bounded retries, full tracing | `agents/common/tools.py`, `packages/shared_schemas/src/shared_schemas/tools.py` | Real facts instead of recalled ones | Validation at the protocol layer, before dispatch | tool eval 23/23; `TestPermissions` |
| **State management** | `TypedDict` state with reducers; runtime deps in `AgentContext`, never in state | `agents/common/state.py` | Checkpointable, testable workflows | State must stay serialisable | node-progression tests |
| **Persistent memory** | Structured trip memory — visited, candidate, rejections *with reasons*, decisions | `db/models/trips.py`, `services/trip_service.py`, `domain/trip.TripMemory` | Later analyses respect earlier decisions | Structured facts, never a chat transcript | `test_trip_memory_is_read_into_the_analysis`, `test_a_trip_remembers_decisions_across_analyses` |
| **Human in the loop** | Narrow escalation triggers; `interrupt()`/resume *and* durable resume by re-execution; resolution writes a verification record | `agents/*/nodes.make_human_review`, `services/review_service.py`, `agents/common/checkpointing.py` | Conflicting sources must not be guessed | Durable across restarts; a reviewer may answer days later | `test_hitl.py` (10 tests), `test_interrupt_resume.py` (6 tests) |

## Production AI engineering

| Skill | Implementation | File / module | Product problem | Why this way | Verified by |
| --- | --- | --- | --- | --- | --- |
| **Evals** | 6 suites, versioned datasets, IR metrics, persisted runs, generated comparison report | `evals/**`, `docs/evals/retrieval-comparison.md` | Prove it works; catch regressions | Built before the AI logic was called finished; found 5 real defects | `python -m evals.run all` — 85/89 cases |
| **Guardrails** | 7 checks: citations, unsupported claims, freshness, sufficiency, injection residue, demo labelling, analysis completeness | `agents/common/guardrails.py` | No evidence → no confident claim; **no analysis → no confident verdict** | Severity tied to whether the answer *leans on* the problem; G7 asks whether the answer was computed at all, not whether evidence backs it | `test_the_model_cannot_invent_a_route`; `test_completeness_guardrail.py`; RAG eval unsupported-claim count 0 |
| **AI security** | 4 defensive layers; capability control is the one that actually holds | `security/injection.py`, `security/allowlist.py`, `agents/common/tools.py` | Ingested pages and pasted text are hostile input | A prompt instruction is not a security control | `tests/security/` (37 tests); security eval 19/19 |
| **Prompt-injection defence** | Detection + neutralisation + data fencing + allowlisted capabilities; a live canary in the corpus | `security/injection.py`, `knowledge/context.py` | An injected page must not change behaviour | Layers, because any single one can be bypassed | `test_an_injected_itinerary_cannot_change_the_verdict`, `test_injection_cannot_reach_a_write_tool` |
| **Observability** | `RunTrace` per analysis: nodes, model calls, prompt versions, retrieval queries, evidence ids, tool calls, cost. OTel and Langfuse optional; PostgreSQL always | `observability/tracing.py`, `db/models/runs.py` | Answer "why did it say that?" | Tracing must not depend on a third-party account | `test_analysis_and_tool_calls_are_persisted_for_replay`; `/admin/runs/{id}` |
| **Cost monitoring** | Per-call token and cost accounting against a pricing table, aggregated per run | `providers/llm.estimate_cost_usd`, `observability/metrics.py` | Know what an analysis costs | Cost is a per-request property | production eval reports tokens/run; `/admin/metrics` |
| **Latency monitoring** | P50/P95/P99 reservoirs per surface, plus per-tool timing | `observability/metrics.py` | Find what is slow | Always-available floor, no backend required | production eval: p50 221 ms, p95 267 ms |
| **Caching** | `Cache` protocol; bounded LRU+TTL locally, Redis when configured, degrading | `core/cache.py` | Embeddings, retrieval, provider responses | Content-addressed keys; must never be unbounded | `TestCaching` (4 tests) |
| **Retries** | Bounded exponential backoff with jitter, transient errors only, plus a circuit breaker | `core/resilience.py` | Transient provider failures | An unbounded retry loop is an outage | `TestRetries` (4), `TestCircuitBreaker` (2) |
| **Fallbacks** | LLM secondary, reranker→fusion order, `call_optional` degradation, tracing→local logs | `providers/llm.FallbackLLMProvider`, `agents/common/tools.call_optional` | One dependency must not fail the request | Degrade the answer, not the request | `TestProviderDegradation` (2 tests) |

## Production software engineering

| Skill | Implementation | File / module | Product problem | Why this way | Verified by |
| --- | --- | --- | --- | --- | --- |
| **External API integration** | 6 provider protocols, live + demo adapters, timeouts, retries, caching, tracing | `providers/**` | Places, transport, weather, LLM, embeddings | Demo mode is first-class so nothing requires credentials | `TestTransportTools`; `/providers` discloses which is live |
| **Testing** | 182 backend, 21 frontend unit, 15 E2E × 2 viewports; both dialects in CI | `backend/tests/**`, `frontend/tests/**` | Confidence to change things | Real database, real graphs, real MCP — only HTTP is faked | `make test`, `make e2e` |
| **CI/CD** | Lint → types → tests (2 dialects) → security → CI evals → E2E → Docker → gated deploy | `.github/workflows/ci.yml`, `nightly-evals.yml` | Every gate green before deploy | CI runs a fast eval subset; the full suite is nightly | workflow definitions |
| **Docker** | Multi-stage, non-root, health-checked images for both apps; one-command compose | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | Reproducible environments | Entrypoint migrates and seeds, both idempotent | `docker compose up` |
| **AWS** | ECS Fargate, RDS+pgvector, ElastiCache, S3, Secrets Manager, CloudWatch — all Terraform | `infra/terraform/*.tf` | Deployable MVP | Fargate over Kubernetes for two services | `terraform validate` passes |
| **PII protection** | Redaction in logs and traces; free text sanitised; secrets never logged; PII excluded from cache keys | `core/logging.py`, `security/injection.py`, `domain/trip.digest_payload` | Traveller text is personal | Over-redaction destroys the trace, so structural ids survive | `TestRedaction` (4 tests) |
| **Latency optimisation** | Content-addressed caching, model routing, single model call per graph, bounded context | across | Fast and cheap enough to run | The cheapest call is the one not made | production eval |

---

## Where the evals changed the system

Evals that only confirm are decoration. These changed real code:

| Finding | Change |
| --- | --- |
| `plainto_tsquery` ANDs terms — lexical search scored 0 against *every* document on natural-language questions | ORed the terms; keyword MRR 0.665 → 0.864, retrieval 17/20 → 20/20 |
| Fusion weights had been tuned against that broken retriever | Re-swept: `rrf_k` 60 → 5, dense weight 1.5 → 0.5 |
| Reranking cost a case for no measurable gain | Default strategy changed to `hybrid`; reranking kept configurable |
| The eval harness measured different fusion parameters than the app used | `dense_weight` passed explicitly at every call site |
| A region weak at a stated interest still outranked a balanced one | Interest fit blends mean with minimum (`INTEREST_MIN_WEIGHT`) |
| A car-only hop was returned as an estimated train | `DemoTransportProvider` returns the car option instead of inventing a service |
| Every analysis escalated to human review | Escalation narrowed to conflicts and stale facts the answer actually depends on |
| A bare `<<<END_STRUCTURED_INPUT>>>` spoof scored 1 and passed | `CRITICAL_RULES` quarantine on a single match |
| A 14-hour return transfer for two nights passed | `MAX_TRANSIT_SHARE` 0.42 → 0.35 |
| Two hops firing the same rule shared one explanation | Narratives keyed per issue, not per rule |
