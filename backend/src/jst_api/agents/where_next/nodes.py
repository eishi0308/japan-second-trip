"""WhereNext graph nodes.

Each node is a ``state -> partial state`` coroutine closing over an
``AgentContext``. The division of labour is the whole design:

* deterministic nodes (``apply_hard_constraints``) decide what is *true*;
* tool nodes (``call_travel_tools``) fetch *real numbers* through MCP;
* retrieval nodes gather *grounded prose*;
* exactly one node (``compare_candidates``) calls a model, and only to explain
  what the earlier nodes already established.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from jst_api.agents.common.guardrails import run_guardrails
from jst_api.agents.common.state import AgentContext, WhereNextState
from jst_api.core.logging import get_logger
from jst_api.db.models import Region
from jst_api.db.repositories.evidence_repo import EvidenceFilters
from jst_api.domain.enums import (
    AnalysisStatus,
    ConfidenceState,
    EvidenceTopic,
    FitLabel,
    TrustLevel,
)
from jst_api.domain.evidence import EvidenceChunk as DomainEvidence
from jst_api.domain.geo import LatLon
from jst_api.domain.region import GatewayAccess, RegionProfile, SeasonalProfile
from jst_api.domain.results import ComparisonOutput
from jst_api.domain.scoring import WEIGHTS, rank_regions
from jst_api.domain.trip import TripContext, TripMemory
from jst_api.knowledge.context import assemble_evidence_context, compact_memory
from jst_api.knowledge.rag import EvidencePipeline, RetrievalRequest
from jst_api.knowledge.rerank import build_reranker
from jst_api.knowledge.retrievers import document_to_domain
from jst_api.providers.llm import TaskClass, complete_with_repair, structured_block
from jst_api.security.injection import sanitise_user_text

log = get_logger(__name__)

#: How many regions are explained in full. The rest are still returned, with
#: their deterministic score and rejection reason, but do not consume context.
MAX_EXPLAINED = 4


def region_from_row(row: Region) -> RegionProfile:
    return RegionProfile(
        code=row.code,
        name=row.name,
        tagline=row.tagline,
        prefectures=list(row.prefectures or []),
        hub_place_slug=row.hub_place_slug,
        centroid=LatLon(row.lat, row.lon),
        gateways={k: GatewayAccess(**v) for k, v in (row.gateways or {}).items()},
        min_recommended_nights=row.min_recommended_nights,
        ideal_nights=row.ideal_nights,
        max_useful_nights=row.max_useful_nights,
        public_transport_score=row.public_transport_score,
        car_free_possible=row.car_free_possible,
        car_recommended=row.car_recommended,
        car_required_highlights=list(row.car_required_highlights or []),
        interest_strength={k: float(v) for k, v in (row.interest_strength or {}).items()},
        seasonal=SeasonalProfile(
            month_scores={
                int(k): float(v) for k, v in (row.seasonal or {}).get("month_scores", {}).items()
            },
            notes={int(k): v for k, v in (row.seasonal or {}).get("notes", {}).items()},
        ),
        booking_complexity=row.booking_complexity,
        luggage_friendliness=row.luggage_friendliness,
        step_free_score=row.step_free_score,
        typical_daily_cost_jpy=dict(row.typical_daily_cost_jpy or {}),
        overlaps_with_visited=list(row.overlaps_with_visited or []),
        is_demo=row.is_demo,
    )


# ---------------------------------------------------------------------------
# 1. parse_trip_context
# ---------------------------------------------------------------------------
def make_parse_trip_context(ctx: AgentContext):
    async def parse_trip_context(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("parse_trip_context")
        ctx.tools.current_node = "parse_trip_context"
        raw = dict(state.get("raw_input") or {})

        # Free text is untrusted: neutralise instruction-shaped content before it
        # can reach any prompt.
        assumptions: list[str] = []
        if raw.get("free_text"):
            cleaned, scan = sanitise_user_text(str(raw["free_text"]))
            raw["free_text"] = cleaned
            if scan.suspicious:
                log.warning("where_next.user_text_injection_flagged", rules=scan.matched_rules)
                assumptions.append(
                    "Instruction-like text in your notes was treated as description, not as a command."
                )

        trip = TripContext.model_validate(raw)
        missing = trip.missing_fields()
        if trip.regional_nights is None:
            assumptions.append(
                f"No regional-nights figure given; assumed {trip.effective_regional_nights} nights for the side trip."
            )
        if trip.month is None:
            assumptions.append("No travel dates given; seasonal suitability uses a neutral prior.")
        if trip.driving is None:
            assumptions.append(
                "Driving preference unknown; scored as a mixed public-transport/car trip."
            )

        return {
            "trip_context": trip.model_dump(mode="json"),
            "visited_places": sorted(trip.visited_normalised),
            "missing_information": missing,
            "assumptions": assumptions,
            "status": AnalysisStatus.RUNNING.value,
        }

    return parse_trip_context


# ---------------------------------------------------------------------------
# 2. load_memory
# ---------------------------------------------------------------------------
def make_load_memory(ctx: AgentContext):
    async def load_memory(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("load_memory")
        ctx.tools.current_node = "load_memory"
        trip_id = state.get("trip_id")
        if not trip_id:
            return {"memory": {}, "previously_rejected": {}}

        data = await ctx.tools.call_optional("get_trip_context", {"trip_id": trip_id})
        if not data or not data.get("found"):
            return {"memory": {}, "previously_rejected": {}}

        memory = TripMemory(
            trip_id=trip_id,
            visited=data.get("visited", []),
            candidate_region=data.get("candidate_region"),
            rejected_regions=data.get("rejected_regions", {}),
            confirmed_preferences=data.get("confirmed_preferences", {}),
            verified_warnings=data.get("verified_warnings", []),
            decisions=data.get("decisions", []),
        )
        merged_visited = sorted(
            {*state.get("visited_places", []), *[v.lower() for v in memory.visited]}
        )
        return {
            "memory": memory.model_dump(mode="json"),
            "previously_rejected": memory.rejected_regions,
            "visited_places": merged_visited,
        }

    return load_memory


# ---------------------------------------------------------------------------
# 3. retrieve_region_candidates
# ---------------------------------------------------------------------------
def make_retrieve_region_candidates(ctx: AgentContext):
    async def retrieve_region_candidates(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("retrieve_region_candidates")
        ctx.tools.current_node = "retrieve_region_candidates"
        async with ctx.session_factory() as session:
            rows = list((await session.scalars(select(Region))).all())
        profiles = [region_from_row(r) for r in rows]
        log.info("where_next.candidates_loaded", count=len(profiles))
        return {
            "structured_facts": {
                "region_codes": [p.code for p in profiles],
                "regions": [p.model_dump(mode="json") for p in profiles],
            }
        }

    return retrieve_region_candidates


# ---------------------------------------------------------------------------
# 4. apply_hard_constraints  (deterministic — the actual ranking)
# ---------------------------------------------------------------------------
def make_apply_hard_constraints(ctx: AgentContext):
    async def apply_hard_constraints(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("apply_hard_constraints")
        ctx.tools.current_node = "apply_hard_constraints"
        trip = TripContext.model_validate(state["trip_context"])
        raw_regions: list[dict[str, Any]] = state["structured_facts"]["regions"]
        profiles = [RegionProfile.model_validate(r) for r in raw_regions]
        previously_rejected = state.get("previously_rejected") or {}

        scores = rank_regions(profiles, trip)
        by_code = {p.code: p for p in profiles}

        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        failures: dict[str, list[dict[str, Any]]] = {}

        for score in scores:
            profile = by_code[score.region_code]
            entry: dict[str, Any] = {
                "region_code": profile.code,
                "region_name": profile.name,
                "tagline": profile.tagline,
                "score": score.score,
                "fit_label": score.label.value,
                "eliminated": score.eliminated,
                "transit_share": score.transit_share,
                "round_trip_hours": score.round_trip_hours,
                "car_required": trip.public_transport_only and not profile.car_free_possible,
                "public_transport_viable": profile.car_free_possible
                and profile.public_transport_score >= 0.5,
                "booking_complexity": profile.booking_complexity,
                "seasonal_note": profile.seasonal.note_for(trip.month),
                "hub_place_slug": profile.hub_place_slug,
                "is_demo": profile.is_demo,
                "components": [
                    {
                        "name": c.name,
                        "value": c.value,
                        "weight": c.weight,
                        "contribution": round(c.contribution, 2),
                        "explanation": c.explanation,
                    }
                    for c in score.components
                ],
                "hard_failures": [
                    {"code": h.code, "explanation": h.explanation} for h in score.hard_failures
                ],
            }
            failures[profile.code] = entry["hard_failures"]

            if profile.code in previously_rejected:
                entry["previously_rejected_reason"] = previously_rejected[profile.code]
                rejected.append(entry)
            elif score.eliminated:
                rejected.append(entry)
            else:
                candidates.append(entry)

        log.info(
            "where_next.scored",
            candidates=len(candidates),
            rejected=len(rejected),
            top=candidates[0]["region_code"] if candidates else None,
        )
        warnings: list[str] = []
        if not candidates:
            warnings.append(
                "Every seeded region failed a hard constraint for this trip. The strongest near-misses are "
                "reported with the specific constraint each one failed."
            )
        return {
            "candidate_regions": candidates,
            "rejected_regions": rejected,
            "hard_constraint_failures": failures,
            "warnings": warnings,
            "constraints": [
                f"rubric_weights={WEIGHTS}",
                f"regional_nights={trip.effective_regional_nights}",
                f"public_transport_only={trip.public_transport_only}",
            ],
        }

    return apply_hard_constraints


# ---------------------------------------------------------------------------
# 5. call_travel_tools
# ---------------------------------------------------------------------------
def make_call_travel_tools(ctx: AgentContext):
    async def call_travel_tools(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("call_travel_tools")
        ctx.tools.current_node = "call_travel_tools"
        trip = TripContext.model_validate(state["trip_context"])
        shortlist = (state.get("candidate_regions") or [])[:MAX_EXPLAINED]
        if not shortlist:
            shortlist = (state.get("rejected_regions") or [])[:2]

        results: dict[str, Any] = {"transport": {}, "weather": {}, "booking": {}}
        arrival = trip.arrival_city or "Tokyo"

        for entry in shortlist:
            hub = entry["hub_place_slug"]
            transport = await ctx.tools.call_optional(
                "search_transport",
                {
                    "from_place": arrival,
                    "to_place": hub,
                    "allow_car": not trip.public_transport_only,
                },
            )
            if transport and transport.get("resolved"):
                results["transport"][entry["region_code"]] = {
                    "from": transport["from_slug"],
                    "to": transport["to_slug"],
                    "best_public": transport.get("best_public_option"),
                    "option_count": len(transport.get("options", [])),
                }

            if trip.month:
                weather = await ctx.tools.call_optional(
                    "get_weather_context", {"place_slug": hub, "month": trip.month}
                )
                if weather and weather.get("resolved"):
                    results["weather"][entry["region_code"]] = {
                        "summary": weather.get("summary"),
                        "snow_likely": weather.get("snow_likely"),
                    }

            booking = await ctx.tools.call_optional(
                "get_booking_requirements", {"place_slugs": [hub], "month": trip.month}
            )
            if booking:
                results["booking"][entry["region_code"]] = {
                    "max_lead_time_days": booking.get("max_lead_time_days"),
                    "english_booking_gaps": booking.get("english_booking_gaps", []),
                    "closed_in_month": booking.get("closed_in_month", []),
                }

        return {"tool_results": results}

    return call_travel_tools


# ---------------------------------------------------------------------------
# 6. retrieve_verified_evidence
# ---------------------------------------------------------------------------
def make_retrieve_verified_evidence(ctx: AgentContext):
    async def retrieve_verified_evidence(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("retrieve_verified_evidence")
        ctx.tools.current_node = "retrieve_verified_evidence"
        trip = TripContext.model_validate(state["trip_context"])
        shortlist = (state.get("candidate_regions") or [])[:MAX_EXPLAINED]
        if not shortlist:
            shortlist = (state.get("rejected_regions") or [])[:2]
        codes = [c["region_code"] for c in shortlist]
        if not codes:
            return {"retrieved_evidence": []}

        interests = ", ".join(i.value for i in trip.interests) or "food onsen nature"
        transport_clause = (
            "without a car using public transport"
            if trip.public_transport_only
            else "by train or car"
        )
        query = (
            f"regional Japan {interests} {transport_clause}, "
            f"{trip.effective_regional_nights} nights from {trip.arrival_city or 'Tokyo'}, access and booking constraints"
        )

        per_region: list[dict[str, Any]] = []
        for code in codes:
            data = await ctx.tools.call_optional(
                "search_verified_evidence",
                {
                    "query": query,
                    "region_codes": [code],
                    "month": trip.month,
                    "limit": 4,
                },
            )
            if not data:
                continue
            for item in data.get("evidence", []):
                item["_region_code"] = code
                per_region.append(item)

        ctx.trace.record_retrieval(
            query=query,
            strategy=ctx.settings.retrieval_strategy,
            evidence_ids=[e["evidence_id"] for e in per_region],
            latency_ms=0,
            regions=codes,
        )
        return {"retrieved_evidence": per_region}

    return retrieve_verified_evidence


# ---------------------------------------------------------------------------
# 7. rerank_evidence  (context assembly + budgeting)
# ---------------------------------------------------------------------------
def make_rerank_evidence(ctx: AgentContext):
    async def rerank_evidence(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("rerank_evidence")
        ctx.tools.current_node = "rerank_evidence"
        raw = state.get("retrieved_evidence") or []
        if not raw:
            return {
                "reranked_evidence": [],
                "evidence_block": "(no evidence retrieved)",
                "quarantined_evidence": [],
            }

        from langchain_core.documents import Document

        documents = [
            Document(
                id=e["evidence_id"],
                page_content=e.get("snippet", ""),
                metadata={
                    "evidence_id": e["evidence_id"],
                    "source_id": e["source_id"],
                    "source_title": e["source_title"],
                    "source_url": e.get("source_url"),
                    "source_type": e["source_type"],
                    "official_source": e.get("official_source", False),
                    "trust_level": e.get("trust_level", TrustLevel.SECONDARY.value),
                    "region_code": e.get("region_code") or e.get("_region_code"),
                    "place_slug": e.get("place_slug"),
                    "topic": e.get("topic", EvidenceTopic.GENERAL.value),
                    "verified_at": e.get("verified_at"),
                    "is_demo": e.get("is_demo", True),
                    "score": e.get("score", 0.0),
                    "fused_score": e.get("score", 0.0),
                },
            )
            for e in raw
        ]

        assembled = assemble_evidence_context(
            documents, token_budget=min(ctx.settings.context_token_budget // 2, 3000)
        )
        return {
            "reranked_evidence": [
                {
                    **document_to_domain(d).model_dump(mode="json"),
                    "region_code": d.metadata.get("region_code"),
                }
                for d in documents
                if d.metadata["evidence_id"] in set(assembled.audit.included_ids)
            ],
            "evidence_block": assembled.block,
            "quarantined_evidence": [
                {"evidence_id": e, "rules": r} for e, r in assembled.audit.quarantined
            ],
            "context_audit": assembled.audit.to_dict(),
        }

    return rerank_evidence


# ---------------------------------------------------------------------------
# 8. compare_candidates  (the one model call)
# ---------------------------------------------------------------------------
def make_compare_candidates(ctx: AgentContext):
    async def compare_candidates(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("compare_candidates")
        ctx.tools.current_node = "compare_candidates"
        trip = TripContext.model_validate(state["trip_context"])
        prompt = ctx.prompts.get("candidate_comparison")

        candidates = (state.get("candidate_regions") or [])[:MAX_EXPLAINED]
        rejected = (state.get("rejected_regions") or [])[:2]
        explained = [*candidates, *rejected]
        if not explained:
            return {
                "explanations": [],
                "unknowns": ["No region could be evaluated for this trip."],
                "analysis_gaps": [
                    "No region survived the hard constraints, so nothing was scored or compared."
                ],
            }

        evidence_by_region: dict[str, list[dict[str, Any]]] = {}
        for item in state.get("reranked_evidence") or []:
            evidence_by_region.setdefault(item.get("region_code") or "", []).append(item)

        tool_results = state.get("tool_results") or {}
        payload_candidates = []
        for entry in explained:
            code = entry["region_code"]
            payload_candidates.append(
                {
                    "region_code": code,
                    "region_name": entry["region_name"],
                    "score": entry["score"],
                    "fit_label": entry["fit_label"],
                    "components": entry["components"],
                    "hard_failures": entry["hard_failures"],
                    "transport": tool_results.get("transport", {}).get(code),
                    "weather": tool_results.get("weather", {}).get(code),
                    "booking": tool_results.get("booking", {}).get(code),
                    "evidence": [
                        {"evidence_id": e["evidence_id"], "summary": e["content"][:220]}
                        for e in evidence_by_region.get(code, [])[:4]
                    ],
                }
            )

        memory_block = compact_memory(
            TripMemory.model_validate(state["memory"]).to_prompt_block()
            if state.get("memory")
            else "No prior trip memory."
        )
        trip_summary = (
            f"{trip.effective_regional_nights} regional nights, in/out {trip.arrival_city or '?'}/"
            f"{trip.departure_city or '?'}, month {trip.month or 'unknown'}, "
            f"interests {', '.join(i.value for i in trip.interests) or 'unstated'}, "
            f"driving {trip.driving.value if trip.driving else 'unknown'}, "
            f"pace {trip.pace.value if trip.pace else 'unstated'}. Memory: {memory_block}"
        )

        payload = {
            "regional_nights": trip.effective_regional_nights,
            "arrival_city": trip.arrival_city,
            "candidates": payload_candidates,
            "unknowns": state.get("missing_information", []),
            "suggested_route": _suggest_route(candidates, tool_results),
        }
        user = (
            f"{prompt.render_user(trip_summary=trip_summary, evidence_block=state.get('evidence_block', ''))}\n\n"
            f"{structured_block(payload)}"
        )

        try:
            output, usages = await complete_with_repair(
                ctx.registry.llm,
                system=prompt.system,
                user=user,
                schema=ComparisonOutput,
                model=ctx.model_for(TaskClass.COMPARISON),
                repair_model=ctx.model_for(TaskClass.REPAIR),
            )
        except Exception as exc:
            log.warning("where_next.comparison_failed", error=str(exc)[:300])
            return {
                "explanations": [],
                "node_errors": [f"compare_candidates: {exc}"],
                "unknowns": [
                    "The explanation model failed; only the deterministic ranking is available."
                ],
            }

        for usage in usages:
            ctx.trace.record_usage(usage, prompt=prompt.label)

        suggested = None
        if output.suggested_route_stops:
            suggested = {
                "region_code": candidates[0]["region_code"] if candidates else None,
                "summary": output.suggested_route_summary or "",
                "stops": output.suggested_route_stops,
                "nights": output.suggested_route_nights,
            }
        return {
            "explanations": [e.model_dump(mode="json") for e in output.explanations],
            "suggested_route": suggested,
            "unknowns": output.unknowns,
        }

    return compare_candidates


def _suggest_route(
    candidates: list[dict[str, Any]], tool_results: dict[str, Any]
) -> dict[str, Any] | None:
    """A skeletal route for the top region, built from structured data only.

    Stops and nights come from the region profile's hub and the deterministic
    night allocation; the model may only describe it, never extend it.
    """
    if not candidates:
        return None
    top = candidates[0]
    transport = (tool_results.get("transport") or {}).get(top["region_code"]) or {}
    return {
        "region_code": top["region_code"],
        "hub": top["hub_place_slug"],
        "summary": (
            f"Base in {top['hub_place_slug'].replace('-', ' ').title()} and day-trip outward; "
            f"{transport.get('best_public', {}).get('duration_minutes', '?')} minutes from your arrival city."
            if transport.get("best_public")
            else f"Base in {top['hub_place_slug'].replace('-', ' ').title()} and day-trip outward."
        ),
        "stops": [],
        "nights": [],
    }


# ---------------------------------------------------------------------------
# 9. grounding_check
# ---------------------------------------------------------------------------
def make_grounding_check(ctx: AgentContext):
    async def grounding_check(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("grounding_check")
        ctx.tools.current_node = "grounding_check"

        evidence = [
            DomainEvidence.model_validate(_strip(e)) for e in state.get("reranked_evidence") or []
        ]
        explanations = state.get("explanations") or []
        prose: list[str] = []
        cited: list[str] = []
        for item in explanations:
            prose.append(item.get("headline", ""))
            prose.extend(item.get("reasons", []))
            prose.extend(item.get("tradeoffs", []))
            prose.extend(item.get("rejected_reasons", []))
            cited.extend(item.get("evidence_ids", []))

        deterministic_values: list[str] = []
        for entry in [
            *(state.get("candidate_regions") or []),
            *(state.get("rejected_regions") or []),
        ]:
            deterministic_values.append(str(entry["score"]))
            deterministic_values.append(str(entry["round_trip_hours"]))
            deterministic_values.extend(c["explanation"] for c in entry["components"])
            deterministic_values.extend(h["explanation"] for h in entry["hard_failures"])
        for group in (state.get("tool_results") or {}).values():
            deterministic_values.append(str(group))

        relevant_slugs = {
            entry["hub_place_slug"]
            for entry in [
                *(state.get("candidate_regions") or []),
                *(state.get("rejected_regions") or []),
            ]
        }
        conflicts = await _detect_conflicts(
            ctx,
            relevant_slugs=relevant_slugs,
            evidence_ids={e.evidence_id for e in evidence},
        )
        # A conflict blocks the answer only when the answer *leans on* it. A
        # region recommendation does not assert a shuttle departure time, so a
        # dispute about one is a caveat to surface, not a reason to stop. The
        # same conflict does block RouteCheck, whose route runs through that stop.
        blocking = [c for c in conflicts if set(c["evidence_ids"]) & set(cited)]
        report = run_guardrails(
            prose_blocks=[p for p in prose if p],
            cited_ids=cited,
            evidence=evidence,
            deterministic_values=deterministic_values,
            quarantined=[
                (q["evidence_id"], q["rules"]) for q in state.get("quarantined_evidence") or []
            ],
            min_evidence=ctx.settings.min_evidence_for_confident_answer,
            conflicts_detected=bool(blocking),
            analysis_gaps=state.get("analysis_gaps") or [],
        )
        return {"guardrail_report": report.to_dict(), "conflicts": conflicts}

    return grounding_check


def _strip(evidence: dict[str, Any]) -> dict[str, Any]:
    out = dict(evidence)
    out.pop("region_code_extra", None)
    return out


async def _detect_conflicts(
    ctx: AgentContext, *, relevant_slugs: set[str], evidence_ids: set[str]
) -> list[dict[str, Any]]:
    """Only conflicts this analysis actually depends on.

    A globally open conflict about a place nobody mentioned is a queue item for
    the admin, not a reason to hold up this traveller's answer. A conflict is
    relevant when its subject names one of this route's places, or when it cites
    a piece of evidence that entered this analysis's context.
    """
    data = await ctx.tools.call_optional("get_verification_status", {"limit": 40})
    if not data:
        return []
    relevant: list[dict[str, Any]] = []
    for c in data.get("conflicts", []):
        subject = str(c.get("subject", ""))
        subject_slug = subject.split(":", 1)[0].strip().lower()
        cited = set(c.get("evidence_ids", []))
        if subject_slug in relevant_slugs or (cited & evidence_ids):
            relevant.append(
                {
                    "field_name": c.get("field_name", ""),
                    "subject": subject,
                    "values": c.get("values", []),
                    "evidence_ids": c.get("evidence_ids", []),
                    "open_review_task_id": c.get("open_review_task_id"),
                }
            )
    return relevant


# ---------------------------------------------------------------------------
# 10. confidence_check (routing) / 11. human_review / 12. answer
# ---------------------------------------------------------------------------
def make_confidence_check(ctx: AgentContext):
    async def confidence_check(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("confidence_check")
        report = state.get("guardrail_report") or {}
        confidence = report.get("confidence", ConfidenceState.MEDIUM.value)
        needs_review = bool(report.get("human_review_required"))
        return {
            "confidence": confidence,
            "human_review_required": needs_review,
            "status": (
                AnalysisStatus.NEEDS_HUMAN_REVIEW.value
                if needs_review
                else AnalysisStatus.COMPLETE.value
            ),
        }

    return confidence_check


def route_after_confidence(state: WhereNextState) -> str:
    return "human_review" if state.get("human_review_required") else "answer"


def make_human_review(ctx: AgentContext):
    async def human_review(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("human_review")
        ctx.tools.current_node = "human_review"
        report = state.get("guardrail_report") or {}
        reason = report.get("review_reason") or "low_confidence"
        conflicts = state.get("conflicts") or []

        if conflicts:
            conflict = conflicts[0]
            subject = conflict["subject"]
            field_name = conflict["field_name"]
            question = (
                f"Sources disagree on {field_name or 'this fact'} for {subject}: "
                f"{', '.join(conflict['values'])}. Confirm the correct value with the operator before this is "
                "shown to a traveller."
            )
            candidate_values = conflict["values"]
            evidence_ids = conflict["evidence_ids"]
        else:
            subject = "where_next:" + (
                (state.get("candidate_regions") or [{}])[0].get("region_code", "unknown")
            )
            field_name = None
            question = (
                "This recommendation did not meet the confidence bar. "
                f"Reason: {reason}. Findings: "
                + "; ".join(f["message"] for f in report.get("findings", [])[:4])
            )
            candidate_values = []
            evidence_ids = [e["evidence_id"] for e in state.get("reranked_evidence") or []][:10]

        created = await ctx.tools.call_optional(
            "create_human_review_request",
            {
                "reason": reason,
                "subject": subject,
                "question": question,
                "field_name": field_name,
                "candidate_values": candidate_values,
                "evidence_ids": evidence_ids,
                "analysis_id": state.get("analysis_id"),
                "thread_id": state.get("thread_id"),
                "priority": "high" if conflicts else "normal",
            },
        )
        task_id = created.get("task_id") if created else None

        if ctx.interactive:
            # LangGraph interrupt/resume: the graph pauses here and the caller
            # resumes with the reviewer's answer. Used by the interactive runner
            # and the HITL tests.
            from langgraph.types import interrupt

            resolution = interrupt(
                {
                    "task_id": task_id,
                    "reason": reason,
                    "subject": subject,
                    "question": question,
                    "candidate_values": candidate_values,
                }
            )
            return {"human_review_task_id": task_id, "human_resolution": resolution}

        # Non-interactive (the API path): the answer is produced now, clearly
        # marked as pending review, and the reviewer's resolution re-runs the
        # analysis later. A reviewer may take days; holding a process open is not
        # a design, it is a leak.
        return {"human_review_task_id": task_id}

    return human_review


def make_answer(ctx: AgentContext):
    async def answer(state: WhereNextState) -> dict[str, Any]:
        ctx.trace.enter_node("answer")
        ctx.tools.current_node = "answer"
        TripContext.model_validate(state["trip_context"])
        explanations = {e["region_code"]: e for e in state.get("explanations") or []}
        evidence_by_id = {e["evidence_id"]: e for e in state.get("reranked_evidence") or []}
        report = state.get("guardrail_report") or {}
        stripped = set(report.get("stripped_claims") or [])

        def build(entry: dict[str, Any], rank: int) -> dict[str, Any]:
            explanation = explanations.get(entry["region_code"], {})

            # Guardrails already flagged unsupported literals; drop the sentences
            # that carry them rather than shipping an unsupported claim.
            def clean(items: list[str]) -> list[str]:
                return [s for s in items if not any(bad in s for bad in stripped)]

            evidence_ids = [i for i in explanation.get("evidence_ids", []) if i in evidence_by_id]
            citations = [
                DomainEvidence.model_validate(_strip(evidence_by_id[i]))
                .citation()
                .model_dump(mode="json")
                for i in evidence_ids
            ]
            return {
                "region_code": entry["region_code"],
                "region_name": entry["region_name"],
                "rank": rank,
                "fit_label": entry["fit_label"],
                "deterministic_score": entry["score"],
                "score_components": entry["components"],
                "headline": explanation.get("headline")
                or f"{entry['region_name']} — {entry['fit_label']}",
                "reasons": clean(explanation.get("reasons", [])),
                "tradeoffs": clean(explanation.get("tradeoffs", [])),
                "rejected_reasons": clean(explanation.get("rejected_reasons", []))
                or [h["explanation"] for h in entry["hard_failures"]],
                "round_trip_transfer_hours": entry["round_trip_hours"],
                "transit_share": entry["transit_share"],
                "car_required": entry["car_required"],
                "public_transport_viable": entry["public_transport_viable"],
                "booking_complexity": entry["booking_complexity"],
                "seasonal_note": entry["seasonal_note"],
                "evidence_ids": evidence_ids,
                "citations": citations,
                "confidence": state.get("confidence", ConfidenceState.MEDIUM.value),
                "is_demo_data": entry.get("is_demo", True),
            }

        candidates = state.get("candidate_regions") or []
        rejected = state.get("rejected_regions") or []
        ranked = [build(c, i + 1) for i, c in enumerate(candidates)]
        rejected_out = [build(r, len(ranked) + i + 1) for i, r in enumerate(rejected)]

        all_citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*ranked, *rejected_out]:
            for citation in item["citations"]:
                if citation["evidence_id"] not in seen:
                    seen.add(citation["evidence_id"])
                    all_citations.append(citation)

        result = {
            "analysis_id": state["analysis_id"],
            "trip_id": state.get("trip_id"),
            "status": state.get("status", AnalysisStatus.COMPLETE.value),
            "recommended": ranked[0] if ranked else None,
            "alternatives": ranked[1:MAX_EXPLAINED],
            "rejected": rejected_out,
            "suggested_route": _final_route(state),
            # All three are ``operator.add`` accumulators several nodes write to,
            # and the comparison prompt is handed the state unknowns, so a model
            # echoing one back would show it twice. Order carries meaning, so
            # dedupe with ``dict.fromkeys`` rather than a set.
            "assumptions": list(dict.fromkeys(state.get("assumptions", []))),
            "missing_information": list(dict.fromkeys(state.get("missing_information", []))),
            "unknowns": list(dict.fromkeys(state.get("unknowns", []))),
            "conflicts": [
                {
                    "field_name": c["field_name"],
                    "subject": c["subject"],
                    "values": c["values"],
                    "evidence_ids": c["evidence_ids"],
                }
                for c in state.get("conflicts") or []
            ],
            "confidence": state.get("confidence", ConfidenceState.MEDIUM.value),
            "human_review_required": bool(state.get("human_review_required")),
            "human_review_task_id": state.get("human_review_task_id"),
            "citations": all_citations,
            "demo_mode": ctx.registry.any_demo,
            "scoring_rubric_version": "1.0.0",
            "prompt_versions": ctx.trace.prompt_versions,
        }
        return {"result": result, "status": result["status"]}

    return answer


def _final_route(state: WhereNextState) -> dict[str, Any] | None:
    suggested = state.get("suggested_route")
    if not suggested:
        return None
    return {
        "region_code": suggested.get("region_code") or "",
        "summary": suggested.get("summary", ""),
        "stops": suggested.get("stops", []),
        "nights": suggested.get("nights", []),
        "rationale": suggested.get("summary", ""),
        "evidence_ids": [],
    }


__all__ = [
    "EvidenceFilters",
    "EvidencePipeline",
    "FitLabel",
    "RetrievalRequest",
    "build_reranker",
    "make_answer",
    "make_apply_hard_constraints",
    "make_call_travel_tools",
    "make_compare_candidates",
    "make_confidence_check",
    "make_grounding_check",
    "make_human_review",
    "make_load_memory",
    "make_parse_trip_context",
    "make_rerank_evidence",
    "make_retrieve_region_candidates",
    "make_retrieve_verified_evidence",
    "region_from_row",
    "route_after_confidence",
]
