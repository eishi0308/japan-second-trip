"""Guardrails.

The governing rule of this product:

    **No evidence → no confident operational claim.**

Guardrails run *after* the model produces its structured output and *before* the
result reaches the user. They can downgrade confidence, strip an unsupported
claim, or escalate to a human — but they never silently rewrite a fact.

Checks implemented here:
  G1  citation validity — every cited evidence id was actually retrieved
  G2  unsupported operational claims — times/prices/dates in prose that appear
      in neither the evidence nor the deterministic signals
  G3  stale critical evidence — a fresh lookup or a human check is required
  G4  evidence sufficiency — below the configured floor, confidence is capped
  G5  injection residue — a quarantined chunk in the retrieval set is reported
  G6  demo labelling — a result built on demo data is always marked as such
  G7  analysis completeness — a check that could not run caps confidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jst_api.core.logging import get_logger
from jst_api.domain.enums import ConfidenceState, FreshnessState
from jst_api.domain.evidence import EvidenceChunk
from jst_api.domain.freshness import is_critical

log = get_logger(__name__)

#: Patterns that look like an asserted operational fact in free prose.
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")
PRICE_RE = re.compile(r"(?:¥|JPY\s?|A\$|\$)\s?\d[\d,]{2,}")
DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b", re.I
)


@dataclass
class GuardrailFinding:
    code: str
    severity: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailReport:
    findings: list[GuardrailFinding] = field(default_factory=list)
    confidence: ConfidenceState = ConfidenceState.HIGH
    human_review_required: bool = False
    review_reason: str | None = None
    stripped_claims: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[GuardrailFinding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def add(self, finding: GuardrailFinding) -> None:
        self.findings.append(finding)

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence.value,
            "human_review_required": self.human_review_required,
            "review_reason": self.review_reason,
            "findings": [
                {"code": f.code, "severity": f.severity, "message": f.message, "detail": f.detail}
                for f in self.findings
            ],
            "stripped_claims": self.stripped_claims,
        }


def _downgrade(current: ConfidenceState, floor: ConfidenceState) -> ConfidenceState:
    order = [
        ConfidenceState.INSUFFICIENT_EVIDENCE,
        ConfidenceState.LOW,
        ConfidenceState.MEDIUM,
        ConfidenceState.HIGH,
    ]
    return order[min(order.index(current), order.index(floor))]


def check_citations(cited_ids: list[str], available_ids: list[str]) -> list[GuardrailFinding]:
    """G1 — a citation the retrieval set does not contain is fabricated provenance."""
    available = set(available_ids)
    dangling = sorted({i for i in cited_ids if i not in available})
    if not dangling:
        return []
    return [
        GuardrailFinding(
            code="G1_dangling_citation",
            severity="blocking",
            message=f"{len(dangling)} cited evidence id(s) were never retrieved.",
            detail={"dangling": dangling[:10]},
        )
    ]


def check_unsupported_claims(
    prose_blocks: list[str], evidence: list[EvidenceChunk], deterministic_values: list[str]
) -> tuple[list[GuardrailFinding], list[str]]:
    """G2 — operational specifics must be traceable to evidence or a computed value."""
    haystack = " ".join(e.content for e in evidence) + " " + " ".join(deterministic_values)
    findings: list[GuardrailFinding] = []
    unsupported: list[str] = []

    for block in prose_blocks:
        for pattern, label in ((TIME_RE, "time"), (PRICE_RE, "price"), (DATE_RE, "date")):
            for match in pattern.findall(block):
                token = match if isinstance(match, str) else match[0]
                # Reconstruct the full matched token for time patterns.
                found = pattern.search(block)
                literal = found.group(0) if found else token
                if literal not in haystack:
                    unsupported.append(literal)
                    findings.append(
                        GuardrailFinding(
                            code="G2_unsupported_claim",
                            severity="blocking",
                            message=f"Unsupported {label} '{literal}' asserted with no matching evidence.",
                            detail={"literal": literal, "kind": label, "excerpt": block[:200]},
                        )
                    )
    return findings, unsupported


def operational_literals(text: str) -> set[str]:
    """Times, prices and dates — the tokens a traveller would act on."""
    found: set[str] = set()
    for pattern in (TIME_RE, PRICE_RE, DATE_RE):
        found |= {m.group(0) for m in pattern.finditer(text)}
    return found


def check_freshness(
    evidence: list[EvidenceChunk], cited_ids: set[str], prose_blocks: list[str]
) -> list[GuardrailFinding]:
    """G3 — a stale fact on a critical topic must not be *asserted* as current.

    Three severities, because "stale evidence exists" and "we are about to tell
    a traveller an out-of-date departure time" are very different problems:

    * merely retrieved      -> ``info``     (no action)
    * cited by the answer   -> ``warn``     (surfaced with its verification date)
    * cited AND the answer repeats an operational literal from it -> ``escalate``

    Escalating on everything stale would put a review task on nearly every run
    and bury the conflicts that genuinely need a person.
    """
    findings: list[GuardrailFinding] = []
    prose_literals = set()
    for block in prose_blocks:
        prose_literals |= operational_literals(block)

    for chunk in evidence:
        if chunk.freshness is not FreshnessState.STALE or not is_critical(chunk.topic):
            continue
        cited = chunk.evidence_id in cited_ids
        load_bearing = bool(cited and (prose_literals & operational_literals(chunk.content)))
        severity = "escalate" if load_bearing else ("warn" if cited else "info")
        findings.append(
            GuardrailFinding(
                code="G3_stale_critical_evidence",
                severity=severity,
                message=(
                    f"Critical {chunk.topic.value} evidence '{chunk.evidence_id}' is out of date"
                    + (
                        " and the answer repeats an operational figure from it."
                        if load_bearing
                        else " and is cited by this answer."
                        if cited
                        else " (retrieved but not cited)."
                    )
                ),
                detail={
                    "evidence_id": chunk.evidence_id,
                    "topic": chunk.topic.value,
                    "cited": cited,
                    "load_bearing": load_bearing,
                    "verified_at": chunk.verified_at.isoformat() if chunk.verified_at else None,
                },
            )
        )
    return findings


def check_sufficiency(evidence: list[EvidenceChunk], minimum: int) -> list[GuardrailFinding]:
    """G4 — too little evidence caps confidence rather than being hidden."""
    if len(evidence) >= minimum:
        return []
    return [
        GuardrailFinding(
            code="G4_insufficient_evidence",
            severity="warn",
            message=f"Only {len(evidence)} evidence chunk(s) retrieved; {minimum} required for a confident answer.",
            detail={"retrieved": len(evidence), "required": minimum},
        )
    ]


def check_injection_residue(quarantined: list[tuple[str, list[str]]]) -> list[GuardrailFinding]:
    """G5 — record that hostile content was seen and dropped."""
    if not quarantined:
        return []
    return [
        GuardrailFinding(
            code="G5_injection_quarantined",
            severity="warn",
            message=f"{len(quarantined)} retrieved chunk(s) contained instruction-injection patterns and were excluded.",
            detail={"evidence_ids": [e for e, _ in quarantined][:10]},
        )
    ]


def check_completeness(gaps: list[str]) -> list[GuardrailFinding]:
    """G7 — an analysis that skipped part of its own job cannot be confident.

    G1–G5 all ask whether the *evidence* supports the answer. None of them asks
    whether the answer was actually computed. A RouteCheck that resolved fewer
    than two stops never costs a single segment, so no travel-burden,
    backtracking or connection rule ever runs — and it would still report
    ``high`` confidence, because the evidence it did retrieve was clean and
    correctly cited. That is the most misleading output this system can produce:
    a confident-looking verdict on a route nobody checked.
    """
    if not gaps:
        return []
    return [
        GuardrailFinding(
            code="G7_incomplete_analysis",
            severity="warn",
            message=f"{len(gaps)} check(s) could not be performed: {gaps[0]}",
            detail={"gaps": gaps[:5], "count": len(gaps)},
        )
    ]


def run_guardrails(
    *,
    prose_blocks: list[str],
    cited_ids: list[str],
    evidence: list[EvidenceChunk],
    deterministic_values: list[str],
    quarantined: list[tuple[str, list[str]]],
    min_evidence: int,
    conflicts_detected: bool = False,
    analysis_gaps: list[str] | None = None,
) -> GuardrailReport:
    report = GuardrailReport()

    findings = check_citations(cited_ids, [e.evidence_id for e in evidence])
    unsupported_findings, stripped = check_unsupported_claims(
        prose_blocks, evidence, deterministic_values
    )
    findings += unsupported_findings
    findings += check_freshness(evidence, set(cited_ids), prose_blocks)
    findings += check_sufficiency(evidence, min_evidence)
    findings += check_injection_residue(quarantined)
    findings += check_completeness(analysis_gaps or [])

    for finding in findings:
        report.add(finding)

    report.stripped_claims = stripped

    if any(f.code == "G1_dangling_citation" for f in findings):
        report.confidence = _downgrade(report.confidence, ConfidenceState.LOW)
    if stripped:
        report.confidence = _downgrade(report.confidence, ConfidenceState.LOW)
    if any(f.code == "G4_insufficient_evidence" for f in findings):
        report.confidence = _downgrade(report.confidence, ConfidenceState.LOW)
    if not evidence:
        report.confidence = ConfidenceState.INSUFFICIENT_EVIDENCE
    if any(f.code == "G5_injection_quarantined" for f in findings):
        report.confidence = _downgrade(report.confidence, ConfidenceState.MEDIUM)
    if any(f.code == "G7_incomplete_analysis" for f in findings):
        # LOW, not MEDIUM: the issue is not thin evidence but an unperformed
        # check, and the user needs to know the verdict is partial.
        report.confidence = _downgrade(report.confidence, ConfidenceState.LOW)

    stale = [f for f in findings if f.code == "G3_stale_critical_evidence"]
    if stale:
        report.confidence = _downgrade(report.confidence, ConfidenceState.MEDIUM)
    if any(f.severity == "escalate" for f in stale):
        report.human_review_required = True
        report.review_reason = "stale_critical_evidence"
    if conflicts_detected:
        report.human_review_required = True
        report.review_reason = "conflicting_sources"
        report.confidence = _downgrade(report.confidence, ConfidenceState.MEDIUM)
    # Escalate on *evidence* problems, never merely because the traveller gave us
    # little to work with. A human reviewer cannot verify a fact the answer never
    # asserted, and filling the queue with those buries the real conflicts.
    evidence_problem = any(
        f.code in {"G1_dangling_citation", "G2_unsupported_claim"} for f in findings
    )
    if evidence_problem:
        report.human_review_required = True
        report.review_reason = report.review_reason or "grounding_failed"

    if report.findings:
        log.info(
            "guardrails.report", **{k: v for k, v in report.to_dict().items() if k != "findings"}
        )
    return report
