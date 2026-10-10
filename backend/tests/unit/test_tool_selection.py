"""Model-driven tool selection: the model proposes, the validator disposes."""

from __future__ import annotations

from jst_api.agents.common.selection import (
    MAX_SELECTED_CALLS,
    ToolPlan,
    ToolSelection,
    selectable_for,
    tool_catalogue,
    validate_plan,
)
from jst_api.agents.common.tools import CONSUMER_ALLOWLISTS
from jst_api.providers.llm import _demo_tool_plan

ADMIN = CONSUMER_ALLOWLISTS["admin_assistant"]


def plan(*selections: tuple[str, dict]) -> ToolPlan:
    return ToolPlan(selections=[ToolSelection(tool=t, arguments=a) for t, a in selections])


class TestTheMenu:
    def test_only_read_tools_on_the_allowlist_are_offered(self):
        offered = selectable_for(ADMIN)
        assert "get_verification_status" in offered
        assert "search_verified_evidence" in offered
        # On the allowlist, but it opens a review task — never the model's call.
        assert "create_human_review_request" not in offered
        assert "save_trip_decision" not in offered

    def test_the_catalogue_carries_each_tools_argument_schema(self):
        catalogue = {entry["tool"]: entry for entry in tool_catalogue(ADMIN)}
        assert "query" in catalogue["search_verified_evidence"]["arguments"]
        assert catalogue["get_place_constraints"]["description"]

    def test_a_narrower_allowlist_narrows_the_menu(self):
        assert selectable_for({"get_place_details"}) == ["get_place_details"]


class TestValidation:
    def test_a_valid_selection_is_planned_with_normalised_arguments(self):
        [call] = validate_plan(
            plan(("search_verified_evidence", {"query": "Ginzan Onsen last bus"})), allowlist=ADMIN
        )
        assert call.status == "planned"
        assert call.arguments == {"query": "Ginzan Onsen last bus"}

    def test_a_write_tool_is_rejected_even_when_asked_for(self):
        [call] = validate_plan(
            plan(("save_trip_decision", {"trip_id": "t", "decision_kind": "candidate_selected"})),
            allowlist=ADMIN,
        )
        assert call.status == "rejected"

    def test_the_review_tool_is_rejected_although_the_consumer_may_call_it(self):
        assert "create_human_review_request" in ADMIN
        [call] = validate_plan(plan(("create_human_review_request", {})), allowlist=ADMIN)
        assert call.status == "rejected"

    def test_an_invented_tool_is_rejected(self):
        [call] = validate_plan(plan(("approve_everything", {})), allowlist=ADMIN)
        assert call.status == "rejected"

    def test_arguments_outside_the_contract_are_rejected(self):
        unknown_field, missing_required = validate_plan(
            plan(
                ("search_verified_evidence", {"query": "onsen", "sql": "drop table sources"}),
                ("get_place_constraints", {}),
            ),
            allowlist=ADMIN,
        )
        assert unknown_field.status == "rejected"
        assert missing_required.status == "rejected"
        assert "invalid arguments" in (missing_required.detail or "")

    def test_a_repeated_call_is_dropped(self):
        first, second = validate_plan(
            plan(
                ("get_place_details", {"query": "Sendai"}),
                ("get_place_details", {"query": "Sendai"}),
            ),
            allowlist=ADMIN,
        )
        assert first.status == "planned"
        assert second.status == "rejected"

    def test_the_plan_is_capped(self):
        many = plan(*[("get_place_details", {"query": f"place {i}"}) for i in range(7)])
        calls = validate_plan(many, allowlist=ADMIN)
        assert sum(c.status == "planned" for c in calls) == MAX_SELECTED_CALLS


class TestDemoSelection:
    def _select(self, request: str) -> list[str]:
        output = _demo_tool_plan({"request": request, "tools": tool_catalogue(ADMIN)}, ToolPlan)
        return [s.tool for s in output.selections]  # type: ignore[attr-defined]

    def test_a_request_about_stale_records_selects_the_status_tool(self):
        assert self._select("Show me Tohoku evidence that is stale or conflicting") == [
            "get_verification_status",
            "search_verified_evidence",
        ]

    def test_a_topic_question_does_not_pull_the_status_report(self):
        assert self._select("What do we hold on Kamikochi lodges?") == ["search_verified_evidence"]

    def test_it_never_selects_a_tool_that_was_not_offered(self):
        output = _demo_tool_plan({"request": "stale records", "tools": []}, ToolPlan)
        assert output.selections == []  # type: ignore[attr-defined]
