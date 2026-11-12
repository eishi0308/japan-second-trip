# Where Next engine (v2)

The planner behind `POST /api/v1/plans`. It follows `PRODUCT_AMENDMENTS.md`:
three destination combinations with different characters, the bad news
stated, every fact dated. Code: `backend/src/jst_api/planner/`.

It is deterministic. The same conditions always give the same plan, and the
planner makes no model call. That lets what-if toggles and reactions
recompute instantly: each is the same request with one field changed. The
only model call is in the service, and only when the traveller wrote
past-trip answers (see *Preferences*).

## Pipeline

1. **Resolve undecided inputs.**
   - Month undecided returns a season choice: winter, spring, summer and
     autumn, each with its own three options.
   - Nights undecided returns 3 nights versus 5 nights.
   - Cities undecided means Tokyo in/out, listed in `assumptions` as
     "Assumed: Tokyo in/out".
2. **Funnel** the catalogue, keeping the real count at each step. For example:
   `149 places → 144 open in January → 135 realistic without a car → 81
   within reach of Tokyo for 4 nights`. Each place that drops out keeps its
   reason.
3. **Combine** survivors into trips of 1 to 3 stops.
   - Stops run in the fastest order, from the arrival city to the departure
     city.
   - Nights are split by each place's typical stay.
   - Pinned (must-include) places are in every combination.
   - Hops over 5 hours are not combined.
   - A combination over the travel budget is ruled out, not just scored low.
4. **Score** each combination with a 100-point rubric (`scoring.py`):

   | Component | Points | Measures |
   | --- | --- | --- |
   | Interests | 35 | Share of the traveller's interests covered |
   | Season | 20 | Month fit at each stop, weighted by nights |
   | Travel | 25 | Moving time against the budget |
   | Transport | 10 | Car need against the traveller's transport |
   | Rhythm | 10 | Nights per stop against each place's typical stay |

   - Preferences then add or subtract a few points.
   - The travel budget is `120 min × nights + 120 min`, scaled by pace.
   - Snow counts as a theme only from December to March.
   - The UI sees one of five levels ("Excellent fit" to "Weak fit") and a
     breakdown such as "Interests 3/3 matched". It never sees the points.
5. **Pick three characters**, which share no unpinned stop where possible:
   - **Classic**: the best combination with a well-known stop.
   - **Unexpected**: the best combination with a hidden-tier stop, preferring
     a different area.
   - **Slow-paced**: the fewest hotel changes and the least moving.
6. **Not for this trip.** Each area with no option is listed with its reason:
   too far, heavy travel, out of season, needs a car, or nothing matching. It
   also gets the single change that would bring it back. That change is found
   by re-running the check with it applied, not written by hand. Example: "If
   you can fly out of Fukuoka, Kyushu becomes a possible option."
7. **Zero results.** The engine tries one relaxation at a time and lists the
   ones that produce options:
   - driving;
   - one or two more nights;
   - a neighbouring month;
   - a faster pace;
   - un-pinning a stop;
   - clearing reactions.

## What each option shows

The character, the destination combination, and a one-line description. Then:

- the fit level and breakdown;
- the moving time and travel load (light, moderate or heavy);
- the car need;
- the season fit;
- 2 or 3 "What's hard" items;
- the verification status with a date.

"What's hard" draws on:

- fragile links that matter in that month (a winter closure is not shown in
  July), each with its fact state, source and verified date;
- a pinned stop that is out of season;
- the longest travel day;
- places where a car helps;
- hotel moves;
- "no verified info yet" for stops with no fragile records.

## Preferences

- **Scene cards** (10) map to catalogue themes.
- **Past-trip answers** go to the `past_trip_preferences` prompt, which
  extracts `liked` interests and `avoid` items (crowds, long transfers, hotel
  changes, cities, early starts).
  - Text that looks like an injection never reaches the model.
  - If the model fails, a keyword extractor gives the same structure.
  - The response says which path ran (`preferences.source`).
- **Reactions:**
  - "More like this" boosts that option's themes and area.
  - "Quieter" favours hidden places over classic ones.
  - "More unexpected" favours hidden places and moves away from those already
    shown.
  - "Not for me" removes those stops, except pinned ones.

## Endpoints

- `POST /api/v1/plans` takes conditions and returns a plan. Every required
  field accepts `null` for "Not decided yet".
- `GET /api/v1/plans/scene-cards` lists the scene cards.
- `GET /api/v1/plans/cities` lists arrival and departure cities, gateways
  first.

## Known limits

- Travel times between two stops go via their hubs. Where two stops share a
  hub, that overestimates a short local hop. This errs towards calling a trip
  heavier, never lighter.
- The one-line description is the stops' catalogue summaries joined
  together. A model-written narrative over the same facts comes later.
- All catalogue data is DEMO.
