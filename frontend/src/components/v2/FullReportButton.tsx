"use client";

import { useState } from "react";
import { v2 } from "@/lib/v2";

/** Demand test (PRODUCT_AMENDMENTS.md §3): records the click, sells nothing. */
export function FullReportButton({
  planId,
  tripId,
  option,
}: {
  planId?: string | null;
  tripId?: string | null;
  option?: number | null;
}) {
  const [message, setMessage] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-col">
      <button
        type="button"
        className="btn-ghost border border-ink-200"
        disabled={message !== null}
        onClick={async () => {
          try {
            const res = await v2.fullReport({ plan_id: planId, trip_id: tripId, option });
            setMessage(res.message);
          } catch {
            setMessage("Thanks. The full report is not available yet.");
          }
        }}
      >
        See full report
      </button>
      {message ? (
        <span role="status" className="mt-1 text-[0.78rem] text-ink-500">
          {message}
        </span>
      ) : null}
    </span>
  );
}
