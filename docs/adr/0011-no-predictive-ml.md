# ADR 0011 — No trained models, and why that is the right call

**Status:** accepted · **Date:** 2026-09-06

## Context

"Recommend a destination" sounds like a ranking problem, and ranking problems
invite a learned model. It is worth writing down why one would be wrong here
rather than merely absent.

## Decision

No model training, fine-tuning, or predictive statistical modelling. Foundation
models are used through APIs, for language tasks only.

## Why a trained ranker would be wrong, not just unnecessary

**There is no label.** Supervised ranking needs ground truth about which region
someone *should* have chosen. That does not exist. Booking data would encode what
was marketed, not what fitted.

**Cold start is the whole product.** The target user is a repeat visitor
planning an unusual trip. There is no interaction history for the exact
combination of dates, nights, gateway and constraints that makes their trip
specific — which is precisely the thing the answer must turn on.

**The constraints are known, not learned.** "Four nights cannot absorb a
ten-hour return transfer" is arithmetic. A model would have to *rediscover* it
from data, approximately, and could then violate it on an unusual input.

**Explainability is the product.** A traveller pays to be told *why* Kyushu is
wrong for this trip. A learned score cannot say. The rubric can, component by
component, and the UI shows the arithmetic.

**Wrong is expensive and rare.** Someone takes this trip once. A ranker that is
right 85% of the time is a poor trade against a rubric that is inspectable and
correctable.

## What is used instead

A documented weighted rubric with hard constraints (`domain/scoring.py`), a rules
engine (`domain/route_rules.py`), foundation models for parsing and explanation,
and hybrid retrieval for grounded evidence.

Deterministic statistics *are* used, extensively: IR metrics, RRF, BM25, cosine
similarity, latency percentiles, cost accounting. Statistics for measurement is
not the same as a learned predictor.

## When this should be revisited

With real usage: a learned reranker over retrieval (there, relevance labels can
come from click-through and feedback) and a calibration model over rubric weights
fitted to satisfaction data. Both would sit *inside* the deterministic frame, not
replace it. Neither is justified before the data exists.

## Consequences

Good: no training pipeline, no serving infrastructure, no drift, no cold start,
fully explainable, reproducible.

Bad: rubric weights are judgement rather than fit-to-data, and adding a region
means authoring its profile by hand. Both are the right trade at this scale, and
the eval suite is where the weights get challenged.
