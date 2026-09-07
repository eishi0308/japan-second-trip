# ADR 0005 — Hybrid retrieval, tuned by measurement

**Status:** accepted · **Date:** 2026-09-06

## Context

Queries in this domain come in two shapes that fail for opposite reasons.

*Exact proper nouns* — "Ginzan Onsen", "Oishida", "Hanagasa Bus", "Kagayaki",
"Chichu Art Museum". An embedding blurs these; several are absent from any
English dictionary a stemmer knows.

*Semantic descriptions* — "effectively impossible without a car", "awkward with a
big suitcase", "somewhere closed for part of the year". The source text never
uses those words. Keyword search returns nothing useful.

## Decision

Run both, fuse with Reciprocal Rank Fusion, then rerank.

RRF was chosen over score normalisation because the two scales are
incomparable — cosine similarity in [-1, 1] against unbounded `ts_rank_cd`/BM25.
RRF consumes only *ranks*, so no min-max heuristic is needed and the result is
reproducible.

**The parameters were measured, not assumed — and measuring found a bug.**

The first sweep produced `k = 10` and a dense weight of 1.5, because at the
paper's `k = 60` hybrid scored *worse* than pure vector: `1/61` and `1/67` are
nearly identical, so an uninformative lexical result could outvote a confident
dense one.

Then a diagnosis of the three still-failing golden queries found the real
problem. PostgreSQL's `plainto_tsquery` **ANDs every term**. The query "should I
buy a rail pass for a single region" became `buy & rail & pass & singl & region`,
and because no document contained all five words, `ts_rank_cd` returned **zero
for every document in the corpus**. Lexical search was contributing nothing at
all to an entire query class, and the fusion weights had been tuned to compensate
for a retriever that was broken rather than weak.

ORing the terms fixed it, and everything downstream had to be re-measured:

| Strategy | Recall@5 | MRR | NDCG@8 | Primary in top-5 |
| --- | --- | --- | --- | --- |
| keyword | 0.806 | 0.864 | 0.813 | 20/20 |
| vector | 0.684 | 0.785 | 0.694 | 18/20 |
| **hybrid** | 0.797 | **0.887** | 0.813 | **20/20** |
| hybrid + rerank | 0.737 | 0.873 | 0.811 | 19/20 |

`rrf_k` moved 10 → 5 and the dense weight 1.5 → 0.5, because the lexical
retriever is now the stronger signal on this corpus. Full per-case detail is in
`docs/evals/retrieval-comparison.md`.

## Alternatives considered

**Vector only.** Simpler and genuinely competitive — it beat untuned hybrid.
Rejected on the lexical cases: it puts the Ginzan access page third for a query
naming the bus operator, and lexical search puts it first.

**Score normalisation instead of RRF.** Rejected: min-max normalisation over a
small result set is unstable, and the normalising constants become another
untuned hyper-parameter.

**Reranking as an obvious win.** Not assumed, and ultimately **rejected as the
default**. Even at its best swept weighting it moves NDCG@8 by −0.002 and loses a
case, for extra latency and — in its LLM form — a model call. It stays
implemented and configurable (`RETRIEVAL_STRATEGY=hybrid_rerank`), because
reranking earns its place by adding precision over a *large* candidate set and a
few dozen chunks is not that. This should be re-evaluated as the corpus grows.

**Keyword only.** Genuinely competitive after the fix — tied with hybrid on
NDCG@8 (0.8134 vs 0.8130, well inside noise) and on primary-in-top-5. Hybrid was
chosen on MRR (0.887 vs 0.864), which is a real difference: it places the right
source higher. If the corpus stayed this small and this hand-authored, dropping
to keyword-only would be a defensible simplification.

## Consequences

Good: measured, reproducible, and the per-class table shows *where* each
retriever earns its place rather than an average that hides it. The measurement
also caught a silent lexical-search failure that no amount of code review had.

Bad: two searches per query (~22 ms vs ~7 ms for vector alone) and two more
parameters to keep honest. The sweep runs nightly so drift is visible.

Honest caveat: 20 golden queries over a few dozen hand-authored chunks is a small
basis for a production default, and the corpus's vocabulary overlaps the queries
more than a scraped one would — which flatters lexical search. The conclusion
here is "measure again after the embedding provider and the corpus change", not
"hybrid is universally best".
