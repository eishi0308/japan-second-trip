/**
 * API client.
 *
 * Server components call the API directly over the internal address; browser
 * components go through the public one. Keeping both in one module means a page
 * never has to think about which side it is on.
 */

import type {
  AnalysisEnvelope,
  EvidenceDetail,
  PricingPlan,
  ProvidersInfo,
  RouteCheckResult,
  TripOut,
  WhereNextResult,
} from "./types";

const SERVER_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const CLIENT_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const isServer = typeof window === "undefined";
export const apiBase = () => (isServer ? SERVER_BASE : CLIENT_BASE);

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "error",
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string;
  /** Server-side fetches are uncached by default: an analysis is never stale-servable. */
  revalidate?: number | false;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, revalidate = false, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${apiBase()}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    ...(isServer ? { cache: revalidate === false ? ("no-store" as const) : undefined, next: revalidate === false ? undefined : { revalidate } } : {}),
  });

  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = (payload as { error?: { message?: string; code?: string; details?: Record<string, unknown> } } | null)?.error;
    throw new ApiRequestError(
      error?.message ?? `Request failed with ${response.status}`,
      response.status,
      error?.code ?? "error",
      error?.details ?? {},
    );
  }
  return payload as T;
}

export const api = {
  whereNext: (body: unknown) =>
    apiFetch<AnalysisEnvelope<WhereNextResult>>("/api/v1/where-next", { method: "POST", body }),
  getWhereNext: (id: string) =>
    apiFetch<AnalysisEnvelope<WhereNextResult>>(`/api/v1/where-next/${id}`),
  routeCheck: (body: unknown) =>
    apiFetch<AnalysisEnvelope<RouteCheckResult>>("/api/v1/route-check", { method: "POST", body }),
  getRouteCheck: (id: string) =>
    apiFetch<AnalysisEnvelope<RouteCheckResult>>(`/api/v1/route-check/${id}`),
  getTrip: (id: string, token?: string) => apiFetch<TripOut>(`/api/v1/trips/${id}`, { token }),
  patchTrip: (id: string, body: unknown, token?: string) =>
    apiFetch<TripOut>(`/api/v1/trips/${id}`, { method: "PATCH", body, token }),
  getEvidence: (id: string) => apiFetch<EvidenceDetail>(`/api/v1/evidence/${id}`),
  feedback: (body: unknown) => apiFetch<{ id: string }>("/api/v1/feedback", { method: "POST", body }),
  pricing: () => apiFetch<PricingPlan[]>("/pricing", { revalidate: 300 }),
  // Deliberately uncached. With a revalidate window this is evaluated during
  // `next build` — inside the image build, where no API exists — so DemoBanner
  // caught the failure, rendered nothing, and that empty banner was baked into
  // the prerendered HTML. A freshly deployed container then served the product's
  // central honesty claim as absent until the first revalidation. Demo status
  // must reflect the running system, so it is read per request.
  providers: () => apiFetch<ProvidersInfo>("/providers"),
  admin: {
    reviews: (token: string) => apiFetch<{ reviews: AdminReview[] }>("/api/v1/admin/reviews", { token }),
    resolve: (token: string, id: string, body: unknown) =>
      apiFetch<Record<string, unknown>>(`/api/v1/admin/reviews/${id}/resolve`, { method: "POST", body, token }),
    sources: (token: string) => apiFetch<{ sources: AdminSource[] }>("/api/v1/admin/sources", { token }),
    createSource: (token: string, body: unknown) =>
      apiFetch<Record<string, unknown>>("/api/v1/admin/sources", { method: "POST", body, token }),
    refreshSource: (token: string, id: string) =>
      apiFetch<Record<string, unknown>>(`/api/v1/admin/sources/${id}/refresh`, { method: "POST", body: {}, token }),
    queue: (token: string) => apiFetch<VerificationQueue>("/api/v1/admin/verification/queue", { token }),
    assistant: (token: string, body: unknown) =>
      apiFetch<AssistantAnswer>("/api/v1/admin/assistant", { method: "POST", body, token }),
    runs: (token: string) => apiFetch<{ runs: AgentRunRow[] }>("/api/v1/admin/runs", { token }),
    run: (token: string, id: string) => apiFetch<RunDetail>(`/api/v1/admin/runs/${id}`, { token }),
    metrics: (token: string) => apiFetch<Record<string, unknown>>("/api/v1/admin/metrics", { token }),
    evals: (token: string) => apiFetch<{ runs: EvalRunRow[] }>("/api/v1/admin/evals", { token }),
    failedTools: (token: string) => apiFetch<{ failed: FailedToolRow[] }>("/api/v1/admin/tool-calls/failed", { token }),
    staleEvidence: (token: string) => apiFetch<{ stale: StaleEvidenceRow[] }>("/api/v1/admin/evidence/stale", { token }),
  },
};

export interface AdminReview {
  id: string;
  reason: string;
  subject: string;
  field_name: string | null;
  question: string;
  candidate_values: string[];
  evidence_ids: string[];
  status: string;
  priority: string;
  analysis_id: string | null;
  created_at: string | null;
  resolved_value: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resumed: boolean;
}

export interface AdminSource {
  id: string;
  title: string;
  url: string | null;
  domain: string | null;
  source_type: string;
  official_source: boolean;
  trust_level: string;
  region_code: string | null;
  place_slug: string | null;
  status: string;
  is_demo: boolean;
  fetched_at: string | null;
  verified_at: string | null;
  content_hash: string | null;
  chunk_count: number;
}

export interface VerificationQueue {
  stale_facts: { subject: string; field_name: string; value: string; verified_at: string | null; freshness: string; topic: string }[];
  changed_sources: { source_id: string; title: string; url: string | null; content_hash: string | null }[];
  open_reviews: AdminReview[];
}

export interface AssistantAnswer {
  summary: string;
  findings: { subject: string; issue: string; severity: string; values: string[]; evidence_ids: string[]; verified_at: string | null; review_task_id: string | null }[];
  suggested_actions: string[];
  detail: string;
  evidence: { evidence_id: string; source_title: string; freshness: string; snippet: string }[];
  tools_available: string[];
  can_write_trip_state: boolean;
  trace: Record<string, unknown>;
}

export interface AgentRunRow {
  id: string;
  analysis_id: string | null;
  graph_name: string;
  thread_id: string;
  status: string;
  node_path: string[];
  step_count: number;
  latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number;
  model_calls: number;
  retries: number;
  fallbacks_used: string[];
  trace_id: string | null;
  error: string | null;
  created_at: string | null;
}

export interface RunDetail {
  run: Record<string, unknown>;
  tool_calls: { id: string; node: string | null; tool_name: string; transport: string; arguments: Record<string, unknown>; result_summary: Record<string, unknown>; ok: boolean; error: string | null; latency_ms: number; attempts: number; cache_hit: boolean }[];
  analysis: Record<string, unknown> | null;
}

export interface EvalRunRow {
  id: string;
  suite: string;
  dataset: string;
  variant: string;
  metrics: Record<string, number | string | Record<string, unknown>>;
  case_count: number;
  passed: number;
  failed: number;
  duration_ms: number;
  git_sha: string | null;
  created_at: string | null;
}

export interface FailedToolRow {
  id: string;
  run_id: string | null;
  tool_name: string;
  node: string | null;
  error: string | null;
  attempts: number;
  latency_ms: number;
  created_at: string | null;
}

export interface StaleEvidenceRow {
  evidence_id: string;
  source_id: string;
  source_title: string;
  topic: string;
  region_code: string | null;
  verified_at: string | null;
  snippet: string;
}
