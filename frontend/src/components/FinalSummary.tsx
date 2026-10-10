import type { FinalExplanation } from "@/lib/types";

/**
 * The closing summary of an analysis: the verdict, what to do next and what to
 * hold loosely. Analyses stored before the summary existed have none, and then
 * nothing is rendered — the detail below stands on its own.
 */
export function FinalSummary({ summary }: { summary: FinalExplanation | null | undefined }) {
  if (!summary || !summary.verdict) return null;
  return (
    <section aria-labelledby="final-summary-heading" className="card p-6">
      <p id="final-summary-heading" className="label mb-2.5">
        In short
      </p>
      <p className="font-serif text-[1.08rem] leading-relaxed text-ink-900">{summary.verdict}</p>

      {summary.next_steps.length > 0 ? (
        <div className="mt-5">
          <p className="label mb-2">What to do next</p>
          <ol className="space-y-1.5 text-[0.9rem] leading-relaxed text-ink-800">
            {summary.next_steps.map((step, index) => (
              <li key={step} className="flex gap-2.5">
                <span aria-hidden="true" className="tabular-nums text-ink-500">
                  {index + 1}.
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {summary.caveats.length > 0 ? (
        <div className="mt-5 border-t border-ink-200 pt-4">
          <p className="label mb-2">Hold loosely</p>
          <ul className="space-y-1.5 text-[0.88rem] leading-relaxed text-ink-700">
            {summary.caveats.map((caveat) => (
              <li key={caveat} className="flex gap-2.5">
                <span aria-hidden="true" className="mt-[0.5rem] h-1 w-1 shrink-0 rounded-full bg-ink-500" />
                <span>{caveat}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
