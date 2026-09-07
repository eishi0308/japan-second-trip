"use client";

import { useMemo, useState } from "react";
import { ApiRequestError, api } from "@/lib/api";

const INTERESTS = ["food", "onsen", "nature", "culture", "hiking", "city", "coast", "snow", "art", "nightlife"] as const;
const GATEWAYS = ["Tokyo", "Osaka", "Kyoto", "Nagoya", "Fukuoka", "Sapporo"] as const;
const COMMON_VISITED = ["Tokyo", "Kyoto", "Osaka", "Hakone", "Nara", "Hiroshima", "Nikko", "Kanazawa", "Takayama"] as const;

interface FormState {
  start_date: string;
  total_nights: string;
  regional_nights: string;
  arrival_city: string;
  departure_city: string;
  visited_places: string[];
  traveller_type: string;
  interests: string[];
  driving: string;
  budget: string;
  pace: string;
  large_luggage: boolean;
  step_free_required: boolean;
  free_text: string;
}

const INITIAL: FormState = {
  start_date: "",
  total_nights: "",
  regional_nights: "",
  arrival_city: "Tokyo",
  departure_city: "Tokyo",
  visited_places: ["Tokyo", "Kyoto", "Osaka"],
  traveller_type: "",
  interests: [],
  driving: "",
  budget: "",
  pace: "",
  large_luggage: false,
  step_free_required: false,
  free_text: "",
};

const STEPS = [
  { id: "trip", title: "The trip", hint: "Dates and shape. All of it optional." },
  { id: "history", title: "Where you've been", hint: "So we don't send you somewhere that feels the same." },
  { id: "style", title: "How you travel", hint: "This is what decides which regions are actually viable." },
] as const;

export function WhereNextForm() {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const toggle = (key: "interests" | "visited_places", value: string) =>
    setForm((prev) => ({
      ...prev,
      [key]: prev[key].includes(value) ? prev[key].filter((v) => v !== value) : [...prev[key], value],
    }));

  const completeness = useMemo(() => {
    const filled = [
      form.start_date,
      form.total_nights,
      form.regional_nights,
      form.arrival_city,
      form.visited_places.length > 0 ? "y" : "",
      form.interests.length > 0 ? "y" : "",
      form.driving,
      form.pace,
    ].filter(Boolean).length;
    return Math.round((filled / 8) * 100);
  }, [form]);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        trip: {
          start_date: form.start_date || null,
          total_nights: form.total_nights ? Number(form.total_nights) : null,
          regional_nights: form.regional_nights ? Number(form.regional_nights) : null,
          arrival_city: form.arrival_city || null,
          departure_city: form.departure_city || null,
          visited_places: form.visited_places,
          traveller_type: form.traveller_type || null,
          interests: form.interests,
          driving: form.driving || null,
          budget: form.budget || null,
          pace: form.pace || null,
          large_luggage: form.large_luggage,
          mobility: form.step_free_required
            ? { step_free_required: true, limited_walking: false, notes: null }
            : null,
          free_text: form.free_text || null,
        },
      };
      const response = await api.whereNext(payload);
      if (response.trip_token && response.trip_id) {
        try {
          window.localStorage.setItem(`jst.trip.${response.trip_id}`, response.trip_token);
        } catch {
          /* private browsing — the trip is still readable by its id */
        }
      }
      // A full navigation, not router.push. The result page is force-dynamic and
      // server-rendered, there is no client state worth carrying across, and the
      // user has just waited on an analysis — so one page load costs nothing.
      // It also avoids a Next 15 failure mode where an RSC navigation issued
      // after an await is aborted and the router silently stays put.
      window.location.assign(`/where-next/result/${response.analysis_id}`);
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not reach the analysis service. Check the API is running and try again.",
      );
      setSubmitting(false);
    }
  }

  const current = STEPS[step]!;

  return (
    <div>
      <ProgressRail step={step} completeness={completeness} onJump={setStep} />

      <div className="mt-8 animate-in" key={current.id}>
        <h2 className="text-title font-serif text-ink-900">{current.title}</h2>
        <p className="prose-measure mt-1.5">{current.hint}</p>

        <div className="mt-7 space-y-7">
          {step === 0 ? <TripStep form={form} set={set} /> : null}
          {step === 1 ? <HistoryStep form={form} set={set} toggle={toggle} /> : null}
          {step === 2 ? <StyleStep form={form} set={set} toggle={toggle} /> : null}
        </div>
      </div>

      {error ? (
        <p className="mt-6 rounded-md border border-signal-critical/30 bg-signal-critical/[0.06] px-4 py-3 text-[0.88rem] text-signal-critical" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-9 flex items-center justify-between gap-4 border-t border-ink-200 pt-6">
        <button
          type="button"
          className="btn-secondary"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0 || submitting}
        >
          Back
        </button>
        <div className="flex items-center gap-3">
          {step < STEPS.length - 1 ? (
            <>
              <button type="button" className="btn-ghost" onClick={submit} disabled={submitting}>
                Skip the rest
              </button>
              <button type="button" className="btn-primary" onClick={() => setStep((s) => s + 1)}>
                Continue
              </button>
            </>
          ) : (
            <button type="button" className="btn-primary" onClick={submit} disabled={submitting}>
              {submitting ? "Analysing…" : "Compare regions"}
            </button>
          )}
        </div>
      </div>

      {submitting ? (
        <p className="mt-4 text-[0.85rem] text-ink-500" role="status" aria-live="polite">
          Scoring every region against your constraints, retrieving evidence, and checking transport…
        </p>
      ) : null}
    </div>
  );
}

function ProgressRail({
  step,
  completeness,
  onJump,
}: {
  step: number;
  completeness: number;
  onJump: (index: number) => void;
}) {
  return (
    <div>
      <div className="flex items-end justify-between">
        <ol className="flex gap-1.5" aria-label="Progress">
          {STEPS.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onJump(index)}
                aria-current={index === step ? "step" : undefined}
                className={`h-1 w-16 rounded-full transition-colors ${
                  index <= step ? "bg-ink-900" : "bg-ink-200"
                }`}
              >
                <span className="sr-only">
                  Step {index + 1}: {item.title}
                </span>
              </button>
            </li>
          ))}
        </ol>
        <p className="text-[0.75rem] tabular-nums text-ink-500">{completeness}% detail</p>
      </div>
      <p className="mt-2.5 text-[0.8rem] text-ink-500">
        Nothing here is required. Anything you leave out becomes a stated assumption in the result.
      </p>
    </div>
  );
}

type Setter = <K extends keyof FormState>(key: K, value: FormState[K]) => void;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[0.78rem] text-ink-500">{hint}</span> : null}
    </label>
  );
}

function TripStep({ form, set }: { form: FormState; set: Setter }) {
  return (
    <>
      <div className="grid gap-5 sm:grid-cols-3">
        <Field label="Start date">
          <input
            type="date"
            className="field mt-1.5"
            value={form.start_date}
            onChange={(e) => set("start_date", e.target.value)}
          />
        </Field>
        <Field label="Total nights in Japan">
          <input
            type="number"
            min={1}
            max={120}
            inputMode="numeric"
            placeholder="12"
            className="field mt-1.5"
            value={form.total_nights}
            onChange={(e) => set("total_nights", e.target.value)}
          />
        </Field>
        <Field label="Nights for the regional leg" hint="The part that isn't Tokyo or Kyoto.">
          <input
            type="number"
            min={1}
            max={60}
            inputMode="numeric"
            placeholder="4"
            className="field mt-1.5"
            value={form.regional_nights}
            onChange={(e) => set("regional_nights", e.target.value)}
          />
        </Field>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Flying into" hint="Transfer time from here is a major part of the score.">
          <select className="field mt-1.5" value={form.arrival_city} onChange={(e) => set("arrival_city", e.target.value)}>
            {GATEWAYS.map((city) => (
              <option key={city} value={city}>
                {city}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Flying out of" hint="An open-jaw trip changes the answer completely.">
          <select
            className="field mt-1.5"
            value={form.departure_city}
            onChange={(e) => set("departure_city", e.target.value)}
          >
            {GATEWAYS.map((city) => (
              <option key={city} value={city}>
                {city}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </>
  );
}

function HistoryStep({
  form,
  set,
  toggle,
}: {
  form: FormState;
  set: Setter;
  toggle: (key: "interests" | "visited_places", value: string) => void;
}) {
  return (
    <>
      <fieldset>
        <legend className="label">Places you&rsquo;ve already been</legend>
        <div className="mt-2.5 flex flex-wrap gap-2">
          {COMMON_VISITED.map((place) => {
            const on = form.visited_places.includes(place);
            return (
              <button
                key={place}
                type="button"
                aria-pressed={on}
                className={on ? "chip-on" : "chip-off"}
                onClick={() => toggle("visited_places", place)}
              >
                {place}
              </button>
            );
          })}
        </div>
        <p className="mt-2.5 text-[0.78rem] text-ink-500">
          Used to score novelty — a region that feels like somewhere you&rsquo;ve already been scores lower.
        </p>
      </fieldset>

      <Field label="Anything else about this trip" hint="Free text. Treated as description, never as an instruction.">
        <textarea
          rows={4}
          className="field mt-1.5 resize-y"
          placeholder="Third trip. Last time we did the Golden Route and found it crowded. Want somewhere we can eat well and sit in a bath."
          value={form.free_text}
          onChange={(e) => set("free_text", e.target.value)}
        />
      </Field>
    </>
  );
}

function StyleStep({
  form,
  set,
  toggle,
}: {
  form: FormState;
  set: Setter;
  toggle: (key: "interests" | "visited_places", value: string) => void;
}) {
  return (
    <>
      <fieldset>
        <legend className="label">What you&rsquo;re actually after</legend>
        <div className="mt-2.5 flex flex-wrap gap-2">
          {INTERESTS.map((interest) => {
            const on = form.interests.includes(interest);
            return (
              <button
                key={interest}
                type="button"
                aria-pressed={on}
                className={on ? "chip-on" : "chip-off"}
                onClick={() => toggle("interests", interest)}
              >
                {interest}
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Will you drive?" hint="The single biggest constraint on which regions work.">
          <select className="field mt-1.5" value={form.driving} onChange={(e) => set("driving", e.target.value)}>
            <option value="">Not sure yet</option>
            <option value="no_car">Public transport only</option>
            <option value="willing">Willing to drive if needed</option>
            <option value="prefers_car">Would rather drive</option>
          </select>
        </Field>
        <Field label="Pace">
          <select className="field mt-1.5" value={form.pace} onChange={(e) => set("pace", e.target.value)}>
            <option value="">No preference</option>
            <option value="relaxed">Relaxed — few moves</option>
            <option value="balanced">Balanced</option>
            <option value="fast">Fast — see a lot</option>
          </select>
        </Field>
        <Field label="Who&rsquo;s travelling">
          <select
            className="field mt-1.5"
            value={form.traveller_type}
            onChange={(e) => set("traveller_type", e.target.value)}
          >
            <option value="">Not saying</option>
            <option value="solo">Solo</option>
            <option value="couple">Couple</option>
            <option value="family">Family</option>
          </select>
        </Field>
        <Field label="Budget">
          <select className="field mt-1.5" value={form.budget} onChange={(e) => set("budget", e.target.value)}>
            <option value="">No preference</option>
            <option value="budget">Budget</option>
            <option value="mid">Mid-range</option>
            <option value="premium">Premium</option>
          </select>
        </Field>
      </div>

      <fieldset className="space-y-2.5">
        <legend className="label">Practicalities</legend>
        <label className="flex items-center gap-2.5 text-[0.9rem] text-ink-700">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            checked={form.large_luggage}
            onChange={(e) => set("large_luggage", e.target.checked)}
          />
          Travelling with large suitcases
        </label>
        <label className="flex items-center gap-2.5 text-[0.9rem] text-ink-700">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            checked={form.step_free_required}
            onChange={(e) => set("step_free_required", e.target.checked)}
          />
          Step-free access is required
        </label>
      </fieldset>
    </>
  );
}
