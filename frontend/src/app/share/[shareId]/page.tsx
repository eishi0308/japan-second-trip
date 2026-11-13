import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ErrorState } from "@/components/primitives";
import { CheckWorkspace } from "@/components/v2/CheckWorkspace";
import { PageHeading } from "@/components/v2/ui";
import { ApiRequestError } from "@/lib/api";
import type { SavedTrip } from "@/lib/v2";
import { formatDate, v2 } from "@/lib/v2";

export const metadata: Metadata = { title: "Shared trip" };

export default async function SharePage({ params }: { params: Promise<{ shareId: string }> }) {
  const { shareId } = await params;
  let trip: SavedTrip;
  try {
    trip = await v2.shared(shareId);
  } catch (err) {
    if (err instanceof ApiRequestError && err.status === 404) notFound();
    return (
      <div className="shell py-16">
        <ErrorState title="This trip is not reachable" message="Reload in a moment." />
      </div>
    );
  }
  return (
    <div className="shell py-12 sm:py-14">
      <PageHeading eyebrow="Shared trip (read-only)" title={trip.title}>
        Checked today{trip.updated_at ? `; last changed ${formatDate(trip.updated_at)}` : ""}.
      </PageHeading>
      <CheckWorkspace initialRequest={trip.check_request} initialResponse={trip.result} readOnly />
    </div>
  );
}
