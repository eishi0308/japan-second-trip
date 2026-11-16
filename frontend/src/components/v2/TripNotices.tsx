"use client";

import { useState } from "react";
import type { TripNotice } from "@/lib/v2";
import { formatDate, v2 } from "@/lib/v2";
import { Icon } from "./ui";

/** "We re-checked your trip" updates after a reviewer resolves a fact it depends on. */
export function TripNotices({
  notices,
  trip,
  onSeen,
}: {
  notices: TripNotice[];
  trip?: { id: string; token: string };
  onSeen?: () => void;
}) {
  const [items, setItems] = useState(notices);
  if (!items.length) return null;
  const unseen = items.filter((n) => !n.seen).length;
  return (
    <section aria-labelledby="updates" className={`card mb-8 p-5 ${unseen ? "border-accent-300 bg-accent-50/60" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="updates" className="font-serif text-lg text-ink-900">
          Updates to your trip{unseen ? ` (${unseen} new)` : ""}
        </h2>
        {trip && unseen ? (
          <button
            type="button"
            className="btn-ghost px-3 py-1.5"
            onClick={async () => {
              try {
                const t = await v2.markNoticesSeen(trip.id, trip.token);
                setItems(t.notices);
                onSeen?.();
              } catch {
                /* leave them unread */
              }
            }}
          >
            Mark as read
          </button>
        ) : null}
      </div>
      <ul className="mt-3 space-y-2">
        {[...items].reverse().map((n) => (
          <li key={`${n.at}-${n.fact_id}`} className="flex gap-2 text-[0.9rem] text-ink-800">
            <Icon name={n.seen ? "check" : "info"} className={`mt-1 h-3.5 w-3.5 shrink-0 ${n.seen ? "text-ink-400" : "text-accent-700"}`} />
            <span>
              {n.text} <span className="text-[0.78rem] text-ink-500">{formatDate(n.at)}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
