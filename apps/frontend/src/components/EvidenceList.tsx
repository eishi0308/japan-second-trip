"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Citation, EvidenceDetail } from "@/lib/types";
import { Badge, FreshnessBadge } from "./primitives";

/**
 * Citations are expandable in place. A verification claim the reader cannot
 * check is just a claim, so the full passage, its source type and its
 * last-verified date are one click away — never a dead footnote.
 */
export function EvidenceList({ citations, title = "Evidence" }: { citations: Citation[]; title?: string }) {
  // One source can contribute several chunks. Listing the same title four times
  // makes the evidence look padded; group by source and say how many passages
  // came from it.
  const grouped = citations.reduce<{ citation: Citation; ids: string[] }[]>((acc, citation) => {
    const existing = acc.find((entry) => entry.citation.source_id === citation.source_id);
    if (existing) {
      existing.ids.push(citation.evidence_id);
      return acc;
    }
    acc.push({ citation, ids: [citation.evidence_id] });
    return acc;
  }, []);

  if (citations.length === 0) {
    return (
      <div className="card p-5">
        <p className="label mb-2">{title}</p>
        <p className="text-[0.88rem] text-ink-600">
          No supporting evidence was retrieved for this section. Nothing above should be treated as
          verified.
        </p>
      </div>
    );
  }

  return (
    <div className="card divide-y divide-ink-200">
      <div className="flex items-center justify-between px-5 py-3">
        <p className="label">{title}</p>
        <p className="text-[0.75rem] text-ink-500">
          {grouped.length} source{grouped.length === 1 ? "" : "s"}
          {citations.length !== grouped.length ? ` · ${citations.length} passages` : ""}
        </p>
      </div>
      {grouped.map((entry) => (
        <EvidenceRow key={entry.citation.source_id} citation={entry.citation} passages={entry.ids} />
      ))}
    </div>
  );
}

function EvidenceRow({ citation, passages }: { citation: Citation; passages: string[] }) {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState<EvidenceDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && details.length === 0 && !loading) {
      setLoading(true);
      try {
        const loaded = await Promise.all(passages.map((id) => api.getEvidence(id)));
        setDetails(loaded);
      } catch {
        setFailed(true);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className="px-5 py-3.5">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-4 text-left"
      >
        <span className="min-w-0">
          <span className="block truncate text-[0.9rem] font-medium text-ink-900">{citation.title}</span>
          <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={citation.official_source ? "info" : "neutral"}>
              {citation.source_type.replace(/_/g, " ")}
            </Badge>
            <FreshnessBadge freshness={citation.freshness} verifiedAt={citation.verified_at} />
            {citation.is_demo ? <Badge tone="warning">demo data</Badge> : null}
          </span>
        </span>
        <span aria-hidden="true" className="mt-1 shrink-0 text-ink-400">
          {open ? "−" : "+"}
        </span>
      </button>

      {open ? (
        <div className="mt-3 border-l-2 border-ink-200 pl-4">
          {loading ? <p className="text-[0.85rem] text-ink-500">Loading the passage…</p> : null}
          {failed ? (
            <p className="text-[0.85rem] text-signal-critical">
              Could not load this evidence. Passage ids: {passages.join(", ")}.
            </p>
          ) : null}
          {details.map((detail, index) => (
            <div key={detail.evidence_id} className={index > 0 ? "mt-4 border-t border-ink-100 pt-4" : ""}>
              <p className="whitespace-pre-line text-[0.86rem] leading-relaxed text-ink-700">
                {detail.content}
              </p>
              <p className="mt-3 text-[0.76rem] text-ink-500">
                {detail.freshness_label} · topic {detail.topic.replace(/_/g, " ")} · trust {detail.trust_level}
                {detail.source_url ? (
                  <>
                    {" · "}
                    <a
                      href={detail.source_url}
                      target="_blank"
                      rel="noreferrer noopener nofollow"
                      className="underline underline-offset-2 hover:text-ink-800"
                    >
                      source
                    </a>
                  </>
                ) : null}
              </p>
              <p className="mt-1 font-mono text-[0.7rem] text-ink-400">{detail.evidence_id}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
