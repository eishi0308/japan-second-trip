import { Skeleton } from "@/components/primitives";

export default function Loading() {
  return (
    <div className="shell py-14" role="status" aria-label="Loading">
      <Skeleton className="h-4 w-28" />
      <Skeleton className="mt-5 h-10 w-2/3" />
      <Skeleton className="mt-3 h-4 w-1/2" />
      <div className="mt-10 space-y-4">
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
      <span className="sr-only">Loading</span>
    </div>
  );
}
