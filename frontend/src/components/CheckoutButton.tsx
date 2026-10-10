"use client";

import { useState } from "react";
import { ApiRequestError, api } from "@/lib/api";
import type { PaidPlanId } from "@/lib/types";

/**
 * Starts a checkout and hands the traveller to wherever the API says it
 * happens: Stripe's hosted page, or the demo checkout when Stripe is not
 * configured. Payment is only ever started by this button being pressed.
 */
export function CheckoutButton({
  planId,
  analysisId = null,
  tripId = null,
  children,
  className = "btn-primary",
}: {
  planId: PaidPlanId;
  analysisId?: string | null;
  tripId?: string | null;
  children: React.ReactNode;
  className?: string;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const checkout = await api.billing.checkout({
        plan_id: planId,
        analysis_id: analysisId,
        trip_id: tripId,
      });
      // A full navigation: the destination is either another origin (Stripe)
      // or an absolute URL built by the API. The button stays pending until
      // the browser leaves, so it cannot be pressed twice.
      window.location.assign(checkout.checkout_url);
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not reach the payment service. Nothing was charged — try again shortly.",
      );
      setPending(false);
    }
  }

  return (
    <div>
      <button type="button" className={className} onClick={start} disabled={pending} aria-busy={pending}>
        {pending ? "Starting checkout…" : children}
      </button>
      <p className="sr-only" role="status" aria-live="polite">
        {pending ? "Starting checkout…" : ""}
      </p>
      {error ? (
        <p
          className="mt-3 rounded-md border border-signal-critical/30 bg-signal-critical/[0.06] px-4 py-3 text-[0.88rem] text-signal-critical"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
