"use client";

import { useState } from "react";
import { ApiRequestError, api } from "@/lib/api";

const EXAMPLE = `Tokyo 3 nights
Sendai 1 night
Ginzan Onsen 1 night
Aomori 1 night
Hakodate 1 night
Tokyo`;

interface Stop {
  name: string;
  nights: string;
}

export function RouteCheckForm() {
  const [mode, setMode] = useState<"text" | "stops">("text");
  const [text, setText] = useState("");
  const [stops, setStops] = useState<Stop[]>([
    { name: "", nights: "2" },
    { name: "", nights: "2" },
  ]);
  const [arrival, setArrival] = useState("Tokyo");
  const [departure, setDeparture] = useState("Tokyo");
  const [driving, setDriving] = useState("no_car");
  const [pace, setPace] = useState("");
  const [luggage, setLuggage] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filledStops = stops.filter((s) => s.name.trim());
  const canSubmit = mode === "text" ? text.trim().length > 3 : filledStops.length >= 2;

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const response = await api.routeCheck({
        itinerary_text: mode === "text" ? text : null,
        stops:
          mode === "stops"
            ? filledStops.map((s) => ({ name: s.name.trim(), nights: Number(s.nights) || 0 }))
            : [],
        trip: {
          arrival_city: arrival || null,
          departure_city: departure || null,
          driving: driving || null,
          pace: pace || null,
          large_luggage: luggage,
          start_date: startDate || null,
        },
      });
      if (response.trip_token && response.trip_id) {
        try {
          window.localStorage.setItem(`jst.trip.${response.trip_id}`, response.trip_token);
        } catch {
          /* ignore */
        }
      }
      // A full navigation, not router.push. The result page is force-dynamic and
      // server-rendered, there is no client state worth carrying across, and the
      // user has just waited on an analysis — so one page load costs nothing.
      // It also avoids a Next 15 failure mode where an RSC navigation issued
      // after an await is aborted and the router silently stays put.
      window.location.assign(`/route-check/result/${response.analysis_id}`);
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not reach the analysis service. Check the API is running and try again.",
      );
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="flex gap-1 rounded-md border border-ink-200 bg-ink-50 p-1" role="tablist" aria-label="Input mode">
        {(
          [
            ["text", "Paste it as you'd write it"],
            ["stops", "Enter stops one by one"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
            className={`flex-1 rounded px-3 py-2 text-[0.85rem] transition-colors ${
              mode === value ? "bg-white text-ink-900 shadow-sm" : "text-ink-600 hover:text-ink-900"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {mode === "text" ? (
          <div>
            <label className="label" htmlFor="itinerary">
              Your itinerary
            </label>
            <textarea
              id="itinerary"
              rows={8}
              className="field mt-2 resize-y font-mono text-[0.88rem] leading-relaxed"
              placeholder={EXAMPLE}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="mt-2 flex items-center justify-between">
              <p className="text-[0.78rem] text-ink-500">
                Free text is fine — nights per stop is all that matters.
              </p>
              <button
                type="button"
                className="text-[0.78rem] text-ink-600 underline underline-offset-4 hover:text-ink-900"
                onClick={() => setText(EXAMPLE)}
              >
                Use the example
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2.5">
            <p className="label">Stops in order</p>
            {stops.map((stop, index) => (
              <div key={index} className="flex gap-2.5">
                <input
                  className="field flex-1"
                  placeholder={index === 0 ? "Tokyo" : "Sendai"}
                  value={stop.name}
                  aria-label={`Stop ${index + 1} name`}
                  onChange={(e) =>
                    setStops((prev) => prev.map((s, i) => (i === index ? { ...s, name: e.target.value } : s)))
                  }
                />
                <input
                  type="number"
                  min={0}
                  max={30}
                  className="field w-24"
                  aria-label={`Nights at stop ${index + 1}`}
                  value={stop.nights}
                  onChange={(e) =>
                    setStops((prev) => prev.map((s, i) => (i === index ? { ...s, nights: e.target.value } : s)))
                  }
                />
                <button
                  type="button"
                  className="btn-ghost px-2.5"
                  aria-label={`Remove stop ${index + 1}`}
                  onClick={() => setStops((prev) => prev.filter((_, i) => i !== index))}
                  disabled={stops.length <= 2}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn-secondary mt-1"
              onClick={() => setStops((prev) => [...prev, { name: "", nights: "1" }])}
            >
              Add a stop
            </button>
          </div>
        )}
      </div>

      <fieldset className="mt-8 border-t border-ink-200 pt-6">
        <legend className="label mb-4">Trip context</legend>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <label className="block">
            <span className="label">Flying into</span>
            <input className="field mt-1.5" value={arrival} onChange={(e) => setArrival(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Flying out of</span>
            <input className="field mt-1.5" value={departure} onChange={(e) => setDeparture(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Start date</span>
            <input
              type="date"
              className="field mt-1.5"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="label">Transport</span>
            <select className="field mt-1.5" value={driving} onChange={(e) => setDriving(e.target.value)}>
              <option value="no_car">Public transport only</option>
              <option value="willing">Willing to drive</option>
              <option value="prefers_car">Driving throughout</option>
              <option value="">Not sure</option>
            </select>
          </label>
          <label className="block">
            <span className="label">Pace you wanted</span>
            <select className="field mt-1.5" value={pace} onChange={(e) => setPace(e.target.value)}>
              <option value="">No preference</option>
              <option value="relaxed">Relaxed</option>
              <option value="balanced">Balanced</option>
              <option value="fast">Fast</option>
            </select>
          </label>
          <label className="mt-6 flex items-center gap-2.5 text-[0.9rem] text-ink-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={luggage}
              onChange={(e) => setLuggage(e.target.checked)}
            />
            Large suitcases
          </label>
        </div>
      </fieldset>

      {error ? (
        <p className="mt-6 rounded-md border border-signal-critical/30 bg-signal-critical/[0.06] px-4 py-3 text-[0.88rem] text-signal-critical" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-8 flex items-center gap-3 border-t border-ink-200 pt-6">
        <button type="button" className="btn-primary" onClick={submit} disabled={!canSubmit || submitting}>
          {submitting ? "Checking…" : "Check this route"}
        </button>
        {!canSubmit ? (
          <p className="text-[0.82rem] text-ink-500">
            {mode === "text" ? "Paste an itinerary to continue." : "Add at least two named stops."}
          </p>
        ) : null}
      </div>

      {submitting ? (
        <p className="mt-4 text-[0.85rem] text-ink-500" role="status" aria-live="polite">
          Resolving stops, costing every hop with real transport data, and running the route rules…
        </p>
      ) : null}
    </div>
  );
}
