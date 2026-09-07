import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfidenceNotice } from "@/components/ConfidenceNotice";
import { EvidenceList } from "@/components/EvidenceList";
import { FeedbackWidget } from "@/components/FeedbackWidget";
import { IssueCard } from "@/components/IssueCard";
import { RouteTimeline } from "@/components/RouteTimeline";
import { HealthBadge, SectionHeading, Stat } from "@/components/primitives";
import { ApiRequestError, api } from "@/lib/api";

export const metadata: Metadata = { title: "RouteCheck — result" };
export const dynamic = "force-dynamic";

export default async function RouteCheckResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let envelope;
  try {
    envelope = await api.getRouteCheck(id);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }
  const result = envelope.result;
  const load = result.travel_load;

  return (
    <div className="shell py-12">
      <div className="max-w-3xl">
        <div className="mb-4 flex items-center gap-3">
          <p className="label">RouteCheck · result</p>
          <HealthBadge health={result.health} />
        </div>
        <h1 className="text-headline font-serif text-ink-900">Route health</h1>
        <p className="prose-measure mt-3 text-[1rem] text-ink-800">{result.health_summary}</p>
      </div>

      {load ? (
        <div className="mt-8 grid grid-cols-2 gap-x-8 gap-y-5 border-y border-ink-200 py-6 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Nights" value={String(load.total_nights)} />
          <Stat label="In transit" value={`${load.total_transit_hours.toFixed(1)}h`} hint={`${load.transit_hours_per_night.toFixed(1)}h per night`} />
          <Stat label="Longest hop" value={`${load.longest_segment_hours.toFixed(1)}h`} />
          <Stat label="Hotel changes" value={String(load.accommodation_changes)} hint={`${load.one_night_stays} single nights`} />
          <Stat label="Transit share" value={`${Math.round(load.transit_share_of_daylight * 100)}%`} hint="of usable hours" />
          <Stat label="Route shape" value={`${load.detour_ratio.toFixed(2)}×`} hint="vs a direct line" />
        </div>
      ) : null}

      {/* min-w-0 on both children: without it a grid track sizes to its content's
          min-content width, and a long unbreakable segment label ("Ginzan Onsen →
          Aomori costs more time than it buys") pushes the whole column past the
          viewport on a phone. */}
      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-10">
          {result.critical_issues.length > 0 ? (
            <section>
              <SectionHeading
                eyebrow="Fix these"
                title={`Critical — ${result.critical_issues.length}`}
                description="These will materially damage the trip as drafted."
              />
              <div className="space-y-4">
                {result.critical_issues.map((issue, index) => (
                  <IssueCard key={`${issue.rule_id}-${index}`} issue={issue} />
                ))}
              </div>
            </section>
          ) : null}

          {result.warnings.length > 0 ? (
            <section>
              <SectionHeading
                eyebrow="Worth reconsidering"
                title={`Warnings — ${result.warnings.length}`}
                description="Not blocking, but each one costs you time or margin."
              />
              <div className="space-y-4">
                {result.warnings.map((issue, index) => (
                  <IssueCard key={`${issue.rule_id}-${index}`} issue={issue} />
                ))}
              </div>
            </section>
          ) : null}

          {result.strengths.length > 0 ? (
            <section>
              <SectionHeading
                eyebrow="Keep this"
                title="What's already working"
                description="A critique that only lists problems is not a critique; it's a complaint."
              />
              <div className="space-y-4">
                {result.strengths.map((issue, index) => (
                  <IssueCard key={`${issue.rule_id}-${index}`} issue={issue} />
                ))}
              </div>
            </section>
          ) : null}

          {result.critical_issues.length === 0 &&
          result.warnings.length === 0 &&
          result.strengths.length === 0 ? (
            <div className="card p-6">
              <p className="font-serif text-lg text-ink-900">No issues found</p>
              <p className="prose-measure mt-2">
                Travel load, stay lengths and connections are all inside sensible limits for this trip.
              </p>
            </div>
          ) : null}

          {result.revised_route ? (
            <section className="card overflow-hidden">
              <div className="border-b border-ink-200 bg-accent-50/60 px-6 py-4">
                <p className="label">Recommended change</p>
                {/* Rendered as wrapping items rather than one joined string: a long
                    route on a narrow screen must wrap between stops, not overflow. */}
                <ol className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 font-serif text-[1.15rem] text-ink-900">
                  {result.revised_route.stops.map((stop, i) => {
                    const nights = result.revised_route!.nights[i] ?? 0;
                    const last = i === result.revised_route!.stops.length - 1;
                    return (
                      <li key={`${stop}-${i}`} className="flex items-baseline gap-2">
                        <span>
                          {stop}
                          {nights > 0 ? (
                            <span className="ml-1 text-[0.85rem] tabular-nums text-ink-600">{nights}N</span>
                          ) : null}
                        </span>
                        {!last ? (
                          <span aria-hidden="true" className="text-ink-300">
                            →
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              </div>
              <div className="space-y-4 px-6 py-5">
                <p className="prose-measure">{result.revised_route.summary}</p>
                {result.revised_route.travel_load && load ? (
                  <div className="grid grid-cols-3 gap-5 rounded-md bg-ink-50 px-4 py-3.5">
                    <Stat
                      label="Transit"
                      value={`${result.revised_route.travel_load.total_transit_hours.toFixed(1)}h`}
                      hint={`was ${load.total_transit_hours.toFixed(1)}h`}
                    />
                    <Stat
                      label="Hotel changes"
                      value={String(result.revised_route.travel_load.accommodation_changes)}
                      hint={`was ${load.accommodation_changes}`}
                    />
                    <Stat
                      label="Single nights"
                      value={String(result.revised_route.travel_load.one_night_stays)}
                      hint={`was ${load.one_night_stays}`}
                    />
                  </div>
                ) : null}
                {result.proposed_fixes[0] ? (
                  <div className="grid gap-5 sm:grid-cols-2">
                    <TradeList title="What you gain" items={result.proposed_fixes[0].gained} tone="good" />
                    <TradeList title="What you lose" items={result.proposed_fixes[0].lost} tone="warning" />
                  </div>
                ) : null}
                {result.proposed_fixes.length > 1 ? (
                  <details className="pt-1">
                    <summary className="cursor-pointer text-[0.84rem] text-ink-600 hover:text-ink-900">
                      Other options that were costed ({result.proposed_fixes.length - 1})
                    </summary>
                    <ul className="mt-2.5 space-y-1.5 text-[0.86rem] text-ink-700">
                      {result.proposed_fixes.slice(1).map((fix) => (
                        <li key={fix.summary}>{fix.summary}</li>
                      ))}
                    </ul>
                    <p className="mt-2 text-[0.78rem] text-ink-500">
                      Every option was re-costed with real transport data before being ranked. The model
                      chose between them; it could not invent one.
                    </p>
                  </details>
                ) : null}
              </div>
            </section>
          ) : null}
        </div>

        <aside className="min-w-0 space-y-6">
          <ConfidenceNotice
            confidence={result.confidence}
            humanReviewRequired={result.human_review_required}
            humanReviewTaskId={result.human_review_task_id}
            unknowns={result.unknowns}
            conflicts={result.conflicts}
            resolvedFacts={result.resolved_facts}
            supersededBy={result.superseded_by}
          />

          {result.parsed_route ? (
            <section className="card p-5">
              <p className="label mb-4">Your route</p>
              <RouteTimeline route={result.parsed_route} />
              {result.unresolved_places.length > 0 ? (
                <p className="mt-4 rounded-md bg-signal-warning/10 px-3 py-2.5 text-[0.82rem] text-ink-700">
                  Not identified: {result.unresolved_places.join(", ")}. These were excluded from the
                  transport and rule checks rather than guessed at.
                </p>
              ) : null}
            </section>
          ) : null}

          <EvidenceList citations={result.citations} title="Sources consulted" />
        </aside>
      </div>

      <div className="mt-12 max-w-3xl space-y-6">
        <div className="flex flex-wrap items-center gap-3 border-t border-ink-200 pt-8">
          <Link href="/route-check" className="btn-primary">
            Check another route
          </Link>
          {result.trip_id ? (
            <Link href={`/trip/${result.trip_id}`} className="btn-secondary">
              Open the trip workspace
            </Link>
          ) : null}
          <Link href="/where-next" className="btn-ghost">
            Reconsider the region
          </Link>
        </div>
        <FeedbackWidget analysisId={result.analysis_id} tripId={result.trip_id} />
        <p className="text-[0.75rem] text-ink-400">
          Analysis {result.analysis_id} · rules v{result.rules_version} · prompts{" "}
          {Object.entries(result.prompt_versions)
            .map(([k, v]) => `${k}@${v}`)
            .join(", ") || "none"}
        </p>
      </div>
    </div>
  );
}

function TradeList({ title, items, tone }: { title: string; items: string[]; tone: "good" | "warning" }) {
  if (items.length === 0) return null;
  const dot = tone === "good" ? "bg-signal-good" : "bg-signal-warning";
  return (
    <div>
      <p className="label">{title}</p>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex gap-2.5 text-[0.86rem] leading-relaxed text-ink-700">
            <span aria-hidden="true" className={`mt-[0.45rem] h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
