# Feasibility engine (v2 RouteCheck)

Does this itinerary actually work, day by day? One engine answers that for
both entry points:

- **Where Next**: every option is checked, and `option.check` carries the
  result.
- **RouteCheck**: the traveller's own itinerary, at `POST /api/v1/checks`.

Code: `backend/src/jst_api/planner/feasibility.py`. It is pure and
deterministic, with no model call.

## Steps

1. **Resolve stops** against the catalogue. Each stop is one of three kinds:
   - a destination, with its fragile links;
   - a hub city;
   - unknown: "No verified info yet". Travel to and from it, connections and
     closures are not checked, and the trip cannot score "Works".
2. **Lay out days.** There is one day per night, plus the departure day. Each
   day shows its moves (depart and arrive times, estimated), moving time, and
   time at the destination. Clock times rest on default assumptions, each
   editable and listed as "Assumed: …":

   | Assumption | Default |
   | --- | --- |
   | Leave the hotel | 09:30 |
   | Sightseeing ends | 18:30 |
   | Land and reach the first city (whole trip only) | 14:00 |
   | Be at the departure city for the flight (whole trip only) | 15:00 |

   A Where Next option is a *regional* leg: it starts from the arrival city in
   the morning and has no flight cutoff.
3. **Rules.** Issues are critical, warning or info:

   | Rule | When |
   | --- | --- |
   | Last connection / ryokan shuttle | Estimated arrival at the connection is after the last departure (critical) or within 45 minutes of it (warning) |
   | Being checked | Sources disagree. No value is shown, the issue is flagged for human review, and it is info only if you arrive well before every reported time |
   | Not yet verified | No verified time is held for the connection (warning) |
   | Seasonal closure | The month is closed or best avoided (critical) |
   | Car required | No car (critical) |
   | Weekly closure | Clashes with real dates (warning); with no dates, info |
   | Long travel day | Over the pace limit: relaxed 4h, balanced 5h, fast 6h30. Warning, or critical when 2h30 over |
   | Late arrival | Arrive after sightseeing ends (warning) |
   | Hotel churn | 3 or more one-night stays in a row (warning); 5 or more (critical) |
   | Travel share | Over 35% of sightseeing time spent moving (warning) |
   | Backtracking | Reordering saves 1h30 or more (warning) |
   | Departure risk | Reaching the departure city after the flight cutoff (critical) |

   Access disruptions are warnings. Weather (only in relevant months) and low
   frequency are info.
4. **Verdict.**
   - **Will not work**: any critical issue.
   - **Needs attention**: any warning.
   - **Works**: otherwise.
5. **Fixes.** Candidate changes, each re-checked in full:
   - reorder;
   - leave earlier (08:30, 07:30, 06:30);
   - move a night between stops;
   - swap a stop for a nearby alternative from the database;
   - skip a stop and give its nights to a neighbour.

   A fix is offered for an issue only if:
   - it resolves that issue;
   - it adds no new critical issue;
   - it does not make the verdict worse;
   - it keeps every pinned stop. **Pinned stops are never removed or
     swapped.** Their nights can change, but never below one.

   Up to two fixes are offered per issue, cheapest first. Each carries a
   before/after diff: what is gained (less moving, more nights, issues fixed)
   and what is lost (dropped stops, earlier starts, new issues).

Every critical or warning issue carries evidence: the source, its fact state
and its verified date. That is the fragile-link record, or the DEMO travel
times for the stop.

The booking to-do list comes only from fragile records about bookings or lead
times, each with its evidence. With dates, it adds a book-by date.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/checks/parse` | Turns pasted text into a stop table to confirm. A model extracts structure only, and the deterministic parser runs if the model is unavailable or the text looks like an injection. Unmatched rows are marked `unknown` and listed in `to_confirm`. |
| `POST /api/v1/checks` | Runs the check on the confirmed table and returns `check` plus `also_consider`: up to three Where Next options under the same conditions. Every customisation (pin, swap, nights, reorder, leave time) is the same call with the edited table. |
| `POST /api/v1/checks/alternatives` | Lists swap candidates for one stop: same area, open, reachable, not already on the trip. Pinned stops get none. |

## Known limits

- Times are estimates. The last stretch to a destination is its hub time, and
  the connection point is assumed to be halfway along it.
- All data is DEMO.
- When a stop is being checked, the issue is flagged `needs_review`. Creating
  the review task and updating saved trips once the review is resolved come
  in M5.
