import type { Metadata } from "next";
import { RouteCheckForm } from "@/components/RouteCheckForm";

export const metadata: Metadata = {
  title: "Check my route",
  description: "Is this itinerary actually realistic? Checked against real transport and a deterministic rules engine.",
};

export default function RouteCheckPage() {
  return (
    <div className="shell max-w-3xl py-14">
      <p className="label mb-4">Path B</p>
      <h1 className="text-headline font-serif text-ink-900">I already have a route. Check it.</h1>
      <p className="prose-measure mt-3">
        Paste the itinerary however you&rsquo;d write it down. Each stop is resolved, every hop is costed
        with real transport data, and a rules engine grades travel burden, accommodation churn, last
        connections, closures and booking lead times.
      </p>
      <div className="mt-10">
        <RouteCheckForm />
      </div>
    </div>
  );
}
