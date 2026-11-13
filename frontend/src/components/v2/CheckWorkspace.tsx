"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Alternative, CheckRequest, CheckResponse, Fix, StopIn } from "@/lib/v2";
import { v2 } from "@/lib/v2";
import { AssumptionList, BookingList, DayTimeline, IssueList, RouteMap, VerdictHeader } from "./CheckViews";
import { FullReportButton } from "./FullReportButton";
import { Icon } from "./ui";

export const tokenKey = (tripId: string) => `jst-trip-token:${tripId}`;

const DEFAULT_ASSUMPTIONS = { leave_hotel: "09:30", day_end: "18:30", landing: "14:00", flight_cutoff: "15:00" };

/**
 * One itinerary, editable, re-checked on every change (PRODUCT_AMENDMENTS.md §4
 * "Customise"). Used by option detail, RouteCheck results and saved trips.
 */
export function CheckWorkspace({
  initialRequest,
  initialResponse,
  planId,
  trip,
  readOnly = false,
}: {
  initialRequest: CheckRequest;
  initialResponse?: CheckResponse;
  planId?: string | null;
  trip?: { id: string; token: string };
  readOnly?: boolean;
}) {
  const [request, setRequest] = useState<CheckRequest>({ ...initialRequest, assumptions: initialRequest.assumptions ?? DEFAULT_ASSUMPTIONS });
  const [response, setResponse] = useState<CheckResponse | null>(initialResponse ?? null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(initialResponse ? new Date() : null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const first = useRef(!!initialResponse);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    let live = true;
    setPending(true);
    const timer = setTimeout(async () => {
      try {
        const res = trip
          ? (await v2.updateTrip(trip.id, trip.token, { check: request })).result
          : await v2.check(request);
        if (!live) return;
        setResponse(res);
        setCheckedAt(new Date());
        setError(null);
      } catch {
        if (live) setError("We could not re-check just now. Showing the last result we have.");
      } finally {
        if (live) setPending(false);
      }
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [request, trip]);

  const update = (stops: StopIn[]) => setRequest({ ...request, stops });
  const applyFix = (fix: Fix) =>
    update(
      fix.stops.map((s, i) => ({
        name: s.slug ?? s.name,
        nights: s.nights,
        pinned: s.pinned,
        leave_at: matchLeave(fix, i),
      })),
    );

  const check = response?.check;
  return (
    <div className="space-y-10">
      <section aria-labelledby="verdict" aria-busy={pending}>
        <h2 id="verdict" className="sr-only">
          Verdict
        </h2>
        {check ? <VerdictHeader check={check} /> : <p className="text-ink-500">Checking…</p>}
        {error ? (
          <p role="alert" className="mt-3 flex gap-2 text-sm text-signal-warning">
            <Icon name="alert" className="mt-0.5 h-4 w-4" />
            {error}
            {checkedAt ? ` (from ${checkedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })})` : ""}
          </p>
        ) : null}
        {pending ? <p className="mt-2 text-[0.8rem] text-ink-500" aria-live="polite">Re-checking…</p> : null}
        {check ? (
          <div className="mt-4">
            <AssumptionList check={check} />
          </div>
        ) : null}
      </section>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-10">
          {!readOnly ? (
            <section aria-labelledby="stops">
              <h2 id="stops" className="mb-3 font-serif text-title text-ink-900">
                Stops
              </h2>
              <ItineraryEditor
                request={request}
                stops={request.stops}
                kinds={check?.stops.map((s) => s.kind)}
                names={check?.stops.map((s) => s.name)}
                onChange={update}
              />
              <AssumptionEditor request={request} onChange={setRequest} />
            </section>
          ) : null}
          {check ? (
            <section aria-labelledby="days">
              <h2 id="days" className="mb-3 font-serif text-title text-ink-900">
                Day by day
              </h2>
              <DayTimeline days={check.days} issues={check.issues} />
            </section>
          ) : null}
          {check ? (
            <section aria-labelledby="issues">
              <h2 id="issues" className="mb-3 font-serif text-title text-ink-900">
                What to look at
              </h2>
              <IssueList issues={check.issues} onApply={readOnly ? undefined : applyFix} />
            </section>
          ) : null}
        </div>
        <aside className="space-y-8">
          {check ? <RouteMap stops={check.stops} /> : null}
          {check ? (
            <section aria-labelledby="booking">
              <h2 id="booking" className="mb-3 font-serif text-lg text-ink-900">
                To book ahead
              </h2>
              <BookingList items={check.booking} />
            </section>
          ) : null}
          {response?.also_consider.length ? (
            <section aria-labelledby="also">
              <h2 id="also" className="mb-2 font-serif text-lg text-ink-900">
                With these conditions, you could also consider
              </h2>
              <ul className="space-y-2 text-[0.88rem]">
                {response.also_consider.map((o) => (
                  <li key={o.title} className="card p-3">
                    <p className="label text-accent-700">{o.character_label}</p>
                    <p className="font-medium text-ink-900">{o.title}</p>
                    <p className="text-[0.78rem] text-ink-500">
                      {o.nights_label} · {o.fit_label}
                    </p>
                  </li>
                ))}
              </ul>
              <Link href="/plan" className="mt-3 inline-block text-sm text-accent-700 hover:underline">
                Explore in Where Next →
              </Link>
            </section>
          ) : null}
          {!readOnly && !trip ? <SavePanel request={request} planId={planId} /> : null}
          {!readOnly ? <FullReportButton planId={planId} tripId={trip?.id} /> : null}
        </aside>
      </div>
    </div>
  );
}

function matchLeave(fix: Fix, index: number): string | null {
  const m = fix.label.match(/^Leave (.+) at (\d\d:\d\d) instead/);
  return m && m[2] && fix.stops[index]?.name === m[1] ? m[2] : null;
}

function ItineraryEditor({
  request,
  stops,
  kinds,
  names,
  onChange,
}: {
  request: CheckRequest;
  stops: StopIn[];
  kinds?: string[];
  names?: string[];
  onChange: (stops: StopIn[]) => void;
}) {
  const label = (i: number, s: StopIn) =>
    names?.length === stops.length && names[i] ? names[i] : s.name.replace(/-/g, " ");
  const [alts, setAlts] = useState<{ index: number; list: Alternative[] } | null>(null);
  const [adding, setAdding] = useState("");
  const set = (i: number, patch: Partial<StopIn>) => onChange(stops.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: number) => {
    const next = [...stops];
    const a = next[i];
    const b = next[i + d];
    if (!a || !b) return;
    next[i] = b;
    next[i + d] = a;
    onChange(next);
  };
  return (
    <div>
      <ol className="divide-y divide-ink-100 rounded-lg border border-ink-200 bg-white">
        {stops.map((s, i) => (
          <li key={`${s.name}-${i}`} className="flex flex-wrap items-center gap-2 px-3 py-2.5">
            <span className="w-5 text-right text-[0.8rem] tabular-nums text-ink-400">{i + 1}</span>
            <span className={`min-w-32 flex-1 font-medium ${kinds?.[i] === "unknown" ? "text-signal-critical" : "text-ink-900"}`}>
              {label(i, s)}
              {kinds?.[i] === "unknown" ? <span className="ml-2 text-[0.75rem] font-normal">No verified info yet</span> : null}
            </span>
            <span className="flex items-center gap-1" aria-label={`Nights at ${label(i, s)}`}>
              <button type="button" className="btn-ghost px-2 py-1" aria-label="One night less" disabled={s.nights <= (s.pinned ? 1 : 0)} onClick={() => set(i, { nights: s.nights - 1 })}>
                −
              </button>
              <span className="w-14 text-center text-sm tabular-nums">{s.nights}N</span>
              <button type="button" className="btn-ghost px-2 py-1" aria-label="One night more" onClick={() => set(i, { nights: s.nights + 1 })}>
                +
              </button>
            </span>
            <button type="button" aria-pressed={!!s.pinned} className={s.pinned ? "chip-on" : "chip-off"} onClick={() => set(i, { pinned: !s.pinned })}>
              <Icon name="pin" className="h-3 w-3" /> {s.pinned ? "Pinned" : "Pin"}
            </button>
            <button type="button" className="btn-ghost px-2 py-1" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
              ↑
            </button>
            <button type="button" className="btn-ghost px-2 py-1" aria-label="Move down" disabled={i === stops.length - 1} onClick={() => move(i, 1)}>
              ↓
            </button>
            <button
              type="button"
              className="btn-ghost px-2 py-1"
              disabled={!!s.pinned}
              onClick={async () => setAlts({ index: i, list: await v2.alternatives(request, i).catch(() => []) })}
            >
              Swap
            </button>
            <button type="button" className="btn-ghost px-2 py-1" aria-label={`Remove ${label(i, s)}`} disabled={!!s.pinned || stops.length < 2} onClick={() => onChange(stops.filter((_, j) => j !== i))}>
              Remove
            </button>
            {alts?.index === i ? (
              <div className="w-full pl-7 pt-2">
                {alts.list.length ? (
                  <ul className="flex flex-wrap gap-2" aria-label={`Alternatives to ${label(i, s)}`}>
                    {alts.list.map((a) => (
                      <li key={a.slug}>
                        <button
                          type="button"
                          className="chip-off"
                          onClick={() => {
                            set(i, { name: a.slug });
                            setAlts(null);
                          }}
                        >
                          {a.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[0.82rem] text-ink-500">No nearby alternative open in this month.</p>
                )}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      <div className="mt-3 flex gap-2">
        <input className="field max-w-xs py-2" placeholder="Add a stop" aria-label="Add a stop" value={adding} onChange={(e) => setAdding(e.target.value)} />
        <button
          type="button"
          className="btn-secondary px-4 py-2"
          disabled={!adding.trim()}
          onClick={() => {
            const last = stops[stops.length - 1];
            const tail = last && last.nights === 0 ? [last] : [];
            const head = tail.length ? stops.slice(0, -1) : stops;
            onChange([...head, { name: adding.trim(), nights: 1 }, ...tail]);
            setAdding("");
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}

function AssumptionEditor({ request, onChange }: { request: CheckRequest; onChange: (r: CheckRequest) => void }) {
  const a = request.assumptions ?? DEFAULT_ASSUMPTIONS;
  const fields: [keyof typeof DEFAULT_ASSUMPTIONS, string][] = [
    ["leave_hotel", "Leave the hotel"],
    ["day_end", "Sightseeing ends"],
    ...(request.mode !== "regional"
      ? ([
          ["landing", "Reach the first city"],
          ["flight_cutoff", "At the departure city by"],
        ] as [keyof typeof DEFAULT_ASSUMPTIONS, string][])
      : []),
  ];
  return (
    <details className="mt-4">
      <summary className="cursor-pointer text-sm text-accent-700">Change the assumed times</summary>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {fields.map(([key, label]) => (
          <label key={key} className="text-[0.8rem] text-ink-600">
            {label}
            <input
              type="time"
              className="field mt-1 py-1.5"
              value={a[key]}
              onChange={(e) => e.target.value && onChange({ ...request, assumptions: { ...a, [key]: e.target.value } })}
            />
          </label>
        ))}
      </div>
    </details>
  );
}

function SavePanel({ request, planId }: { request: CheckRequest; planId?: string | null }) {
  const router = useRouter();
  const [title, setTitle] = useState("My next Japan trip");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <section aria-labelledby="save" className="card p-4">
      <h2 id="save" className="font-serif text-lg text-ink-900">
        Save this trip
      </h2>
      <p className="mt-1 text-[0.8rem] text-ink-500">Keep it, edit it later, and share a read-only link.</p>
      <form
        className="mt-3 space-y-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const res = await v2.saveTrip({ title, email: email || null, plan_id: planId, check: request });
            try {
              window.localStorage.setItem(tokenKey(res.trip.id as string), res.token);
            } catch {
              /* private mode: the token still travels in the URL hash */
            }
            router.push(`/trip/${res.trip.id}#${res.token}`);
          } catch {
            setError("Could not save. Check the email address and try again.");
            setBusy(false);
          }
        }}
      >
        <input className="field py-2" aria-label="Trip name" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
        <input className="field py-2" aria-label="Email (optional)" type="email" placeholder="Email (optional)" value={email} onChange={(e) => setEmail(e.target.value)} />
        {error ? <p role="alert" className="text-[0.8rem] text-signal-critical">{error}</p> : null}
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "Saving…" : "Save trip"}
        </button>
      </form>
    </section>
  );
}
