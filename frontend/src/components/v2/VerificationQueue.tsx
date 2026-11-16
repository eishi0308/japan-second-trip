"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api";
import type { FactQueueItem, FactResolution } from "@/lib/v2";
import { formatDate, v2 } from "@/lib/v2";
import { FactMark, Icon } from "./ui";

const TOKEN_KEY = "jst.admin.token";
const TIMED = new Set(["last_connection", "ryokan_shuttle"]);

/**
 * /admin: facts that need a person (PRODUCT_AMENDMENTS.md §5), being checked
 * first. Resolving one updates the fact, closes its task and re-checks every
 * saved trip that depends on it.
 */
export function VerificationQueue() {
  const [token, setToken] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [items, setItems] = useState<FactQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, FactResolution>>({});

  const load = useCallback(async (t: string) => {
    setError(null);
    try {
      const res = await v2.factQueue(t);
      setItems(res.items);
      setToken(t);
      try {
        window.sessionStorage.setItem(TOKEN_KEY, t);
      } catch {
        /* ignore */
      }
    } catch (err) {
      setToken(null);
      setError(err instanceof ApiRequestError && (err.status === 401 || err.status === 403) ? "That token was rejected." : "Could not reach the admin API.");
    }
  }, []);

  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem(TOKEN_KEY);
      if (stored) void load(stored);
    } catch {
      /* ignore */
    }
  }, [load]);

  if (!token) {
    return (
      <form
        className="card max-w-md p-6"
        onSubmit={(e) => {
          e.preventDefault();
          void load(draft);
        }}
      >
        <label className="label" htmlFor="queue-token">
          Admin token
        </label>
        <input id="queue-token" type="password" className="field mt-2" value={draft} onChange={(e) => setDraft(e.target.value)} autoComplete="off" />
        {error ? <p role="alert" className="mt-2 text-sm text-signal-critical">{error}</p> : null}
        <button type="submit" className="btn-primary mt-4" disabled={!draft}>
          Open the queue
        </button>
      </form>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-ink-600">{items?.length ?? 0} facts need a person.</p>
        <button type="button" className="btn-ghost px-3 py-1.5" onClick={() => void load(token)}>
          Refresh
        </button>
        <Link href="/admin/ops" className="text-sm text-accent-700 hover:underline">
          Operations console →
        </Link>
      </div>
      {Object.values(done).length ? (
        <ul className="mt-4 space-y-1.5" aria-live="polite">
          {Object.values(done).map((r) => (
            <li key={r.fact_id} className="flex gap-2 text-[0.85rem] text-signal-good">
              <Icon name="check" className="mt-0.5 h-4 w-4" />
              Resolved{r.value ? ` as ${r.value}` : ""}. {r.tasks_closed} task closed, {r.trips_updated.length} saved trip
              {r.trips_updated.length === 1 ? "" : "s"} re-checked and notified.
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="mt-6 space-y-4">
        {(items ?? []).map((item) => (
          <QueueRow
            key={item.fact_id}
            item={item}
            token={token}
            onResolved={(r) => {
              setDone((d) => ({ ...d, [r.fact_id]: r }));
              void load(token);
            }}
          />
        ))}
        {items && !items.length ? <li className="card p-6 text-ink-600">Nothing to check. Every fact is dated and current.</li> : null}
      </ul>
    </div>
  );
}

function QueueRow({ item, token, onResolved }: { item: FactQueueItem; token: string; onResolved: (r: FactResolution) => void }) {
  const timed = TIMED.has(item.kind);
  const [value, setValue] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("admin");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canConfirm = item.state !== "being_checked";

  return (
    <li className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <FactMark state={item.state} date={item.verified_at} />
        {item.severity === "critical" ? <span className="text-[0.75rem] font-medium text-signal-critical">Can break a stay</span> : null}
        {item.task_id ? <span className="text-[0.75rem] text-ink-500">Review requested</span> : null}
        <span className="text-[0.75rem] text-ink-500">
          {item.trips_affected} saved trip{item.trips_affected === 1 ? "" : "s"} depend on this
        </span>
      </div>
      <p className="mt-2 font-medium text-ink-900">
        {item.destination}: {item.title}
      </p>
      <p className="mt-1 text-[0.88rem] text-ink-700">{item.detail}</p>
      <p className="mt-1 text-[0.82rem] text-ink-500">
        {item.candidate_values.length ? `Reported values: ${item.candidate_values.join(", ")}` : null}
        {item.current_value ? `Last confirmed value: ${item.current_value}` : null}
        {item.verified_at ? ` (checked ${formatDate(item.verified_at)})` : " (never checked)"}
      </p>
      <form
        className="mt-4 grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)_8rem_auto] sm:items-end"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            onResolved(
              await v2.resolveFact(token, item.fact_id, {
                value: timed ? value || null : null,
                source_url: url || null,
                note: note || null,
                reviewer,
              }),
            );
          } catch (err) {
            setError(err instanceof ApiRequestError ? err.message : "Could not resolve.");
            setBusy(false);
          }
        }}
      >
        {timed ? (
          <label className="text-[0.8rem] text-ink-600">
            Confirmed time
            <input
              className="field mt-1 py-1.5"
              placeholder="HH:MM"
              pattern="^([01]\d|2[0-3]):[0-5]\d$"
              required={!canConfirm}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
        ) : (
          <span />
        )}
        <label className="text-[0.8rem] text-ink-600">
          Source link
          <input className="field mt-1 py-1.5" type="url" placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} />
        </label>
        <label className="text-[0.8rem] text-ink-600">
          Note
          <input className="field mt-1 py-1.5" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </label>
        <label className="text-[0.8rem] text-ink-600">
          Reviewer
          <input className="field mt-1 py-1.5" value={reviewer} onChange={(e) => setReviewer(e.target.value)} required />
        </label>
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "Saving…" : timed && value ? "Confirm this time" : canConfirm ? "Still correct" : "Confirm"}
        </button>
      </form>
      {error ? <p role="alert" className="mt-2 text-sm text-signal-critical">{error}</p> : null}
    </li>
  );
}
