import type { Metadata } from "next";
import { AdminConsole } from "@/components/admin/AdminConsole";

export const metadata: Metadata = { title: "Admin" };

export default function AdminPage() {
  return (
    <div className="shell py-12">
      <p className="label mb-3">Internal</p>
      <h1 className="text-headline font-serif text-ink-900">Verification &amp; operations</h1>
      <p className="prose-measure mt-3">
        Source management, the human review queue, agent-run inspection and eval history. Everything
        here needs an admin token; nothing here is reachable by a traveller.
      </p>
      <div className="mt-10">
        <AdminConsole />
      </div>
    </div>
  );
}
