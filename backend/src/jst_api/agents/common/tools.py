"""The tool belt the graphs call.

Everything an agent can do to the outside world goes through here, and this
layer enforces the properties the raw MCP session cannot:

* **Allowlist per consumer.** WhereNext, RouteCheck and the admin assistant each
  get a different set. A tool absent from a consumer's list cannot be called
  even if something in the context asks for it — which is the capability half of
  the prompt-injection defence.
* **Budget.** A hard cap on tool calls per run. Exceeding it raises rather than
  looping.
* **Bounded retries with backoff**, on transient failures only.
* **Tracing.** Every call records tool, node, redacted arguments, latency,
  attempts, cache hit and outcome onto the ``RunTrace``.
* **Failure containment.** ``call_optional`` returns ``None`` instead of raising,
  for capabilities the graph can proceed without. That is how a provider outage
  degrades the answer instead of failing the request.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from jst_api.core.errors import AgentBudgetExceeded, ForbiddenError
from jst_api.core.logging import get_logger
from jst_api.observability.tracing import RunTrace, ToolCallRecord
from shared_schemas.tools import TOOL_CONTRACTS, ToolPermission
from travel_mcp.session import McpToolError, TravelMcpSession

log = get_logger(__name__)

#: Per-consumer allowlists. Least privilege, declared not inferred.
CONSUMER_ALLOWLISTS: dict[str, set[str]] = {
    "where_next": {
        "search_verified_evidence",
        "get_source_evidence",
        "get_place_details",
        "get_place_constraints",
        "search_transport",
        "get_route_context",
        "calculate_travel_load",
        "get_booking_requirements",
        "get_weather_context",
        "get_verification_status",
        "create_human_review_request",
        "get_trip_context",
        "save_trip_decision",
    },
    "route_check": {
        "search_verified_evidence",
        "get_source_evidence",
        "get_place_details",
        "get_place_constraints",
        "search_transport",
        "get_route_context",
        "calculate_travel_load",
        "check_route_constraints",
        "get_booking_requirements",
        "get_verification_status",
        "create_human_review_request",
        "get_trip_context",
    },
    # The admin assistant may read everything and escalate, but may not write
    # trip state — it acts on behalf of a reviewer, not a traveller.
    "admin_assistant": {
        "search_verified_evidence",
        "get_source_evidence",
        "get_place_details",
        "get_place_constraints",
        "get_booking_requirements",
        "get_verification_status",
        "create_human_review_request",
    },
}

TRANSIENT_TOOL_ERRORS = ("timeout", "temporarily unavailable", "connection", "circuit open")


@dataclass
class ToolBudget:
    max_calls: int = 20
    used: int = 0

    def consume(self, tool: str) -> None:
        self.used += 1
        if self.used > self.max_calls:
            raise AgentBudgetExceeded(
                f"tool-call budget of {self.max_calls} exhausted (last: {tool})",
                details={"tool": tool, "budget": self.max_calls},
            )


@dataclass
class ToolBelt:
    """Bound to one consumer, one MCP session and one trace."""

    session: TravelMcpSession
    consumer: str
    trace: RunTrace
    budget: ToolBudget = field(default_factory=ToolBudget)
    current_node: str | None = None

    @property
    def allowlist(self) -> set[str]:
        return CONSUMER_ALLOWLISTS.get(self.consumer, set())

    def can_call(self, tool: str) -> bool:
        return tool in self.allowlist

    def assert_allowed(self, tool: str) -> None:
        if tool not in TOOL_CONTRACTS:
            raise ForbiddenError(f"unknown tool '{tool}'", details={"tool": tool})
        if not self.can_call(tool):
            raise ForbiddenError(
                f"consumer '{self.consumer}' is not permitted to call '{tool}'",
                details={
                    "tool": tool,
                    "consumer": self.consumer,
                    "allowed": sorted(self.allowlist),
                },
            )

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool through the MCP gateway. Raises on final failure."""
        self.assert_allowed(tool)
        contract = TOOL_CONTRACTS[tool]
        self.budget.consume(tool)

        attempts = 0
        started = time.perf_counter()
        last_error: Exception | None = None

        while attempts < contract.max_attempts:
            attempts += 1
            try:
                async with self.trace.aspan(
                    f"mcp.{tool}", kind="tool", tool=tool, consumer=self.consumer, attempt=attempts
                ):
                    result = await asyncio.wait_for(
                        self.session.call(tool, arguments), timeout=contract.timeout_seconds
                    )
            except (McpToolError, TimeoutError) as exc:
                last_error = exc
                message = str(exc).lower()
                transient = isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or any(
                    marker in message for marker in TRANSIENT_TOOL_ERRORS
                )
                if not transient or attempts >= contract.max_attempts:
                    break
                await asyncio.sleep(0.2 * attempts)
            else:
                latency = int((time.perf_counter() - started) * 1000)
                self.trace.record_tool_call(
                    ToolCallRecord(
                        tool_name=tool,
                        node=self.current_node,
                        transport="mcp",
                        arguments=arguments,
                        ok=True,
                        latency_ms=latency,
                        attempts=attempts,
                        result_summary=_summarise(result.data),
                    )
                )
                return result.data

        latency = int((time.perf_counter() - started) * 1000)
        self.trace.record_tool_call(
            ToolCallRecord(
                tool_name=tool,
                node=self.current_node,
                transport="mcp",
                arguments=arguments,
                ok=False,
                latency_ms=latency,
                attempts=attempts,
                error=str(last_error)[:500],
            )
        )
        log.warning(
            "tool.failed",
            tool=tool,
            consumer=self.consumer,
            attempts=attempts,
            error=str(last_error)[:300],
        )
        raise last_error if last_error else RuntimeError(f"{tool} failed")

    async def call_optional(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Call a tool the graph can continue without.

        This is the degradation seam: a weather or booking lookup that fails
        produces a slightly thinner answer, not a failed request.
        """
        try:
            return await self.call(tool, arguments)
        except AgentBudgetExceeded:
            raise
        except Exception as exc:
            log.info("tool.optional_failed_continuing", tool=tool, error=str(exc)[:200])
            self.trace.record_fallback(f"tool_skipped:{tool}")
            return None

    def writes_allowed(self) -> list[str]:
        return sorted(
            t for t in self.allowlist if TOOL_CONTRACTS[t].permission is not ToolPermission.READ
        )


def _summarise(data: dict[str, Any]) -> dict[str, Any]:
    """Compact result summary for the trace — never the whole payload."""
    summary: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
        elif isinstance(value, dict):
            summary[f"{key}_keys"] = sorted(value)[:8]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value if not isinstance(value, str) else value[:160]
    return summary
