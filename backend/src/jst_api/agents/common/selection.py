"""Model-driven tool selection, with the model kept on a short lead.

Where the right lookups depend on what was asked — the admin assistant's
free-text reviewer requests — the model chooses which tools to call and with
what arguments. It chooses; it does not act. Every selection is checked here
before anything is dispatched:

* the tool must be on the consumer's allowlist **and** read-only — a tool that
  writes state or opens a review task is never selectable, whatever the request
  or a retrieved document says;
* the arguments must validate against that tool's typed input contract;
* duplicates are dropped and the plan is capped.

A selection that fails any check is recorded as rejected and not executed. The
traveller-facing graphs do not use this: their tool sequence is fixed by the
workflow, because a route check that skips the transport lookup is not a
different plan, it is a wrong answer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared_schemas.tools import (
    TOOL_CONTRACTS,
    GetBookingRequirementsInput,
    GetPlaceConstraintsInput,
    GetPlaceDetailsInput,
    GetSourceEvidenceInput,
    GetVerificationStatusInput,
    SearchEvidenceInput,
    ToolPermission,
)

#: Tools a model may select, with the contract its arguments must satisfy.
SELECTABLE_TOOLS: dict[str, type[BaseModel]] = {
    "get_verification_status": GetVerificationStatusInput,
    "search_verified_evidence": SearchEvidenceInput,
    "get_source_evidence": GetSourceEvidenceInput,
    "get_place_details": GetPlaceDetailsInput,
    "get_place_constraints": GetPlaceConstraintsInput,
    "get_booking_requirements": GetBookingRequirementsInput,
}

MAX_SELECTED_CALLS = 4


class ToolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(max_length=60)
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=240)


class ToolPlan(BaseModel):
    """What the model returns for the ``tool_selection`` prompt."""

    model_config = ConfigDict(extra="forbid")

    selections: list[ToolSelection] = Field(default_factory=list, max_length=8)


@dataclass
class PlannedCall:
    tool: str
    arguments: dict[str, Any]
    reason: str
    status: Literal["planned", "executed", "failed", "rejected"] = "planned"
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def selectable_for(allowlist: set[str]) -> list[str]:
    """The read-only tools this consumer's model may choose from."""
    return sorted(
        name
        for name in SELECTABLE_TOOLS
        if name in allowlist and TOOL_CONTRACTS[name].permission is ToolPermission.READ
    )


def tool_catalogue(allowlist: set[str]) -> list[dict[str, Any]]:
    """The menu shown to the model: name, purpose and argument schema."""
    return [
        {
            "tool": name,
            "description": TOOL_CONTRACTS[name].description,
            "arguments": SELECTABLE_TOOLS[name].model_json_schema().get("properties", {}),
        }
        for name in selectable_for(allowlist)
    ]


def validate_plan(
    plan: ToolPlan, *, allowlist: set[str], max_calls: int = MAX_SELECTED_CALLS
) -> list[PlannedCall]:
    """Turn a model's plan into calls that are safe to dispatch, rejecting the rest."""
    permitted = set(selectable_for(allowlist))
    calls: list[PlannedCall] = []
    seen: set[str] = set()
    accepted = 0

    for selection in plan.selections:
        call = PlannedCall(
            tool=selection.tool, arguments=selection.arguments, reason=selection.reason
        )
        calls.append(call)
        if selection.tool not in permitted:
            call.status = "rejected"
            call.detail = "not a tool this assistant may select"
            continue
        try:
            validated = SELECTABLE_TOOLS[selection.tool].model_validate(selection.arguments)
        except ValidationError as exc:
            call.status = "rejected"
            call.detail = f"invalid arguments: {exc.errors()[0]['msg']}"[:200]
            continue
        call.arguments = validated.model_dump(mode="json", exclude_defaults=True)
        fingerprint = f"{call.tool}:{json.dumps(call.arguments, sort_keys=True)}"
        if fingerprint in seen:
            call.status = "rejected"
            call.detail = "duplicate of an earlier selection"
            continue
        if accepted >= max_calls:
            call.status = "rejected"
            call.detail = f"over the limit of {max_calls} selected calls"
            continue
        seen.add(fingerprint)
        accepted += 1
    return calls
