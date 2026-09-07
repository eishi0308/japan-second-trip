"""Admin verification assistant — the third MCP consumer.

An internal, AI-assisted triage step for the reviewer. It answers questions like
*"show me Tohoku evidence that is stale or conflicting"* by calling the same
``travel-intelligence-mcp`` capabilities the traveller-facing agents use.

The reason it exists architecturally, and not as a demo: it proves the gateway
is a genuine reuse boundary rather than a wrapper around one caller. It also has
the *narrowest* allowlist of the three consumers — it can read and escalate, but
it cannot write trip state, and it can never approve its own findings. Approval
is a human action, by construction.

This is a single-shot assistant, not a graph: there is no branching decision to
make, so a StateGraph here would be ceremony.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jst_api.agents.common.tools import ToolBelt, ToolBudget
from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.observability.tracing import RunTrace
from jst_api.prompts.registry import PromptRegistry
from jst_api.providers.llm import TaskClass, complete_with_repair, structured_block
from jst_api.providers.registry import ProviderRegistry
from jst_api.security.injection import sanitise_user_text
from jst_api.services.mcp_backend import JstTravelBackend
from travel_mcp.session import TravelMcpSession

log = get_logger(__name__)


class AdminFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    issue: str
    severity: str = "warning"
    values: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verified_at: str | None = None
    review_task_id: str | None = None


class AdminAssistantAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(max_length=1200)
    findings: list[AdminFinding] = Field(default_factory=list, max_length=25)
    suggested_actions: list[str] = Field(default_factory=list, max_length=8)
    detail: str = Field(default="", max_length=4000)


class AdminAssistant:
    CONSUMER = "admin_assistant"

    def __init__(
        self,
        session_factory: Any,
        registry: ProviderRegistry,
        prompts: PromptRegistry,
        settings: Settings,
    ) -> None:
        self._backend = JstTravelBackend(session_factory, registry, settings)
        self._registry = registry
        self._prompts = prompts
        self._settings = settings

    async def ask(self, request: str, *, region_code: str | None = None) -> dict[str, Any]:
        cleaned, scan = sanitise_user_text(request, max_chars=1000)
        if scan.suspicious:
            log.warning("admin_assistant.injection_flagged", rules=scan.matched_rules)

        trace = RunTrace(graph_name="admin_assistant", thread_id="admin")
        findings: list[dict[str, Any]] = []

        async with TravelMcpSession(self._backend) as mcp:
            belt = ToolBelt(
                session=mcp,
                consumer=self.CONSUMER,
                trace=trace,
                budget=ToolBudget(max_calls=8),
            )
            belt.current_node = "triage"

            status = await belt.call_optional(
                "get_verification_status", {"limit": 50, "stale_only": False}
            )
            if status:
                for entry in status.get("entries", []):
                    if entry.get("requires_reverification"):
                        findings.append(
                            {
                                "subject": entry["subject"],
                                "issue": (
                                    f"{entry['field_name']} = '{entry['value']}' is {entry['freshness']}; "
                                    "it is past its re-check window for this topic."
                                ),
                                "severity": "warning",
                                "values": [entry["value"]],
                                "evidence_ids": [],
                                "verified_at": entry.get("verified_at"),
                                "review_task_id": None,
                            }
                        )
                for conflict in status.get("conflicts", []):
                    findings.append(
                        {
                            "subject": conflict["subject"],
                            "issue": (
                                f"Sources disagree on {conflict['field_name']}: "
                                f"{', '.join(conflict['values'])}. Not resolvable automatically."
                            ),
                            "severity": "critical",
                            "values": conflict["values"],
                            "evidence_ids": conflict.get("evidence_ids", []),
                            "verified_at": None,
                            "review_task_id": conflict.get("open_review_task_id"),
                        }
                    )

            # Retrieval over the same gateway, so the reviewer's question steers
            # which evidence is surfaced.
            evidence = await belt.call_optional(
                "search_verified_evidence",
                {
                    "query": cleaned,
                    "region_codes": [region_code] if region_code else [],
                    "limit": 5,
                },
            )
            evidence_refs = (evidence or {}).get("evidence", [])

            if region_code:
                findings = [
                    f
                    for f in findings
                    if region_code in f["subject"]
                    or any(e["evidence_id"] in f["evidence_ids"] for e in evidence_refs)
                    or f["severity"] == "critical"
                ]

            prompt = self._prompts.get("admin_verification")
            payload = {
                "findings": findings,
                "evidence": [
                    {
                        "evidence_id": e["evidence_id"],
                        "source": e["source_title"],
                        "freshness": e["freshness"],
                        "verified_at": e.get("verified_at"),
                        "snippet": e.get("snippet", "")[:240],
                    }
                    for e in evidence_refs
                ],
                "region_code": region_code,
            }
            user = f"{prompt.render_user(request=cleaned)}\n\n{structured_block(payload)}"

            try:
                answer, usages = await complete_with_repair(
                    self._registry.llm,
                    system=prompt.system,
                    user=user,
                    schema=AdminAssistantAnswer,
                    model=self._registry.router.model_for(TaskClass.ADMIN),
                )
                for usage in usages:
                    trace.record_usage(usage, prompt=prompt.label)
                result = answer.model_dump(mode="json")
            except Exception as exc:
                log.warning("admin_assistant.model_failed", error=str(exc)[:300])
                result = {
                    "summary": f"{len(findings)} record(s) need attention (model narration unavailable).",
                    "findings": findings,
                    "suggested_actions": [
                        "Open each record in the evidence inspector and verify against the source."
                    ],
                    "detail": "",
                }

        result["evidence"] = evidence_refs
        result["trace"] = trace.summary()
        result["tools_available"] = sorted(
            ToolBelt(
                session=None,  # type: ignore[arg-type]
                consumer=self.CONSUMER,
                trace=trace,
            ).allowlist
        )
        result["can_write_trip_state"] = False
        return result
