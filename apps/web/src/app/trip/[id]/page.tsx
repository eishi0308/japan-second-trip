import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge, EmptyState, SectionHeading } from "@/components/primitives";
import { ApiRequestError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Trip workspace" };
export const dynamic = "force-dynamic";

export default async function TripPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let trip;
  try {
    trip = await api.getTrip(id);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }

  const context = trip.trip as Record<string, unknown>;
  const rejected = Object.entries(trip.rejected_regions);

  return (
    <div className="shell max-w-4xl py-12">
      <p className="label mb-3">Trip workspace</p>
      <h1 className="text-headline font-serif text-ink-900">{trip.title}</h1>
      <p className="prose-measure mt-3">
        What the system remembers about this trip. Structured decisions only — where you&rsquo;ve been,
        what&rsquo;s in the running, what you ruled out and why. Not a chat transcript.
      </p>

      <section className="mt-10">
        <SectionHeading eyebrow="Context" title="The trip as we understand it" />
        <dl className="card grid grid-cols-2 gap-x-8 gap-y-5 p-6 sm:grid-cols-3">
          <Detail label="Arrival" value={str(context.arrival_city)} />
          <Detail label="Departure" value={str(context.departure_city)} />
          <Detail label="Start date" value={str(context.start_date)} />
          <Detail label="Total nights" value={str(context.total_nights)} />
          <Detail label="Regional nights" value={str(context.regional_nights)} />
          <Detail label="Transport" value={str(context.driving)?.replace(/_/g, " ")} />
          <Detail label="Pace" value={str(context.pace)} />
          <Detail label="Travellers" value={str(context.traveller_type)} />
          <Detail
            label="Interests"
            value={Array.isArray(context.interests) && context.interests.length > 0 ? (context.interests as string[]).join(", ") : null}
          />
        </dl>
      </section>

      <div className="mt-10 grid gap-8 md:grid-cols-2">
        <section>
          <SectionHeading eyebrow="Memory" title="Where you've been" />
          <div className="card p-5">
            {trip.visited.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {trip.visited.map((place) => (
                  <span key={place} className="chip-off cursor-default">
                    {place}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-[0.88rem] text-ink-600">No travel history recorded.</p>
            )}
          </div>
        </section>

        <section>
          <SectionHeading eyebrow="Memory" title="Current candidate" />
          <div className="card p-5">
            {trip.candidate_region ? (
              <p className="font-serif text-[1.1rem] text-ink-900">
                {trip.candidate_region.replace(/_/g, " ")}
              </p>
            ) : (
              <p className="text-[0.88rem] text-ink-600">No region selected yet.</p>
            )}
          </div>
        </section>
      </div>

      {rejected.length > 0 ? (
        <section className="mt-10">
          <SectionHeading
            eyebrow="Memory"
            title="Ruled out"
            description="These will not be re-proposed without acknowledging why they were rejected."
          />
          <ul className="card divide-y divide-ink-200">
            {rejected.map(([code, reason]) => (
              <li key={code} className="px-5 py-3.5">
                <p className="font-medium text-ink-900">{code.replace(/_/g, " ")}</p>
                <p className="mt-0.5 text-[0.86rem] leading-relaxed text-ink-600">{reason}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {trip.verified_warnings.length > 0 ? (
        <section className="mt-10">
          <SectionHeading eyebrow="Memory" title="Warnings carried forward" />
          <ul className="card divide-y divide-ink-200">
            {trip.verified_warnings.map((warning) => (
              <li key={warning} className="px-5 py-3 text-[0.88rem] text-ink-700">
                {warning}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-10">
        <SectionHeading eyebrow="History" title="Analyses on this trip" />
        {trip.analyses.length === 0 ? (
          <EmptyState
            title="Nothing analysed yet"
            description="Run a region comparison or a route check and it will appear here."
            action={{ href: "/where-next", label: "Start with Where Next" }}
          />
        ) : (
          <ul className="card divide-y divide-ink-200">
            {trip.analyses.map((analysis) => (
              <li key={analysis.analysis_id}>
                <Link
                  href={
                    analysis.kind === "where_next"
                      ? `/where-next/result/${analysis.analysis_id}`
                      : `/route-check/result/${analysis.analysis_id}`
                  }
                  className="flex items-start justify-between gap-4 px-5 py-4 transition-colors hover:bg-ink-50"
                >
                  <span className="min-w-0">
                    <span className="block text-[0.9rem] font-medium text-ink-900">
                      {analysis.kind === "where_next" ? "Where Next" : "RouteCheck"}
                    </span>
                    <span className="mt-0.5 block truncate text-[0.85rem] text-ink-600">{analysis.summary}</span>
                    <span className="mt-1.5 flex items-center gap-2">
                      {analysis.human_review_required ? <Badge tone="warning">awaiting review</Badge> : null}
                      {analysis.confidence ? (
                        <span className="text-[0.75rem] text-ink-500">{analysis.confidence} confidence</span>
                      ) : null}
                    </span>
                  </span>
                  <span className="shrink-0 text-[0.78rem] tabular-nums text-ink-400">
                    {analysis.created_at?.slice(0, 10)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {trip.decisions.length > 0 ? (
        <section className="mt-10">
          <SectionHeading eyebrow="Audit" title="Decision log" />
          <ol className="card divide-y divide-ink-200 font-mono text-[0.78rem]">
            {trip.decisions.slice().reverse().map((decision, index) => (
              <li key={`${decision}-${index}`} className="px-5 py-2.5 text-ink-600">
                {decision}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <div className="mt-12 flex flex-wrap gap-3 border-t border-ink-200 pt-8">
        <Link href="/where-next" className="btn-secondary">
          Reconsider the region
        </Link>
        <Link href="/route-check" className="btn-secondary">
          Check an itinerary
        </Link>
      </div>
    </div>
  );
}

function str(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="mt-1 text-[0.92rem] text-ink-900">{value ?? <span className="text-ink-400">not set</span>}</dd>
    </div>
  );
}
