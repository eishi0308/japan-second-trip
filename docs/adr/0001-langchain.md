# ADR 0001 — LangChain owns the knowledge and retrieval layer

**Status:** accepted · **Date:** 2026-09-06

## Context

The product's credibility rests on grounded evidence: access caveats, booking
mechanics and operational notes that resist normalising into columns. That needs
a real ingestion and retrieval pipeline — loading, cleaning, chunking with
metadata, embedding, dense and lexical retrieval, fusion, reranking, context
assembly — not a vector-store call with a prompt around it.

## Decision

LangChain owns that layer, in production, not as a wrapper:

- `Embeddings` — `knowledge/embeddings.py` adapts the provider abstraction to
  LangChain's interface, so everything downstream depends on LangChain rather
  than a vendor.
- `BaseRetriever` — `DenseRetriever`, `KeywordRetriever` and `HybridRetriever`
  in `knowledge/retrievers.py` are real subclasses returning `Document` objects
  whose metadata carries evidence id, source id, trust level and verification
  date all the way to the citation in the UI.
- Text splitters — `RecursiveCharacterTextSplitter` inside a heading-aware
  pre-split, so an "Access" section and a "Booking" section never share a chunk.
- `Document` — the unit passed between loaders, chunker, retrievers, reranker
  and context assembler.
- LCEL — `knowledge/rag.py` composes retrieve → assemble → prompt → structured
  output as runnables, so the same pipeline serves the agents, the evals and the
  admin assistant instead of three hand-rolled copies.

## Alternatives considered

**Hand-rolled retrieval.** Fewer dependencies, and for a single retriever it
would be less code. Rejected because the pipeline is genuinely multi-stage, and
because `Document` metadata propagation is exactly the part that is tedious and
easy to get subtly wrong — a citation that loses its evidence id is a citation
that cannot be audited.

**LlamaIndex.** A reasonable fit for the RAG half. Rejected for consistency: the
orchestration layer is LangGraph, and one ecosystem across both means one
`Document` shape and one callback surface.

## Consequences

Good: composable pipeline, one abstraction across retrievers, easy to add a
retriever or swap an embedding provider.

Bad: a large dependency for the subset used, and LangChain's sync/async split
required an explicit decision — the retrievers are async-only and raise on the
sync entry point rather than bridging with `asyncio.run`, which would deadlock
inside the running loop.

`langchain-community` was deliberately dropped: it is sunset, and the only thing
needed from it was a document loader that is ~40 lines to write directly.
