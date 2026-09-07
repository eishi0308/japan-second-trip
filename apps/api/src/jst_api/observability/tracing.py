"""Tracing, cost and latency accounting.

One ``RunTrace`` per analysis. It records the whole causal chain —
request → graph run → node → model call (with prompt version) → retrieval query
→ evidence ids → MCP tool → external provider → response — together with
latency, tokens, estimated cost, retries and fallbacks.

Three sinks, in decreasing order of preference, all optional:
  * OpenTelemetry spans when an OTLP endpoint is configured;
  * Langfuse when its keys are configured (AI-specific trace UI);
  * always: structured local logs plus ``agent_runs`` / ``tool_calls`` rows,
    which is what the admin agent-run inspector reads.

Nothing here is required for the app to run — if every sink is unconfigured the
trace still persists to PostgreSQL, so "observability works" is not conditional
on a third-party account.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jst_api.core.logging import get_logger, redact_value
from jst_api.providers.base import LLMUsage

log = get_logger(__name__)

_otel_tracer: Any = None
_otel_ready = False


def init_tracing(settings: Any) -> None:
    """Configure OpenTelemetry once at startup, if an endpoint is set."""
    global _otel_tracer, _otel_ready
    if _otel_ready or not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": "japan-second-trip-api",
                "deployment.environment": settings.environment,
            }
        )
        provider = TracerProvider(resource=resource)
        if settings.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
            )
        trace.set_tracer_provider(provider)
        _otel_tracer = trace.get_tracer("jst")
        log.info("tracing.otel_enabled", endpoint=settings.otel_exporter_otlp_endpoint)
    except Exception as exc:  # pragma: no cover - optional dependency path
        log.warning("tracing.otel_init_failed", error=str(exc))
    finally:
        _otel_ready = True


@dataclass
class SpanRecord:
    name: str
    kind: str
    started_at: float
    duration_ms: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "error": self.error,
        }


@dataclass
class ToolCallRecord:
    tool_name: str
    node: str | None
    transport: str
    arguments: dict[str, Any]
    ok: bool
    latency_ms: int
    attempts: int = 1
    cache_hit: bool = False
    error: str | None = None
    result_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunTrace:
    graph_name: str
    thread_id: str
    analysis_id: str | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    node_path: list[str] = field(default_factory=list)
    spans: list[SpanRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usages: list[LLMUsage] = field(default_factory=list)
    retrieval_events: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    fallbacks_used: list[str] = field(default_factory=list)
    retries: int = 0
    error: str | None = None
    step_count: int = 0

    # ---- accumulation -----------------------------------------------------
    def enter_node(self, node: str) -> None:
        self.node_path.append(node)
        self.step_count += 1

    def record_usage(self, usage: LLMUsage, *, prompt: str | None = None) -> None:
        self.usages.append(usage)
        if usage.fell_back:
            self.fallbacks_used.append(f"llm:{usage.provider}")
        if prompt:
            prompt_id, _, version = prompt.partition("@")
            self.prompt_versions[prompt_id] = version or "unknown"

    def record_tool_call(self, record: ToolCallRecord) -> None:
        self.tool_calls.append(record)
        if record.attempts > 1:
            self.retries += record.attempts - 1

    def record_retrieval(
        self, *, query: str, strategy: str, evidence_ids: list[str], latency_ms: int, **extra: Any
    ) -> None:
        self.retrieval_events.append(
            {
                "query": query[:200],
                "strategy": strategy,
                "evidence_ids": evidence_ids,
                "latency_ms": latency_ms,
                **extra,
            }
        )
        for eid in evidence_ids:
            if eid not in self.evidence_ids:
                self.evidence_ids.append(eid)

    def record_fallback(self, name: str) -> None:
        self.fallbacks_used.append(name)

    # ---- derived ----------------------------------------------------------
    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    @property
    def prompt_tokens(self) -> int:
        return sum(u.prompt_tokens for u in self.usages)

    @property
    def completion_tokens(self) -> int:
        return sum(u.completion_tokens for u in self.usages)

    @property
    def estimated_cost_usd(self) -> float:
        return round(sum(u.estimated_cost_usd for u in self.usages), 6)

    @property
    def model_calls(self) -> int:
        return len(self.usages)

    def summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "graph": self.graph_name,
            "thread_id": self.thread_id,
            "analysis_id": self.analysis_id,
            "nodes": self.node_path,
            "steps": self.step_count,
            "latency_ms": self.latency_ms,
            "model_calls": self.model_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "tool_calls": len(self.tool_calls),
            "failed_tool_calls": sum(1 for t in self.tool_calls if not t.ok),
            "cache_hits": sum(1 for t in self.tool_calls if t.cache_hit),
            "retries": self.retries,
            "fallbacks": self.fallbacks_used,
            "evidence_count": len(self.evidence_ids),
            "prompt_versions": self.prompt_versions,
            "error": self.error,
        }

    # ---- span helpers -----------------------------------------------------
    @contextmanager
    def span(self, name: str, kind: str = "internal", **attributes: Any):
        record = SpanRecord(
            name=name, kind=kind, started_at=time.perf_counter(), attributes=dict(attributes)
        )
        otel_span = None
        if _otel_tracer is not None:
            otel_span = _otel_tracer.start_span(name)
            for key, value in attributes.items():
                otel_span.set_attribute(key, str(redact_value(key, value)))
        try:
            yield record
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            if otel_span is not None:
                otel_span.record_exception(exc)
            raise
        finally:
            record.duration_ms = int((time.perf_counter() - record.started_at) * 1000)
            self.spans.append(record)
            if otel_span is not None:
                otel_span.set_attribute("duration_ms", record.duration_ms)
                otel_span.end()

    @asynccontextmanager
    async def aspan(self, name: str, kind: str = "internal", **attributes: Any):
        with self.span(name, kind, **attributes) as record:
            yield record

    # ---- persistence -------------------------------------------------------
    async def persist(self, session: Any, *, status: str = "complete") -> str:
        """Write the run and its tool calls. Tolerant by design: a tracing
        failure must never fail the user's analysis."""
        from jst_api.db.models import AgentRun, ToolCall

        try:
            run = AgentRun(
                analysis_id=self.analysis_id,
                graph_name=self.graph_name,
                thread_id=self.thread_id,
                status=status,
                node_path=self.node_path,
                step_count=self.step_count,
                started_at=self.started_at,
                finished_at=datetime.now(UTC),
                latency_ms=self.latency_ms,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                estimated_cost_usd=self.estimated_cost_usd,
                model_calls=self.model_calls,
                retries=self.retries,
                fallbacks_used=self.fallbacks_used,
                trace_id=self.trace_id,
                error=self.error,
            )
            session.add(run)
            await session.flush()
            for call in self.tool_calls:
                session.add(
                    ToolCall(
                        run_id=run.id,
                        node=call.node,
                        tool_name=call.tool_name,
                        transport=call.transport,
                        arguments=redact_value("arguments", call.arguments),
                        result_summary=call.result_summary,
                        ok=call.ok,
                        error=call.error,
                        latency_ms=call.latency_ms,
                        attempts=call.attempts,
                        cache_hit=call.cache_hit,
                    )
                )
            await session.flush()
            log.info("trace.persisted", **self.summary())
            await self._emit_langfuse()
            return run.id
        except Exception as exc:  # pragma: no cover - tracing must not break the request
            log.warning("trace.persist_failed", error=str(exc))
            return ""

    async def _emit_langfuse(self) -> None:
        """Optional AI-trace sink. Absent keys are a no-op, not an error."""
        from jst_api.core.config import get_settings

        settings = get_settings()
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return
        try:  # pragma: no cover - requires a configured account
            from langfuse import Langfuse

            client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            trace = client.trace(id=self.trace_id, name=self.graph_name, metadata=self.summary())
            for span in self.spans:
                trace.span(name=span.name, metadata=span.to_dict())
            client.flush()
        except Exception as exc:
            log.warning("trace.langfuse_failed", error=str(exc))
