import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ErrorState } from "@/components/primitives";
import { ConditionSummary, Funnel, NotForThisTrip, Notices, OptionCard } from "@/components/v2/OptionCard";
import { Reactions, ReplanButton } from "@/components/v2/PlanActions";
import { FullReportButton } from "@/components/v2/FullReportButton";
import { Icon, PageHeading } from "@/components/v2/ui";
import { ApiRequestError } from "@/lib/api";
import type { OptionSet, PlanRequest, PlanResponse } from "@/lib/v2";
import { applySuggestion, MONTHS, v2 } from "@/lib/v2";

export const metadata: Metadata = { title: "Three trips" };

export default async function PlanResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let res: PlanResponse;
  try {
    res = await v2.getPlan(id);
  } catch (err) {
    if (err instanceof ApiRequestError && err.status === 404) notFound();
    return (
      <div className="shell py-16">
        <ErrorState title="The planner is not reachable" message="Your plan is saved. Reload in a moment to see it." />
      </div>
    );
  }
  const { plan, request } = res;

  return (
    <div className="shell py-12 sm:py-14">
      {plan.kind === "options" && plan.result ? (
        <>
          <PageHeading eyebrow="Where next" title="Three trips that work">
            Different in character, each checked day by day. Open one to see the timeline.
          </PageHeading>
          <ConditionSummary plan={plan} month={plan.result.month} nights={plan.result.nights} assumptions={plan.assumptions} />
          <Notices plan={plan} />
          <div className="mt-4">
            <Funnel steps={plan.result.funnel} />
          </div>
          <Options set={plan.result} request={request} planId={id} />
          <div className="mt-6 flex flex-wrap items-center gap-3">
            {plan.result.options.length > 1 ? (
              <Link href={`/plan/${id}/compare`} className="btn-primary">
                Compare side by side
              </Link>
            ) : null}
            <Link href={`/plan?from=${id}`} className="btn-ghost">
              Change my answers
            </Link>
            {preferenceNote(res)}
          </div>
          <NotForThisTrip rejections={plan.result.not_for_this_trip} />
        </>
      ) : null}

      {plan.kind === "season_choice" ? (
        <>
          <PageHeading eyebrow="Where next" title="Pick a season">
            You have not picked a month yet. Here is what each season would look like.
          </PageHeading>
          <ConditionSummary plan={plan} assumptions={plan.assumptions} />
          <Notices plan={plan} />
          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            {plan.seasons.map((s) => (
              <Choice
                key={s.season}
                title={s.label}
                set={s.result}
                action={
                  <ReplanButton request={request} patch={{ month: s.month }} className="btn-primary w-full">
                    Choose {s.season}
                  </ReplanButton>
                }
              />
            ))}
          </div>
        </>
      ) : null}

      {plan.kind === "nights_choice" ? (
        <>
          <PageHeading eyebrow="Where next" title="How many nights?">
            You have not decided how long yet. Compare a shorter and a longer trip in{" "}
            {MONTHS[(request.month ?? 1) - 1]}.
          </PageHeading>
          <ConditionSummary plan={plan} month={request.month} assumptions={plan.assumptions} />
          <Notices plan={plan} />
          <div className="mt-8 grid gap-5 md:grid-cols-2">
            {plan.nights_options.map((n) => (
              <Choice
                key={n.nights}
                title={n.label}
                set={n.result}
                action={
                  <ReplanButton request={request} patch={{ regional_nights: n.nights }} className="btn-primary w-full">
                    Go with {n.nights} nights
                  </ReplanButton>
                }
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function preferenceNote(res: PlanResponse) {
  if (res.preferences.source === "none") return null;
  return (
    <p className="text-[0.8rem] text-ink-500">
      From your answers: {res.preferences.interests.join(", ") || "no interests"}
      {res.preferences.avoid.length ? `; less ${res.preferences.avoid.join(", ").replace(/_/g, " ")}` : ""}.
    </p>
  );
}

function Options({ set, request, planId }: { set: OptionSet; request: PlanRequest; planId: string }) {
  if (!set.options.length) {
    return (
      <div className="card mt-8 p-6" role="status">
        <p className="font-serif text-lg text-ink-900">No trip fits all of these conditions</p>
        <p className="prose-measure mt-2">
          These are the smallest changes that would give you options. Each one is checked.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          {set.zero_results_suggestions.map((s) => (
            <ReplanButton key={s.change} request={request} patch={applySuggestion(request, s.change, set)}>
              {s.label} ({s.options_found} option{s.options_found > 1 ? "s" : ""})
            </ReplanButton>
          ))}
          {!set.zero_results_suggestions.length ? (
            <Link href={`/plan?from=${planId}`} className="btn-secondary">
              Change my answers
            </Link>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <div className="mt-8 grid gap-5 lg:grid-cols-3">
      {set.options.map((option, n) => (
        <OptionCard
          key={option.title}
          option={option}
          href={`/plan/${planId}/option/${n}`}
          footer={
            <div className="space-y-3">
              <Reactions request={request} stops={option.stops.map((s) => s.slug)} />
              <div className="flex flex-wrap gap-2">
                <Link href={`/plan/${planId}/option/${n}`} className="btn-secondary">
                  Day by day
                </Link>
                <FullReportButton planId={planId} option={n} />
              </div>
            </div>
          }
        />
      ))}
    </div>
  );
}

function Choice({ title, set, action }: { title: string; set: OptionSet; action: React.ReactNode }) {
  return (
    <section className="card flex flex-col p-5" aria-label={title}>
      <h2 className="font-serif text-title text-ink-900">{title}</h2>
      <ul className="mt-4 space-y-3">
        {set.options.map((o) => (
          <li key={o.title}>
            <p className="label text-accent-700">{o.character_label}</p>
            <p className="font-medium text-ink-900">{o.title}</p>
            <p className="text-[0.8rem] text-ink-500">
              {o.nights_label} · {o.fit.label}
            </p>
          </li>
        ))}
        {!set.options.length ? (
          <li className="flex gap-2 text-sm text-ink-600">
            <Icon name="info" className="mt-0.5 h-4 w-4" /> Nothing fits these conditions in this season.
          </li>
        ) : null}
      </ul>
      <div className="mt-auto pt-5">{action}</div>
    </section>
  );
}
