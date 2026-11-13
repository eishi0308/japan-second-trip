import Link from "next/link";
import { OptionCard } from "@/components/v2/OptionCard";
import type { PlanResponse } from "@/lib/v2";
import { v2 } from "@/lib/v2";

/** One real result, computed now by the same engine (not a mock-up). */
const SAMPLE = {
  month: 1,
  regional_nights: 4,
  arrival_city: "Tokyo",
  departure_city: "Tokyo",
  interests: ["onsen", "snow", "food"],
  save: false,
};

export default async function Landing() {
  let sample: PlanResponse | null = null;
  try {
    sample = await v2.createPlan(SAMPLE);
  } catch {
    sample = null;
  }
  const options = sample?.plan.result?.options ?? [];

  return (
    <div>
      <section className="shell pb-14 pt-16 sm:pt-24">
        <p className="label mb-4">For your second (or fifth) trip to Japan</p>
        <h1 className="max-w-4xl font-serif text-display text-ink-900">
          Three trips beyond Tokyo, Kyoto and Osaka. Each one checked.
        </h1>
        <p className="prose-measure mt-6 text-[1.05rem]">
          Tell us your month, your nights and how you like to travel. We suggest three destination combinations that fit,
          tell you what is hard about each, and check them day by day: last buses, closures, long travel days.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link href="/plan" className="btn-primary">
            Find my next trip
          </Link>
          <Link href="/check" className="btn-secondary">
            Check my route
          </Link>
          <span className="text-[0.82rem] text-ink-500">No sign-up. Nothing to book or pay.</span>
        </div>
      </section>

      {options.length ? (
        <section className="border-t border-ink-100 bg-ink-50/50 py-14" aria-labelledby="sample">
          <div className="shell">
            <p className="label">A real result</p>
            <h2 id="sample" className="mt-1 font-serif text-headline text-ink-900">
              January, 4 nights, Tokyo in and out, no car
            </h2>
            <p className="prose-measure mt-2">Onsen, snow and food. Computed just now from our destination database.</p>
            <div className="mt-8 grid gap-5 lg:grid-cols-3">
              {options.map((o) => (
                <OptionCard key={o.title} option={o} />
              ))}
            </div>
            {sample?.plan.result?.not_for_this_trip[0] ? (
              <p className="mt-6 text-[0.9rem] text-ink-700">
                <span className="font-medium">Not for this trip: {sample.plan.result.not_for_this_trip[0].area_label}.</span>{" "}
                {sample.plan.result.not_for_this_trip[0].if_you_change}
              </p>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
