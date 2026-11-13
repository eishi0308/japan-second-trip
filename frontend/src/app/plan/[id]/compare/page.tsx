import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ErrorState } from "@/components/primitives";
import { CompareTable } from "@/components/v2/CompareTable";
import { PageHeading } from "@/components/v2/ui";
import { ApiRequestError } from "@/lib/api";
import type { PlanResponse } from "@/lib/v2";
import { v2 } from "@/lib/v2";

export const metadata: Metadata = { title: "Compare" };

export default async function ComparePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let res: PlanResponse;
  try {
    res = await v2.getPlan(id);
  } catch (err) {
    if (err instanceof ApiRequestError && err.status === 404) notFound();
    return (
      <div className="shell py-16">
        <ErrorState title="The planner is not reachable" message="Reload in a moment." />
      </div>
    );
  }
  return (
    <div className="shell py-12 sm:py-14">
      <Link href={`/plan/${id}`} className="text-sm text-accent-700 hover:underline">
        ← Back to the three trips
      </Link>
      <PageHeading eyebrow="Compare" title="Side by side">
        The same rows for each trip. Try a what-if: the comparison is recomputed straight away.
      </PageHeading>
      <CompareTable initial={res} planId={id} />
    </div>
  );
}
