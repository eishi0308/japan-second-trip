"""Eval datasets and run history stored alongside the app.

Keeping eval results in the operational database (rather than only in files)
means the admin dashboard can show retrieval quality trending over time and a
CI run can compare against the previous baseline.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jst_api.db.base import Base, TimestampMixin, id_column
from jst_api.db.types import JSONBCompat


class EvalCase(Base, TimestampMixin):
    __tablename__ = "eval_cases"

    id: Mapped[str] = id_column("ec")
    dataset: Mapped[str] = mapped_column(String(60), index=True)
    case_key: Mapped[str] = mapped_column(String(120), index=True)
    suite: Mapped[str] = mapped_column(String(40), index=True)
    """retrieval | rag | tool | agent | security"""
    query: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    expected: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    tags: Mapped[list] = mapped_column(JSONBCompat, default=list)
    dataset_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EvalRun(Base, TimestampMixin):
    __tablename__ = "eval_runs"

    id: Mapped[str] = id_column("er")
    suite: Mapped[str] = mapped_column(String(40), index=True)
    dataset: Mapped[str] = mapped_column(String(60))
    dataset_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    variant: Mapped[str] = mapped_column(String(60), default="default")
    """e.g. keyword_only | vector_only | hybrid | hybrid_rerank"""
    git_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prompt_versions: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list[EvalResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvalResult(Base, TimestampMixin):
    __tablename__ = "eval_results"

    id: Mapped[str] = id_column("erx")
    run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    case_key: Mapped[str] = mapped_column(String(120), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    metrics: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    detail: Mapped[dict] = mapped_column(JSONBCompat, default=dict)
    judge_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    judge_prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    run: Mapped[EvalRun] = relationship(back_populates="results")
