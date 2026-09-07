import Link from "next/link";
import type { Confidence, FitLabel, Freshness, RouteHealth, Severity } from "@/lib/types";

export function Badge({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: "neutral" | "critical" | "warning" | "good" | "info";
  children: React.ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "border-ink-300 bg-ink-50 text-ink-600",
    critical: "border-signal-critical/30 bg-signal-critical/10 text-signal-critical",
    warning: "border-signal-warning/30 bg-signal-warning/10 text-signal-warning",
    good: "border-signal-good/30 bg-signal-good/10 text-signal-good",
    info: "border-signal-info/30 bg-signal-info/10 text-signal-info",
  } as const;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[0.72rem] font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

const FIT_TONE: Record<FitLabel, "good" | "info" | "warning" | "critical"> = {
  strong: "good",
  good: "info",
  marginal: "warning",
  not_recommended: "critical",
};

const FIT_LABEL: Record<FitLabel, string> = {
  strong: "Strong fit",
  good: "Good fit",
  marginal: "Marginal",
  not_recommended: "Not recommended for this trip",
};

export function FitBadge({ label }: { label: FitLabel }) {
  return <Badge tone={FIT_TONE[label]}>{FIT_LABEL[label]}</Badge>;
}

const HEALTH: Record<RouteHealth, { tone: "good" | "warning" | "critical"; text: string }> = {
  healthy: { tone: "good", text: "Healthy" },
  needs_improvement: { tone: "warning", text: "Needs improvement" },
  high_risk: { tone: "critical", text: "High risk" },
};

export function HealthBadge({ health }: { health: RouteHealth }) {
  const meta = HEALTH[health];
  return <Badge tone={meta.tone}>{meta.text}</Badge>;
}

const SEVERITY: Record<Severity, { tone: "critical" | "warning" | "good" | "info"; text: string }> = {
  critical: { tone: "critical", text: "Critical" },
  warning: { tone: "warning", text: "Warning" },
  good: { tone: "good", text: "Working well" },
  info: { tone: "info", text: "Note" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const meta = SEVERITY[severity];
  return <Badge tone={meta.tone}>{meta.text}</Badge>;
}

const CONFIDENCE: Record<Confidence, { tone: "good" | "info" | "warning" | "critical"; text: string }> = {
  high: { tone: "good", text: "High confidence" },
  medium: { tone: "info", text: "Medium confidence" },
  low: { tone: "warning", text: "Low confidence" },
  insufficient_evidence: { tone: "critical", text: "Insufficient evidence" },
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const meta = CONFIDENCE[confidence];
  return <Badge tone={meta.tone}>{meta.text}</Badge>;
}

const FRESHNESS: Record<Freshness, { tone: "good" | "warning" | "critical" | "neutral"; text: string }> = {
  fresh: { tone: "good", text: "Verified" },
  ageing: { tone: "warning", text: "Re-check before booking" },
  stale: { tone: "critical", text: "Out of date" },
  unverified: { tone: "neutral", text: "Not verified" },
};

export function FreshnessBadge({ freshness, verifiedAt }: { freshness: Freshness; verifiedAt: string | null }) {
  const meta = FRESHNESS[freshness];
  const date = verifiedAt ? new Date(verifiedAt).toISOString().slice(0, 10) : null;
  return (
    <Badge tone={meta.tone}>
      {meta.text}
      {date ? ` · ${date}` : ""}
    </Badge>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  id,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  id?: string;
}) {
  return (
    <div className="mb-5">
      {eyebrow ? <p className="label mb-1.5">{eyebrow}</p> : null}
      <h2 id={id} className="text-title font-serif text-ink-900">
        {title}
      </h2>
      {description ? <p className="prose-measure mt-2">{description}</p> : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="card px-6 py-12 text-center">
      <p className="font-serif text-lg text-ink-800">{title}</p>
      <p className="prose-measure mx-auto mt-2 text-center">{description}</p>
      {action ? (
        <Link href={action.href} className="btn-secondary mt-5">
          {action.label}
        </Link>
      ) : null}
    </div>
  );
}

export function ErrorState({ title, message, retry }: { title: string; message: string; retry?: React.ReactNode }) {
  return (
    <div className="card border-signal-critical/25 bg-signal-critical/[0.04] px-6 py-8" role="alert">
      <p className="font-serif text-lg text-ink-900">{title}</p>
      <p className="prose-measure mt-2">{message}</p>
      {retry ? <div className="mt-5">{retry}</div> : null}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`relative overflow-hidden rounded bg-ink-100 ${className}`} aria-hidden="true">
      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/60 to-transparent motion-safe:animate-[shimmer_1.4s_infinite]" />
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="label">{label}</p>
      <p className="mt-1 font-serif text-[1.35rem] tabular-nums text-ink-900">{value}</p>
      {hint ? <p className="mt-0.5 text-[0.78rem] text-ink-500">{hint}</p> : null}
    </div>
  );
}
