"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api";
import type { City, PlanRequest, PlanResponse, SceneCard, Transport, Pace } from "@/lib/v2";
import { INTERESTS, MONTHS, v2 } from "@/lib/v2";

const UNDECIDED = "";
const DEFAULT_VISITED = ["Tokyo", "Kyoto", "Osaka"];

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-sm font-medium text-ink-800">{label}</p>
      {children}
      {hint ? <p className="mt-1 text-[0.78rem] text-ink-500">{hint}</p> : null}
    </div>
  );
}

function Chip({
  on,
  onClick,
  children,
  disabled,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      onClick={onClick}
      className={`${on ? "chip-on" : "chip-off"} disabled:cursor-not-allowed disabled:opacity-40`}
    >
      {children}
    </button>
  );
}

export function PlanForm({
  cities,
  sceneCards,
  initial,
}: {
  cities: City[];
  sceneCards: SceneCard[];
  initial?: PlanRequest;
}) {
  const router = useRouter();
  const [month, setMonth] = useState<string>(initial?.month ? String(initial.month) : UNDECIDED);
  const [startDate, setStartDate] = useState<string>(initial?.start_date ?? "");
  const [nights, setNights] = useState<string>(initial?.regional_nights ? String(initial.regional_nights) : UNDECIDED);
  const [arrival, setArrival] = useState<string>(initial?.arrival_city ?? UNDECIDED);
  const [departure, setDeparture] = useState<string>(initial?.departure_city ?? UNDECIDED);
  const [interests, setInterests] = useState<string[]>(initial?.interests ?? []);
  const [visited, setVisited] = useState<string[]>(initial?.visited ?? DEFAULT_VISITED);
  const [visitedText, setVisitedText] = useState("");
  const [transport, setTransport] = useState<Transport>(initial?.transport ?? "no_car");
  const [pace, setPace] = useState<Pace>(initial?.pace ?? "balanced");
  const [bigLuggage, setBigLuggage] = useState(initial?.big_luggage ?? false);
  const [kids, setKids] = useState(initial?.kids ?? false);
  const [limitedWalking, setLimitedWalking] = useState(initial?.limited_walking ?? false);
  const [mustInclude, setMustInclude] = useState((initial?.must_include ?? []).join(", "));
  const [freeText, setFreeText] = useState(initial?.free_text ?? "");
  const [best, setBest] = useState(initial?.past_trip_best ?? "");
  const [tired, setTired] = useState(initial?.past_trip_tired ?? "");
  const [scenes, setScenes] = useState<string[]>(initial?.scene_cards ?? []);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<PlanResponse | "waiting" | null>(null);
  const [shown, setShown] = useState(0);

  const toggle = (list: string[], value: string, max?: number) =>
    list.includes(value) ? list.filter((v) => v !== value) : max && list.length >= max ? list : [...list, value];

  const funnel =
    generating && generating !== "waiting"
      ? (generating.plan.result?.funnel ?? generating.plan.seasons[0]?.result.funnel ?? generating.plan.nights_options[0]?.result.funnel ?? [])
      : [];

  useEffect(() => {
    if (!generating || generating === "waiting") return;
    if (shown < funnel.length) {
      const t = setTimeout(() => setShown((n) => n + 1), 380);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => router.push(`/plan/${generating.plan_id}`), 450);
    return () => clearTimeout(t);
  }, [generating, shown, funnel.length, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const body: PlanRequest = {
      month: month ? Number(month) : null,
      start_date: startDate || null,
      regional_nights: nights ? Number(nights) : null,
      arrival_city: arrival || null,
      departure_city: departure || null,
      interests,
      visited,
      transport,
      pace,
      big_luggage: bigLuggage,
      kids,
      limited_walking: limitedWalking,
      must_include: mustInclude
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      scene_cards: interests.length ? [] : scenes,
      past_trip_best: interests.length ? null : best || null,
      past_trip_tired: interests.length ? null : tired || null,
      free_text: freeText || null,
    };
    setGenerating("waiting");
    setShown(0);
    try {
      setGenerating(await v2.createPlan(body));
    } catch (err) {
      setGenerating(null);
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "We could not reach the planner. Check your connection and try again.",
      );
    }
  }

  if (generating) {
    return (
      <div className="card mx-auto max-w-xl p-8" role="status" aria-live="polite">
        <p className="label">Narrowing it down</p>
        <h2 className="mt-2 font-serif text-title text-ink-900">Finding three trips that work</h2>
        <ol className="mt-6 space-y-3 tabular-nums">
          {generating === "waiting" ? (
            <li className="text-ink-500">Reading the destination database…</li>
          ) : (
            funnel.slice(0, Math.max(1, shown)).map((step) => (
              <li key={step.label} className="flex items-baseline gap-3 animate-in">
                <span className="w-12 text-right font-serif text-xl text-ink-900">{step.count}</span>
                <span className="text-ink-700">{step.label}</span>
              </li>
            ))
          )}
        </ol>
      </div>
    );
  }

  const gateways = cities.filter((c) => c.is_international_gateway);
  const others = cities.filter((c) => !c.is_international_gateway);
  const cityOptions = (
    <>
      <option value={UNDECIDED}>Not decided yet</option>
      <optgroup label="International airports">
        {gateways.map((c) => (
          <option key={c.slug} value={c.name}>
            {c.name}
          </option>
        ))}
      </optgroup>
      <optgroup label="Other cities">
        {others.map((c) => (
          <option key={c.slug} value={c.name}>
            {c.name}
          </option>
        ))}
      </optgroup>
    </>
  );

  return (
    <form onSubmit={submit} className="space-y-10" aria-label="Plan your next Japan trip">
      <section aria-labelledby="required" className="card space-y-6 p-5 sm:p-7">
        <h2 id="required" className="font-serif text-title text-ink-900">
          The basics
        </h2>
        <p className="-mt-3 text-sm text-ink-500">Any of these can be &ldquo;Not decided yet&rdquo;.</p>
        <div className="grid gap-6 sm:grid-cols-2">
          <Field label="When are you going?" hint="A month, or a start date if you have one.">
            <div className="flex gap-2">
              <select aria-label="Travel month" className="field" value={month} onChange={(e) => setMonth(e.target.value)}>
                <option value={UNDECIDED}>Not decided yet</option>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
              <input
                aria-label="Start date"
                type="date"
                className="field"
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                  if (e.target.value) setMonth(String(new Date(e.target.value).getUTCMonth() + 1));
                }}
              />
            </div>
          </Field>
          <Field label="Nights outside Tokyo, Kyoto and Osaka">
            <select aria-label="Regional nights" className="field" value={nights} onChange={(e) => setNights(e.target.value)}>
              <option value={UNDECIDED}>Not decided yet</option>
              {Array.from({ length: 14 }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n} night{n > 1 ? "s" : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Arriving in">
            <select aria-label="Arrival city" className="field" value={arrival} onChange={(e) => setArrival(e.target.value)}>
              {cityOptions}
            </select>
          </Field>
          <Field label="Leaving from" hint="Can differ from where you arrive.">
            <select aria-label="Departure city" className="field" value={departure} onChange={(e) => setDeparture(e.target.value)}>
              {cityOptions}
            </select>
          </Field>
        </div>
      </section>

      <section aria-labelledby="optional" className="space-y-7">
        <h2 id="optional" className="font-serif text-title text-ink-900">
          If you know
        </h2>
        <Field label="Interests" hint={`Pick up to 3. ${interests.length}/3 chosen.`}>
          <div className="flex flex-wrap gap-2">
            {INTERESTS.map((i) => (
              <Chip
                key={i}
                on={interests.includes(i)}
                disabled={!interests.includes(i) && interests.length >= 3}
                onClick={() => setInterests(toggle(interests, i, 3))}
              >
                <span className="capitalize">{i}</span>
              </Chip>
            ))}
          </div>
        </Field>

        {interests.length === 0 ? (
          <div className="card space-y-6 border-dashed p-5 sm:p-6" aria-label="Help us find your kind of trip">
            <p className="text-sm text-ink-600">No interests yet? Either of these is enough.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Best moment on your last Japan trip?">
                <textarea aria-label="Best moment on your last Japan trip" className="field min-h-20" maxLength={500} value={best} onChange={(e) => setBest(e.target.value)} />
              </Field>
              <Field label="What tired you, or what would you skip next time?">
                <textarea aria-label="What tired you, or what you would skip" className="field min-h-20" maxLength={500} value={tired} onChange={(e) => setTired(e.target.value)} />
              </Field>
            </div>
            <Field label="Which of these appeal?">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {sceneCards.map((card) => (
                  <button
                    key={card.slug}
                    type="button"
                    aria-pressed={scenes.includes(card.slug)}
                    onClick={() => setScenes(toggle(scenes, card.slug))}
                    className={`rounded-md border px-3 py-4 text-left text-[0.85rem] transition-colors ${
                      scenes.includes(card.slug)
                        ? "border-accent-600 bg-accent-50 text-accent-900"
                        : "border-ink-200 bg-white text-ink-700 hover:border-ink-400"
                    }`}
                  >
                    {card.title}
                  </button>
                ))}
              </div>
            </Field>
          </div>
        ) : null}

        <Field label="Places you have already been" hint="We will not suggest these.">
          <div className="flex flex-wrap items-center gap-2">
            {visited.map((v) => (
              <Chip key={v} on onClick={() => setVisited(visited.filter((x) => x !== v))}>
                {v} <span aria-hidden="true">×</span>
                <span className="sr-only">remove</span>
              </Chip>
            ))}
            <input
              aria-label="Add a place you have been"
              className="field w-44 py-1.5"
              placeholder="Add a place"
              value={visitedText}
              onChange={(e) => setVisitedText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && visitedText.trim()) {
                  e.preventDefault();
                  setVisited([...visited, visitedText.trim()]);
                  setVisitedText("");
                }
              }}
            />
          </div>
        </Field>

        <div className="grid gap-6 sm:grid-cols-2">
          <Field label="Getting around">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Getting around">
              {(
                [
                  ["no_car", "No car"],
                  ["can_drive", "Can drive"],
                  ["either", "Either"],
                ] as const
              ).map(([value, label]) => (
                <Chip key={value} on={transport === value} onClick={() => setTransport(value)}>
                  {label}
                </Chip>
              ))}
            </div>
          </Field>
          <Field label="Pace">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Pace">
              {(["relaxed", "balanced", "fast"] as const).map((value) => (
                <Chip key={value} on={pace === value} onClick={() => setPace(value)}>
                  <span className="capitalize">{value}</span>
                </Chip>
              ))}
            </div>
          </Field>
        </div>

        <Field label="Anything to plan around?">
          <div className="flex flex-wrap gap-2">
            <Chip on={bigLuggage} onClick={() => setBigLuggage(!bigLuggage)}>
              Big luggage
            </Chip>
            <Chip on={kids} onClick={() => setKids(!kids)}>
              Travelling with kids
            </Chip>
            <Chip on={limitedWalking} onClick={() => setLimitedWalking(!limitedWalking)}>
              Limited walking
            </Chip>
          </div>
        </Field>

        <div className="grid gap-6 sm:grid-cols-2">
          <Field label="Must include" hint="e.g. Shirakawa-go. We plan the rest around it.">
            <input aria-label="Must include" className="field" value={mustInclude} onChange={(e) => setMustInclude(e.target.value)} placeholder="Separate places with commas" />
          </Field>
          <Field label="What kind of trip?">
            <input aria-label="What kind of trip?" className="field" maxLength={500} value={freeText} onChange={(e) => setFreeText(e.target.value)} placeholder="In your own words (optional)" />
          </Field>
        </div>
      </section>

      {error ? (
        <p role="alert" className="rounded-md border border-signal-critical/30 bg-signal-critical/[0.05] px-4 py-3 text-sm text-signal-critical">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" className="btn-primary">
          Show me three trips
        </button>
        <p className="text-[0.8rem] text-ink-500">No sign-up. Nothing is booked.</p>
      </div>
    </form>
  );
}
