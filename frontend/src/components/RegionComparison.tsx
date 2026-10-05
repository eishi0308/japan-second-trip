import type { RegionRecommendation } from "@/lib/types";

const CLOSE_CALL_POINTS = 3;

function bookingEffort(complexity: number): string {
  return complexity > 0.6 ? "High" : complexity > 0.4 ? "Moderate" : "Low";
}

/** Every scored region on one screen, so the ranking is readable before any card is. */
export function RegionComparison({
  recommended,
  alternatives,
  rejected,
}: {
  recommended: RegionRecommendation | null;
  alternatives: RegionRecommendation[];
  rejected: RegionRecommendation[];
}) {
  const ranked = [...(recommended ? [recommended] : []), ...alternatives];
  if (ranked.length + rejected.length < 2) return null;

  const runnerUp = alternatives[0];
  const gap = recommended && runnerUp ? recommended.deterministic_score - runnerUp.deterministic_score : null;
  const points = gap === null ? 0 : Math.round(gap);

  return (
    <section aria-labelledby="comparison-heading" className="card overflow-hidden">
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-ink-200 px-6 py-4">
        <h2 id="comparison-heading" className="label">
          At a glance
        </h2>
        {recommended && runnerUp && gap !== null ? (
          <p className="text-[0.86rem] text-ink-700">
            {gap <= CLOSE_CALL_POINTS ? (
              <>
                <span className="font-medium text-ink-900">A close call.</span> {runnerUp.region_name} is{" "}
                {points === 0 ? "level" : `${points} ${points === 1 ? "point" : "points"} behind`}.
              </>
            ) : (
              <>
                <span className="font-medium text-ink-900">A clear lead.</span> {recommended.region_name} is{" "}
                {points} points ahead of {runnerUp.region_name}.
              </>
            )}
          </p>
        ) : null}
      </header>

      <ol className="divide-y divide-ink-100">
        {ranked.map((region, index) => (
          <Row key={region.region_code} region={region} position={index + 1} best={index === 0 && !!recommended} />
        ))}
        {rejected.map((region) => (
          <Row key={region.region_code} region={region} ruledOut />
        ))}
      </ol>
    </section>
  );
}

function Row({
  region,
  position,
  best = false,
  ruledOut = false,
}: {
  region: RegionRecommendation;
  position?: number;
  best?: boolean;
  ruledOut?: boolean;
}) {
  const score = Math.round(region.deterministic_score);
  return (
    <li>
      <a
        href={`#region-${region.region_code}`}
        className={`grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-6 py-3.5 hover:bg-ink-50 sm:grid-cols-[1.5rem_minmax(0,13rem)_minmax(0,1fr)_auto] ${
          best ? "bg-ink-50/70" : ""
        }`}
      >
        <span className="text-[0.82rem] tabular-nums text-ink-400">{ruledOut ? "—" : position}</span>

        <span className="min-w-0">
          <span
            className={`block truncate font-serif text-[1.1rem] ${ruledOut ? "text-ink-500" : "text-ink-900"}`}
          >
            {region.region_name}
          </span>
          <span className="block text-[0.78rem] text-ink-500">
            {ruledOut
              ? "Ruled out"
              : `${region.round_trip_transfer_hours.toFixed(1)}h travel · ${
                  region.public_transport_viable ? "no car needed" : "car needed"
                } · ${bookingEffort(region.booking_complexity).toLowerCase()} booking effort`}
          </span>
        </span>

        {ruledOut ? (
          <span className="col-span-3 text-[0.82rem] leading-snug text-ink-600 sm:col-span-2">
            {region.rejected_reasons[0] ?? "Failed a hard constraint for this trip."}
          </span>
        ) : (
          <>
            <span
              aria-hidden="true"
              className="order-last col-span-3 h-1.5 overflow-hidden rounded-full bg-ink-100 sm:order-none sm:col-span-1"
            >
              <span
                className={`block h-full rounded-full ${best ? "bg-ink-900" : "bg-ink-400"}`}
                style={{ width: `${Math.max(0, Math.min(100, region.deterministic_score))}%` }}
              />
            </span>
            <span className="text-right font-serif text-[1.25rem] tabular-nums leading-none text-ink-900">
              {score}
              <span className="ml-0.5 font-sans text-[0.72rem] text-ink-400">/100</span>
            </span>
          </>
        )}
      </a>
    </li>
  );
}
