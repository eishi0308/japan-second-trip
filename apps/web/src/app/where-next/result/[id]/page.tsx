import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfidenceNotice } from "@/components/ConfidenceNotice";
import { EvidenceList } from "@/components/EvidenceList";
import { FeedbackWidget } from "@/components/FeedbackWidget";
import { RegionCard } from "@/components/RegionCard";
import { EmptyState, SectionHeading } from "@/components/primitives";
import { ApiRequestError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Where next — result" };
export const dynamic = "force-dynamic";

export default async function WhereNextResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let envelope;
  try {
    envelope = await api.getWhereNext(id);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }
  const result = envelope.result;

  return (
    <div className="shell py-12">
      <div className="max-w-3xl">
        <p className="label mb-3">Where next · result</p>
        <h1 className="text-headline font-serif text-ink-900">
          {result.recommended
            ? `${result.recommended.region_name} is the strongest fit for this trip`
            : "No region cleared the constraints for this trip"}
        </h1>
        <p className="prose-measure mt-3">
          Every region was scored by the same rubric against your dates, nights, gateway and travel
          style. The regions ruled out are shown too, with the constraint each one failed.
        </p>
      </div>

      <div className="mt-8 max-w-3xl">
        <ConfidenceNotice
          confidence={result.confidence}
          humanReviewRequired={result.human_review_required}
          humanReviewTaskId={result.human_review_task_id}
          assumptions={result.assumptions}
          unknowns={result.unknowns}
          missingInformation={result.missing_information}
          conflicts={result.conflicts}
          resolvedFacts={result.resolved_facts}
          supersededBy={result.superseded_by}
        />
      </div>

      <div className="mt-10 space-y-8">
        {result.recommended ? (
          <RegionCard region={result.recommended} variant="recommended" />
        ) : (
          <EmptyState
            title="Nothing fits this shape of trip"
            description="Every seeded region failed a hard constraint. The near-misses below name the specific constraint — usually too few regional nights for the transfer involved."
            action={{ href: "/where-next", label: "Adjust the trip" }}
          />
        )}

        {result.alternatives.length > 0 ? (
          <section>
            <SectionHeading
              eyebrow="Also worth considering"
              title="Alternatives"
              description="Ranked by the same rubric. A close second is often the better choice once you weigh the trade-offs yourself."
            />
            <div className="grid min-w-0 gap-6 xl:grid-cols-2">
              {result.alternatives.map((region) => (
                <RegionCard key={region.region_code} region={region} />
              ))}
            </div>
          </section>
        ) : null}

        {result.rejected.length > 0 ? (
          <section>
            <SectionHeading
              eyebrow="Ruled out"
              title="Not recommended for this trip"
              description="These are good destinations. They are the wrong answer for this particular trip, and the reason is stated rather than hidden."
            />
            <div className="grid min-w-0 gap-6 xl:grid-cols-2">
              {result.rejected.map((region) => (
                <RegionCard key={region.region_code} region={region} variant="rejected" />
              ))}
            </div>
          </section>
        ) : null}

        {result.suggested_route?.summary ? (
          <section className="card p-6">
            <SectionHeading eyebrow="Shape of the leg" title="A starting point" />
            <p className="prose-measure">{result.suggested_route.summary}</p>
            <Link href="/route-check" className="btn-secondary mt-5">
              Draft it, then check the route
            </Link>
          </section>
        ) : null}

        <section className="max-w-3xl">
          <SectionHeading
            eyebrow="Provenance"
            title="Everything this analysis read"
            description="Open any source to read the passage, its type, and when it was last verified."
          />
          <EvidenceList citations={result.citations} title="All sources used" />
        </section>

        <div className="flex flex-wrap items-center gap-3 border-t border-ink-200 pt-8">
          <Link href="/route-check" className="btn-primary">
            Check an itinerary for this region
          </Link>
          {result.trip_id ? (
            <Link href={`/trip/${result.trip_id}`} className="btn-secondary">
              Open the trip workspace
            </Link>
          ) : null}
          <Link href="/where-next" className="btn-ghost">
            Change the trip
          </Link>
        </div>

        <FeedbackWidget analysisId={result.analysis_id} tripId={result.trip_id} />

        <p className="pt-2 text-[0.75rem] text-ink-400">
          Analysis {result.analysis_id} · rubric v{result.scoring_rubric_version} · prompts{" "}
          {Object.entries(result.prompt_versions)
            .map(([k, v]) => `${k}@${v}`)
            .join(", ") || "none"}
        </p>
      </div>
    </div>
  );
}
