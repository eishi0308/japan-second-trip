import type { Metadata } from "next";
import { DemoCheckout } from "@/components/Checkout";
import { Badge } from "@/components/primitives";

export const metadata: Metadata = { title: "Demo checkout" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value) ?? null;

export default async function DemoCheckoutPage({ searchParams }: { searchParams: SearchParams }) {
  const purchaseId = first((await searchParams).purchase);

  return (
    <div className="shell max-w-3xl py-14">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="label">Checkout</p>
        <Badge tone="info">Demo · no card, no charge</Badge>
      </div>
      <h1 className="text-headline font-serif text-ink-900">Demo checkout</h1>
      <p className="prose-measure mt-3">
        This is not a real payment page. It exists so the purchase flow can be followed end to end on a
        system with no payment provider attached.
      </p>
      <div className="mt-10">
        <DemoCheckout purchaseId={purchaseId} />
      </div>
    </div>
  );
}
