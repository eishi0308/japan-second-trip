# Data model

22 tables in one PostgreSQL database. The organising decision is the split
between **structured facts** and **retrievable prose** — see
`docs/adr/0005-hybrid-search.md`.

## Catalogue — structured facts

Queried with SQL, never through vector search, because the deterministic rules
depend on them being exact.

| Table | Holds | Why structured |
| --- | --- | --- |
| `regions` | gateway access hours, night ranges, transport score, interest strengths, seasonal profile, booking complexity | every one is an input to the fit rubric; in a vector index the score would be unreproducible |
| `places` | coordinates, aliases, region, station, stay length, step-free | coordinates drive the backtracking rule; aliases drive resolution |
| `transport_constraints` | duration, transfers, distance, `requires_car`, `last_departure_local`, `final_leg_minutes`, operator, `verified_at` | the single most safety-critical number in the product |
| `booking_constraints` | lead time, English availability, closed months/weekdays, deposit | deterministic checks need exact comparisons |

`last_departure_local` + `final_leg_minutes` are what let rule `R06` work out
whether a traveller makes the last bus of the day.

## Knowledge — the RAG side

| Table | Holds | Notes |
| --- | --- | --- |
| `sources` | url, domain, type, official flag, trust level, `fetched_at`, `verified_at`, `freshness_ttl_days`, `content_hash`, status | `content_hash` is how source-change detection works |
| `source_documents` | raw + cleaned content, metadata, chunk count | the raw text is kept so a chunking change can be replayed without re-fetching |
| `evidence_chunks` | content, `search_text`, `vector(384)` embedding, region, place, topic, transport mode, season months, trust, `verified_at` | both retrieval signals over the same row |
| `verification_records` | subject, field, value, `verified_at`, `verified_by`, method, confidence, status | superseded rather than overwritten — the history of what was believed |

Indexes on `evidence_chunks`:

- `hnsw (embedding vector_cosine_ops)` — dense ANN
- `gin (to_tsvector('english', search_text))` — full-text
- `gin (search_text gin_trgm_ops)` — trigram, for proper nouns the dictionary
  does not know
- btree on `region_code`, `place_slug`, `topic`, and a composite on
  `(region_code, topic)` — the pre-filter path

## Trips — persistent memory

| Table | Holds |
| --- | --- |
| `users` | optional; travellers are anonymous by default |
| `trips` | dates, nights, gateways, preferences, current candidate, verified warnings, decision log |
| `visited_places` | travel history, used for novelty scoring |
| `candidate_regions` | per-trip status (`considered`/`shortlisted`/`selected`/`rejected`) with the reason and score |
| `routes`, `route_segments` | stored itineraries with their costed segments |

A traveller's explicit rejection outranks a later automated shortlisting — a
guard in `TripService._upsert_candidate`, so the system cannot quietly
re-recommend something they ruled out.

## Runs — observability and HITL

| Table | Holds |
| --- | --- |
| `analyses` | input, result, status, confidence, evidence ids, prompt versions |
| `agent_runs` | graph, thread, **node path**, steps, latency, tokens, cost, retries, fallbacks, trace id |
| `tool_calls` | tool, node, transport (`mcp`/`local`), redacted arguments, result summary, ok, latency, attempts, cache hit |
| `human_review_tasks` | reason, subject, question, candidate values, evidence, status, resolution, `resumed` |
| `feedback` | rating, helpfulness, comment, reported inaccuracy |

`agent_runs.node_path` is what the agent eval asserts on: a node that stops
running is a test failure, not a silent change.

## Evals

`eval_cases`, `eval_runs`, `eval_results` — runs carry the git SHA, the dataset
version, the prompt versions and the retrieval variant, so a metric change can be
attributed rather than guessed at. The admin console reads these.

## Portability

The same models run on SQLite for tests and offline demos. `db/types.py` provides
a dialect-aware `Vector` (pgvector column vs JSON text) and `JSONBCompat`
(`jsonb` vs `json`). Retrieval semantics differ by necessity and that difference
is confined to `db/repositories/evidence_repo.py`. CI runs the whole suite
against both dialects so neither path rots.
