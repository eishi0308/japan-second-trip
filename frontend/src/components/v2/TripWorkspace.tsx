"use client";

import { useEffect, useState } from "react";
import type { SavedTrip } from "@/lib/v2";
import { v2 } from "@/lib/v2";
import { CheckWorkspace, tokenKey } from "./CheckWorkspace";
import { PageHeading } from "./ui";

/** /trip/[id]: the owner's workspace. The owner token lives in this browser only. */
export function TripWorkspace({ id }: { id: string }) {
  const [token, setToken] = useState<string | null>(null);
  const [trip, setTrip] = useState<SavedTrip | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let t: string | null = null;
    const hash = window.location.hash.slice(1);
    try {
      if (hash) window.localStorage.setItem(tokenKey(id), hash);
      t = window.localStorage.getItem(tokenKey(id));
    } catch {
      t = hash || null;
    }
    if (hash) window.history.replaceState(null, "", window.location.pathname);
    if (!t) {
      setError("This browser does not hold the key to edit this trip. Ask the owner for the share link to view it.");
      return;
    }
    setToken(t);
    v2.getTrip(id, t)
      .then(setTrip)
      .catch(() => setError("We could not open this trip. It may have been saved in another browser."));
  }, [id]);

  if (error) return <p role="alert" className="card p-6 text-ink-700">{error}</p>;
  if (!trip || !token) return <p className="text-ink-500">Opening your trip…</p>;

  const shareUrl = `${window.location.origin}/share/${trip.share_id}`;
  return (
    <div>
      <PageHeading eyebrow="Saved trip" title={trip.title}>
        Every change re-checks the trip and saves it. Facts we are still checking update here once they are resolved.
      </PageHeading>
      <div className="-mt-3 mb-8 flex flex-wrap items-center gap-3">
        <input className="field max-w-md py-2 text-[0.85rem]" readOnly value={shareUrl} aria-label="Read-only share link" />
        <button
          type="button"
          className="btn-secondary px-4 py-2"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(shareUrl);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "Copied" : "Copy share link"}
        </button>
        <span className="text-[0.8rem] text-ink-500">Anyone with the link can view, not edit.</span>
      </div>
      <CheckWorkspace initialRequest={trip.check_request} initialResponse={trip.result} planId={trip.plan_id} trip={{ id, token }} />
    </div>
  );
}
