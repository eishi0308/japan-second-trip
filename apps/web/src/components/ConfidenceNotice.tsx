import type { ConflictingEvidence, Confidence, ResolvedFact } from "@/lib/types";
import { Badge, ConfidenceBadge } from "./primitives";

/**
 * The trust panel. Deliberately near the top of every result: what the system
 * assumed, what it could not establish, what is disputed, and whether a person
 * has been asked to check something.
 */
export function ConfidenceNotice({
  confidence,
  humanReviewRequired,
  humanReviewTaskId,
  assumptions = [],
  unknowns = [],
  missingInformation = [],
  conflicts = [],
  resolvedFacts = [],
  supersededBy = null,
}: {
  confidence: Confidence;
  humanReviewRequired: boolean;
  humanReviewTaskId: string | null;
  assumptions?: string[];
  unknowns?: string[];
  missingInformation?: string[];
  conflicts?: ConflictingEvidence[];
  resolvedFacts?: ResolvedFact[];
  supersededBy?: string | null;
}) {
  const hasNotes =
    assumptions.length > 0 ||
    unknowns.length > 0 ||
    missingInformation.length > 0 ||
    conflicts.length > 0 ||
    resolvedFacts.length > 0;

  return (
    <section aria-label="Confidence and caveats" className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-ink-200 bg-ink-50/60 px-5 py-3">
        <ConfidenceBadge confidence={confidence} />
        {humanReviewRequired ? <Badge tone="warning">Sent for human verification</Badge> : null}
        {supersededBy ? <Badge tone="info">Superseded by a re-run</Badge> : null}
      </div>

      <div className="space-y-4 px-5 py-4">
        {humanReviewRequired ? (
          <p className="text-[0.88rem] leading-relaxed text-ink-700">
            Part of this analysis depends on something the system could not settle on its own. A reviewer
            has been asked to confirm it
            {humanReviewTaskId ? (
              <span className="font-mono text-[0.78rem] text-ink-500"> ({humanReviewTaskId})</span>
            ) : null}
            . Treat the affected details as unconfirmed until then.
          </p>
        ) : null}

        {resolvedFacts.length > 0 ? (
          <Block title="Confirmed by a reviewer">
            {resolvedFacts.map((fact) => (
              <li key={`${fact.subject}-${fact.value}`}>
                <span className="font-medium text-ink-800">{fact.subject}</span> — {fact.field ?? "value"}:{" "}
                <span className="font-medium">{fact.value}</span>, verified by {fact.verified_by} on{" "}
                {fact.verified_at.slice(0, 10)}
              </li>
            ))}
          </Block>
        ) : null}

        {conflicts.length > 0 ? (
          <Block title="Sources disagree" tone="warning">
            {conflicts.map((conflict) => (
              <li key={conflict.subject}>
                <span className="font-medium text-ink-800">{conflict.subject}</span>
                {conflict.field_name ? ` (${conflict.field_name})` : ""} —{" "}
                {conflict.values.map((value) => `"${value}"`).join(" vs ")}. Not resolved automatically.
              </li>
            ))}
          </Block>
        ) : null}

        {assumptions.length > 0 ? (
          <Block title="Assumptions made">
            {assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </Block>
        ) : null}

        {unknowns.length > 0 ? (
          <Block title="Not established">
            {unknowns.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </Block>
        ) : null}

        {missingInformation.length > 0 ? (
          <Block title="You didn't tell us">
            {missingInformation.map((item) => (
              <li key={item}>{item.replace(/_/g, " ")}</li>
            ))}
          </Block>
        ) : null}

        {!hasNotes && !humanReviewRequired ? (
          <p className="text-[0.88rem] text-ink-600">
            No assumptions, unknowns or source conflicts affected this result.
          </p>
        ) : null}
      </div>
    </section>
  );
}

function Block({
  title,
  children,
  tone = "neutral",
}: {
  title: string;
  children: React.ReactNode;
  tone?: "neutral" | "warning";
}) {
  return (
    <div>
      <p className={`label ${tone === "warning" ? "text-signal-warning" : ""}`}>{title}</p>
      <ul className="mt-1.5 space-y-1 text-[0.86rem] leading-relaxed text-ink-700">{children}</ul>
    </div>
  );
}
