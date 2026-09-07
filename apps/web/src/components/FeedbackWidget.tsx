"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/**
 * Feedback feeds the eval backlog, not a model. A reported inaccuracy is a
 * candidate golden case; nothing here is used to fine-tune anything.
 */
export function FeedbackWidget({ analysisId, tripId }: { analysisId: string; tripId: string | null }) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const [helpful, setHelpful] = useState<boolean | null>(null);
  const [comment, setComment] = useState("");
  const [inaccurate, setInaccurate] = useState(false);

  async function send(value: boolean) {
    setHelpful(value);
    setState("sending");
    try {
      await api.feedback({
        analysis_id: analysisId,
        trip_id: tripId,
        helpful: value,
        comment: comment || null,
        reported_inaccuracy: inaccurate,
      });
      setState("sent");
    } catch {
      setState("failed");
    }
  }

  if (state === "sent") {
    return (
      <div className="card px-5 py-4 text-[0.88rem] text-ink-600" role="status">
        Thank you — recorded. Reported inaccuracies become candidate cases in the eval set.
      </div>
    );
  }

  return (
    <div className="card px-5 py-4">
      <p className="label mb-2.5">Was this useful?</p>
      <div className="flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          className={helpful === true ? "chip-on" : "chip-off"}
          onClick={() => send(true)}
          disabled={state === "sending"}
        >
          Yes
        </button>
        <button
          type="button"
          className={helpful === false ? "chip-on" : "chip-off"}
          onClick={() => send(false)}
          disabled={state === "sending"}
        >
          Not really
        </button>
        <label className="ml-2 flex items-center gap-2 text-[0.82rem] text-ink-600">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            checked={inaccurate}
            onChange={(e) => setInaccurate(e.target.checked)}
          />
          Something here is factually wrong
        </label>
      </div>
      <textarea
        rows={2}
        className="field mt-3 resize-y text-[0.88rem]"
        placeholder="Optional: what was wrong, or what you needed instead."
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {state === "failed" ? (
        <p className="mt-2 text-[0.82rem] text-signal-critical">Could not send that. Try again shortly.</p>
      ) : null}
    </div>
  );
}
