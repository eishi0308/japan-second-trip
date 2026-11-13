"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Option, PlanRequest, PlanResponse } from "@/lib/v2";
import { v2 } from "@/lib/v2";
import { FactMark, FitLevel, VerdictMark } from "./ui";

type Toggle = "drive" | "plus_night" | "osaka";

const TOGGLES: [Toggle, string][] = [
  ["drive", "If I can drive"],
  ["plus_night", "+1 night"],
  ["osaka", "Fly out of Osaka"],
];

function patched(request: PlanRequest, on: Set<Toggle>, nights: number): PlanRequest {
  return {
    ...request,
    save: false,
    ...(on.has("drive") ? { transport: "either" as const } : {}),
    ...(on.has("plus_night") ? { regional_nights: nights + 1 } : {}),
    ...(on.has("osaka") ? { departure_city: "Osaka" } : {}),
  };
}

function bookingText(option: Option): string {
  const n = option.check?.booking.length ?? 0;
  return n ? `${n} thing${n > 1 ? "s" : ""} to book ahead` : "Nothing to book ahead on record";
}

/** Same rows, same order, for every option (PRODUCT_AMENDMENTS.md §4). */
const ROWS: { label: string; cell: (o: Option) => React.ReactNode }[] = [
  { label: "Total travel time", cell: (o) => o.travel.moving_label },
  { label: "Hotel changes", cell: (o) => (o.travel.hotel_changes ? String(o.travel.hotel_changes) : "None") },
  { label: "Car needed", cell: (o) => o.car_label },
  { label: "Season fit", cell: (o) => o.season_label },
  { label: "Interest match", cell: (o) => o.fit.breakdown.find((b) => b.name === "interests")?.text ?? "" },
  { label: "Booking difficulty", cell: (o) => bookingText(o) },
  {
    label: "Verification",
    cell: (o) => (
      <span className="flex flex-col items-start gap-1">
        <FactMark state={o.verification.state} date={o.verification.oldest_verified_at} />
        {o.check ? <VerdictMark verdict={o.check.verdict} label={o.check.verdict_label} /> : null}
      </span>
    ),
  },
];

export function CompareTable({ initial, planId }: { initial: PlanResponse; planId: string }) {
  const [on, setOn] = useState<Set<Toggle>>(new Set());
  const [res, setRes] = useState<PlanResponse>(initial);
  const [loading, setLoading] = useState(false);
  const nights = initial.plan.result?.nights ?? initial.request.regional_nights ?? 4;

  useEffect(() => {
    if (!on.size) {
      setRes(initial);
      return;
    }
    let live = true;
    setLoading(true);
    v2.createPlan(patched(initial.request, on, nights))
      .then((r) => live && setRes(r))
      .catch(() => undefined)
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [on, initial, nights]);

  const options = res.plan.result?.options ?? [];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="What if">
        <span className="label mr-1">What if</span>
        {TOGGLES.map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={on.has(key)}
            className={on.has(key) ? "chip-on" : "chip-off"}
            onClick={() => {
              const next = new Set(on);
              if (next.has(key)) next.delete(key);
              else next.add(key);
              setOn(next);
            }}
          >
            {label}
          </button>
        ))}
        <span className="text-[0.8rem] text-ink-500" aria-live="polite">
          {loading ? "Recomputing…" : on.size ? "Showing the changed trip" : ""}
        </span>
      </div>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-left text-[0.88rem]">
          <caption className="sr-only">Three options compared</caption>
          <thead>
            <tr>
              <th scope="col" className="w-44 border-b border-ink-200 py-3 pr-4 align-bottom">
                <span className="sr-only">Row</span>
              </th>
              {options.map((o, n) => (
                <th key={o.title} scope="col" className="border-b border-ink-200 px-3 py-3 align-bottom font-normal">
                  <p className="label text-accent-700">{o.character_label}</p>
                  <p className="mt-1 font-serif text-lg leading-snug text-ink-900">
                    {on.size ? (
                      o.title
                    ) : (
                      <Link href={`/plan/${planId}/option/${n}`} className="hover:underline">
                        {o.title}
                      </Link>
                    )}
                  </p>
                  <p className="text-[0.78rem] text-ink-500">{o.nights_label}</p>
                  <div className="mt-2">
                    <FitLevel level={o.fit.level} label={o.fit.label} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.label} className="border-b border-ink-100">
                <th scope="row" className="py-3 pr-4 align-top font-medium text-ink-700">
                  {row.label}
                </th>
                {options.map((o) => (
                  <td key={o.title} className="px-3 py-3 align-top text-ink-800">
                    {row.cell(o)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!options.length ? <p className="mt-4 text-sm text-ink-600">No trip fits with these changes.</p> : null}
      </div>
    </div>
  );
}
