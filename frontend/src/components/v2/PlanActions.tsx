"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { PlanRequest, ReactionKind } from "@/lib/v2";
import { v2 } from "@/lib/v2";

/** Re-plans with one change and opens the new plan. */
export function useReplan(request: PlanRequest) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function replan(key: string, patch: Partial<PlanRequest>) {
    setBusy(key);
    setError(null);
    try {
      const res = await v2.createPlan({ ...request, ...patch, save: true });
      router.push(`/plan/${res.plan_id}`);
    } catch {
      setError("That did not work. Try again in a moment.");
      setBusy(null);
    }
  }
  return { busy, error, replan };
}

export function ReplanButton({
  request,
  patch,
  children,
  className = "btn-secondary",
}: {
  request: PlanRequest;
  patch: Partial<PlanRequest>;
  children: React.ReactNode;
  className?: string;
}) {
  const { busy, error, replan } = useReplan(request);
  return (
    <>
      <button type="button" className={className} disabled={busy !== null} onClick={() => replan("go", patch)}>
        {busy ? "Working…" : children}
      </button>
      {error ? <span role="alert" className="text-sm text-signal-critical">{error}</span> : null}
    </>
  );
}

const REACTIONS: [ReactionKind, string][] = [
  ["more_like_this", "More like this"],
  ["quieter", "Quieter"],
  ["more_unexpected", "More unexpected"],
  ["not_for_me", "Not for me"],
];

export function Reactions({ request, stops }: { request: PlanRequest; stops: string[] }) {
  const { busy, error, replan } = useReplan(request);
  return (
    <div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="React to this option">
        {REACTIONS.map(([kind, label]) => (
          <button
            key={kind}
            type="button"
            className="chip-off"
            disabled={busy !== null}
            onClick={() => replan(kind, { reactions: [...(request.reactions ?? []), { kind, stops }] })}
          >
            {busy === kind ? "Working…" : label}
          </button>
        ))}
      </div>
      {error ? <p role="alert" className="mt-2 text-sm text-signal-critical">{error}</p> : null}
    </div>
  );
}
