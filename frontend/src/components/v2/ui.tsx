/**
 * Small presentational pieces shared by every v2 screen.
 *
 * Design rules (PRODUCT_AMENDMENTS.md §2 and §8):
 * - status colour always comes with an icon and words, never colour alone;
 * - no percentages, no "confidence", no machinery words;
 * - every fact shows its date; "Verified" never appears without one.
 */

import type { Evidence, FactState, Severity, Verdict } from "@/lib/v2";
import { formatDate } from "@/lib/v2";

type Tone = "good" | "warning" | "critical" | "info" | "neutral";

const TONE_CLASS: Record<Tone, string> = {
  good: "border-signal-good/30 bg-signal-good/[0.07] text-signal-good",
  warning: "border-signal-warning/30 bg-signal-warning/[0.08] text-signal-warning",
  critical: "border-signal-critical/30 bg-signal-critical/[0.06] text-signal-critical",
  info: "border-accent-200 bg-accent-50 text-accent-700",
  neutral: "border-ink-200 bg-ink-50 text-ink-600",
};

export function Icon({ name, className = "h-3.5 w-3.5" }: { name: string; className?: string }) {
  const paths: Record<string, React.ReactNode> = {
    check: <path d="M3.5 8.5l3 3 6-7" />,
    cross: <path d="M4.5 4.5l7 7m0-7l-7 7" />,
    alert: (
      <>
        <path d="M8 2.5l6 11H2l6-11z" />
        <path d="M8 6.5v3.2M8 11.6v.1" />
      </>
    ),
    clock: (
      <>
        <circle cx="8" cy="8" r="5.8" />
        <path d="M8 4.8V8l2.2 1.6" />
      </>
    ),
    question: (
      <>
        <circle cx="8" cy="8" r="5.8" />
        <path d="M6.4 6.4a1.7 1.7 0 113 1.1c-.6.5-1.4.8-1.4 1.8M8 11.4v.1" />
      </>
    ),
    search: (
      <>
        <circle cx="7" cy="7" r="4.2" />
        <path d="M10.2 10.2l3.3 3.3" />
      </>
    ),
    info: (
      <>
        <circle cx="8" cy="8" r="5.8" />
        <path d="M8 7.2v3.8M8 5v.1" />
      </>
    ),
    pin: <path d="M8 14s4.5-4.3 4.5-7.6a4.5 4.5 0 10-9 0C3.5 9.7 8 14 8 14zm0-6a1.6 1.6 0 100-3.2A1.6 1.6 0 008 8z" />,
  };
  return (
    <svg
      viewBox="0 0 16 16"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.info}
    </svg>
  );
}

export function Pill({ tone, icon, children }: { tone: Tone; icon?: string; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[0.75rem] font-medium ${TONE_CLASS[tone]}`}
    >
      {icon ? <Icon name={icon} /> : null}
      {children}
    </span>
  );
}

const FACT: Record<FactState, { tone: Tone; icon: string; text: string }> = {
  verified: { tone: "good", icon: "check", text: "Checked" },
  stale: { tone: "warning", icon: "clock", text: "May be out of date" },
  unverified: { tone: "neutral", icon: "question", text: "No verified info yet" },
  being_checked: { tone: "warning", icon: "search", text: "Being checked" },
};

/** A fact's state. "Checked" always carries its date. */
export function FactMark({ state, date }: { state: FactState; date?: string | null }) {
  const meta = FACT[state];
  const when = (state === "verified" || state === "stale") && date ? ` ${formatDate(date)}` : "";
  return (
    <Pill tone={meta.tone} icon={meta.icon}>
      {meta.text}
      {when}
    </Pill>
  );
}

const VERDICT: Record<Verdict, { tone: Tone; icon: string }> = {
  works: { tone: "good", icon: "check" },
  needs_attention: { tone: "warning", icon: "alert" },
  will_not_work: { tone: "critical", icon: "cross" },
};

export function VerdictMark({ verdict, label }: { verdict: Verdict; label: string }) {
  const meta = VERDICT[verdict];
  return (
    <Pill tone={meta.tone} icon={meta.icon}>
      {label}
    </Pill>
  );
}

const SEVERITY: Record<Severity, { tone: Tone; icon: string; text: string }> = {
  critical: { tone: "critical", icon: "cross", text: "Breaks the trip" },
  warning: { tone: "warning", icon: "alert", text: "Look at this" },
  info: { tone: "info", icon: "info", text: "Good to know" },
};

export function SeverityMark({ severity }: { severity: Severity }) {
  const meta = SEVERITY[severity];
  return (
    <Pill tone={meta.tone} icon={meta.icon}>
      {meta.text}
    </Pill>
  );
}

/** Five steps, never a percentage. */
export function FitLevel({ level, label }: { level: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-2" aria-label={`${label}, ${level} of 5`}>
      <span className="flex gap-1" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((n) => (
          <span key={n} className={`h-2 w-4 rounded-sm ${n <= level ? "bg-accent-600" : "bg-ink-200"}`} />
        ))}
      </span>
      <span className="text-sm font-medium text-ink-800">{label}</span>
    </span>
  );
}

const LOAD_WIDTH = { light: "w-1/3", moderate: "w-2/3", heavy: "w-full" } as const;

export function LoadBar({ load, label }: { load: "light" | "moderate" | "heavy"; label: string }) {
  const tone = load === "heavy" ? "bg-signal-warning" : "bg-accent-500";
  return (
    <div>
      <div className="flex items-baseline justify-between text-[0.8rem] text-ink-600">
        <span>{label}</span>
        <span>{load.charAt(0).toUpperCase() + load.slice(1)} travel</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-ink-100" aria-hidden="true">
        <div className={`h-1.5 rounded-full ${tone} ${LOAD_WIDTH[load]}`} />
      </div>
    </div>
  );
}

export function EvidenceLine({ evidence }: { evidence: Evidence }) {
  return (
    <li className="flex flex-wrap items-center gap-2 text-[0.8rem] text-ink-600">
      <FactMark state={evidence.fact_state} date={evidence.verified_at} />
      <span>{evidence.label}</span>
      {evidence.is_demo ? <DemoTag /> : null}
    </li>
  );
}

export function DemoTag() {
  return (
    <span className="rounded border border-signal-warning/30 bg-signal-warning/[0.08] px-1.5 py-px text-[0.68rem] font-semibold uppercase tracking-wide text-signal-warning">
      Demo
    </span>
  );
}

export function AssumedChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-accent-300 bg-accent-50 px-2.5 py-0.5 text-[0.75rem] text-accent-800">
      {label}
    </span>
  );
}

export function PageHeading({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: React.ReactNode }) {
  return (
    <header className="mb-8">
      {eyebrow ? <p className="label mb-2">{eyebrow}</p> : null}
      <h1 className="font-serif text-headline text-ink-900">{title}</h1>
      {children ? <div className="prose-measure mt-3">{children}</div> : null}
    </header>
  );
}
