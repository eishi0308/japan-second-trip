"""Observability and human-in-the-loop tables.

Every analysis is replayable: which graph ran, which node produced what, which
tools were called with what arguments, which evidence was used, what it cost.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat


class Analysis(Base, TimestampMixin):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_trip_kind", "trip_id", "kind"),)

    id: Mapped[str] = id_column("an")
    trip_id: Mapped[str | None] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), index=True)
    """where_next | route_check"""
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    confidence: Mapped[str | None] = mapped_column(String(30), nullable=True)
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    input_payload: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    result_payload: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSONBCompat, default=list)
    prompt_versions: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    runs: Mapped[list[AgentRun]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = id_column("run")
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True, nullable=True
    )
    graph_name: Mapped[str] = mapped_column(String(60), index=True)
    thread_id: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    node_path: Mapped[list] = mapped_column(JSONBCompat, default=list)
    """Ordered list of node names actually executed — the agent-eval signal."""
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    fallbacks_used: Mapped[list] = mapped_column(JSONBCompat, default=list)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[Analysis | None] = relationship(back_populates="runs")
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_name_ok", "tool_name", "ok"),)

    id: Mapped[str] = id_column("tc")
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    node: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(80), index=True)
    transport: Mapped[str] = mapped_column(String(20), default="mcp")
    """mcp | local — records whether the capability crossed the MCP boundary."""
    arguments: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    """Redacted before persistence (see core/logging.redact_value)."""
    result_summary: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped[AgentRun | None] = relationship(back_populates="tool_calls")


class HumanReviewTask(Base, TimestampMixin):
    __tablename__ = "human_review_tasks"
    __table_args__ = (Index("ix_review_status_reason", "status", "reason"),)

    id: Mapped[str] = id_column("hr")
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), index=True, nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    thread_id: Mapped[str | None] = mapped_column(String(60), index=True, nullable=True)
    """LangGraph thread to resume once a human resolves this."""
    reason: Mapped[str] = mapped_column(String(50), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    field_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    candidate_values: Mapped[list] = mapped_column(JSONBCompat, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSONBCompat, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="normal")

    resolved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[str] = id_column("fb")
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True
    )
    trip_id: Mapped[str | None] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_inaccuracy: Mapped[bool] = mapped_column(Boolean, default=False)
