# ADR 0004 — PostgreSQL + pgvector for both relational and vector data

**Status:** accepted · **Date:** 2026-09-06

## Context

The system stores relational travel data (regions, places, transport
constraints, trips, analyses, verification records) *and* vector embeddings for
evidence retrieval. Retrieval needs to filter on the relational data before
searching — region, place, topic, trust level, verification age, season — and
those filters are what keep retrieval quality high on a small corpus.

## Decision

One PostgreSQL database with the `pgvector` extension. Evidence chunks carry
their embedding in a `vector(384)` column alongside their metadata, indexed with
HNSW for cosine distance and GIN for `tsvector` full-text plus trigram.

Tests and the offline demo run the *same* SQLAlchemy models against SQLite, with
a dialect-aware `Vector` type. Where semantics genuinely differ — native pgvector
ANN vs NumPy cosine, `ts_rank_cd` vs Okapi BM25 — that difference is confined to
`db/repositories/evidence_repo.py`. Both dialects search the same `search_text`
column, and CI runs the whole suite against both.

## Alternatives considered

**A dedicated vector database (Pinecone, Weaviate, Qdrant).** Better ANN at
scale. Rejected: it splits the transaction boundary. Ingesting a source would
write metadata to PostgreSQL and vectors elsewhere, with no way to make that
atomic — so a partial failure leaves evidence that exists in one store and not
the other. Pre-filtering on region and verification date would also become a
two-phase dance instead of a `WHERE` clause. The corpus is thousands of chunks;
pgvector is not the bottleneck.

**PostgreSQL full-text only.** Rejected by measurement, not principle: the
retrieval eval shows lexical search alone reaches MRR 0.665 against 0.858 for
the tuned hybrid, and it misses every semantically-phrased query outright.

**Embeddings in SQLite for everything.** Rejected: no ANN index, no real FTS
ranking, and it would make the production path the untested one.

## Consequences

Good: one database, one backup, one transaction. Pre-filtering is a `WHERE`
clause. Local development needs no vector service.

Bad: pgvector at very large scale needs tuning that a purpose-built store gives
by default, and the SQLite fallback means two retrieval code paths — mitigated by
running the full suite against both dialects in CI.

The embedding dimension is fixed at the schema level. Changing it is a migration,
not a config flip, and the settings field says so.
