import type { Metadata } from "next";
import { CheckoutReturn } from "@/components/Checkout";

export const metadata: Metadata = { title: "Checkout" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value) ?? null;

export default async function CheckoutReturnPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const purchaseId = first(params.purchase);
  const cancelled = first(params.cancelled) === "1";

  return (
    <div className="shell max-w-3xl py-14">
      <p className="label mb-4">Checkout</p>
      <h1 className="text-headline font-serif text-ink-900">
        {cancelled ? "Checkout cancelled" : "Your payment"}
      </h1>
      <p className="prose-measure mt-3">
        {cancelled
          ? "You left the payment page before paying."
          : "Card details are handled on Stripe's page and never reach this site. The status below is read back from Stripe."}
      </p>
      <div className="mt-10">
        <CheckoutReturn purchaseId={purchaseId} cancelled={cancelled} />
      </div>
    </div>
  );
}
