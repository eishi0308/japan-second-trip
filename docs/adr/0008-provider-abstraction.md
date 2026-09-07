# ADR 0008 — Every external capability behind an interface, with a demo adapter

**Status:** accepted · **Date:** 2026-09-06

## Context

The system depends on LLMs, embeddings, place resolution, transport routing and
weather. A portfolio project that only runs with five paid API keys cannot be
demonstrated, cannot be tested in CI, and cannot be evaluated reproducibly.

## Decision

Six protocols — `LLMProvider`, `EmbeddingProvider`, `PlaceProvider`,
`TransportProvider`, `WeatherProvider`, `Reranker` — each with a live adapter and
a **demo adapter that genuinely works**:

- `DemoEmbeddingProvider` — a deterministic hashing vectoriser (signed feature
  hashing over word unigrams, bigrams and character 4-grams, sub-linear TF, L2
  normalised) plus a small hand-authored travel concept lexicon. Not a neural
  embedding and never presented as one, but it produces real cosine similarity
  (0.33 related vs 0.02 unrelated), which is what makes the offline retrieval
  benchmark meaningful rather than decorative.
- `DemoLLMProvider` — reads the machine-readable block every prompt carries and
  composes a schema-valid object. A real model reads the same block as data.
- Demo place/transport/weather — the seeded catalogue, with geometric estimates
  as a clearly-labelled fallback.

Demo mode is a **first-class supported state**, not a stub: `demo_mode` on every
result, `is_demo` on every source, a banner and per-citation badges in the UI.

## Alternatives considered

**Mocks in tests only.** Rejected: it makes the demo path untested and the
demonstration impossible without credentials.

**Record/replay fixtures.** Good for adapter tests, useless for the evals, which
need to run on queries that were never recorded.

**One provider, no abstraction.** Rejected: an outage or a key rotation would
take the product down, and the fallback chain would have nowhere to go.

## Consequences

Good: `git clone && make dev` produces a fully working system. CI needs no
secrets. Evals are reproducible on any machine. Adding a provider is one class.

Bad: two implementations per capability to maintain, and demo results are not
real travel advice — which is why they are labelled everywhere rather than
quietly presented as fact.
