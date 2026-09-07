# Product decisions

## Who this is for

A repeat visitor to Japan. They have done Tokyo, Kyoto and Osaka. They are
capable, independent travellers who research properly — which is exactly why the
generic tools fail them: those tools answer questions they have already answered.

They are not asking "what is in Tohoku". They are asking "given eleven nights,
four of them regional, flying Tokyo in and out, in October, without a car — does
Tohoku actually work, or am I about to spend two days on trains?"

## Two products, one insight

**Where Next** reduces choice paralysis. The difficulty is not discovering that
Tohoku exists; it is knowing which region fits *this* trip.

**RouteCheck** is the stronger transactional pain. Someone with a drafted
itinerary has already invested; telling them it will not work — and why, and what
to change — has immediate value.

Both rest on the same insight: **the constraint is the trip, not the
destination.** Kyushu is superb and wrong for three nights out of Tokyo. Nothing
about Kyushu changes; the trip does.

## Decisions worth defending

**The product says no.** "Not recommended for this trip" is a first-class result
with its own section, not a low-ranked card. A recommender that only recommends
is a brochure.

**Negative information is not hidden.** Trade-offs sit beside reasons, at the
same weight. Confidence, assumptions, unknowns and demo-data labels are shown,
not buried in a tooltip.

**The score is inspectable.** Any traveller can open the rubric and see the
arithmetic: component, value, weight, points, and the sentence explaining it.
A number nobody can interrogate is a number nobody should trust.

**"Verified" always carries a date.** Never a bare badge. Stale critical evidence
says so. The freshness clock is per-topic, because a bus time ages faster than a
description of a region.

**Demo data is labelled everywhere.** A product whose entire claim is
verification cannot be coy about the provenance of its own answers.

**A critique says what is working.** A route check that only lists problems is a
complaint. The strengths section exists so the traveller knows what to keep.

**No booking, ever.** The system recommends and verifies. It cannot book, pay or
contact anyone, and the MCP gateway says so in its own instructions.

## What was deliberately not built

**A chat interface.** The obvious thing to build, and wrong. These are structured
decisions with structured inputs. A form that takes eight fields and returns a
ranked comparison respects the user's time more than a conversation that
extracts the same eight fields one message at a time.

**Nationwide coverage.** Five regions, properly. Fifty regions of shallow data
would look more impressive and be less useful — and would make the verification
claim impossible to honour.

**Hotel and flight search.** Solved, competitive, and not the problem.

**A generic itinerary generator.** The market is saturated with them and they are
all wrong in the same way: they produce plausible itineraries with invented
travel times.

**Personalised recommendations from behaviour.** No data, no labels, and cold
start is the whole product. See `docs/adr/0011-no-predictive-ml.md`.

## Pricing hypothesis

| Plan | Price | Rationale |
| --- | --- | --- |
| Where Next preview | free | the decision is the hook; enough to be genuinely useful |
| Verified Regional Route | A$59 | one-off, against a trip costing thousands |
| RouteCheck | A$129 | the stronger pain — the traveller has already invested and wants to know if it holds |

Configurable server-side (`PRICE_*`), because these are hypotheses under test,
not constants. Payment is not wired up in demo mode, and no part of the system
performs a payment action autonomously.

## What would need to be true

- repeat visitors will pay to be told *not* to do something;
- verification is a durable differentiator as generic AI planners improve;
- a curated corpus can be maintained at a cost the pricing supports.

The third is the real risk. It is why the admin verification workflow, the
freshness policy and the source-change detection exist in the MVP rather than
being deferred: if maintaining verified evidence is not tractable, the product
does not work, and that should be discovered early.

## Honest limitations

- Five seeded regions with hand-authored demo data — not a verified dataset.
- Transport durations are approximations, not timetables.
- Fit-score weights are judgement, not fitted to satisfaction data.
- Never tested with a real traveller. Everything above is a hypothesis.
