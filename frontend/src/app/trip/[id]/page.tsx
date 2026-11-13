import type { Metadata } from "next";
import { TripWorkspace } from "@/components/v2/TripWorkspace";

export const metadata: Metadata = { title: "Your trip" };

export default async function TripPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="shell py-12 sm:py-14">
      <TripWorkspace id={id} />
    </div>
  );
}
