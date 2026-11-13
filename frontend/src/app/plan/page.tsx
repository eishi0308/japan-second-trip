import type { Metadata } from "next";
import { PlanForm } from "@/components/v2/PlanForm";
import { PageHeading } from "@/components/v2/ui";
import { ErrorState } from "@/components/primitives";
import type { City, PlanRequest, SceneCard } from "@/lib/v2";
import { v2 } from "@/lib/v2";

export const metadata: Metadata = { title: "Plan your next trip" };

export default async function PlanPage({ searchParams }: { searchParams: Promise<{ from?: string }> }) {
  const { from } = await searchParams;
  let cities: City[] = [];
  let cards: SceneCard[] = [];
  let initial: PlanRequest | undefined;
  try {
    [cities, cards] = await Promise.all([v2.cities(), v2.sceneCards()]);
    if (from) initial = (await v2.getPlan(from)).request;
  } catch {
    return (
      <div className="shell py-16">
        <ErrorState title="The planner is not reachable" message="We could not load the form. Try again in a moment." />
      </div>
    );
  }
  return (
    <div className="shell max-w-4xl py-12 sm:py-16">
      <PageHeading eyebrow="Where next" title="Where should your next Japan trip go?">
        Tell us what you know. We suggest three trips beyond Tokyo, Kyoto and Osaka, check that each one works, and show
        you what is hard about it.
      </PageHeading>
      <PlanForm cities={cities} sceneCards={cards} initial={initial} />
    </div>
  );
}
