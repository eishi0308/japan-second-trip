import type { Metadata } from "next";
import { RouteCheckFlow } from "@/components/v2/RouteCheckFlow";
import { PageHeading } from "@/components/v2/ui";

export const metadata: Metadata = { title: "Check my route" };

export default function CheckPage() {
  return (
    <div className="shell py-12 sm:py-16">
      <PageHeading eyebrow="RouteCheck" title="Does your itinerary actually work?">
        Paste what you have. We read it into a table for you to confirm, then check it day by day: last buses, closures,
        long travel days, and what to fix without losing the stops you care about.
      </PageHeading>
      <RouteCheckFlow />
    </div>
  );
}
