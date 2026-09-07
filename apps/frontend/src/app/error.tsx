"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="shell max-w-measure py-24">
      <p className="label mb-3 text-signal-critical">Something went wrong</p>
      <h1 className="text-headline font-serif text-ink-900">This page couldn&rsquo;t load</h1>
      <p className="prose-measure mt-3">
        Most often this means the API is not reachable. Check that it is running on the configured base
        URL, then try again.
      </p>
      {error.digest ? <p className="mt-3 font-mono text-[0.78rem] text-ink-400">digest {error.digest}</p> : null}
      <div className="mt-8 flex gap-3">
        <button type="button" onClick={reset} className="btn-primary">
          Try again
        </button>
        <Link href="/" className="btn-secondary">
          Back to the start
        </Link>
      </div>
    </div>
  );
}
