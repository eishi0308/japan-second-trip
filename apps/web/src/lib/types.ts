/**
 * Wire types mirroring the API's Pydantic schemas.
 *
 * Hand-maintained rather than generated, so the frontend can be read on its own
 * — but every field name here exists in `apps/api/src/jst_api/domain/results.py`
 * and `api/schemas.py`, and the contract test in `tests/contract.test.ts`
 * fails if the API drifts.
 */

export type FitLabel = "strong" | "good" | "marginal" | "not_recommended";
export type Severity = "critical" | "warning" | "info" | "good";
export type RouteHealth = "healthy" | "needs_improvement" | "high_risk";
export type Confidence = "high" | "medium" | "low" | "insufficient_evidence";
export type Freshness = "fresh" | "ageing" | "stale" | "unverified";

export interface Citation {
  evidence_id: string;
  source_id: string;
  title: string;
  url: string | null;
  source_type: string;
  official_source: boolean;
  verified_at: string | null;
  freshness: Freshness;
  is_demo: boolean;
}

export interface ScoreComponent {
  name: string;
  value: number;
  weight: number;
  contribution: number;
  explanation: string;
}

export interface RegionRecommendation {
  region_code: string;
  region_name: string;
  rank: number;
  fit_label: FitLabel;
  deterministic_score: number;
  score_components: ScoreComponent[];
  headline: string;
  reasons: string[];
  tradeoffs: string[];
  rejected_reasons: string[];
  round_trip_transfer_hours: number;
  transit_share: number;
  car_required: boolean;
  public_transport_viable: boolean;
  booking_complexity: number;
  seasonal_note: string | null;
  evidence_ids: string[];
  citations: Citation[];
  confidence: Confidence;
  is_demo_data: boolean;
}

export interface ConflictingEvidence {
  field_name: string;
  subject: string;
  values: string[];
  evidence_ids: string[];
}

export interface ResolvedFact {
  subject: string;
  field: string | null;
  value: string;
  verified_by: string;
  verified_at: string;
}

export interface WhereNextResult {
  analysis_id: string;
  trip_id: string | null;
  status: string;
  generated_at: string;
  recommended: RegionRecommendation | null;
  alternatives: RegionRecommendation[];
  rejected: RegionRecommendation[];
  suggested_route: {
    region_code: string;
    summary: string;
    stops: string[];
    nights: number[];
    rationale: string;
  } | null;
  assumptions: string[];
  missing_information: string[];
  unknowns: string[];
  conflicts: ConflictingEvidence[];
  confidence: Confidence;
  human_review_required: boolean;
  human_review_task_id: string | null;
  citations: Citation[];
  resolved_facts: ResolvedFact[];
  superseded_by: string | null;
  demo_mode: boolean;
  scoring_rubric_version: string;
  prompt_versions: Record<string, string>;
}

export interface RouteIssue {
  issue_type: string;
  severity: Severity;
  segment: string | null;
  title: string;
  explanation: string;
  deterministic_signal: Record<string, string | number | boolean>;
  rule_id: string | null;
  evidence_ids: string[];
  proposed_fix: string | null;
}

export interface TravelLoad {
  total_nights: number;
  total_transit_hours: number;
  longest_segment_hours: number;
  accommodation_changes: number;
  one_night_stays: number;
  transit_hours_per_night: number;
  transit_share_of_daylight: number;
  detour_ratio: number;
  segments_requiring_car: number;
  estimated_segments: number;
  is_travel_dominated: boolean;
}

export interface RouteStop {
  order: number;
  raw_name: string;
  place_slug: string | null;
  display_name: string | null;
  nights: number;
  region_code: string | null;
  lat: number | null;
  lon: number | null;
  resolved: boolean;
  resolution_note: string | null;
}

export interface RouteSegment {
  from_order: number;
  to_order: number;
  from_name: string;
  to_name: string;
  mode: string;
  duration_minutes: number;
  transfers: number;
  distance_km: number | null;
  requires_car: boolean;
  last_departure_local: string | null;
  final_leg_minutes: number | null;
  provider: string;
  is_estimate: boolean;
  evidence_ids: string[];
  notes: string | null;
}

export interface RouteCheckResult {
  analysis_id: string;
  trip_id: string | null;
  status: string;
  generated_at: string;
  health: RouteHealth;
  health_summary: string;
  parsed_route: { stops: RouteStop[]; segments: RouteSegment[]; arrival_city: string | null; departure_city: string | null } | null;
  travel_load: TravelLoad | null;
  critical_issues: RouteIssue[];
  warnings: RouteIssue[];
  strengths: RouteIssue[];
  revised_route: {
    stops: string[];
    nights: number[];
    summary: string;
    travel_load: TravelLoad | null;
    rationale: string;
  } | null;
  proposed_fixes: { summary: string; changed: string[]; gained: string[]; lost: string[]; evidence_ids: string[] }[];
  unknowns: string[];
  unresolved_places: string[];
  conflicts: ConflictingEvidence[];
  confidence: Confidence;
  human_review_required: boolean;
  human_review_task_id: string | null;
  citations: Citation[];
  resolved_facts: ResolvedFact[];
  superseded_by: string | null;
  demo_mode: boolean;
  rules_version: string;
  prompt_versions: Record<string, string>;
}

export interface AnalysisEnvelope<T> {
  analysis_id: string;
  trip_id: string | null;
  trip_token: string | null;
  kind: string;
  status: string;
  demo_mode: boolean;
  demo_providers: Record<string, boolean>;
  latency_ms: number;
  trace: Record<string, unknown>;
  result: T;
}

export interface TripOut {
  id: string;
  title: string;
  trip: Record<string, unknown>;
  visited: string[];
  candidate_region: string | null;
  rejected_regions: Record<string, string>;
  verified_warnings: string[];
  decisions: string[];
  analyses: { analysis_id: string; kind: string; status: string; confidence: string | null; human_review_required: boolean; created_at: string | null; summary: string }[];
  created_at: string | null;
  updated_at: string | null;
}

export interface EvidenceDetail {
  evidence_id: string;
  content: string;
  source_id: string;
  source_title: string;
  source_url: string | null;
  source_type: string;
  official_source: boolean;
  trust_level: string;
  topic: string;
  region_code: string | null;
  place_slug: string | null;
  verified_at: string | null;
  freshness: Freshness;
  freshness_label: string;
  is_demo: boolean;
}

export interface PricingPlan {
  id: string;
  name: string;
  price_aud: number;
  cadence: string;
  description: string;
  features: string[];
  cta: string;
  highlight: boolean;
}

export interface ProvidersInfo {
  providers: Record<string, { provider: string; demo: boolean; model?: string }>;
  demo_mode: boolean;
}

export interface ApiError {
  error: { code: string; message: string; details: Record<string, unknown> };
}
