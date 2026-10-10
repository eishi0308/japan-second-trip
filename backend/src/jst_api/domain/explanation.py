"""The closing summary of an analysis, and its deterministic form.

The summary is the last thing written and the first thing read: a verdict, what
to do next, and what to hold loosely. A model writes it when one is available,
but it may only restate facts the analysis already established — so the same
facts can always produce a plain version without a model. That plain version is
the fallback when the model fails or says something the facts do not support,
and it is what the demo provider returns.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_NEXT_STEPS = 3
MAX_CAVEATS = 3

REVIEW_CAVEAT = (
    "A reviewer has been asked to confirm a disputed detail; "
    "treat it as unconfirmed until that is done."
)
LOW_CONFIDENCE_CAVEAT = (
    "Confidence in this analysis is low: too little of it could be backed by verified evidence."
)


class FinalExplanationOutput(BaseModel):
    """What the model returns for the ``final_explanation`` prompt."""

    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(max_length=600)
    next_steps: list[str] = Field(default_factory=list, max_length=MAX_NEXT_STEPS)
    caveats: list[str] = Field(default_factory=list, max_length=MAX_CAVEATS)


class FinalExplanation(FinalExplanationOutput):
    """The summary as stored on a result, with where it came from."""

    source: Literal["model", "deterministic"] = "deterministic"


def deterministic_final_explanation(facts: dict[str, Any]) -> FinalExplanationOutput:
    """Build the summary from the established facts alone, with no model."""
    supporting = [s for s in facts.get("supporting") or [] if s]
    verdict = str(facts.get("headline_fact") or "The analysis is complete.")
    if supporting:
        verdict = f"{verdict.rstrip('.')}. {supporting[0]}"

    next_steps: list[str] = []
    if facts.get("recommended_change"):
        next_steps.append(str(facts["recommended_change"]))
    next_steps.extend(str(s) for s in facts.get("actions") or [])

    caveats: list[str] = []
    for conflict in facts.get("conflicts") or []:
        caveats.append(f"Sources disagree on {conflict}; that detail is unconfirmed.")
    if facts.get("human_review_required"):
        caveats.append(REVIEW_CAVEAT)
    if facts.get("confidence") == "low":
        caveats.append(LOW_CONFIDENCE_CAVEAT)
    caveats.extend(str(u) for u in facts.get("unknowns") or [])

    return FinalExplanationOutput(
        verdict=verdict[:600],
        next_steps=list(dict.fromkeys(next_steps))[:MAX_NEXT_STEPS],
        caveats=list(dict.fromkeys(caveats))[:MAX_CAVEATS],
    )
