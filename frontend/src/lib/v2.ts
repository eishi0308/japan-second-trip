/**
 * Types and calls for the v2 product: Where Next plans, feasibility checks,
 * saved trips. They mirror the backend Pydantic models in
 * `backend/src/jst_api/planner/results.py` and `api/v1/{plans,checks,saved_trips}.py`.
 */

import { apiFetch } from "./api";

// ---------------------------------------------------------------- shared
export type FactState = "verified" | "stale" | "unverified" | "being_checked";
export type Verdict = "works" | "needs_attention" | "will_not_work";
export type Severity = "critical" | "warning" | "info";

export interface Assumption {
  field: string;
  value: string;
  label: string;
}

export interface Evidence {
  source_id: string | null;
  label: string;
  fact_state: FactState;
  verified_at: string | null;
  is_demo: boolean;
}

// ---------------------------------------------------------------- checks
export interface CheckStop {
  name: string;
  slug: string | null;
  kind: "place" | "city" | "unknown";
  nights: number;
  pinned: boolean;
  area: string | null;
  lat: number | null;
  lon: number | null;
}

export interface Move {
  origin: string;
  destination: string;
  depart: string;
  arrive: string;
  minutes: number;
  transfers: number;
  estimated: boolean;
}

export interface Day {
  day: number;
  date: string | null;
  title: string;
  overnight: string | null;
  moving_minutes: number;
  staying_minutes: number;
  moving_label: string;
  staying_label: string;
  moves: Move[];
  issue_ids: string[];
}

export interface Fix {
  id: string;
  label: string;
  stops: CheckStop[];
  diff: { gained: string[]; lost: string[] };
  verdict_after: Verdict;
  verdict_after_label: string;
}

export interface Issue {
  id: string;
  kind: string;
  severity: Severity;
  title: string;
  why: string;
  day: number | null;
  stop: string | null;
  needs_review: boolean;
  fixes: Fix[];
  evidence: Evidence[];
}

export interface BookingItem {
  stop: string;
  text: string;
  lead_time_days: number | null;
  book_by: string | null;
  evidence: Evidence;
}

export interface CheckResult {
  verdict: Verdict;
  verdict_label: string;
  summary: string;
  stops: CheckStop[];
  assumptions: Assumption[];
  days: Day[];
  issues: Issue[];
  booking: BookingItem[];
  moving_minutes: number;
  hotel_changes: number;
  is_demo: boolean;
}

export interface StopIn {
  name: string;
  nights: number;
  pinned?: boolean;
  leave_at?: string | null;
}

export interface CheckRequest {
  stops: StopIn[];
  month?: number | null;
  start_date?: string | null;
  arrival_city?: string | null;
  departure_city?: string | null;
  transport?: Transport;
  pace?: Pace;
  big_luggage?: boolean;
  mode?: "whole_trip" | "regional";
  assumptions?: { leave_hotel: string; day_end: string; landing: string; flight_cutoff: string };
}

export interface AlsoConsider {
  character_label: string;
  title: string;
  nights_label: string;
  fit_label: string;
}

export interface CheckResponse {
  check: CheckResult;
  also_consider: AlsoConsider[];
}

export interface ParsedRow {
  name: string;
  nights: number;
  status: "known" | "city" | "unknown";
  matched_name: string | null;
  slug: string | null;
  area: string | null;
  note: string | null;
}

export interface ParsedItinerary {
  rows: ParsedRow[];
  arrival_city: string | null;
  departure_city: string | null;
  to_confirm: string[];
  source: string;
}

export interface Alternative {
  slug: string;
  name: string;
  area: string;
  summary: string;
  is_demo: boolean;
}

// ---------------------------------------------------------------- plans
export type Transport = "no_car" | "can_drive" | "either";
export type Pace = "relaxed" | "balanced" | "fast";
export type ReactionKind = "more_like_this" | "quieter" | "more_unexpected" | "not_for_me";

export interface PlanRequest {
  month?: number | null;
  start_date?: string | null;
  regional_nights?: number | null;
  arrival_city?: string | null;
  departure_city?: string | null;
  interests?: string[];
  visited?: string[];
  transport?: Transport;
  pace?: Pace;
  big_luggage?: boolean;
  kids?: boolean;
  limited_walking?: boolean;
  must_include?: string[];
  scene_cards?: string[];
  past_trip_best?: string | null;
  past_trip_tired?: string | null;
  free_text?: string | null;
  reactions?: { kind: ReactionKind; stops: string[] }[];
  save?: boolean;
}

export interface OptionStop {
  slug: string;
  name: string;
  area: string;
  prefecture: string;
  nights: number;
  tier: string;
  summary: string;
  pinned: boolean;
  is_demo: boolean;
  lat: number | null;
  lon: number | null;
}

export interface HardItem {
  text: string;
  kind: string;
  fact_state: FactState | null;
  verified_at: string | null;
  source_id: string | null;
  is_demo: boolean;
}

export interface Option {
  character: "classic" | "unexpected" | "slow_paced";
  character_label: string;
  title: string;
  nights_label: string;
  description: string;
  stops: OptionStop[];
  fit: { level: number; label: string; breakdown: { name: string; text: string }[]; adjusted_for: string[] };
  travel: {
    moving_minutes: number;
    moving_label: string;
    load: "light" | "moderate" | "heavy";
    hotel_changes: number;
    longest_leg: { origin: string; destination: string; minutes: number; transfers: number };
    legs: { origin: string; destination: string; minutes: number; transfers: number }[];
  };
  car: "none" | "helpful" | "required";
  car_label: string;
  season: number;
  season_label: string;
  whats_hard: HardItem[];
  verification: { state: FactState; label: string; oldest_verified_at: string | null; is_demo: boolean };
  check: CheckResult | null;
}

export interface Rejection {
  area: string;
  area_label: string;
  example: string;
  reason: string;
  if_you_change: string | null;
}

export interface OptionSet {
  month: number;
  nights: number;
  options: Option[];
  not_for_this_trip: Rejection[];
  funnel: { label: string; count: number }[];
  zero_results_suggestions: { change: string; label: string; options_found: number }[];
}

export interface PlanResult {
  kind: "options" | "season_choice" | "nights_choice";
  assumptions: Assumption[];
  interests: string[];
  notices: { code: string; text: string }[];
  result: OptionSet | null;
  seasons: { season: string; label: string; month: number; result: OptionSet }[];
  nights_options: { nights: number; label: string; result: OptionSet }[];
  is_demo: boolean;
}

export interface PlanResponse {
  plan_id: string | null;
  request: PlanRequest;
  plan: PlanResult;
  preferences: { interests: string[]; avoid: string[]; source: string };
  demo_mode: boolean;
  latency_ms: number;
}

export interface SceneCard {
  slug: string;
  title: string;
  themes: string[];
}

export interface City {
  slug: string;
  name: string;
  area: string;
  is_international_gateway: boolean;
}

// ---------------------------------------------------------------- saved trips
export interface SavedTrip {
  id: string | null;
  share_id: string;
  title: string;
  plan_id: string | null;
  has_email: boolean | null;
  read_only: boolean;
  check_request: CheckRequest;
  result: CheckResponse;
  updated_at: string | null;
}

// ---------------------------------------------------------------- calls
export const v2 = {
  createPlan: (body: PlanRequest) => apiFetch<PlanResponse>("/api/v1/plans", { method: "POST", body }),
  getPlan: (id: string) => apiFetch<PlanResponse>(`/api/v1/plans/${encodeURIComponent(id)}`),
  sceneCards: () => apiFetch<SceneCard[]>("/api/v1/plans/scene-cards"),
  cities: () => apiFetch<City[]>("/api/v1/plans/cities"),
  parse: (text: string) => apiFetch<ParsedItinerary>("/api/v1/checks/parse", { method: "POST", body: { text } }),
  check: (body: CheckRequest) => apiFetch<CheckResponse>("/api/v1/checks", { method: "POST", body }),
  alternatives: (body: CheckRequest, index: number) =>
    apiFetch<Alternative[]>("/api/v1/checks/alternatives", { method: "POST", body: { ...body, index } }),
  saveTrip: (body: { title: string; email?: string | null; plan_id?: string | null; check: CheckRequest }) =>
    apiFetch<{ trip: SavedTrip; token: string }>("/api/v1/saved-trips", { method: "POST", body }),
  getTrip: (id: string, token: string) => apiFetch<SavedTrip>(`/api/v1/saved-trips/${encodeURIComponent(id)}`, { token }),
  updateTrip: (id: string, token: string, body: { title?: string; check?: CheckRequest }) =>
    apiFetch<SavedTrip>(`/api/v1/saved-trips/${encodeURIComponent(id)}`, { method: "PUT", body, token }),
  shared: (shareId: string) => apiFetch<SavedTrip>(`/api/v1/shared/${encodeURIComponent(shareId)}`),
  fullReport: (body: { plan_id?: string | null; trip_id?: string | null; option?: number | null }) =>
    apiFetch<{ status: string; message: string }>("/api/v1/demand", {
      method: "POST",
      body: { kind: "full_report", ...body },
    }),
};

// ---------------------------------------------------------------- helpers
export const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export const INTERESTS = ["food", "onsen", "nature", "culture", "hiking", "city", "coast", "snow", "art", "nightlife"];

export function hours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}` : `${m} min`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** The option as an itinerary the feasibility engine can re-check (regional leg). */
export function optionToCheck(option: Option, request: PlanRequest, month: number): CheckRequest {
  return {
    stops: option.stops.map((s) => ({ name: s.slug, nights: s.nights, pinned: s.pinned })),
    month,
    arrival_city: request.arrival_city ?? null,
    departure_city: request.departure_city ?? null,
    transport: request.transport ?? "no_car",
    pace: request.pace ?? "balanced",
    big_luggage: request.big_luggage ?? false,
    mode: "regional",
  };
}

/** Turn a zero-results suggestion code into the request change it describes. */
export function applySuggestion(request: PlanRequest, change: string, set: OptionSet): PlanRequest {
  if (change === "can_drive") return { ...request, transport: "either" };
  if (change === "nights_plus_1") return { ...request, regional_nights: set.nights + 1 };
  if (change === "nights_plus_2") return { ...request, regional_nights: set.nights + 2 };
  if (change === "pace_fast") return { ...request, pace: "fast" };
  if (change === "walking") return { ...request, limited_walking: false };
  if (change === "reset_reactions") return { ...request, reactions: [] };
  if (change.startsWith("month_")) return { ...request, month: Number(change.slice(6)) };
  if (change.startsWith("unpin_")) {
    const slug = change.slice(6);
    return { ...request, must_include: (request.must_include ?? []).filter((p) => p !== slug && p.toLowerCase().replace(/\s+/g, "-") !== slug) };
  }
  return request;
}
