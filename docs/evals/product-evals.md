# Product evals (M6)

`python -m evals.run product`. Part of the CI subset (`python -m evals.run ci`).

The other suites measure the AI machinery. This one measures the promises the
product makes to a traveller (PRODUCT_AMENDMENTS.md §11, M6). Every case goes
through the real API on the real seeded catalogue. The suite seeds its own
throwaway SQLite database, so it needs no database server. Set
`PRODUCT_EVAL_DATABASE_URL` to point it at another database instead.

Dataset: [`evals/datasets/product_v1.json`](../../evals/datasets/product_v1.json),
with 14 Where Next requests (both hero demos, other months, cities, driving,
kids and limited walking, must-include places, undecided nights, a 2-night and a
10-night trip, December Hokkaido, an August coast drive) and 6 RouteChecks (the
Ginzan hero, a late start, two trips with two pins, an unknown place, a pinned
place closed in winter). Report: `evals/reports/product.json`.

## What is checked

| Property | Rule | Result |
| --- | --- | --- |
| Option diversity | 3 options as Classic / Unexpected / Slow-paced; no unpinned place shared between two options | 1.00 |
| Rejection correctness | an area under "Not for this trip" has no option in it and gives a reason | 1.00 |
| Counterfactuals honoured | apply each "if you change X" to the request and plan again: a note saying the area "becomes" an option must put it in the options; a "fits too" note must at least stop it being ruled out for that reason | 27/27 |
| Pinned-stop preservation | must-include places are pinned in every option; no fix, in any option or RouteCheck, drops a pinned stop | 1.00 |
| No uncited operational facts | every warning or critical issue has evidence with a source; verified or stale evidence is dated; fragile issues name their fact; a fact being checked never shows its conflicting values; every booking deadline has dated evidence; "no verified info yet" never states a time | 1.00 (74 claims) |

The suite fails if any case fails, or if any counterfactual is not honoured.

## What it caught

The first run failed: Nyuto Onsen's ryokan pick-up record has never been
verified and has no source, yet it produced a "must be booked" item under "To
book ahead". A booking deadline is an operational claim, so the checker now
makes booking items only from dated evidence
(`planner/feasibility.py`, `_booking`; unit test
`test_an_unverified_booking_note_gives_no_booking_deadline`).

## Counterfactual promises (M7)

The first M6 run showed that after applying an "if you change X" note, the
area appeared in the three options only 6 times in 18, although every note
said it "becomes a possible option". The engine now re-plans with the change
before making that promise, tries every candidate change first (flying out of,
more nights, flying into and out of), and otherwise says the area "fits too,
though other areas would still rank higher".

The suite now fails if any "becomes an option" note does not put the area in
the options. Result: 18/18 notes honoured, and 14/18 (0.78, up from 0.33) now
promise and deliver an option.

## Hero demos as browser tests

[`frontend/tests/e2e/hero-demo.spec.ts`](../../frontend/tests/e2e/hero-demo.spec.ts)
runs both hero demos from §10 in a real browser against the real API, on
desktop and mobile viewports:

1. Plan (January, 4 nights, Tokyo in/out, no car, onsen + snow + food): three
   options in character order, Kyushu ruled out with "If you can fly out of
   Fukuoka", compare plus a what-if toggle, day-by-day timeline (5 days) with
   dated evidence, pin and swap re-run the check, save, then open the read-only
   share link.
2. RouteCheck on "Tokyo 3N, Sendai 1N, Ginzan Onsen 1N, Aomori 1N, Hakodate 1N,
   Tokyo" with Ginzan pinned: fixes are applied one by one and Ginzan stays
   pinned and cannot be removed.
3. The vague user: season choice, then nights choice, then three options with
   "Assumed: Tokyo in/out"; "Not for me" regenerates the options.

[`frontend/tests/e2e/review-loop.spec.ts`](../../frontend/tests/e2e/review-loop.spec.ts)
runs the M5 review loop the same way: a trip through Ginzan Onsen is saved
while its last bus is "Being checked"; an admin confirms 17:00 with a source in
`/admin`; the owner's trip and the share link both show the update. It runs
once (desktop only) and needs a freshly seeded database, as CI has.

Run with both servers up: `cd frontend && E2E_ADMIN_TOKEN=<the API's ADMIN_TOKEN> npx playwright test`.
