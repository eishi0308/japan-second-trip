"""G7 — an analysis that skipped part of its own job cannot report confidence.

G1–G5 all ask whether the evidence supports the answer. None of them asked
whether the answer was ever computed, and that gap produced the single most
misleading output this system can emit: a RouteCheck that resolved fewer than two
stops costs no segment and runs no transport rule, yet returned **high**
confidence, because the evidence it happened to retrieve was clean and correctly
cited.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jst_api.agents.common.guardrails import check_completeness, run_guardrails
from jst_api.domain.enums import ConfidenceState, EvidenceTopic, FreshnessState, TrustLevel
from jst_api.domain.evidence import EvidenceChunk, SourceRef


def chunk(
    evidence_id: str = "ev_1", content: str = "Buses run hourly from the station."
) -> EvidenceChunk:
    """A clean, fresh, well-cited chunk — so only the gap can move confidence."""
    return EvidenceChunk(
        evidence_id=evidence_id,
        source=SourceRef(
            source_id="src_1",
            title="Official transport page",
            url="https://example.jp/access",
            source_type="official_tourism",
            official_source=True,
            trust_level=TrustLevel.PRIMARY,
            verified_at=datetime.now(UTC),
            is_demo=True,
        ),
        topic=EvidenceTopic.TRANSPORT_ACCESS,
        content=content,
        freshness=FreshnessState.FRESH,
        verified_at=datetime.now(UTC),
    )


def report(*, gaps: list[str] | None = None, evidence: list[EvidenceChunk] | None = None):
    return run_guardrails(
        prose_blocks=["This itinerary holds up."],
        cited_ids=["ev_1"],
        evidence=evidence if evidence is not None else [chunk()],
        deterministic_values=[],
        quarantined=[],
        min_evidence=1,
        analysis_gaps=gaps,
    )


class TestTheCheck:
    def test_no_gaps_is_no_finding(self):
        assert check_completeness([]) == []

    def test_a_gap_produces_one_finding_naming_it(self):
        findings = check_completeness(["Only 1 stop(s) resolved, so no segment was costed."])
        assert len(findings) == 1
        assert findings[0].code == "G7_incomplete_analysis"
        assert "no segment was costed" in findings[0].message

    def test_several_gaps_are_reported_together_with_a_count(self):
        findings = check_completeness(["first gap", "second gap", "third gap"])
        assert len(findings) == 1
        assert findings[0].detail["count"] == 3
        assert findings[0].detail["gaps"] == ["first gap", "second gap", "third gap"]


class TestConfidence:
    def test_clean_evidence_and_no_gaps_stays_high(self):
        """The control case — otherwise the test below proves nothing."""
        assert report().confidence is ConfidenceState.HIGH

    def test_a_gap_caps_confidence_at_low(self):
        """The exact defect: clean evidence, but nothing was actually checked."""
        assert report(gaps=["no segment was costed"]).confidence is ConfidenceState.LOW

    def test_a_gap_does_not_raise_an_already_lower_confidence(self):
        """No evidence at all is worse than an incomplete analysis."""
        assert (
            report(gaps=["no segment was costed"], evidence=[]).confidence
            is ConfidenceState.INSUFFICIENT_EVIDENCE
        )

    def test_a_gap_is_not_blocking(self):
        """A partial answer is still worth showing — clearly labelled, not withheld."""
        result = report(gaps=["no segment was costed"])
        assert result.passed
        assert not result.blocking

    def test_the_gap_reaches_the_serialised_report(self):
        """The API and the admin console both read the dict form."""
        data = report(gaps=["no segment was costed"]).to_dict()
        assert data["confidence"] == ConfidenceState.LOW.value
        codes = [f["code"] for f in data["findings"]]
        assert "G7_incomplete_analysis" in codes


class TestBackwardsCompatibility:
    @pytest.mark.parametrize("gaps", [None, []])
    def test_omitting_the_argument_changes_nothing(self, gaps):
        assert report(gaps=gaps).confidence is ConfidenceState.HIGH
