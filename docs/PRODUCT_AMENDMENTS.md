# Product Amendments — Japan Second Trip (v2)

Read docs/SPEC.md (the original master build prompt) and this file.
Keep every technical requirement in SPEC.md (stack, LangChain, LangGraph, MCP,
hybrid retrieval, evals, security, observability, Docker, CI/CD, AWS).
This file changes the PRODUCT, USER EXPERIENCE and v1 SCOPE.
If this file and SPEC.md conflict on product or UX, this file wins.

## 1. Product definition

One line: Recommend three realistic next-Japan trips beyond Tokyo, Kyoto and
Osaka, matched to the traveller's conditions, and prove each one actually works.
Target user: overseas repeat visitors who have done Tokyo/Kyoto/Osaka.
Where Next is the main product. RouteCheck is (a) the feasibility engine that
automatically checks every Where Next option and (b) a secondary entry point for
people who already have an itinerary.

## 2. Experience principles (apply to every screen)

1. Narrow it down: never show more than 3 options.
2. Show the bad news: every option shows "What's hard" and there is always a
   "Not for this trip" section with reasons.
3. Date every fact: every critical fact shows its source and last-verified date.
   Never show "Verified" without a date. Never invent times, prices or rules.
4. Show answers, not machinery: no words like grounding, confidence, RAG,
   embedding in the UI. Evidence opens on tap.
5. The user decides: no booking or payment actions.

## 3. Required changes vs SPEC.md

- Recommend DESTINATION COMBINATIONS (e.g. "Nyuto Onsen + Kakunodate, 2N + 2N"),
  not regions ("Tohoku").
- Return exactly 3 options with different characters: Classic / Unexpected /
  Slow-paced. Plus a collapsible "Not for this trip" list. Each rejection says
  what would change the answer (e.g. "If you can fly out of Fukuoka, Kyushu
  becomes a strong option").
- Fit score: deterministic rubric, shown as 5 levels plus a breakdown
  (e.g. "Interests 3/3 matched"). No percentages in the UI.
- Input: one screen. Required: travel month (or dates), regional nights,
  arrival city, departure city (can differ). Optional chips: interests (max 3),
  places already visited (Tokyo/Kyoto/Osaka pre-selected), transport
  (no car / can drive / either; default no car), pace (default balanced),
  constraints (big luggage, kids, limited walking), free-text "What kind of trip?".
- Analysis is DAY-BY-DAY: each day shows moving time vs time at destination.
  When the user gives no times, use visible, editable default assumptions
  (e.g. leave hotel 09:30) and label them as assumptions.
- Fixes respect user priorities: user can pin must-keep stops; fixes never
  remove a pinned stop. Show a before/after diff with what is gained and lost.
- RouteCheck verdict has 3 levels: Works / Needs attention / Will not work.
  Every issue = concrete problem + why + 2 fix options + evidence and date.
- RouteCheck extraction: show the parsed itinerary as an editable table and
  require user confirmation before analysis.
- After RouteCheck, offer "With these conditions, you could also consider..."
  linking into Where Next.
- Conflicting or stale critical facts: show "Being checked" to the user, create a
  human review task, and notify/update the saved trip when resolved.
- Remove Stripe from v1. Add a "See full report" button that only records clicks
  (demand test). Keep pricing config for later.
- UI language: English first. Japanese sources may be cited with an English
  summary and a link to the original.

## 4. New features

- Compare screen: 3 options side by side, same rows in the same order:
  total travel time, hotel changes, car needed, season fit, interest match,
  booking difficulty, verification status.
- What-if toggles on Compare: "If I can drive", "+1 night", "Fly out of Osaka".
  Recompute deterministically and instantly (no LLM call needed for scoring).
- Customise: pin, swap a stop for alternatives from the database, change nights,
  reorder. Every change re-runs the feasibility check automatically.
- Booking to-do list per trip (only items backed by evidence).
- Share link for a saved trip (read-only).
- Zero-results state: suggest the smallest condition changes that produce results.
- Generating screen: show real filtering progress with real counts
  (e.g. "180 places -> 92 open in January -> 31 realistic without a car"),
  and render options as each completes.

## 4b. Users with clear, partial or vague conditions

The core user is often VAGUE: "sometime next year, about a week, somewhere
beyond Tokyo/Kyoto/Osaka". Design ONE entry flow that adapts to how specific
the answers are. Do not make users pick a "type".

- Every required input (month, regional nights, arrival/departure city) has a
  "Not decided yet" option. Never block on it.
  - Month undecided -> show seasonal options side by side (spring/summer/
    autumn/winter), user picks a season, then 3 options.
  - Nights undecided -> show "With 3 nights" vs "With 5 nights" options.
  - Cities undecided -> assume Tokyo in/out, label it "Assumed", editable,
    and testable via what-if.
- "Must include" places input in Where Next (not only RouteCheck): pin them
  and propose the rest around them (e.g. "Shirakawa-go fixed, suggest the
  other 2 nights").
- No interests given -> show two inline helpers on the same screen:
  1. Past-trip questions: "Best moment on your last Japan trip?" and
     "What tired you or you'd skip next time?" Infer interests and things to
     avoid from the answers (LLM extraction into structured preferences).
  2. Scene cards (~10): snowy onsen town, island art, satoyama farm village,
     castle town, fishing village by the sea, mountain views, local market
     food, etc. Users pick the ones that appeal.
- Reaction buttons on every option card: "More like this", "Quieter",
  "More unexpected", "Not for me". Regenerate using the reactions.
- Assumed values are always visible in the condition summary as "Assumed".

Acceptance: a user who answers only "Not decided yet" to all required fields
and picks 2 scene cards still reaches 3 sensible options in under 2 minutes.

## 5. Screens (v1)

```
/                       Landing: headline, primary CTA (Where Next), secondary
                        CTA (Check my route), one real sample result, no signup.
/plan                   Single-screen input.
/plan/[id]              3 option cards + "Not for this trip".
/plan/[id]/compare      Comparison + what-if.
/plan/[id]/option/[n]   Map and stop order, day-by-day timeline with
                        moving/staying bars, fragile-link warnings, booking
                        list, evidence list, pin/swap.
/check                  Paste itinerary -> confirm parsed table -> results
                        (same results components as option detail).
/trip/[id]              Saved trip workspace (signup happens here, at save).
/admin                  Verification queue (stale, conflicting, unverified).
```

Option card content, top to bottom: character label, destination combination,
one-line description, fit (5 levels + breakdown), travel-load bar, car needed,
season fit, What's hard (2-3 items), verification status with date.

## 6. Coverage and data (product rules)

- Destination database: start with 100-200 destinations nationwide with
  structured attributes: hub city and travel time from hubs, car need
  (none/helpful/required), season fit by month, themes, popularity tier
  (classic/middle/hidden), fragile links present.
- Intercity backbone: travel time and transfers between major hubs nationwide.
- Deep verification only for ~30 "fragile" destinations (last buses, ryokan
  shuttles, seasonal closures, booking difficulty). Seed demo examples such as
  Ginzan Onsen, Shirakawa-go, Kamikochi, Naoshima, Takachiho, Iya Valley,
  Nyuto Onsen.
- Anything outside the database: say "No verified info yet" and check only
  intercity movement. Never fill gaps with guesses.
- Every seed/demo fact is visibly labelled DEMO in the UI.
- The LLM selects and explains combinations from the database. It never
  creates operational facts.

## 7. Error and edge states (must exist)

zero results, unverified fact, conflicting facts ("Being checked"), stale fact,
external provider down (show last known value with date), LLM down (show
deterministic results without narrative), unparseable itinerary (highlight the
parts to confirm), destination not in database.

## 8. Design

Calm, editorial, premium. White / ink / indigo base; green, amber, red only for
status, always with icon + text. Serif headings, sans-serif body. Mobile-first;
compare table widens on desktop. Subtle motion only. No stock photos unless
licensed. WCAG AA contrast, keyboard navigation, screen-reader labels.

## 9. Out of scope for v1

Payments, PDF/calendar export, pre-departure re-check notifications,
post-trip feedback, full Japanese UI.

## 10. Hero demo (must work perfectly end to end)

Australian couple, 3rd visit, January, Tokyo in/out, 4 regional nights,
no car, interests: onsen, snow, food.
Expected: 3 distinct options (Classic / Unexpected / Slow-paced), Kyushu or
other high-overhead regions listed under "Not for this trip" with an
"if you change X" note, compare + what-if works, option detail shows a
day-by-day timeline with at least one fragile-link warning backed by dated
evidence, pin + swap re-runs the check, trip saves and shares.
Also: RouteCheck on "Tokyo 3N, Sendai 1N, Ginzan Onsen 1N, Aomori 1N,
Hakodate 1N, Tokyo" with Ginzan pinned must not remove Ginzan.

Second hero demo (vague user): all required fields "Not decided yet",
last trip answer "Loved Nishiki Market food walks, tired of crowds",
scene cards: snowy onsen town + fishing village. Expected: season choice
screen, then 3 options with "Assumed: Tokyo in/out" visible, and reaction
buttons regenerate options.

## 11. Milestones (stop and report after each)

- **M1** Data: destination database, intercity backbone, fragile-link records,
  seed data with DEMO labels.
- **M2** Where Next engine: deterministic filtering + scoring + 3 diverse options +
  rejections with "if you change X" + undecided inputs, must-include pins,
  past-trip/scene-card preference inference, reaction-based regeneration.
- **M3** Feasibility engine: day-by-day analysis, fragile-link checks, verdicts,
  fixes with pins; reused by Where Next and RouteCheck.
- **M4** Frontend: all v1 screens, states and design rules above.
- **M5** Human review loop end to end ("Being checked" -> resolved -> trip updated).
- **M6** Evals: add product evals (option diversity, rejection correctness,
  pinned-stop preservation, no uncited operational facts) to the SPEC.md
  eval suite; hero demo as an automated E2E test.

Each report: what works, what was tested (actually run), what is DEMO data,
known gaps. Make routine technical decisions yourself.
