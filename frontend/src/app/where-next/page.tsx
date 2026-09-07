import type { Metadata } from "next";
import { WhereNextForm } from "@/components/WhereNextForm";

export const metadata: Metadata = {
  title: "Where should I go next?",
  description: "Tell us the trip. Every region is scored against your actual constraints.",
};

export default function WhereNextPage() {
  return (
    <div className="shell max-w-3xl py-14">
      <p className="label mb-4">Path A</p>
      <h1 className="text-headline font-serif text-ink-900">Where should I go next?</h1>
      <p className="prose-measure mt-3">
        Three short steps. Nothing is required — the more you give, the fewer assumptions the analysis
        has to make, and every assumption it does make is stated in the result.
      </p>
      <div className="mt-10">
        <WhereNextForm />
      </div>
    </div>
  );
}
