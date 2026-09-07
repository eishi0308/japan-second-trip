# Evals

Evals were built before the AI logic was called finished, and they changed it.
Eight defects below came from these suites, not from reading the code.

```bash
python -m evals.run all         # every suite
python -m evals.run ci          # the fast subset CI runs on every PR
python -m evals.run retrieval   # one suite
python -m evals.runners.sweep   # retrieval hyper-parameter sweep
```

Every suite runs on **demo providers** so results are reproducible on any
machine, including CI with no credentials. Runs persist to `eval_runs` with the
git SHA, dataset version, prompt versions and retrieval variant, so a metric
change can be attributed rather than guessed at.

## Suites

| Suite | Cases | Measures |
| --- | --- | --- |
| retrieval | 20 × 4 strategies | Recall@K, Precision@K, MRR, NDCG@8, latency, by query class |
| rag | 6 | evidence relevance, citation correctness, groundedness, unsupported-claim rate, refusal correctness |
| tool | 23 | argument validity, output shape, permissions, budget enforcement, recovery |
| agent | 8 | node progression, rule firing, candidate rejection, revision quality, escalation, budgets |
| security | 19 | injection detection and quarantine, false positives, allowlist, PII redaction, capability control |
| production | 12 | P50/P95/P99 latency, tokens, cost, retries, fallbacks, cache hit rate |

## Latest measured results

```
retrieval    20/20   hybrid: recall@5 0.797  MRR 0.887  NDCG@8 0.813  p50 22ms
tool         23/23   p50 20ms
security     19/19
rag           6/6    relevance 1.00  citations 1.00  grounded 1.00  unsupported 0
agent         8/8    p50 381ms  p95 570ms  12.5 nodes  13.5 tool calls
production   12/12   p50 307ms  p95 350ms  5209 tokens/run
```

Retrieval reached 20/20 only after the eval exposed a real bug in lexical search
(below). It sat at 17/20 for most of the build, and the three failures were kept
red rather than removed, because they were the ones worth fixing.

## Retrieval methodology

Relevance is authored against **source titles**, not evidence ids, so the dataset
survives re-seeding. Cases are labelled `lexical`, `semantic` or `mixed`, and the
report breaks metrics down by class — the headline average hides *where* each
retriever earns its place, which is the entire argument for fusing them.

NDCG uses graded relevance with the designated primary source weighted 2: several
sources can be relevant to "which places need a car", but exactly one is the
passage the traveller needed, and burying it below three near-misses is worse
than the flat metric suggests.

A case passes when the primary source appears in the **top five** — the practical
bar for "the traveller would have seen it".

Full comparison: `docs/evals/retrieval-comparison.md`.

## RAG methodology

Deterministic wherever possible, because these dimensions have exact answers:

- **evidence relevance** — did retrieval return the source the question needs?
- **citation correctness** — does every cited id exist in the retrieval set?
- **groundedness** — does the answer assert times/prices/dates that appear in no
  evidence and no deterministic signal?
- **structured-output validity** — did the model return a schema-valid object?
- **refusal correctness** — for questions the corpus cannot answer, does the
  system decline rather than invent? Two cases exist purely to test this
  ("exact 2027 shinkansen fares", "visitor numbers for Yamadera").

An LLM judge is deliberately **not** used for these. Where a judge is used, the
judge model and prompt version are stored with the score, because one LLM judge
is not truth.

## Agent methodology

Asserts on the checkable parts of a run, not on prose: which nodes executed,
which rules fired at which severity, which region was rejected and for what
stated constraint, whether the revision reduces transit, whether budgets held,
whether an unresolvable stop degrades instead of crashing, and whether a
conflicting fact escalates instead of being resolved.

The suite establishes its own fixtures — it re-opens the seeded conflict — because
an eval that silently passes because a fixture disappeared is worse than no eval.

## Security methodology

Asserts specific properties, and equally that ordinary travel prose is **not**
flagged: a scanner with false positives is a scanner that gets switched off. The
seeded corpus contains a live injection canary, so the defence is exercised on
every run rather than assumed.

## What the evals actually caught

| Finding | Fix |
| --- | --- |
| `plainto_tsquery` ANDs every term, so lexical search returned `ts_rank_cd = 0` for *every* document on natural-language questions | ORed the terms; keyword MRR 0.665 → 0.864 and all three failing golden queries fixed |
| Fusion weights had been tuned against that crippled lexical retriever | re-swept: `rrf_k` 60 → 5, dense weight 1.5 → 0.5 |
| Reranking cost a case and added latency for no gain | default strategy changed to `hybrid`; reranking stays implemented and configurable |
| The eval harness passed different fusion parameters than the app used | `dense_weight` passed explicitly at every call site |
| A region weak at a stated interest outranked a balanced one | interest fit blends mean with minimum |
| A car-only hop was returned as an estimated train | provider returns the car option instead of inventing a service |
| Every analysis escalated to human review | escalation narrowed to what the answer depends on |
| A bare delimiter spoof scored 1 and passed | critical patterns quarantine on a single match |
| A 14h return transfer for 2 nights passed the hard constraint | `MAX_TRANSIT_SHARE` 0.42 → 0.35 |
| Two hops firing one rule shared an explanation | narratives keyed per issue |

## CI

The `ci` subset (retrieval, tool, security, rag) runs on every pull request —
fast, deterministic, no network. The full suite plus the hyper-parameter sweep
runs nightly and opens an issue on regression rather than blocking a merge: an
eval regression is information, and the branch it came from has already landed.
