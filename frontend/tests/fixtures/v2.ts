import type { CheckResult, Issue, Option } from "@/lib/v2";

export const issue: Issue = {
  id: "last_connection:ginzan-onsen:5",
  kind: "last_connection",
  severity: "warning",
  title: "Last bus from Oishida Station: being checked",
  why: "Sources disagree on this detail, so we cannot confirm you make it.",
  day: 5,
  stop: "ginzan-onsen",
  needs_review: true,
  evidence: [
    { source_id: "src_1", label: "DEMO record, sources disagree, being checked", fact_state: "being_checked", verified_at: "2026-09-20T00:00:00Z", is_demo: true },
  ],
  fixes: [
    {
      id: "fix1",
      label: "Leave Sendai at 07:30 instead of 09:30",
      stops: [
        { name: "Sendai", slug: "sendai", kind: "place", nights: 1, pinned: false, area: "tohoku", lat: 38.26, lon: 140.87 },
        { name: "Ginzan Onsen", slug: "ginzan-onsen", kind: "place", nights: 2, pinned: true, area: "tohoku", lat: 38.57, lon: 140.53 },
      ],
      diff: { gained: ["Fixes: Last bus from Oishida Station: being checked"], lost: ["Earlier start: leave Sendai at 07:30"] },
      verdict_after: "works",
      verdict_after_label: "Works",
    },
  ],
};

export const check: CheckResult = {
  verdict: "needs_attention",
  verdict_label: "Needs attention",
  summary: "1 thing to look at.",
  stops: issue.fixes[0]!.stops,
  assumptions: [{ field: "leave_hotel", value: "09:30", label: "Assumed: leave the hotel at 09:30" }],
  days: [
    { day: 1, date: null, title: "Tokyo → Sendai", overnight: "Sendai", moving_minutes: 100, staying_minutes: 440, moving_label: "1h40 moving", staying_label: "7h20 at the destination", moves: [], issue_ids: [] },
  ],
  issues: [issue],
  booking: [],
  moving_minutes: 100,
  hotel_changes: 1,
  is_demo: true,
};

export const option: Option = {
  character: "unexpected",
  character_label: "Unexpected",
  title: "Morioka + Nyuto Onsen",
  nights_label: "2N + 2N",
  description: "Noodles and milky baths.",
  stops: [
    { slug: "morioka", name: "Morioka", area: "tohoku", prefecture: "Iwate", nights: 2, tier: "middle", summary: "", pinned: false, is_demo: true, lat: 39.7, lon: 141.15 },
    { slug: "nyuto-onsen", name: "Nyuto Onsen", area: "tohoku", prefecture: "Akita", nights: 2, tier: "hidden", summary: "", pinned: true, is_demo: true, lat: 39.8, lon: 140.75 },
  ],
  fit: { level: 4, label: "Strong fit", breakdown: [{ name: "interests", text: "Interests 3/3 matched (onsen, snow, food)" }], adjusted_for: [] },
  travel: {
    moving_minutes: 500,
    moving_label: "8h20 moving in total",
    load: "moderate",
    hotel_changes: 1,
    longest_leg: { origin: "Nyuto Onsen", destination: "Tokyo", minutes: 245, transfers: 2 },
    legs: [],
  },
  car: "none",
  car_label: "No car needed",
  season: 2,
  season_label: "January: a good time",
  whats_hard: [
    { text: "Nyuto Onsen: Last bus from Tazawako Station", kind: "last_connection", fact_state: "verified", verified_at: "2026-10-01T00:00:00Z", source_id: "src_2", is_demo: true },
    { text: "Longest travel day: 4h05, Nyuto Onsen to Tokyo", kind: "travel_burden", fact_state: null, verified_at: null, source_id: null, is_demo: true },
  ],
  verification: { state: "verified", label: "DEMO data, last checked 14 Oct 2026", oldest_verified_at: "2026-10-14T00:00:00Z", is_demo: true },
  check,
};
