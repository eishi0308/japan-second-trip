import Link from "next/link";
import type { Assumption, Option, PlanResult, Rejection } from "@/lib/v2";
import { MONTHS } from "@/lib/v2";
import { AssumedChip, DemoTag, FactMark, FitLevel, Icon, LoadBar, VerdictMark } from "./ui";

/**
 * Option card, top to bottom as PRODUCT_AMENDMENTS.md §5 orders it:
 * character, combination, one line, fit, travel load, car, season,
 * What's hard, verification with date.
 */
export function OptionCard({
  option,
  href,
  footer,
}: {
  option: Option;
  href?: string;
  footer?: React.ReactNode;
}) {
  return (
    <article className="card flex h-full flex-col p-5 sm:p-6" aria-label={`${option.character_label}: ${option.title}`}>
      <p className="label text-accent-700">{option.character_label}</p>
      <h3 className="mt-1.5 font-serif text-title text-ink-900">
        {href ? (
          <Link href={href} className="hover:underline">
            {option.title}
          </Link>
        ) : (
          option.title
        )}
      </h3>
      <p className="mt-0.5 text-sm tabular-nums text-ink-500">{option.nights_label}</p>
      <p className="mt-3 text-[0.92rem] leading-relaxed text-ink-700">{option.description}</p>

      <div className="mt-5 space-y-2">
        <FitLevel level={option.fit.level} label={option.fit.label} />
        <ul className="space-y-0.5 text-[0.8rem] text-ink-600">
          {option.fit.breakdown.map((line) => (
            <li key={line.name}>{line.text}</li>
          ))}
        </ul>
      </div>

      <div className="mt-5">
        <LoadBar load={option.travel.load} label={option.travel.moving_label} />
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-[0.82rem]">
        <div>
          <dt className="label">Car</dt>
          <dd className="mt-0.5 text-ink-800">{option.car_label}</dd>
        </div>
        <div>
          <dt className="label">Season</dt>
          <dd className="mt-0.5 text-ink-800">{option.season_label}</dd>
        </div>
      </dl>

      <div className="mt-5">
        <p className="label">What&apos;s hard</p>
        <ul className="mt-2 space-y-1.5 text-[0.85rem] text-ink-700">
          {option.whats_hard.map((item) => (
            <li key={item.text} className="flex gap-2">
              <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-warning" />
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto pt-5">
        <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-4 text-[0.78rem] text-ink-600">
          <FactMark state={option.verification.state} date={option.verification.oldest_verified_at} />
          {option.check ? <VerdictMark verdict={option.check.verdict} label={option.check.verdict_label} /> : null}
          {option.verification.is_demo ? <DemoTag /> : null}
        </div>
        <p className="mt-2 text-[0.75rem] text-ink-500">{option.verification.label}</p>
        {footer ? <div className="mt-4">{footer}</div> : null}
      </div>
    </article>
  );
}

export function NotForThisTrip({ rejections }: { rejections: Rejection[] }) {
  if (!rejections.length) return null;
  return (
    <details className="card group mt-8 p-5 sm:p-6">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
        <span>
          <span className="font-serif text-lg text-ink-900">Not for this trip</span>
          <span className="ml-2 text-sm text-ink-500">{rejections.length} areas ruled out, and why</span>
        </span>
        <span className="text-sm text-accent-700 group-open:hidden">Show</span>
        <span className="hidden text-sm text-accent-700 group-open:inline">Hide</span>
      </summary>
      <ul className="mt-5 divide-y divide-ink-100">
        {rejections.map((r) => (
          <li key={r.area} className="py-3.5">
            <p className="font-medium text-ink-900">
              {r.area_label} <span className="font-normal text-ink-500">(e.g. {r.example})</span>
            </p>
            <p className="mt-1 text-[0.9rem] text-ink-700">{r.reason}</p>
            {r.if_you_change ? (
              <p className="mt-1 flex gap-1.5 text-[0.9rem] text-accent-800">
                <Icon name="info" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {r.if_you_change}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function ConditionSummary({
  plan,
  month,
  nights,
  assumptions,
}: {
  plan: PlanResult;
  month?: number | null;
  nights?: number | null;
  assumptions: Assumption[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[0.82rem] text-ink-700" aria-label="Your conditions">
      {month ? <span className="chip-off cursor-default">{MONTHS[month - 1]}</span> : null}
      {nights ? <span className="chip-off cursor-default">{nights} regional nights</span> : null}
      {plan.interests.map((i) => (
        <span key={i} className="chip-off cursor-default capitalize">
          {i}
        </span>
      ))}
      {assumptions.map((a) => (
        <AssumedChip key={a.field} label={a.label} />
      ))}
    </div>
  );
}

export function Notices({ plan }: { plan: PlanResult }) {
  const notices = plan.notices.filter((n) => n.code !== "demo_data");
  if (!notices.length) return null;
  return (
    <ul className="mt-4 space-y-2">
      {notices.map((n) => (
        <li key={n.text} className="flex gap-2 rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-[0.85rem] text-ink-700">
          <Icon name="question" className="mt-0.5 h-4 w-4 shrink-0 text-ink-500" />
          {n.text}
        </li>
      ))}
    </ul>
  );
}

export function Funnel({ steps }: { steps: { label: string; count: number }[] }) {
  return (
    <p className="text-[0.82rem] tabular-nums text-ink-500" aria-label="How we narrowed it down">
      {steps.map((s, i) => (
        <span key={s.label}>
          {i > 0 ? <span aria-hidden="true"> → </span> : null}
          <span className="text-ink-700">{s.count}</span> {s.label}
        </span>
      ))}
    </p>
  );
}
