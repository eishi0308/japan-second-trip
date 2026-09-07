"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, api } from "@/lib/api";
import type {
  AdminReview,
  AdminSource,
  AgentRunRow,
  AssistantAnswer,
  EvalRunRow,
  FailedToolRow,
  RunDetail,
  VerificationQueue,
} from "@/lib/api";
import { Badge, SectionHeading, Skeleton } from "@/components/primitives";

const TABS = [
  { id: "queue", label: "Verification queue" },
  { id: "assistant", label: "Assistant" },
  { id: "sources", label: "Sources" },
  { id: "runs", label: "Agent runs" },
  { id: "evals", label: "Evals" },
  { id: "ops", label: "Operations" },
] as const;

type TabId = (typeof TABS)[number]["id"];
const TOKEN_KEY = "jst.admin.token";

export function AdminConsole() {
  const [token, setToken] = useState("");
  const [authed, setAuthed] = useState(false);
  const [tab, setTab] = useState<TabId>("queue");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem(TOKEN_KEY);
      if (stored) {
        setToken(stored);
        setAuthed(true);
      }
    } catch {
      /* ignore */
    }
  }, []);

  async function authenticate(candidate: string) {
    setChecking(true);
    setError(null);
    try {
      await api.admin.reviews(candidate);
      // Session storage, not local: an admin token should not outlive the tab.
      try {
        window.sessionStorage.setItem(TOKEN_KEY, candidate);
      } catch {
        /* ignore */
      }
      setToken(candidate);
      setAuthed(true);
    } catch (err) {
      setError(
        err instanceof ApiRequestError && err.status === 401
          ? "That token was rejected."
          : "Could not reach the admin API.",
      );
    } finally {
      setChecking(false);
    }
  }

  if (!authed) {
    return (
      <form
        className="card max-w-md p-6"
        onSubmit={(e) => {
          e.preventDefault();
          void authenticate(token);
        }}
      >
        <label className="label" htmlFor="admin-token">
          Admin token
        </label>
        <input
          id="admin-token"
          type="password"
          className="field mt-2"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="ADMIN_TOKEN"
          autoComplete="off"
        />
        <p className="mt-2 text-[0.78rem] text-ink-500">
          Held in session storage only, and never sent anywhere but this API.
        </p>
        {error ? (
          <p className="mt-3 text-[0.85rem] text-signal-critical" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" className="btn-primary mt-5 w-full" disabled={checking || !token}>
          {checking ? "Checking…" : "Sign in"}
        </button>
      </form>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1 border-b border-ink-200" role="tablist" aria-label="Admin sections">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-[0.88rem] transition-colors ${
              tab === item.id
                ? "border-ink-900 text-ink-900"
                : "border-transparent text-ink-500 hover:text-ink-800"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mt-8">
        {tab === "queue" ? <QueueTab token={token} /> : null}
        {tab === "assistant" ? <AssistantTab token={token} /> : null}
        {tab === "sources" ? <SourcesTab token={token} /> : null}
        {tab === "runs" ? <RunsTab token={token} /> : null}
        {tab === "evals" ? <EvalsTab token={token} /> : null}
        {tab === "ops" ? <OpsTab token={token} /> : null}
      </div>
    </div>
  );
}

function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loader());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, loading, error, reload };
}

function Panel({
  loading,
  error,
  children,
}: {
  loading: boolean;
  error: string | null;
  children: React.ReactNode;
}) {
  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (error) {
    return (
      <p className="card border-signal-critical/30 p-5 text-[0.88rem] text-signal-critical" role="alert">
        {error}
      </p>
    );
  }
  return <>{children}</>;
}

function QueueTab({ token }: { token: string }) {
  const { data, loading, error, reload } = useAsync<VerificationQueue>(() => api.admin.queue(token), [token]);

  return (
    <Panel loading={loading} error={error}>
      <SectionHeading
        eyebrow="Human in the loop"
        title="Open review tasks"
        description="Raised when approved sources disagree, a critical fact goes stale, or a grounding check fails. Resolving one writes a verification record and re-runs every analysis that was blocked on it."
      />
      {data?.open_reviews.length === 0 ? (
        <p className="card p-5 text-[0.88rem] text-ink-600">Queue is clear.</p>
      ) : (
        <div className="space-y-4">
          {data?.open_reviews.map((review) => (
            <ReviewCard key={review.id} review={review} token={token} onResolved={reload} />
          ))}
        </div>
      )}

      <div className="mt-10 grid gap-8 lg:grid-cols-2">
        <div>
          <SectionHeading eyebrow="Freshness" title="Facts past their re-check window" />
          {data?.stale_facts.length === 0 ? (
            <p className="card p-5 text-[0.88rem] text-ink-600">Nothing stale.</p>
          ) : (
            <ul className="card divide-y divide-ink-200">
              {data?.stale_facts.map((fact) => (
                <li key={`${fact.subject}-${fact.field_name}`} className="px-5 py-3.5">
                  <p className="text-[0.9rem] font-medium text-ink-900">{fact.subject}</p>
                  <p className="mt-0.5 text-[0.84rem] text-ink-600">
                    {fact.field_name} = {fact.value}
                  </p>
                  <p className="mt-1.5 flex items-center gap-2 text-[0.76rem] text-ink-500">
                    <Badge tone="critical">{fact.freshness}</Badge>
                    topic {fact.topic.replace(/_/g, " ")} · last verified {fact.verified_at?.slice(0, 10) ?? "never"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <SectionHeading eyebrow="Change detection" title="Sources that changed since verification" />
          {data?.changed_sources.length === 0 ? (
            <p className="card p-5 text-[0.88rem] text-ink-600">No source has changed.</p>
          ) : (
            <ul className="card divide-y divide-ink-200">
              {data?.changed_sources.map((source) => (
                <li key={source.source_id} className="px-5 py-3.5">
                  <p className="text-[0.9rem] font-medium text-ink-900">{source.title}</p>
                  <p className="mt-0.5 font-mono text-[0.72rem] text-ink-500">{source.content_hash?.slice(0, 16)}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}

function ReviewCard({
  review,
  token,
  onResolved,
}: {
  review: AdminReview;
  token: string;
  onResolved: () => void;
}) {
  const [value, setValue] = useState(review.candidate_values[0] ?? "");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("admin");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function resolve(dismiss: boolean) {
    setBusy(true);
    setFailure(null);
    try {
      const result = await api.admin.resolve(token, review.id, {
        resolved_value: value || "dismissed",
        resolution_note: note || null,
        reviewer,
        dismiss,
      });
      setOutcome(String(result.message ?? "Resolved."));
      onResolved();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Could not resolve");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-serif text-[1.05rem] text-ink-900">{review.subject}</p>
          <p className="mt-0.5 text-[0.8rem] text-ink-500">
            {review.reason.replace(/_/g, " ")}
            {review.field_name ? ` · ${review.field_name}` : ""}
          </p>
        </div>
        <Badge tone={review.priority === "high" ? "critical" : "neutral"}>{review.priority}</Badge>
      </div>

      <p className="prose-measure mt-3">{review.question}</p>

      {review.candidate_values.length > 0 ? (
        <div className="mt-4">
          <p className="label mb-2">Values in dispute</p>
          <div className="flex flex-wrap gap-2">
            {review.candidate_values.map((candidate) => (
              <button
                key={candidate}
                type="button"
                className={value === candidate ? "chip-on" : "chip-off"}
                onClick={() => setValue(candidate)}
              >
                {candidate}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {outcome ? (
        <p className="mt-4 rounded-md bg-signal-good/10 px-4 py-3 text-[0.86rem] text-signal-good" role="status">
          {outcome}
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
            <input
              className="field"
              placeholder="Verified value"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label="Verified value"
            />
            <input
              className="field"
              placeholder="Reviewer"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              aria-label="Reviewer name"
            />
          </div>
          <textarea
            rows={2}
            className="field resize-y text-[0.88rem]"
            placeholder="How was this confirmed? (operator phone call, official page, timetable photo…)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {failure ? <p className="text-[0.84rem] text-signal-critical">{failure}</p> : null}
          <div className="flex gap-2.5">
            <button type="button" className="btn-primary" onClick={() => resolve(false)} disabled={busy || !value}>
              {busy ? "Saving…" : "Record verified value"}
            </button>
            <button type="button" className="btn-secondary" onClick={() => resolve(true)} disabled={busy}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {review.evidence_ids.length > 0 ? (
        <p className="mt-3 font-mono text-[0.7rem] text-ink-400">evidence: {review.evidence_ids.join(", ")}</p>
      ) : null}
    </article>
  );
}

function AssistantTab({ token }: { token: string }) {
  const [request, setRequest] = useState("Show me Tohoku evidence that is stale or conflicting");
  const [region, setRegion] = useState("");
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.admin.assistant(token, { request, region_code: region || null }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <SectionHeading
        eyebrow="Third MCP consumer"
        title="Verification assistant"
        description="Triages the same travel-intelligence capabilities the traveller-facing agents use, through the same MCP gateway — with the narrowest permission set of the three. It can read and escalate. It cannot approve its own findings."
      />
      <div className="card p-5">
        <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
          <input
            className="field"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            aria-label="Request"
          />
          <input
            className="field"
            placeholder="region code (optional)"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            aria-label="Region code"
          />
        </div>
        <button type="button" className="btn-primary mt-3" onClick={ask} disabled={busy}>
          {busy ? "Triaging…" : "Ask"}
        </button>
        {error ? <p className="mt-3 text-[0.86rem] text-signal-critical">{error}</p> : null}
      </div>

      {answer ? (
        <div className="mt-6 space-y-5">
          <div className="card p-5">
            <p className="label mb-2">Summary</p>
            <p className="prose-measure">{answer.summary}</p>
          </div>

          {answer.findings.length > 0 ? (
            <ul className="card divide-y divide-ink-200">
              {answer.findings.map((finding) => (
                <li key={`${finding.subject}-${finding.issue}`} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-medium text-ink-900">{finding.subject}</p>
                    <Badge tone={finding.severity === "critical" ? "critical" : "warning"}>
                      {finding.severity}
                    </Badge>
                  </div>
                  <p className="mt-1 text-[0.88rem] leading-relaxed text-ink-700">{finding.issue}</p>
                </li>
              ))}
            </ul>
          ) : null}

          {answer.suggested_actions.length > 0 ? (
            <div className="card p-5">
              <p className="label mb-2">Suggested next steps</p>
              <ul className="space-y-1.5 text-[0.88rem] text-ink-700">
                {answer.suggested_actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="card p-5">
            <p className="label mb-2">Capability boundary</p>
            <p className="text-[0.85rem] text-ink-600">
              Tools this consumer may call: {answer.tools_available.join(", ")}.
            </p>
            <p className="mt-1.5 text-[0.85rem] text-ink-600">
              Can write trip state: <strong>{answer.can_write_trip_state ? "yes" : "no"}</strong>. MCP tool
              calls in this request: {String((answer.trace as { tool_calls?: number }).tool_calls ?? 0)}.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SourcesTab({ token }: { token: string }) {
  const { data, loading, error, reload } = useAsync<{ sources: AdminSource[] }>(
    () => api.admin.sources(token),
    [token],
  );
  const [form, setForm] = useState({ url: "", title: "", region_code: "", terms: false });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function ingest() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.admin.createSource(token, {
        url: form.url || null,
        title: form.title,
        region_code: form.region_code || null,
        terms_confirmed: form.terms,
        source_type: "official_tourism",
        trust_level: "primary",
        official_source: true,
      });
      setMessage(`Ingested — ${result.chunks_written} chunk(s) written.`);
      reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel loading={loading} error={error}>
      <SectionHeading
        eyebrow="Knowledge base"
        title="Add a source"
        description="Only allowlisted https domains can be ingested, and the operator must assert that the source's terms permit it. Nothing crawls."
      />
      <div className="card p-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            className="field"
            placeholder="https://www.japan.travel/en/..."
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            aria-label="Source URL"
          />
          <input
            className="field"
            placeholder="Title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            aria-label="Source title"
          />
          <input
            className="field"
            placeholder="region code (optional)"
            value={form.region_code}
            onChange={(e) => setForm({ ...form, region_code: e.target.value })}
            aria-label="Region code"
          />
          <label className="flex items-center gap-2.5 text-[0.86rem] text-ink-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-ink-300 text-accent-600"
              checked={form.terms}
              onChange={(e) => setForm({ ...form, terms: e.target.checked })}
            />
            I confirm this source&rsquo;s terms permit ingestion
          </label>
        </div>
        <button type="button" className="btn-primary mt-3" onClick={ingest} disabled={busy || !form.title}>
          {busy ? "Ingesting…" : "Ingest"}
        </button>
        {message ? <p className="mt-3 text-[0.86rem] text-ink-700">{message}</p> : null}
      </div>

      <div className="mt-8">
        <SectionHeading eyebrow="Knowledge base" title={`Sources (${data?.sources.length ?? 0})`} />
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[46rem] text-left text-[0.84rem]">
            <thead className="border-b border-ink-200 text-ink-500">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Title</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Type</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Region</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Chunks</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Verified</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {data?.sources.map((source) => (
                <tr key={source.id}>
                  <td className="px-4 py-2.5 text-ink-900">
                    {source.title}
                    {source.is_demo ? <Badge tone="warning" className="ml-2">demo</Badge> : null}
                  </td>
                  <td className="px-4 py-2.5 text-ink-600">{source.source_type.replace(/_/g, " ")}</td>
                  <td className="px-4 py-2.5 text-ink-600">{source.region_code ?? "—"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink-700">{source.chunk_count}</td>
                  <td className="px-4 py-2.5 tabular-nums text-ink-600">{source.verified_at?.slice(0, 10) ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={source.status === "changed" ? "warning" : "neutral"}>{source.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  );
}

function RunsTab({ token }: { token: string }) {
  const { data, loading, error } = useAsync<{ runs: AgentRunRow[] }>(() => api.admin.runs(token), [token]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);

  async function open(id: string) {
    setSelected(id);
    setDetail(null);
    try {
      setDetail(await api.admin.run(token, id));
    } catch {
      setDetail(null);
    }
  }

  return (
    <Panel loading={loading} error={error}>
      <SectionHeading
        eyebrow="Observability"
        title="Agent runs"
        description="Every analysis is replayable: which nodes ran, which tools were called with what arguments, what it cost."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_1fr]">
        <ul className="card max-h-[34rem] divide-y divide-ink-200 overflow-y-auto">
          {data?.runs.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => open(run.id)}
                className={`w-full px-4 py-3 text-left transition-colors hover:bg-ink-50 ${
                  selected === run.id ? "bg-ink-50" : ""
                }`}
              >
                <span className="flex items-center justify-between gap-3">
                  <span className="text-[0.86rem] font-medium text-ink-900">{run.graph_name}</span>
                  <span className="text-[0.75rem] tabular-nums text-ink-500">{run.latency_ms ?? 0}ms</span>
                </span>
                <span className="mt-0.5 block text-[0.75rem] text-ink-500">
                  {run.step_count} nodes · {run.model_calls} model calls · ${run.estimated_cost_usd.toFixed(4)}
                </span>
                {run.error ? <Badge tone="critical" className="mt-1.5">error</Badge> : null}
              </button>
            </li>
          ))}
        </ul>

        <div>
          {detail ? (
            <div className="space-y-5">
              <div className="card p-5">
                <p className="label mb-2">Node path</p>
                <div className="flex flex-wrap gap-1.5">
                  {(detail.run.node_path as string[]).map((node, i) => (
                    <span key={`${node}-${i}`} className="rounded bg-ink-100 px-2 py-1 font-mono text-[0.72rem] text-ink-700">
                      {node}
                    </span>
                  ))}
                </div>
              </div>
              <div className="card overflow-x-auto">
                <p className="label px-5 pt-4">Tool calls ({detail.tool_calls.length})</p>
                <table className="mt-2 w-full min-w-[40rem] text-left text-[0.8rem]">
                  <thead className="border-b border-ink-200 text-ink-500">
                    <tr>
                      <th scope="col" className="px-5 py-2 font-medium">Tool</th>
                      <th scope="col" className="px-3 py-2 font-medium">Node</th>
                      <th scope="col" className="px-3 py-2 font-medium">Via</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">ms</th>
                      <th scope="col" className="px-3 py-2 font-medium">OK</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {detail.tool_calls.map((call) => (
                      <tr key={call.id}>
                        <td className="px-5 py-2 font-mono text-[0.74rem] text-ink-800">{call.tool_name}</td>
                        <td className="px-3 py-2 text-ink-600">{call.node ?? "—"}</td>
                        <td className="px-3 py-2 text-ink-500">{call.transport}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-ink-600">{call.latency_ms}</td>
                        <td className="px-3 py-2">
                          {call.ok ? <Badge tone="good">ok</Badge> : <Badge tone="critical">fail</Badge>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="card p-5 text-[0.88rem] text-ink-600">Select a run to inspect it.</p>
          )}
        </div>
      </div>
    </Panel>
  );
}

function EvalsTab({ token }: { token: string }) {
  const { data, loading, error } = useAsync<{ runs: EvalRunRow[] }>(() => api.admin.evals(token), [token]);
  return (
    <Panel loading={loading} error={error}>
      <SectionHeading
        eyebrow="Quality"
        title="Eval history"
        description="Written by `python -m evals.run`. Retrieval strategies are recorded as separate variants so a change can be compared like for like."
      />
      {data?.runs.length === 0 ? (
        <p className="card p-5 text-[0.88rem] text-ink-600">
          No eval runs recorded yet. Run <code className="font-mono">python -m evals.run all</code>.
        </p>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-[0.84rem]">
            <thead className="border-b border-ink-200 text-ink-500">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Suite</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Variant</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Passed</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Key metric</th>
                <th scope="col" className="px-4 py-2.5 font-medium">SHA</th>
                <th scope="col" className="px-4 py-2.5 font-medium">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {data?.runs.map((run) => (
                <tr key={run.id}>
                  <td className="px-4 py-2.5 text-ink-900">{run.suite}</td>
                  <td className="px-4 py-2.5 font-mono text-[0.76rem] text-ink-600">{run.variant}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink-700">
                    {run.passed}/{run.case_count}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-ink-600">{keyMetric(run)}</td>
                  <td className="px-4 py-2.5 font-mono text-[0.74rem] text-ink-500">{run.git_sha ?? "—"}</td>
                  <td className="px-4 py-2.5 tabular-nums text-ink-500">{run.created_at?.slice(0, 16).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function keyMetric(run: EvalRunRow): string {
  const m = run.metrics as Record<string, number>;
  if (typeof m["ndcg@8"] === "number") return `ndcg@8 ${m["ndcg@8"].toFixed(3)}`;
  if (typeof m["groundedness"] === "number") return `grounded ${m["groundedness"].toFixed(2)}`;
  if (typeof m["p95_latency_ms"] === "number") return `p95 ${m["p95_latency_ms"]}ms`;
  if (typeof m["pass_rate"] === "number") return `pass ${(m["pass_rate"] * 100).toFixed(0)}%`;
  return "—";
}

function OpsTab({ token }: { token: string }) {
  const metrics = useAsync<Record<string, unknown>>(() => api.admin.metrics(token), [token]);
  const failed = useAsync<{ failed: FailedToolRow[] }>(() => api.admin.failedTools(token), [token]);

  const latency = (metrics.data?.latency ?? {}) as Record<string, { p50_ms: number; p95_ms: number; count: number }>;
  const rates = (metrics.data?.rates ?? {}) as Record<string, number>;
  const cost = (metrics.data?.cost ?? {}) as Record<string, number>;

  return (
    <Panel loading={metrics.loading} error={metrics.error}>
      <SectionHeading eyebrow="Operations" title="Latency, cost and reliability" />
      <div className="grid gap-5 md:grid-cols-2">
        <div className="card p-5">
          <p className="label mb-3">Latency</p>
          <table className="w-full text-left text-[0.84rem]">
            <thead className="text-ink-500">
              <tr>
                <th scope="col" className="pb-1.5 font-medium">Surface</th>
                <th scope="col" className="pb-1.5 text-right font-medium">p50</th>
                <th scope="col" className="pb-1.5 text-right font-medium">p95</th>
                <th scope="col" className="pb-1.5 text-right font-medium">n</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {Object.entries(latency).map(([name, stats]) => (
                <tr key={name}>
                  <td className="py-1.5 font-mono text-[0.76rem] text-ink-700">{name}</td>
                  <td className="py-1.5 text-right tabular-nums text-ink-800">{stats.p50_ms}ms</td>
                  <td className="py-1.5 text-right tabular-nums text-ink-800">{stats.p95_ms}ms</td>
                  <td className="py-1.5 text-right tabular-nums text-ink-500">{stats.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card p-5">
          <p className="label mb-3">Rates &amp; cost</p>
          <dl className="space-y-2 text-[0.86rem]">
            {Object.entries(rates).map(([name, value]) => (
              <div key={name} className="flex justify-between">
                <dt className="text-ink-600">{name.replace(/_/g, " ")}</dt>
                <dd className="tabular-nums text-ink-900">{(value * 100).toFixed(1)}%</dd>
              </div>
            ))}
            <div className="flex justify-between border-t border-ink-100 pt-2">
              <dt className="text-ink-600">total estimated cost</dt>
              <dd className="tabular-nums text-ink-900">${(cost.total_usd ?? 0).toFixed(4)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-600">mean per run</dt>
              <dd className="tabular-nums text-ink-900">${(cost.mean_usd_per_run ?? 0).toFixed(5)}</dd>
            </div>
          </dl>
        </div>
      </div>

      <div className="mt-8">
        <SectionHeading eyebrow="Reliability" title="Failed tool calls" />
        {failed.data?.failed.length === 0 ? (
          <p className="card p-5 text-[0.88rem] text-ink-600">No failed tool calls recorded.</p>
        ) : (
          <ul className="card divide-y divide-ink-200">
            {failed.data?.failed.map((row) => (
              <li key={row.id} className="px-5 py-3">
                <p className="font-mono text-[0.8rem] text-ink-900">{row.tool_name}</p>
                <p className="mt-0.5 text-[0.82rem] text-ink-600">{row.error}</p>
                <p className="mt-0.5 text-[0.74rem] text-ink-400">
                  {row.attempts} attempt(s) · {row.latency_ms}ms · {row.created_at?.slice(0, 16).replace("T", " ")}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
