import type { RouteIssue } from "@/lib/types";
import { SeverityBadge } from "./primitives";

export function IssueCard({ issue }: { issue: RouteIssue }) {
  const border = {
    critical: "border-l-signal-critical",
    warning: "border-l-signal-warning",
    good: "border-l-signal-good",
    info: "border-l-signal-info",
  }[issue.severity];

  const signals = Object.entries(issue.deterministic_signal);

  return (
    <article className={`card min-w-0 border-l-[3px] ${border} p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-balance font-serif text-[1.05rem] text-ink-900">{issue.title}</h3>
          {issue.segment ? <p className="mt-0.5 text-[0.8rem] text-ink-500">{issue.segment}</p> : null}
        </div>
        <SeverityBadge severity={issue.severity} />
      </div>

      <p className="prose-measure mt-2.5">{issue.explanation}</p>

      {issue.proposed_fix ? (
        <p className="mt-3 rounded-md bg-ink-50 px-3.5 py-2.5 text-[0.86rem] text-ink-700">
          <span className="label mr-2">Fix</span>
          {issue.proposed_fix}
        </p>
      ) : null}

      {signals.length > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-[0.8rem] text-ink-600 hover:text-ink-900">
            The measurements behind this
          </summary>
          <dl className="mt-2.5 grid grid-cols-2 gap-x-5 gap-y-1.5 text-[0.8rem] sm:grid-cols-3">
            {signals.map(([key, value]) => (
              <div key={key}>
                <dt className="text-ink-500">{key.replace(/_/g, " ")}</dt>
                <dd className="tabular-nums text-ink-900">{String(value)}</dd>
              </div>
            ))}
          </dl>
          {issue.rule_id ? (
            <p className="mt-2.5 font-mono text-[0.7rem] text-ink-400">rule {issue.rule_id}</p>
          ) : null}
        </details>
      ) : null}
    </article>
  );
}
