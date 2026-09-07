# ADR 0012 — A fuzzy place match is a suggestion, never a resolution

**Status:** accepted · **Date:** 2026-09-07

## Context

Travellers type place names loosely: abbreviations, half-remembered spellings,
station names instead of towns. Resolution has to be forgiving, because a stop
that fails to resolve is excluded from every transport and rule check and the
critique gets thinner.

So the demo catalogue provider scored each candidate — name equality, substring
containment, then `difflib` edit distance — and accepted the best above `0.72`.

That silently produced a wrong answer. `Narnia` is not a place in Japan, but it
scores **0.833** against Tokyo's alias `narita`, cleared the bar, and became a
**Tokyo** stop: costed with real shinkansen durations, folded into the travel-load
maths, and shown as a resolved leg of a route through a city the traveller never
named. This is precisely the failure the product exists to prevent, committed by
the product itself.

The obvious fix — raise the threshold — does not work. Measured on this
catalogue:

| Query | Candidate | Score | Should it match? |
| --- | --- | --- | --- |
| `Sendia` | `Sendai` | 0.833 | yes — an ordinary typo |
| `Narnia` | `narita` | 0.833 | **no** — a different place entirely |
| `Nagaon` | `Nagano` | 0.833 | yes |
| `Hakone` | `Hakodate` | 0.714 | no |
| `Kanazawa city` | `Kanazawa` | 0.762 | yes |

The distributions overlap exactly. No threshold separates a typo from a
coincidence, because edit distance does not model the thing that matters.

## Decision

Gate on the **kind** of match, not its score. The provider reports `match_kind`
alongside `confidence`, and it travels through the MCP contract:

* `exact` — the query equals a name, slug or alias. Trusted.
* `contains` — one string contains the other (`Kanazawa city` → `Kanazawa`).
  Trusted.
* `fuzzy` — edit distance only. **Never trusted.**

A `fuzzy` match is returned to the caller but is not accepted as the stop.
RouteCheck treats it exactly as it treats a name it has never seen: the stop is
excluded from transport and rule checks, listed in `unresolved_places`, and the
near miss is offered back as a question — *"Did you mean 'Narnia' → Tokyo?"* —
in the R23 issue the traveller actually reads. Guardrail G7 then caps confidence,
because a route with an unchecked stop has not been fully checked.

Kind outranks score when picking the best candidate, so a trusted `contains`
match on the right place is never shadowed by a higher-scoring `fuzzy` match on
a different one.

## Consequences

**The cost is real and accepted.** `Sendia` is no longer silently corrected to
`Sendai`; it comes back as "did you mean Sendai?" and needs one confirmation.
That is worse for a fast-typing user and better for a correct one. Given the
choice between an extra click and a confidently costed route through the wrong
city, the product's whole thesis picks the click.

**It generalises past this provider.** A real geocoder returns calibrated
confidence and its own notion of match quality; the gate becomes "trust what the
geocoder calls a confident match", and the policy — *refuse rather than guess,
and show the guess you refused* — is unchanged.

## Alternatives considered

**Raise the threshold.** Rejected on measurement: `0.85` would drop `Sendia`,
`Nagaon` and `Kanazawa city` while `Narnia`→`narita` at 0.833 still needs
rejecting. No value works.

**Require a margin over the runner-up.** Plausible — `Narnia` beats its second
candidate by only 0.106 — but still a heuristic over the same weak signal, and
there is no labelled set here to tune or validate a margin against. Untuned
heuristics presented as safety are worse than an honest refusal.

**Accept the match and lower confidence.** Rejected: the stop would still be
costed, so the travel-load numbers, the segment rules and the proposed fixes
would all be computed for the wrong city. A confidence label does not undo a
wrong route; it just apologises for it.

**Ask the model to adjudicate.** Rejected under
[ADR 0006](0006-deterministic-rules.md): resolution decides what gets costed, so
it belongs in deterministic code, and an LLM guessing at place identity is the
same failure with more steps.

## Evidence

`apps/api/tests/integration/test_place_resolution.py` pins all of it: the match
kinds, the refusal, the suggestion reaching the user, the real stops still being
analysed, and — guarding against over-correction — that aliases and substrings
still resolve.
