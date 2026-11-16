import type { Metadata } from "next";
import { VerificationQueue } from "@/components/v2/VerificationQueue";

export const metadata: Metadata = { title: "Verification queue" };

export default function AdminPage() {
  return (
    <div className="shell py-12">
      <p className="label mb-3">Internal</p>
      <h1 className="text-headline font-serif text-ink-900">Verification queue</h1>
      <p className="prose-measure mt-3">
        Facts travellers see as &ldquo;Being checked&rdquo;, out of date, or not yet verified. Confirm one and every saved
        trip that depends on it is re-checked and told what changed. Needs an admin token.
      </p>
      <div className="mt-10">
        <VerificationQueue />
      </div>
    </div>
  );
}
