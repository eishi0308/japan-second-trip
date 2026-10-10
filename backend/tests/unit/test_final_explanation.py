"""The closing summary: written by a model, but never allowed to outrun the facts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from jst_api.agents.common.explanation import FALLBACK_NAME, write_final_explanation
from jst_api.domain.explanation import (
    MAX_CAVEATS,
    FinalExplanationOutput,
    deterministic_final_explanation,
)
from jst_api.observability.tracing import RunTrace
from jst_api.prompts.registry import get_prompts
from jst_api.providers.base import LLMUsage

FACTS: dict[str, Any] = {
    "flow": "route_check",
    "headline_fact": "Route health is needs improvement: 1 critical problem(s) and 2 warning(s)",
    "supporting": ["Ginzan Onsen → Aomori costs more time than it buys"],
    "recommended_change": "Switch to the revised route: Tokyo 3N → Sendai 2N → Aomori 2N → Tokyo.",
    "confidence": "medium",
    "human_review_required": False,
    "conflicts": [],
    "unknowns": [],
}


class FakeLLM:
    name = "fake"
    is_demo = False

    def __init__(self, reply: FinalExplanationOutput | Exception) -> None:
        self._reply = reply
        self.calls = 0

    async def complete_structured(self, **kwargs: Any):
        self.calls += 1
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply, LLMUsage(model="fake-fast", provider="fake")


def make_ctx(llm: FakeLLM) -> Any:
    return SimpleNamespace(
        prompts=get_prompts(),
        registry=SimpleNamespace(llm=llm),
        trace=RunTrace(graph_name="t", thread_id="t"),
        model_for=lambda task: "fake-fast",
    )


class TestDeterministicSummary:
    def test_it_leads_with_the_decision_and_its_main_reason(self):
        summary = deterministic_final_explanation(FACTS)
        assert summary.verdict.startswith("Route health is needs improvement")
        assert "Ginzan Onsen → Aomori" in summary.verdict
        assert summary.next_steps == [FACTS["recommended_change"]]
        assert summary.caveats == []

    def test_a_disputed_detail_becomes_a_caveat_and_no_value_is_chosen(self):
        facts = {
            **FACTS,
            "conflicts": ["ginzan-onsen:oishida_last_bus (last_shuttle_departure)"],
            "human_review_required": True,
        }
        summary = deterministic_final_explanation(facts)
        assert any("Sources disagree" in c for c in summary.caveats)
        assert any("reviewer" in c for c in summary.caveats)
        assert "17:00" not in " ".join(summary.caveats)

    def test_low_confidence_is_said_plainly(self):
        summary = deterministic_final_explanation({**FACTS, "confidence": "low"})
        assert any("low" in c for c in summary.caveats)

    def test_the_lists_are_bounded(self):
        facts = {**FACTS, "unknowns": [f"unknown {i}" for i in range(10)]}
        assert len(deterministic_final_explanation(facts).caveats) == MAX_CAVEATS


@pytest.mark.asyncio
class TestWrittenSummary:
    async def test_a_supported_summary_is_kept_and_its_prompt_version_recorded(self):
        llm = FakeLLM(
            FinalExplanationOutput(
                verdict="This route needs work: Ginzan Onsen → Aomori costs more time than it buys.",
                next_steps=["Switch to Tokyo 3N → Sendai 2N → Aomori 2N → Tokyo."],
            )
        )
        ctx = make_ctx(llm)
        summary = await write_final_explanation(ctx, FACTS)
        assert summary["source"] == "model"
        assert summary["verdict"].startswith("This route needs work")
        assert ctx.trace.prompt_versions["final_explanation"] == "1.0.0"
        assert FALLBACK_NAME not in ctx.trace.fallbacks_used

    async def test_an_invented_departure_time_is_discarded(self):
        llm = FakeLLM(
            FinalExplanationOutput(
                verdict="This route needs work. Catch the 17:45 bus from Oishida to be safe.",
            )
        )
        ctx = make_ctx(llm)
        summary = await write_final_explanation(ctx, FACTS)
        assert summary["source"] == "deterministic"
        assert "17:45" not in summary["verdict"]
        assert FALLBACK_NAME in ctx.trace.fallbacks_used, "the fallback must be traced"

    async def test_a_summary_that_drops_a_disputed_detail_is_discarded(self):
        facts = {**FACTS, "conflicts": ["ginzan-onsen:oishida_last_bus (last_shuttle_departure)"]}
        llm = FakeLLM(FinalExplanationOutput(verdict="This route needs work.", caveats=[]))
        summary = await write_final_explanation(make_ctx(llm), facts)
        assert summary["source"] == "deterministic"
        assert any("Sources disagree" in c for c in summary["caveats"])

    async def test_a_model_outage_still_yields_a_summary(self):
        ctx = make_ctx(FakeLLM(ConnectionError("model unreachable")))
        summary = await write_final_explanation(ctx, FACTS)
        assert summary["source"] == "deterministic"
        assert summary["verdict"]
        assert FALLBACK_NAME in ctx.trace.fallbacks_used


@pytest.mark.asyncio
class TestSummaryOnResults:
    async def test_where_next_carries_a_summary_naming_the_recommendation(self, analysis_service):
        run = await analysis_service.run_where_next(
            {"regional_nights": 3, "arrival_city": "Tokyo", "interests": ["food", "onsen"]}
        )
        summary = run.result["final_explanation"]
        assert run.result["recommended"]["region_name"] in summary["verdict"]
        assert "final_explanation" in run.result["prompt_versions"]

    async def test_route_check_carries_a_summary_with_the_revised_route(self, analysis_service):
        run = await analysis_service.run_route_check(
            {
                "itinerary_text": "Tokyo 3 nights, Sendai 1 night, Ginzan Onsen 1 night, "
                "Aomori 1 night, Hakodate 1 night, then Tokyo",
                "driving": "no_car",
            }
        )
        summary = run.result["final_explanation"]
        assert "Route health" in summary["verdict"]
        assert any("revised route" in step for step in summary["next_steps"])
        assert "final_explanation" in run.result["prompt_versions"]
