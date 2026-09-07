"use client";

import { useState } from "react";
import type { RegionRecommendation } from "@/lib/types";
import { EvidenceList } from "./EvidenceList";
import { Badge, FitBadge, Stat } from "./primitives";

export function RegionCard({
  region,
  variant = "alternative",
}: {
  region: RegionRecommendation;
  variant?: "recommended" | "alternative" | "rejected";
}) {
  const [showRubric, setShowRubric] = useState(false);
  const rejected = variant === "rejected";

  return (
    <article
      className={`card overflow-hidden ${
        variant === "recommended" ? "border-ink-900 ring-1 ring-ink-900" : ""
      } ${rejected ? "border-dashed bg-ink-50/40" : ""}`}
    >
      <header className="border-b border-ink-200 px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="label">
              {variant === "recommended" ? "Best fit" : rejected ? "Not recommended for this trip" : `Alternative`}
            </p>
            <h3 className="mt-1 font-serif text-[1.45rem] text-ink-900">{region.region_name}</h3>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <FitBadge label={region.fit_label} />
            <p className="font-serif text-[1.6rem] tabular-nums leading-none text-ink-900">
              {region.deterministic_score.toFixed(0)}
              <span className="ml-0.5 text-[0.8rem] font-sans text-ink-400">/100</span>
            </p>
          </div>
        </div>
        <p className="prose-measure mt-3">{region.headline}</p>
      </header>

      <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-b border-ink-200 px-6 py-4 sm:grid-cols-4">
        <Stat
          label="Return transfer"
          value={`${region.round_trip_transfer_hours.toFixed(1)}h`}
          hint={`${Math.round(region.transit_share * 100)}% of the leg`}
        />
        <Stat
          label="Without a car"
          value={region.public_transport_viable ? "Viable" : "Difficult"}
          hint={region.car_required ? "car effectively required" : undefined}
        />
        <Stat
          label="Booking effort"
          value={
            region.booking_complexity > 0.6 ? "High" : region.booking_complexity > 0.4 ? "Moderate" : "Low"
          }
          hint={`complexity ${region.booking_complexity.toFixed(2)}`}
        />
        <Stat label="Sources" value={String(region.citations.length)} hint="cited below" />
      </div>

      <div className="space-y-5 px-6 py-5">
        {region.reasons.length > 0 ? (
          <List title={rejected ? "What it has going for it" : "Why this fits"} tone="good" items={region.reasons} />
        ) : null}
        {region.tradeoffs.length > 0 ? (
          <List title="What you give up" tone="warning" items={region.tradeoffs} />
        ) : null}
        {region.rejected_reasons.length > 0 ? (
          <List title="Why it doesn't work on this trip" tone="critical" items={region.rejected_reasons} />
        ) : null}
        {region.seasonal_note ? (
          <p className="rounded-md bg-ink-50 px-4 py-3 text-[0.86rem] leading-relaxed text-ink-700">
            <span className="label mr-2">Season</span>
            {region.seasonal_note}
          </p>
        ) : null}
      </div>

      <div className="border-t border-ink-200 px-6 py-4">
        <button
          type="button"
          onClick={() => setShowRubric((v) => !v)}
          aria-expanded={showRubric}
          className="text-[0.82rem] text-ink-600 underline underline-offset-4 hover:text-ink-900"
        >
          {showRubric ? "Hide" : "Show"} how this score was calculated
        </button>
        {showRubric ? (
          <div className="mt-4 overflow-x-auto">
            <p className="mb-3 text-[0.82rem] text-ink-600">
              A fixed weighted rubric over your stated constraints — not a model output. The same inputs
              always produce this same number.
            </p>
            <table className="w-full min-w-[34rem] text-left text-[0.82rem]">
              <thead>
                <tr className="border-b border-ink-200 text-ink-500">
                  <th scope="col" className="py-2 pr-4 font-medium">Component</th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">Value</th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">Weight</th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">Points</th>
                  <th scope="col" className="py-2 font-medium">Why</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {region.score_components.map((component) => (
                  <tr key={component.name} className="align-top">
                    <td className="py-2 pr-4 font-medium text-ink-800">{component.name.replace(/_/g, " ")}</td>
                    <td className="py-2 pr-4 text-right tabular-nums text-ink-600">{component.value.toFixed(2)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums text-ink-500">{component.weight.toFixed(2)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums text-ink-900">
                      {component.contribution.toFixed(1)}
                    </td>
                    <td className="py-2 text-ink-600">{component.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {region.citations.length > 0 ? (
        <div className="border-t border-ink-200 p-4">
          <EvidenceList citations={region.citations} title={`Evidence for ${region.region_name}`} />
        </div>
      ) : null}

      {region.is_demo_data ? (
        <div className="border-t border-ink-200 px-6 py-2.5">
          <Badge tone="warning">Scored on demo region data</Badge>
        </div>
      ) : null}
    </article>
  );
}

function List({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "warning" | "critical";
}) {
  const dot = {
    good: "bg-signal-good",
    warning: "bg-signal-warning",
    critical: "bg-signal-critical",
  }[tone];
  return (
    <div>
      <p className="label">{title}</p>
      <ul className="mt-2 space-y-2">
        {items.map((item) => (
          <li key={item} className="flex gap-3 text-[0.9rem] leading-relaxed text-ink-700">
            <span aria-hidden="true" className={`mt-[0.5rem] h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
