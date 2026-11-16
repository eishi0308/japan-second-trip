# Human review loop (M5)

"Being checked" → a reviewer resolves it → saved trips are updated.

## When a fact needs a person

The feasibility engine flags a fragile fact for review (`needs_review`) when
it is either of these:

- **Conflicting:** sources disagree. The traveller sees "Being checked". No
  value is shown or used, and the issue says a reviewer has been asked.
- **Stale and critical:** past its freshness window and able to break a stay
  (for example a last bus). The traveller sees "being checked" with the last
  confirmed value *and its date*. It is never shown as current.

Every flagged issue carries `fact_id`, the fragile-link record it rests on.

## The loop

1. **A task is opened.** Each check (Where Next options, RouteCheck, saved
   trips, share links) calls `ensure_tasks`. It opens one `HumanReviewTask`
   per fact (subject `fragile:<id>`, reason `fragile_fact`), never two for the
   same fact. A critical fact gets high priority.
2. **The queue.** `/admin` (and `GET /api/v1/admin/facts/queue`) lists every
   fact that is being checked, then stale, then unverified, with critical facts
   first. Each row shows the reported values (for a conflict, never a
   "current" one), when it was last checked, whether a review was requested,
   and how many saved trips depend on it.
3. **The reviewer resolves it.** This is `POST /api/v1/admin/facts/{id}/resolve`:
   - For a last bus or shuttle, the confirmed time (`HH:MM`, required when
     sources disagree); for a stale fact, an empty value confirms it is still
     right.
   - The fragile link becomes `verified`, dated now. Its conflicting values are
     cleared, and it points to a new `human_review` source (with the link the
     reviewer gave, the reviewer, and a note).
   - A `VerificationRecord` is written and supersedes any earlier one, so the
     history stays.
   - The open task is closed with the value, the reviewer and the time.
4. **Trips are updated.** Every saved trip that includes the place is
   re-checked on the new fact. Each one gets a notice such as "Ginzan Onsen:
   last bus from Oishida Station confirmed as 17:00 on 17 Nov 2026. We
   re-checked your trip: Needs attention → Works." The comparison is with the
   verdict the owner last saw (`saved_trips.last_verdict`). The owner sees the
   notice at `/trip/[id]` and can mark it read; the share link shows it too.

The model never picks between disputed values, and neither does the code. A
disputed time becomes a fact only through a reviewer.

## Tested

`backend/tests/integration/test_review_loop.py` runs the whole loop on the
seeded Ginzan conflict through the real API:
- save a trip;
- a task opens, once;
- the queue shows the trip depends on the fact;
- an admin resolves it with a source;
- the trip's notice and evidence update;
- the fact leaves the queue;
- the share link shows the update.

It also checks that a non-time value is refused and that only admins can see
or resolve the queue. Frontend tests cover the queue screen and the trip
notices.

## Not in v1

- Email notifications. The notice lives on the trip; the owner's email (if
  given) is stored but nothing is sent.
- Automatic re-checking of stale facts against a live source. A person
  confirms them.
