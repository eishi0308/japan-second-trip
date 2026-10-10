"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge, ErrorState, Skeleton } from "@/components/primitives";
import { ApiRequestError, api } from "@/lib/api";
import { analysisHref, formatAud, tripHref } from "@/lib/billing";
import type { Purchase } from "@/lib/types";

type Failure = { kind: "missing" | "not_found" | "unavailable"; message: string };

type Loaded =
  | { state: "loading" }
  | { state: "failed"; failure: Failure }
  | { state: "ready"; purchase: Purchase };

function toFailure(err: unknown): Failure {
  if (err instanceof ApiRequestError && err.status === 404) {
    return {
      kind: "not_found",
      message:
        "No purchase has this id. The link may be mistyped, or from a database that has since been reset. Nothing was charged.",
    };
  }
  if (err instanceof ApiRequestError) return { kind: "unavailable", message: err.message };
  return {
    kind: "unavailable",
    message: "Could not reach the payment service. Check the API is running and try again.",
  };
}

const NO_ID: Failure = {
  kind: "missing",
  message: "This page needs a purchase id in its address. Start a checkout from a result page instead.",
};

/**
 * Runs `request` for the purchase on mount and whenever `retry` is called.
 * The requests behind this are idempotent on the server, so a repeat (React
 * strict mode, a reload, the back button) cannot change the outcome.
 */
function usePurchase(purchaseId: string | null, request: (id: string) => Promise<Purchase>) {
  const [loaded, setLoaded] = useState<Loaded>(
    purchaseId ? { state: "loading" } : { state: "failed", failure: NO_ID },
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!purchaseId) return;
    let stale = false;
    request(purchaseId).then(
      (purchase) => {
        if (!stale) setLoaded({ state: "ready", purchase });
      },
      (err: unknown) => {
        if (!stale) setLoaded({ state: "failed", failure: toFailure(err) });
      },
    );
    return () => {
      stale = true;
    };
  }, [purchaseId, request, attempt]);

  const retry = useCallback(() => {
    setLoaded({ state: "loading" });
    setAttempt((n) => n + 1);
  }, []);
  const setPurchase = useCallback((purchase: Purchase) => setLoaded({ state: "ready", purchase }), []);

  return { loaded, retry, setPurchase };
}

/** `/checkout/demo` — the stand-in for a card form when Stripe is not configured. */
export function DemoCheckout({ purchaseId }: { purchaseId: string | null }) {
  const { loaded, retry, setPurchase } = usePurchase(purchaseId, api.billing.purchase);
  const [acting, setActing] = useState<"confirm" | "cancel" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function act(kind: "confirm" | "cancel", id: string) {
    setActing(kind);
    setActionError(null);
    try {
      setPurchase(await (kind === "confirm" ? api.billing.demoConfirm(id) : api.billing.cancel(id)));
    } catch (err) {
      setActionError(toFailure(err).message);
    } finally {
      setActing(null);
    }
  }

  if (loaded.state === "loading") return <CheckoutLoading label="Loading the purchase…" />;
  if (loaded.state === "failed") return <CheckoutFailure failure={loaded.failure} onRetry={retry} />;

  const purchase = loaded.purchase;
  if (purchase.status !== "pending") return <Outcome purchase={purchase} />;

  if (!purchase.is_demo) {
    return (
      <div className="space-y-5">
        <PurchaseSummary purchase={purchase} />
        <div className="card px-6 py-6" role="status" aria-live="polite">
          <p className="font-serif text-lg text-ink-900">This is a card payment, not a demo purchase</p>
          <p className="prose-measure mt-2">
            It can only be completed on Stripe&rsquo;s page, so it cannot be confirmed here.
          </p>
          <Link href={`/checkout/return?purchase=${encodeURIComponent(purchase.id)}`} className="btn-secondary mt-5">
            Check the payment status
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PurchaseSummary purchase={purchase} />
      <div className="card px-6 py-6">
        <p className="prose-measure">
          Stripe is not configured on this system, so this page stands in for the card form. Confirming
          marks the purchase as paid without asking for a card. <strong>No money moves.</strong>
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn-primary"
            onClick={() => act("confirm", purchase.id)}
            disabled={acting !== null}
          >
            {acting === "confirm" ? "Confirming…" : "Confirm demo purchase"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => act("cancel", purchase.id)}
            disabled={acting !== null}
          >
            {acting === "cancel" ? "Cancelling…" : "Cancel"}
          </button>
        </div>
        <p className="sr-only" role="status" aria-live="polite">
          {acting === "confirm" ? "Confirming the demo purchase…" : acting === "cancel" ? "Cancelling…" : ""}
        </p>
        {actionError ? (
          <p
            className="mt-4 rounded-md border border-signal-critical/30 bg-signal-critical/[0.06] px-4 py-3 text-[0.88rem] text-signal-critical"
            role="alert"
          >
            {actionError}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/** `/checkout/return` — where Stripe sends the traveller back, paid or not. */
export function CheckoutReturn({ purchaseId, cancelled }: { purchaseId: string | null; cancelled: boolean }) {
  const { loaded, retry } = usePurchase(purchaseId, cancelled ? api.billing.cancel : api.billing.sync);

  if (loaded.state === "loading") {
    return <CheckoutLoading label={cancelled ? "Cancelling the checkout…" : "Confirming your payment…"} />;
  }
  if (loaded.state === "failed") return <CheckoutFailure failure={loaded.failure} onRetry={retry} />;
  return <Outcome purchase={loaded.purchase} onRecheck={retry} />;
}

function CheckoutLoading({ label }: { label: string }) {
  return (
    <div className="card px-6 py-6" role="status" aria-live="polite">
      <p className="text-[0.88rem] text-ink-600">{label}</p>
      <Skeleton className="mt-4 h-5 w-2/3" />
      <Skeleton className="mt-3 h-4 w-1/3" />
    </div>
  );
}

function CheckoutFailure({ failure, onRetry }: { failure: Failure; onRetry: () => void }) {
  const title =
    failure.kind === "not_found"
      ? "That purchase doesn't exist"
      : failure.kind === "missing"
        ? "No purchase to show"
        : "The purchase could not be loaded";
  return (
    <ErrorState
      title={title}
      message={failure.message}
      retry={
        <div className="flex flex-wrap gap-3">
          {failure.kind === "unavailable" ? (
            <button type="button" className="btn-primary" onClick={onRetry}>
              Try again
            </button>
          ) : null}
          <Link href="/" className="btn-secondary">
            Back to the start
          </Link>
        </div>
      }
    />
  );
}

function PurchaseSummary({ purchase }: { purchase: Purchase }) {
  return (
    <dl className="card grid grid-cols-2 gap-x-8 gap-y-4 px-6 py-5 sm:grid-cols-3">
      <div className="col-span-2 sm:col-span-1">
        <dt className="label">Plan</dt>
        <dd className="mt-1 font-serif text-[1.1rem] text-ink-900">{purchase.plan_name}</dd>
      </div>
      <div>
        <dt className="label">Amount</dt>
        <dd className="mt-1 font-serif text-[1.1rem] tabular-nums text-ink-900">{formatAud(purchase.amount_aud)}</dd>
      </div>
      <div>
        <dt className="label">Reference</dt>
        <dd className="mt-1 break-all text-[0.85rem] text-ink-700">{purchase.id}</dd>
      </div>
    </dl>
  );
}

/** A purchase that is no longer waiting on the traveller: paid, cancelled, or still unconfirmed by Stripe. */
function Outcome({ purchase, onRecheck }: { purchase: Purchase; onRecheck?: () => void }) {
  const analysis = analysisHref(purchase);
  const trip = tripHref(purchase);
  const paid = purchase.status === "paid";
  const cancelled = purchase.status === "cancelled";

  return (
    <div className="space-y-5">
      <PurchaseSummary purchase={purchase} />
      <div
        className={`card px-6 py-6 ${paid ? "border-signal-good/30 bg-signal-good/[0.04]" : ""}`}
        role="status"
        aria-live="polite"
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <p className="font-serif text-lg text-ink-900">
            {paid ? "Payment confirmed" : cancelled ? "Checkout cancelled" : "Payment not confirmed yet"}
          </p>
          <Badge tone={paid ? "good" : cancelled ? "neutral" : "warning"}>
            {paid ? "Paid" : cancelled ? "Cancelled" : "Pending"}
          </Badge>
          {purchase.is_demo ? <Badge tone="info">Demo · no charge</Badge> : null}
        </div>
        <p className="prose-measure mt-2">
          {paid
            ? purchase.is_demo
              ? `${purchase.plan_name} is marked as paid. This was a demo purchase — no card was taken and nothing was charged.`
              : `${formatAud(purchase.amount_aud)} was paid for ${purchase.plan_name}.`
            : cancelled
              ? "Nothing was charged. Your analysis is unchanged, and you can start a new checkout from it at any time."
              : "Stripe has not reported this payment as complete. If you have just paid, it can take a moment to arrive."}
          {paid && purchase.paid_at ? ` Recorded ${new Date(purchase.paid_at).toISOString().slice(0, 10)}.` : ""}
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          {!paid && !cancelled && onRecheck ? (
            <button type="button" className="btn-primary" onClick={onRecheck}>
              Check again
            </button>
          ) : null}
          {analysis ? (
            <Link href={analysis} className={paid || cancelled ? "btn-primary" : "btn-secondary"}>
              Back to your analysis
            </Link>
          ) : null}
          {trip ? (
            <Link href={trip} className={analysis ? "btn-secondary" : "btn-primary"}>
              Open the trip workspace
            </Link>
          ) : null}
          {!analysis && !trip ? (
            <Link href="/" className="btn-primary">
              Back to the start
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
