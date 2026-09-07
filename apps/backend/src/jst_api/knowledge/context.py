"""Context engineering: what actually reaches the model, and what does not.

Context is treated as a scarce, budgeted resource rather than "everything we
have". For each LLM call the assembler decides:

* which evidence is relevant (already filtered and reranked upstream);
* what to drop as near-duplicate (two sources saying the same thing waste budget
  and bias the model toward the repeated claim);
* how much trip memory to replay (structured summary, never a chat transcript);
* the hard token ceiling, enforced by truncating the *lowest-ranked* evidence
  first so the best material always survives;
* quarantining anything that scans as a prompt injection.

Every assembly returns an audit record — included ids, dropped ids and why —
which is written to the trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.documents import Document

from jst_api.core.logging import get_logger
from jst_api.domain.evidence import EvidenceChunk
from jst_api.knowledge.retrievers import document_to_domain
from jst_api.security.injection import fence, neutralise, scan_for_injection

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Jaccard similarity above which two chunks are treated as saying the same thing.
NEAR_DUPLICATE_THRESHOLD = 0.82


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _shingles(text: str, n: int = 5) -> set[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class ContextAudit:
    included_ids: list[str] = field(default_factory=list)
    dropped_duplicates: list[tuple[str, str]] = field(default_factory=list)
    dropped_over_budget: list[str] = field(default_factory=list)
    quarantined: list[tuple[str, list[str]]] = field(default_factory=list)
    token_estimate: int = 0
    budget: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "included_ids": self.included_ids,
            "dropped_duplicates": [{"dropped": d, "kept": k} for d, k in self.dropped_duplicates],
            "dropped_over_budget": self.dropped_over_budget,
            "quarantined": [{"evidence_id": e, "rules": r} for e, r in self.quarantined],
            "token_estimate": self.token_estimate,
            "budget": self.budget,
        }


@dataclass
class AssembledContext:
    evidence: list[EvidenceChunk]
    block: str
    audit: ContextAudit

    @property
    def evidence_ids(self) -> list[str]:
        return [e.evidence_id for e in self.evidence]


def deduplicate(documents: list[Document]) -> tuple[list[Document], list[tuple[str, str]]]:
    """Drop near-duplicate chunks, keeping the higher-ranked one."""
    kept: list[tuple[Document, set[str]]] = []
    dropped: list[tuple[str, str]] = []
    for doc in documents:
        shingle = _shingles(doc.page_content)
        duplicate_of: str | None = None
        for existing_doc, existing_shingle in kept:
            if jaccard(shingle, existing_shingle) >= NEAR_DUPLICATE_THRESHOLD:
                duplicate_of = existing_doc.metadata["evidence_id"]
                break
        if duplicate_of:
            dropped.append((doc.metadata["evidence_id"], duplicate_of))
        else:
            kept.append((doc, shingle))
    return [d for d, _ in kept], dropped


def assemble_evidence_context(
    documents: list[Document],
    *,
    token_budget: int,
    max_chars_per_chunk: int = 700,
    header: str = "EVIDENCE",
) -> AssembledContext:
    audit = ContextAudit(budget=token_budget)

    # 1. quarantine hostile content before anything else touches it
    safe: list[Document] = []
    for doc in documents:
        scan = scan_for_injection(doc.page_content)
        if scan.quarantine:
            audit.quarantined.append((doc.metadata["evidence_id"], scan.matched_rules))
            log.warning(
                "context.quarantined_evidence",
                evidence_id=doc.metadata["evidence_id"],
                rules=scan.matched_rules,
            )
            continue
        if scan.suspicious:
            doc = Document(
                id=doc.id,
                page_content=neutralise(doc.page_content),
                metadata={**doc.metadata, "injection_flags": scan.matched_rules},
            )
        safe.append(doc)

    # 2. drop near-duplicates
    deduped, dropped = deduplicate(safe)
    audit.dropped_duplicates = dropped

    # 3. fill to budget, best-ranked first
    lines: list[str] = []
    evidence: list[EvidenceChunk] = []
    used = 0
    for index, doc in enumerate(deduped, start=1):
        domain_chunk = document_to_domain(doc)
        block = domain_chunk.to_context_block(index, max_chars=max_chars_per_chunk)
        cost = approx_tokens(block)
        if used + cost > token_budget and evidence:
            audit.dropped_over_budget.extend(
                d.metadata["evidence_id"] for d in deduped[index - 1 :]
            )
            break
        lines.append(block)
        evidence.append(domain_chunk)
        audit.included_ids.append(domain_chunk.evidence_id)
        used += cost

    audit.token_estimate = used
    body = "\n\n".join(lines) if lines else "(no evidence retrieved for this query)"
    return AssembledContext(evidence=evidence, block=fence(header, body), audit=audit)


def compact_memory(memory_block: str, *, max_tokens: int = 300) -> str:
    """Trip memory is already structured; this only guards the ceiling."""
    if approx_tokens(memory_block) <= max_tokens:
        return memory_block
    budget_chars = max_tokens * 4
    return memory_block[:budget_chars].rsplit("\n", 1)[0] + "\n… (memory truncated)"
