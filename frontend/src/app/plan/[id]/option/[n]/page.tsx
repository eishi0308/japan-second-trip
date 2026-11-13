import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ErrorState } from "@/components/primitives";
import { CheckWorkspace } from "@/components/v2/CheckWorkspace";
import { FitLevel, Icon, PageHeading } from "@/components/v2/ui";
import { ApiRequestError } from "@/lib/api";
import type { PlanResponse } from "@/lib/v2";
import { optionToCheck, v2 } from "@/lib/v2";

export const metadata: Metadata = { title: "Option detail" };

export default async function OptionPage({ params }: { params: Promise<{ id: string; n: string }> }) {
  const { id, n } = await params;
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
  const set = res.plan.result;
  const option = set?.options[Number(n)];
  if (!set || !option || !option.check) notFound();

  return (
    <div className="shell py-12 sm:py-14">
      <Link href={`/plan/${id}`} className="text-sm text-accent-700 hover:underline">
        ← Back to the three trips
      </Link>
      <PageHeading eyebrow={option.character_label} title={option.title}>
        {option.description}
      </PageHeading>
      <div className="-mt-4 mb-8 flex flex-wrap items-center gap-4">
        <FitLevel level={option.fit.level} label={option.fit.label} />
        <span className="text-sm text-ink-600">{option.nights_label}</span>
        <span className="text-sm text-ink-600">{option.car_label}</span>
        <span className="text-sm text-ink-600">{option.season_label}</span>
      </div>
      <section aria-labelledby="hard" className="mb-10">
        <h2 id="hard" className="label mb-2">
          What&apos;s hard
        </h2>
        <ul className="space-y-1.5">
          {option.whats_hard.map((h) => (
            <li key={h.text} className="flex gap-2 text-[0.92rem] text-ink-800">
              <Icon name="alert" className="mt-1 h-3.5 w-3.5 shrink-0 text-signal-warning" />
              {h.text}
            </li>
          ))}
        </ul>
      </section>
      <CheckWorkspace
        initialRequest={optionToCheck(option, res.request, set.month)}
        initialResponse={{ check: option.check, also_consider: [] }}
        planId={id}
      />
    </div>
  );
}
