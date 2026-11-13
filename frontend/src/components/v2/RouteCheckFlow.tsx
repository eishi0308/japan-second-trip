"use client";

import { useState } from "react";
import type { CheckRequest, CheckResponse, ParsedItinerary } from "@/lib/v2";
import { MONTHS, v2 } from "@/lib/v2";
import { CheckWorkspace } from "./CheckWorkspace";
import { Icon } from "./ui";

const SAMPLE = "Tokyo 3N, Sendai 1N, Ginzan Onsen 1N, Aomori 1N, Hakodate 1N, Tokyo";

/** Paste → confirm the parsed table → results (PRODUCT_AMENDMENTS.md §3). */
export function RouteCheckFlow() {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedItinerary | null>(null);
  const [rows, setRows] = useState<{ name: string; nights: number; pinned: boolean; status: string }[]>([]);
  const [month, setMonth] = useState("");
  const [arrival, setArrival] = useState("");
  const [departure, setDeparture] = useState("");
  const [confirmed, setConfirmed] = useState<{ request: CheckRequest; response: CheckResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function parse() {
    setBusy(true);
    setError(null);
    try {
      const p = await v2.parse(text);
      setParsed(p);
      setRows(p.rows.map((r) => ({ name: r.slug && r.status === "known" ? r.matched_name ?? r.name : r.name, nights: r.nights, pinned: false, status: r.status })));
      setArrival(p.arrival_city ?? "");
      setDeparture(p.departure_city ?? "");
    } catch {
      setError("We could not read that just now. Try again, or type the stops into the table.");
      setParsed({ rows: [], arrival_city: null, departure_city: null, to_confirm: [], source: "failed" });
      setRows([{ name: "", nights: 1, pinned: false, status: "unknown" }]);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    setError(null);
    const request: CheckRequest = {
      stops: rows.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), nights: r.nights, pinned: r.pinned })),
      month: Number(month),
      arrival_city: arrival || null,
      departure_city: departure || null,
      mode: "whole_trip",
    };
    try {
      setConfirmed({ request, response: await v2.check(request) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The check did not run.");
    } finally {
      setBusy(false);
    }
  }

  if (confirmed) {
    return (
      <div>
        <button type="button" className="btn-ghost mb-6 px-0" onClick={() => setConfirmed(null)}>
          ← Edit the table
        </button>
        <CheckWorkspace initialRequest={confirmed.request} initialResponse={confirmed.response} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <section className="card p-5 sm:p-6" aria-labelledby="paste">
        <h2 id="paste" className="font-serif text-title text-ink-900">
          1. Paste your itinerary
        </h2>
        <textarea
          className="field mt-4 min-h-32"
          aria-label="Your itinerary"
          placeholder={SAMPLE}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-3">
          <button type="button" className="btn-primary" disabled={!text.trim() || busy} onClick={parse}>
            {busy && !parsed ? "Reading…" : "Read my itinerary"}
          </button>
          <button type="button" className="btn-ghost" onClick={() => setText(SAMPLE)}>
            Use an example
          </button>
        </div>
      </section>

      {parsed ? (
        <section className="card p-5 sm:p-6" aria-labelledby="confirm">
          <h2 id="confirm" className="font-serif text-title text-ink-900">
            2. Check we read it right
          </h2>
          <p className="mt-1 text-sm text-ink-500">Edit anything that is wrong. Nothing is checked until you confirm.</p>
          {parsed.to_confirm.length ? (
            <ul className="mt-4 space-y-1.5">
              {parsed.to_confirm.map((line) => (
                <li key={line} className="flex gap-2 rounded-md border border-signal-warning/30 bg-signal-warning/[0.06] px-3 py-2 text-[0.85rem] text-ink-800">
                  <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-signal-warning" />
                  {line}
                </li>
              ))}
            </ul>
          ) : null}
          <table className="mt-4 w-full text-left text-[0.9rem]">
            <thead>
              <tr className="border-b border-ink-200 text-[0.75rem] uppercase tracking-wide text-ink-500">
                <th className="py-2 pr-2 font-medium">Stop</th>
                <th className="w-24 py-2 pr-2 font-medium">Nights</th>
                <th className="w-20 py-2 pr-2 font-medium">Pin</th>
                <th className="w-10 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={`border-b border-ink-100 ${r.status === "unknown" ? "bg-signal-warning/[0.06]" : ""}`}>
                  <td className="py-2 pr-2">
                    <input
                      className="field py-1.5"
                      aria-label={`Stop ${i + 1}`}
                      value={r.name}
                      onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, name: e.target.value, status: "edited" } : x)))}
                    />
                    {r.status === "unknown" ? <p className="mt-1 text-[0.75rem] text-signal-warning">Not in our database: we can only check travel to and from it.</p> : null}
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      min={0}
                      max={30}
                      className="field py-1.5"
                      aria-label={`Nights at stop ${i + 1}`}
                      value={r.nights}
                      onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, nights: Number(e.target.value) } : x)))}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="checkbox"
                      aria-label={`Pin stop ${i + 1}`}
                      checked={r.pinned}
                      onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, pinned: e.target.checked } : x)))}
                    />
                  </td>
                  <td className="py-2">
                    <button type="button" className="btn-ghost px-2 py-1" aria-label={`Remove stop ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="btn-ghost mt-2" onClick={() => setRows([...rows, { name: "", nights: 1, pinned: false, status: "edited" }])}>
            + Add a stop
          </button>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <label className="text-sm text-ink-700">
              Travel month
              <select className="field mt-1" value={month} onChange={(e) => setMonth(e.target.value)} required>
                <option value="">Choose a month</option>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-ink-700">
              Arriving in
              <input className="field mt-1" value={arrival} onChange={(e) => setArrival(e.target.value)} placeholder="First stop" />
            </label>
            <label className="text-sm text-ink-700">
              Leaving from
              <input className="field mt-1" value={departure} onChange={(e) => setDeparture(e.target.value)} placeholder="Last stop" />
            </label>
          </div>
          <button type="button" className="btn-primary mt-6" disabled={!month || !rows.some((r) => r.name.trim() && r.nights > 0) || busy} onClick={run}>
            {busy ? "Checking…" : "This is right: check it"}
          </button>
        </section>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-signal-critical">
          {error}
        </p>
      ) : null}
    </div>
  );
}
