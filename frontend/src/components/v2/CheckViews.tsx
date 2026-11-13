/**
 * Presentational pieces of a feasibility check, shared by option detail,
 * RouteCheck results, saved trips and share links.
 */

import type { BookingItem, CheckResult, CheckStop, Day, Fix, Issue } from "@/lib/v2";
import { formatDate, hours } from "@/lib/v2";
import { DemoTag, EvidenceLine, Icon, SeverityMark, VerdictMark } from "./ui";

export function VerdictHeader({ check }: { check: CheckResult }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <VerdictMark verdict={check.verdict} label={check.verdict_label} />
      <p className="text-[0.95rem] text-ink-700">{check.summary}</p>
      <p className="text-[0.82rem] text-ink-500">
        {hours(check.moving_minutes)} moving · {check.hotel_changes} hotel change{check.hotel_changes === 1 ? "" : "s"}
      </p>
    </div>
  );
}

/** Schematic map: stops placed by latitude and longitude, in travel order. */
export function RouteMap({ stops }: { stops: CheckStop[] }) {
  const pts = stops.filter((s) => s.lat != null && s.lon != null && s.nights > 0);
  if (pts.length === 0) return null;
  const lats = pts.map((p) => p.lat as number);
  const lons = pts.map((p) => p.lon as number);
  const pad = 0.6;
  const minLat = Math.min(...lats) - pad;
  const maxLat = Math.max(...lats) + pad;
  const minLon = Math.min(...lons) - pad;
  const maxLon = Math.max(...lons) + pad;
  const W = 320;
  const H = 220;
  const span = Math.max(maxLon - minLon, (maxLat - minLat) * 1.2);
  const x = (lon: number) => 20 + ((lon - minLon) / span) * (W - 40);
  const y = (lat: number) => H - 20 - ((lat - minLat) / (span / 1.2)) * (H - 40);
  const line = pts.map((p) => `${x(p.lon as number)},${y(p.lat as number)}`).join(" ");
  return (
    <figure className="card p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Map of stops: ${pts.map((p) => p.name).join(", ")}`}>
        <rect x="0" y="0" width={W} height={H} fill="#f7f7f6" rx="6" />
        <polyline points={line} fill="none" stroke="#7180bf" strokeWidth="2" strokeDasharray="4 4" />
        {pts.map((p, i) => (
          <g key={`${p.name}-${i}`}>
            <circle cx={x(p.lon as number)} cy={y(p.lat as number)} r="9" fill={p.pinned ? "#3d4b8c" : "#ffffff"} stroke="#3d4b8c" strokeWidth="2" />
            <text x={x(p.lon as number)} y={y(p.lat as number) + 3.5} textAnchor="middle" fontSize="10" fill={p.pinned ? "#ffffff" : "#3d4b8c"} fontWeight="600">
              {i + 1}
            </text>
            <text x={x(p.lon as number) + 13} y={y(p.lat as number) + 4} fontSize="11" fill="#1c1c1a">
              {p.name}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="mt-2 text-[0.75rem] text-ink-500">Schematic, not to scale. Filled circles are pinned stops.</figcaption>
    </figure>
  );
}

export function DayTimeline({ days, issues }: { days: Day[]; issues: Issue[] }) {
  const byId = new Map(issues.map((i) => [i.id, i]));
  return (
    <ol className="space-y-3" aria-label="Day by day">
      {days.map((day) => {
        const total = Math.max(1, day.moving_minutes + day.staying_minutes);
        const dayIssues = day.issue_ids.map((id) => byId.get(id)).filter((i): i is Issue => !!i && i.severity !== "info");
        return (
          <li key={day.day} className="card p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-medium text-ink-900">
                <span className="label mr-2">Day {day.day}</span>
                {day.date ? <span className="mr-2 text-[0.8rem] text-ink-500">{formatDate(day.date)}</span> : null}
                {day.title}
              </p>
              <p className="text-[0.8rem] text-ink-500">{day.overnight ? `Night in ${day.overnight}` : "Last day"}</p>
            </div>
            <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-ink-100" aria-hidden="true">
              <div className="bg-accent-600" style={{ width: `${(day.moving_minutes / total) * 100}%` }} />
              <div className="bg-accent-200" style={{ width: `${(day.staying_minutes / total) * 100}%` }} />
            </div>
            <p className="mt-1.5 flex flex-wrap gap-x-4 text-[0.8rem] text-ink-600">
              <span>
                <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-accent-600" aria-hidden="true" />
                {day.moving_label}
              </span>
              <span>
                <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-accent-200" aria-hidden="true" />
                {day.staying_label}
              </span>
            </p>
            {day.moves.length ? (
              <ul className="mt-2 space-y-0.5 text-[0.8rem] tabular-nums text-ink-600">
                {day.moves.map((m, i) => (
                  <li key={i}>
                    {m.origin} {m.depart} → {m.destination} {m.arrive}
                    {m.minutes ? ` (${hours(m.minutes)}${m.transfers ? `, ${m.transfers} change${m.transfers > 1 ? "s" : ""}` : ""})` : ""}
                    {m.estimated ? <span className="ml-1 text-ink-400">estimated</span> : null}
                  </li>
                ))}
              </ul>
            ) : null}
            {dayIssues.length ? (
              <ul className="mt-2 space-y-1">
                {dayIssues.map((i) => (
                  <li key={i.id} className="flex gap-1.5 text-[0.82rem] text-ink-800">
                    <Icon name={i.severity === "critical" ? "cross" : "alert"} className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${i.severity === "critical" ? "text-signal-critical" : "text-signal-warning"}`} />
                    <a href={`#${cssId(i.id)}`} className="hover:underline">
                      {i.title}
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function cssId(id: string) {
  return `issue-${id.replace(/[^a-zA-Z0-9-]/g, "-")}`;
}

export function IssueList({ issues, onApply }: { issues: Issue[]; onApply?: (fix: Fix) => void }) {
  if (!issues.length) {
    return <p className="flex items-center gap-2 text-sm text-ink-600"><Icon name="check" className="h-4 w-4 text-signal-good" /> Nothing to flag on these assumptions.</p>;
  }
  return (
    <ul className="space-y-4">
      {issues.map((issue) => (
        <li key={issue.id} id={cssId(issue.id)} className="card scroll-mt-24 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityMark severity={issue.severity} />
            {issue.day ? <span className="text-[0.78rem] text-ink-500">Day {issue.day}</span> : null}
          </div>
          <p className="mt-2 font-medium text-ink-900">{issue.title}</p>
          <p className="mt-1 text-[0.9rem] text-ink-700">{issue.why}</p>
          {issue.needs_review ? (
            <p className="mt-2 flex gap-1.5 text-[0.85rem] text-signal-warning">
              <Icon name="search" className="mt-0.5 h-3.5 w-3.5" /> A reviewer has been asked to check this. Your saved trip updates when it is resolved.
            </p>
          ) : null}
          {issue.evidence.length ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-[0.82rem] text-accent-700">Evidence</summary>
              <ul className="mt-2 space-y-1.5">
                {issue.evidence.map((e, i) => (
                  <EvidenceLine key={i} evidence={e} />
                ))}
              </ul>
            </details>
          ) : null}
          {issue.fixes.length ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {issue.fixes.map((fix) => (
                <FixCard key={fix.id} fix={fix} onApply={onApply} />
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function FixCard({ fix, onApply }: { fix: Fix; onApply?: (fix: Fix) => void }) {
  return (
    <div className="rounded-md border border-ink-200 bg-ink-50/60 p-4">
      <p className="text-[0.9rem] font-medium text-ink-900">{fix.label}</p>
      <p className="mt-1 text-[0.78rem] text-ink-500">Afterwards: {fix.verdict_after_label}</p>
      <div className="mt-2 grid gap-2 text-[0.8rem] sm:grid-cols-2">
        <div>
          <p className="label text-signal-good">Gain</p>
          <ul className="mt-1 space-y-0.5 text-ink-700">
            {fix.diff.gained.length ? fix.diff.gained.map((g) => <li key={g}>+ {g}</li>) : <li>—</li>}
          </ul>
        </div>
        <div>
          <p className="label text-signal-critical">Lose</p>
          <ul className="mt-1 space-y-0.5 text-ink-700">
            {fix.diff.lost.length ? fix.diff.lost.map((l) => <li key={l}>− {l}</li>) : <li>Nothing</li>}
          </ul>
        </div>
      </div>
      {onApply ? (
        <button type="button" className="btn-secondary mt-3 px-3 py-1.5" onClick={() => onApply(fix)}>
          Apply this fix
        </button>
      ) : null}
    </div>
  );
}

export function BookingList({ items }: { items: BookingItem[] }) {
  if (!items.length) {
    return <p className="text-sm text-ink-600">Nothing on record that needs booking ahead.</p>;
  }
  return (
    <ul className="space-y-3">
      {items.map((b) => (
        <li key={b.text} className="card p-4">
          <p className="font-medium text-ink-900">{b.text}</p>
          <p className="mt-1 text-[0.82rem] text-ink-600">
            {b.lead_time_days ? `Book about ${b.lead_time_days} days ahead` : "Book ahead"}
            {b.book_by ? ` (by ${formatDate(b.book_by)})` : ""}
          </p>
          <ul className="mt-2">
            <EvidenceLine evidence={b.evidence} />
          </ul>
        </li>
      ))}
    </ul>
  );
}

export function AssumptionList({ check }: { check: CheckResult }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {check.assumptions.map((a) => (
        <li key={a.field} className="rounded-full border border-dashed border-accent-300 bg-accent-50 px-2.5 py-0.5 text-[0.75rem] text-accent-800">
          {a.label}
        </li>
      ))}
      {check.is_demo ? (
        <li>
          <DemoTag />
        </li>
      ) : null}
    </ul>
  );
}
