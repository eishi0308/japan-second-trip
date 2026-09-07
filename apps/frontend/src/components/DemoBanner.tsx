import { api } from "@/lib/api";

/**
 * Honest disclosure of what is live and what is seeded.
 *
 * A product whose entire claim is verification cannot be coy about the
 * provenance of its own answers. This renders whenever any capability is
 * running on a demo adapter.
 */
export async function DemoBanner() {
  let demo = true;
  let providers: Record<string, { provider: string; demo: boolean }> = {};
  try {
    const info = await api.providers();
    demo = info.demo_mode;
    providers = info.providers;
  } catch {
    return null; // the API being down is the page's problem, not the banner's
  }
  if (!demo) return null;

  const demoNames = Object.entries(providers)
    .filter(([, v]) => v.demo)
    .map(([k]) => k);

  return (
    <div className="border-b border-signal-warning/25 bg-[#fdf8ef]" role="status" aria-label="Demo mode notice">
      <div className="shell flex flex-wrap items-center gap-x-2 gap-y-1 py-2 text-[0.78rem] text-ink-700">
        <span className="rounded bg-signal-warning/15 px-1.5 py-0.5 font-medium text-signal-warning">
          Demo data
        </span>
        <span>
          Running without live credentials. Travel times, booking rules and evidence are seeded
          approximations, labelled as such throughout — not verified live data.
        </span>
        <span className="text-ink-400">Demo adapters: {demoNames.join(", ")}</span>
      </div>
    </div>
  );
}
