"""Write the closing summary of a finished analysis.

Runs last, after the grounding and confidence checks, so it has to hold itself
to the same rule they enforce: no operational claim without support. Here the
support is the fact sheet the summary is written from. A summary that asserts a
time, price or date the fact sheet does not contain, or that drops a disputed
detail, is discarded and the deterministic version is used instead — the result
always carries a summary, and never an unsupported one.
"""

from __future__ import annotations

import json
from typing import Any

from jst_api.agents.common.guardrails import operational_literals
from jst_api.agents.common.state import AgentContext
from jst_api.core.logging import get_logger
from jst_api.domain.explanation import (
    FinalExplanation,
    FinalExplanationOutput,
    deterministic_final_explanation,
)
from jst_api.providers.llm import TaskClass, complete_with_repair, structured_block

log = get_logger(__name__)

FALLBACK_NAME = "final_explanation:deterministic"


def describe_conflict(conflict: dict[str, Any]) -> str:
    """A disputed record in words: ``ginzan-onsen:oishida_last_bus`` reads as a key, not a fact."""

    def words(value: str) -> str:
        return value.replace(":", " — ").replace("_", " ").replace("-", " ")

    return f"the {words(conflict['field_name'])} recorded for {words(conflict['subject'])}"


def unsupported_literals(output: FinalExplanationOutput, facts: dict[str, Any]) -> set[str]:
    """Times, prices and dates in the summary that the fact sheet does not contain."""
    prose = " ".join([output.verdict, *output.next_steps, *output.caveats])
    supported = json.dumps(facts, ensure_ascii=False, default=str)
    return {literal for literal in operational_literals(prose) if literal not in supported}


def _violation(output: FinalExplanationOutput, facts: dict[str, Any]) -> str | None:
    unsupported = unsupported_literals(output, facts)
    if unsupported:
        return f"unsupported literal(s): {', '.join(sorted(unsupported))}"
    if not output.verdict.strip():
        return "empty verdict"
    if (facts.get("conflicts") or facts.get("human_review_required")) and not output.caveats:
        return "a disputed detail was left out of the caveats"
    return None


async def write_final_explanation(ctx: AgentContext, facts: dict[str, Any]) -> dict[str, Any]:
    """Return the summary for ``facts`` as a ``FinalExplanation`` payload."""
    prompt = ctx.prompts.get("final_explanation")
    user = f"{prompt.render_user(flow=facts.get('flow', 'analysis'))}\n\n{structured_block(facts)}"

    reason: str | None
    try:
        output, usages = await complete_with_repair(
            ctx.registry.llm,
            system=prompt.system,
            user=user,
            schema=FinalExplanationOutput,
            model=ctx.model_for(TaskClass.EXPLANATION),
            repair_model=ctx.model_for(TaskClass.REPAIR),
        )
    except Exception as exc:
        reason = f"model call failed: {str(exc)[:200]}"
    else:
        for usage in usages:
            ctx.trace.record_usage(usage, prompt=prompt.label)
        reason = _violation(output, facts)
        if reason is None:
            return FinalExplanation(**output.model_dump(), source="model").model_dump(mode="json")

    log.warning("final_explanation.fallback", reason=reason)
    ctx.trace.record_fallback(FALLBACK_NAME)
    fallback = deterministic_final_explanation(facts)
    return FinalExplanation(**fallback.model_dump(), source="deterministic").model_dump(mode="json")
