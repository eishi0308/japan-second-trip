import { CheckoutButton } from "@/components/CheckoutButton";
import { Badge } from "@/components/primitives";
import { api } from "@/lib/api";
import { PLAN_NAMES, formatAud } from "@/lib/billing";
import type { BillingMode, PaidPlanId, Purchase } from "@/lib/types";

/**
 * The purchase call-to-action on a result page. It sits beside the result and
 * gates nothing: everything the analysis found is already on the page.
 *
 * If billing cannot be read the offer is simply absent — a result page must
 * never fail because the payment side is down.
 */
export async function PurchaseOffer({
  planId,
  analysisId,
  tripId,
}: {
  planId: PaidPlanId;
  analysisId: string;
  tripId: string | null;
}) {
  let config;
  try {
    config = await api.billing.config();
  } catch {
    return null;
  }
  const price = config.prices_aud[planId];
  if (typeof price !== "number" || price <= 0) return null;

  let paid: Purchase | null = null;
  try {
    const purchases = await api.billing.purchases(analysisId);
    paid = purchases.find((p) => p.plan_id === planId && p.status === "paid") ?? null;
  } catch {
    paid = null;
  }

  return (
    <PurchaseOfferView
      planId={planId}
      analysisId={analysisId}
      tripId={tripId}
      priceAud={price}
      mode={config.mode}
      paid={paid}
    />
  );
}

export function PurchaseOfferView({
  planId,
  analysisId,
  tripId,
  priceAud,
  mode,
  paid,
}: {
  planId: PaidPlanId;
  analysisId: string;
  tripId: string | null;
  priceAud: number;
  mode: BillingMode;
  paid: Purchase | null;
}) {
  const name = PLAN_NAMES[planId];
  const headingId = `purchase-offer-${planId}`;

  if (paid) {
    return (
      <section className="card px-5 py-4" aria-labelledby={headingId}>
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 id={headingId} className="font-serif text-[1.02rem] text-ink-900">
            {paid.plan_name}
          </h2>
          <Badge tone="good">Purchased</Badge>
          {paid.is_demo ? <Badge tone="info">Demo purchase · no charge</Badge> : null}
        </div>
        <p className="mt-1.5 text-[0.85rem] text-ink-600">
          {formatAud(paid.amount_aud)} recorded against this analysis
          {paid.paid_at ? ` on ${new Date(paid.paid_at).toISOString().slice(0, 10)}` : ""}.
        </p>
      </section>
    );
  }

  return (
    <section className="card px-5 py-5" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        <div className="min-w-0">
          <p className="label mb-1.5">Buy this analysis</p>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 id={headingId} className="font-serif text-[1.05rem] text-ink-900">
              {name}
            </h2>
            <p className="font-serif text-[1.05rem] tabular-nums text-ink-900">{formatAud(priceAud)}</p>
            {mode === "demo" ? <Badge tone="info">Demo checkout · no charge</Badge> : null}
            {mode === "stripe_test" ? <Badge tone="warning">Stripe test mode</Badge> : null}
          </div>
          <p className="mt-2 max-w-measure text-[0.85rem] leading-relaxed text-ink-600">
            Nothing on this page is locked — the full result stays readable either way.{" "}
            {mode === "demo"
              ? "This is a demo checkout: no card is asked for and no money moves."
              : "Card details are entered on Stripe's page and never reach this site."}
          </p>
        </div>
        <CheckoutButton planId={planId} analysisId={analysisId} tripId={tripId} className="btn-secondary">
          Buy {name}
        </CheckoutButton>
      </div>
    </section>
  );
}
