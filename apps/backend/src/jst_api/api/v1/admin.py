"""Admin surface: sources, ingestion, verification queue, inspectors, evals.

Every route here requires an admin bearer token. Ingestion additionally requires
an explicit ``terms_confirmed`` assertion from the operator and validates the URL
against the domain allowlist before a single byte is fetched.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from jst_api.api.deps import (
    AdminDep,
    AnalysisDep,
    RegistryDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from jst_api.api.schemas import AdminAssistantIn, ReviewResolveIn, SourceCreateIn
from jst_api.core.errors import NotFoundError, ValidationFailedError
from jst_api.db.models import (
    AgentRun,
    Analysis,
    EvalRun,
    EvidenceChunk,
    Source,
    ToolCall,
)
from jst_api.domain.enums import EvidenceTopic, SourceType, TrustLevel
from jst_api.knowledge.embeddings import ProviderEmbeddings
from jst_api.knowledge.ingest import IngestionService
from jst_api.observability.metrics import METRICS
from jst_api.prompts.registry import get_prompts
from jst_api.security.allowlist import assert_ingestable
from jst_api.services.review_service import ReviewService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[])


# ---------------------------------------------------------------------------
# sources + ingestion
# ---------------------------------------------------------------------------
@router.get("/sources")
async def list_sources(
    _admin: AdminDep, session: SessionDep, limit: int = Query(default=100, le=500)
) -> dict[str, Any]:
    rows = list(
        (await session.scalars(select(Source).order_by(desc(Source.created_at)).limit(limit))).all()
    )
    counts = {
        r[0]: r[1]
        for r in (
            await session.execute(
                select(EvidenceChunk.source_id, func.count()).group_by(EvidenceChunk.source_id)
            )
        ).all()
    }
    return {
        "sources": [
            {
                "id": s.id,
                "title": s.title,
                "url": s.url,
                "domain": s.domain,
                "source_type": s.source_type,
                "official_source": s.official_source,
                "trust_level": s.trust_level,
                "region_code": s.region_code,
                "place_slug": s.place_slug,
                "status": s.status,
                "is_demo": s.is_demo,
                "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
                "verified_at": s.verified_at.isoformat() if s.verified_at else None,
                "content_hash": s.content_hash,
                "chunk_count": counts.get(s.id, 0),
            }
            for s in rows
        ],
        "total": len(rows),
    }


@router.post("/sources", status_code=201)
async def create_source(
    payload: SourceCreateIn,
    _admin: AdminDep,
    session: SessionDep,
    registry: RegistryDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    if not payload.url and not payload.text:
        raise ValidationFailedError("Provide either a url or text to ingest")
    if payload.url:
        if not payload.terms_confirmed:
            raise ValidationFailedError(
                "terms_confirmed must be true: the operator asserts this source's terms permit ingestion"
            )
        # Raises IngestionNotAllowed (403) before anything is fetched.
        assert_ingestable(payload.url, settings.ingest_domain_allowlist)

    service = IngestionService(session, ProviderEmbeddings(registry.embeddings), settings)
    if payload.url:
        result = await service.ingest_url(
            payload.url,
            source_type=SourceType(payload.source_type),
            region_code=payload.region_code,
            place_slug=payload.place_slug,
            trust_level=TrustLevel(payload.trust_level),
            official_source=payload.official_source,
            title=payload.title,
        )
    else:
        result = await service.ingest_text(
            payload.text or "",
            title=payload.title,
            source_type=SourceType(payload.source_type),
            region_code=payload.region_code,
            place_slug=payload.place_slug,
            trust_level=TrustLevel(payload.trust_level),
            official_source=payload.official_source,
            topic=EvidenceTopic(payload.topic),
            is_demo=False,
        )
    return result.to_dict()


@router.post("/sources/{source_id}/refresh")
async def refresh_source(
    source_id: str,
    _admin: AdminDep,
    session: SessionDep,
    registry: RegistryDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    service = IngestionService(session, ProviderEmbeddings(registry.embeddings), settings)
    result = await service.refresh_source(source_id)
    return result.to_dict()


@router.get("/allowlist")
async def get_allowlist(_admin: AdminDep, settings: SettingsDep) -> dict[str, Any]:
    return {"domains": settings.ingest_domain_allowlist}


# ---------------------------------------------------------------------------
# verification queue
# ---------------------------------------------------------------------------
@router.get("/reviews")
async def list_reviews(
    _admin: AdminDep,
    session: SessionDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    service = ReviewService(session)
    tasks = await service.list_open(status=status, limit=limit)
    return {
        "reviews": [
            {
                "id": t.id,
                "reason": t.reason,
                "subject": t.subject,
                "field_name": t.field_name,
                "question": t.question,
                "candidate_values": list(t.candidate_values or []),
                "evidence_ids": list(t.evidence_ids or []),
                "status": t.status,
                "priority": t.priority,
                "analysis_id": t.analysis_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "resolved_value": t.resolved_value,
                "resolved_by": t.resolved_by,
                "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
                "resumed": t.resumed,
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.post("/reviews/{task_id}/resolve")
async def resolve_review(
    task_id: str,
    payload: ReviewResolveIn,
    _admin: AdminDep,
    session: SessionDep,
    analysis_service: AnalysisDep,
) -> dict[str, Any]:
    service = ReviewService(session, analysis_service)
    outcome = await service.resolve(
        task_id,
        resolved_value=payload.resolved_value,
        resolution_note=payload.resolution_note,
        reviewer=payload.reviewer,
        source_url=payload.source_url,
        dismiss=payload.dismiss,
    )
    return {
        "task_id": outcome.task_id,
        "status": outcome.status,
        "verification_id": outcome.verification_id,
        "resumed": outcome.resumed,
        "resumed_analysis_id": outcome.resumed_analysis_id,
        "message": outcome.message,
    }


@router.get("/verification/queue")
async def verification_queue(_admin: AdminDep, session: SessionDep) -> dict[str, Any]:
    return await ReviewService(session).stale_and_conflicting()


# ---------------------------------------------------------------------------
# assistant (third MCP consumer)
# ---------------------------------------------------------------------------
@router.post("/assistant")
async def admin_assistant(
    payload: AdminAssistantIn,
    _admin: AdminDep,
    registry: RegistryDep,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
) -> dict[str, Any]:
    from jst_api.agents.admin_assistant import AdminAssistant

    assistant = AdminAssistant(session_factory, registry, get_prompts(), settings)
    return await assistant.ask(payload.request, region_code=payload.region_code)


# ---------------------------------------------------------------------------
# inspectors
# ---------------------------------------------------------------------------
@router.get("/runs")
async def list_runs(
    _admin: AdminDep, session: SessionDep, limit: int = Query(default=50, le=200)
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(select(AgentRun).order_by(desc(AgentRun.created_at)).limit(limit))
        ).all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "analysis_id": r.analysis_id,
                "graph_name": r.graph_name,
                "thread_id": r.thread_id,
                "status": r.status,
                "node_path": list(r.node_path or []),
                "step_count": r.step_count,
                "latency_ms": r.latency_ms,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "estimated_cost_usd": r.estimated_cost_usd,
                "model_calls": r.model_calls,
                "retries": r.retries,
                "fallbacks_used": list(r.fallbacks_used or []),
                "trace_id": r.trace_id,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, _admin: AdminDep, session: SessionDep) -> dict[str, Any]:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found", details={"run_id": run_id})
    calls = list((await session.scalars(select(ToolCall).where(ToolCall.run_id == run_id))).all())
    analysis = await session.get(Analysis, run.analysis_id) if run.analysis_id else None
    return {
        "run": {
            "id": run.id,
            "graph_name": run.graph_name,
            "status": run.status,
            "node_path": list(run.node_path or []),
            "latency_ms": run.latency_ms,
            "estimated_cost_usd": run.estimated_cost_usd,
            "prompt_tokens": run.prompt_tokens,
            "completion_tokens": run.completion_tokens,
            "fallbacks_used": list(run.fallbacks_used or []),
            "error": run.error,
        },
        "tool_calls": [
            {
                "id": c.id,
                "node": c.node,
                "tool_name": c.tool_name,
                "transport": c.transport,
                "arguments": c.arguments,
                "result_summary": c.result_summary,
                "ok": c.ok,
                "error": c.error,
                "latency_ms": c.latency_ms,
                "attempts": c.attempts,
                "cache_hit": c.cache_hit,
            }
            for c in calls
        ],
        "analysis": {
            "id": analysis.id,
            "kind": analysis.kind,
            "status": analysis.status,
            "confidence": analysis.confidence,
            "evidence_ids": list(analysis.evidence_ids or []),
            "prompt_versions": dict(analysis.prompt_versions or {}),
        }
        if analysis
        else None,
    }


@router.get("/tool-calls/failed")
async def failed_tool_calls(
    _admin: AdminDep, session: SessionDep, limit: int = Query(default=50, le=200)
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(
                select(ToolCall)
                .where(ToolCall.ok.is_(False))
                .order_by(desc(ToolCall.created_at))
                .limit(limit)
            )
        ).all()
    )
    return {
        "failed": [
            {
                "id": c.id,
                "run_id": c.run_id,
                "tool_name": c.tool_name,
                "node": c.node,
                "error": c.error,
                "attempts": c.attempts,
                "latency_ms": c.latency_ms,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ]
    }


@router.get("/evidence/stale")
async def stale_evidence(
    _admin: AdminDep, session: SessionDep, days: int = Query(default=180, ge=1, le=2000)
) -> dict[str, Any]:
    from jst_api.db.repositories.evidence_repo import EvidenceRepository

    rows = await EvidenceRepository(session).stale_evidence(older_than_days=days, limit=100)
    return {
        "stale": [
            {
                "evidence_id": c.id,
                "source_id": s.id,
                "source_title": s.title,
                "topic": c.topic,
                "region_code": c.region_code,
                "verified_at": c.verified_at.isoformat() if c.verified_at else None,
                "snippet": c.content[:200],
            }
            for c, s in rows
        ],
        "threshold_days": days,
    }


@router.get("/metrics")
async def metrics(_admin: AdminDep) -> dict[str, Any]:
    return METRICS.snapshot()


@router.get("/prompts")
async def prompt_versions(_admin: AdminDep) -> dict[str, Any]:
    registry = get_prompts()
    return {
        "prompts": [
            {
                "id": p.id,
                "version": p.version,
                "task_class": p.task_class,
                "description": p.description,
            }
            for p in registry.all()
        ]
    }


@router.get("/evals")
async def eval_runs(
    _admin: AdminDep, session: SessionDep, limit: int = Query(default=25, le=100)
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(select(EvalRun).order_by(desc(EvalRun.created_at)).limit(limit))
        ).all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "suite": r.suite,
                "dataset": r.dataset,
                "dataset_version": r.dataset_version,
                "variant": r.variant,
                "metrics": r.metrics,
                "case_count": r.case_count,
                "passed": r.passed,
                "failed": r.failed,
                "duration_ms": r.duration_ms,
                "git_sha": r.git_sha,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
