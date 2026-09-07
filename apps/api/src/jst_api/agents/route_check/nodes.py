"""RouteCheck graph nodes.

The critical property of this workflow: **the language model never decides
whether something is wrong.** It parses free text at the front, and writes prose
at the back. Everything between — place resolution, transport durations, rule
evaluation, severity grading, revision generation and revision costing — is
deterministic code and tool calls over verified data.

That is why the critique can be trusted and regression-tested.
"""

from __future__ import annotations

from typing import Any

from jst_api.agents.common.guardrails import run_guardrails
from jst_api.agents.common.state import AgentContext, RouteCheckState
from jst_api.core.logging import get_logger
from jst_api.domain.enums import (
    AnalysisStatus,
    ConfidenceState,
    EvidenceTopic,
    IssueType,
    RouteHealth,
    Severity,
    TrustLevel,
)
from jst_api.domain.evidence import EvidenceChunk as DomainEvidence
from jst_api.domain.results import CritiqueOutput, ExtractedItinerary
from jst_api.domain.revision import choose_best, generate_candidates
from jst_api.domain.route import Route, RouteSegment, RouteStop
from jst_api.domain.route_rules import RULES_VERSION
from jst_api.domain.trip import TripContext, TripMemory
from jst_api.knowledge.context import assemble_evidence_context, compact_memory
from jst_api.providers.llm import TaskClass, complete_with_repair, structured_block
from jst_api.security.injection import sanitise_user_text

log = get_logger(__name__)

MAX_STOPS = 15
MAX_REVISION_CANDIDATES = 8


def issue_key(issue: dict[str, Any]) -> str:
    """Stable per-issue identity.

    ``rule_id`` alone is not unique: R01_travel_burden fires once per offending
    hop. Keying narratives by rule id alone put the Ginzan→Aomori explanation on
    the Sendai→Ginzan warning — the same numbers attached to the wrong segment.
    """
    return f"{issue.get('rule_id', 'unknown')}::{issue.get('segment') or 'route'}"


"""Bounded because each candidate costs one deterministic tool call."""


# ---------------------------------------------------------------------------
# 1. parse_itinerary
# ---------------------------------------------------------------------------
def make_parse_itinerary(ctx: AgentContext):
    async def parse_itinerary(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("parse_itinerary")
        ctx.tools.current_node = "parse_itinerary"

        # Structured entry skips the model entirely — no reason to pay for, or
        # risk, an extraction the user already did for us.
        if state.get("raw_stops"):
            stops = [
                {
                    "name": str(s.get("name", "")).strip()[:100],
                    "nights": int(s.get("nights", 0)),
                    "note": None,
                }
                for s in state["raw_stops"]
                if str(s.get("name", "")).strip()
            ][:MAX_STOPS]
            trip = TripContext.model_validate(state.get("trip_context") or {})
            return {
                "extracted": {
                    "stops": stops,
                    "arrival_city": trip.arrival_city or (stops[0]["name"] if stops else None),
                    "departure_city": trip.departure_city or (stops[-1]["name"] if stops else None),
                    "ambiguities": [],
                    "source": "structured_input",
                }
            }

        raw_text = state.get("raw_text") or ""
        cleaned, scan = sanitise_user_text(raw_text, max_chars=4000)
        if scan.suspicious:
            log.warning("route_check.itinerary_injection_flagged", rules=scan.matched_rules)

        prompt = ctx.prompts.get("itinerary_extraction")
        trip = TripContext.model_validate(state.get("trip_context") or {})
        payload = {
            "raw_text": cleaned,
            "arrival_city": trip.arrival_city,
            "departure_city": trip.departure_city,
        }
        user = f"{prompt.render_user(raw_text=cleaned)}\n\n{structured_block(payload)}"

        try:
            extracted, usages = await complete_with_repair(
                ctx.registry.llm,
                system=prompt.system,
                user=user,
                schema=ExtractedItinerary,
                model=ctx.model_for(TaskClass.EXTRACTION),
                repair_model=ctx.model_for(TaskClass.REPAIR),
            )
        except Exception as exc:
            log.warning("route_check.extraction_failed", error=str(exc)[:300])
            return {
                "extracted": {"stops": [], "ambiguities": [], "source": "failed"},
                "node_errors": [f"parse_itinerary: {exc}"],
                "unknowns": [
                    "Could not read the itinerary text. Try the structured stop entry instead."
                ],
                "analysis_gaps": ["The itinerary text could not be read, so no stop was checked."],
            }

        for usage in usages:
            ctx.trace.record_usage(usage, prompt=prompt.label)

        data = extracted.model_dump(mode="json")
        data["stops"] = data["stops"][:MAX_STOPS]
        data["source"] = "llm_extraction"
        if scan.suspicious:
            data.setdefault("ambiguities", []).append(
                "Instruction-like text in your itinerary was treated as description, not as a command."
            )
        return {"extracted": data}

    return parse_itinerary


# ---------------------------------------------------------------------------
# 2. resolve_places
# ---------------------------------------------------------------------------
def make_resolve_places(ctx: AgentContext):
    async def resolve_places(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("resolve_places")
        ctx.tools.current_node = "resolve_places"
        stops = (state.get("extracted") or {}).get("stops") or []
        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []

        for index, stop in enumerate(stops):
            data = await ctx.tools.call_optional("get_place_details", {"query": stop["name"]})
            if not data or not data.get("resolved"):
                unresolved.append(stop["name"])
                resolved.append(
                    {
                        "order": index,
                        "raw_name": stop["name"],
                        "place_slug": None,
                        "display_name": stop["name"],
                        "nights": stop["nights"],
                        "resolved": False,
                        "resolution_note": "Not in the place catalogue — excluded from transport and rule checks.",
                    }
                )
                continue
            place = data["place"]

            # An edit-distance-only match is a *suggestion*, never a resolution.
            # The score cannot tell a typo from a different place — "Sendia" →
            # "Sendai" and "Narnia" → Tokyo's alias "narita" both score 0.833 —
            # so accepting one silently costed a real route through a city the
            # traveller never named. Exact and substring matches are safe;
            # anything else is handed back for confirmation and excluded from the
            # checks, which is the same contract as a name we do not know at all.
            if place.get("match_kind", "exact") == "fuzzy":
                unresolved.append(stop["name"])
                resolved.append(
                    {
                        "order": index,
                        "raw_name": stop["name"],
                        "place_slug": None,
                        "display_name": stop["name"],
                        "nights": stop["nights"],
                        "resolved": False,
                        "resolution_note": (
                            f"No confident match for '{stop['name']}' — did you mean "
                            f"{place['name']}? Re-enter it to confirm; it was left out of the "
                            "transport and rule checks rather than guessed at."
                        ),
                        # Unresolved stops are dropped from ``parsed_route``, so the
                        # note above never reaches the user on its own. R23 picks
                        # this up and puts the suggestion in its proposed fix.
                        "suggestion": place["name"],
                    }
                )
                continue

            resolved.append(
                {
                    "order": index,
                    "raw_name": stop["name"],
                    "place_slug": place["slug"],
                    "display_name": place["name"],
                    "nights": stop["nights"],
                    "region_code": place.get("region_code"),
                    "lat": place["lat"],
                    "lon": place["lon"],
                    "resolved": True,
                    "resolution_note": (
                        None
                        if place.get("resolution_confidence", 1.0) >= 0.95
                        else f"Matched '{stop['name']}' to {place['name']}."
                    ),
                }
            )

        log.info("route_check.places_resolved", total=len(stops), unresolved=len(unresolved))
        return {"resolved_stops": resolved, "unresolved_places": unresolved}

    return resolve_places


# ---------------------------------------------------------------------------
# 3. load_trip_state
# ---------------------------------------------------------------------------
def make_load_trip_state(ctx: AgentContext):
    async def load_trip_state(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("load_trip_state")
        ctx.tools.current_node = "load_trip_state"
        trip_id = state.get("trip_id")
        if not trip_id:
            return {"memory": {}}
        data = await ctx.tools.call_optional("get_trip_context", {"trip_id": trip_id})
        if not data or not data.get("found"):
            return {"memory": {}}
        memory = TripMemory(
            trip_id=trip_id,
            visited=data.get("visited", []),
            candidate_region=data.get("candidate_region"),
            rejected_regions=data.get("rejected_regions", {}),
            confirmed_preferences=data.get("confirmed_preferences", {}),
            verified_warnings=data.get("verified_warnings", []),
            decisions=data.get("decisions", []),
        )
        merged = dict(state.get("trip_context") or {})
        merged.setdefault("arrival_city", data.get("arrival_city"))
        merged.setdefault("departure_city", data.get("departure_city"))
        return {"memory": memory.model_dump(mode="json"), "trip_context": merged}

    return load_trip_state


# ---------------------------------------------------------------------------
# 4. retrieve_structured_facts
# ---------------------------------------------------------------------------
def make_retrieve_structured_facts(ctx: AgentContext):
    async def retrieve_structured_facts(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("retrieve_structured_facts")
        ctx.tools.current_node = "retrieve_structured_facts"
        trip = TripContext.model_validate(state.get("trip_context") or {})
        slugs = [s["place_slug"] for s in state.get("resolved_stops") or [] if s.get("place_slug")]
        if not slugs:
            return {"structured_facts": {}}

        booking = await ctx.tools.call_optional(
            "get_booking_requirements", {"place_slugs": slugs[:12], "month": trip.month}
        )
        verification = await ctx.tools.call_optional("get_verification_status", {"limit": 40})
        return {
            "structured_facts": {
                "booking": booking or {},
                "verification": verification or {},
                "place_slugs": slugs,
            }
        }

    return retrieve_structured_facts


# ---------------------------------------------------------------------------
# 5. call_transport_tools
# ---------------------------------------------------------------------------
def make_call_transport_tools(ctx: AgentContext):
    async def call_transport_tools(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("call_transport_tools")
        ctx.tools.current_node = "call_transport_tools"
        trip = TripContext.model_validate(state.get("trip_context") or {})
        stops = state.get("resolved_stops") or []
        resolved = [s for s in stops if s.get("resolved")]
        if len(resolved) < 2:
            return {
                "tool_results": {},
                "unknowns": [
                    "Fewer than two stops could be resolved, so no transport analysis is possible."
                ],
                "analysis_gaps": [
                    f"Only {len(resolved)} stop(s) resolved to the catalogue, so no segment was "
                    "costed and no transport rule ran."
                ],
            }

        data = await ctx.tools.call_optional(
            "get_route_context",
            {
                "place_slugs": [s["place_slug"] for s in resolved],
                "nights": [s["nights"] for s in resolved],
                "allow_car": not trip.public_transport_only,
                "arrival_city": trip.arrival_city,
                "departure_city": trip.departure_city,
            },
        )
        legs = (data or {}).get("legs", [])
        return {
            "tool_results": {
                "legs": legs,
                "total_transit_minutes": (data or {}).get("total_transit_minutes", 0),
                "estimated_legs": (data or {}).get("estimated_legs", 0),
            }
        }

    return call_transport_tools


# ---------------------------------------------------------------------------
# 6. retrieve_constraints
# ---------------------------------------------------------------------------
def make_retrieve_constraints(ctx: AgentContext):
    async def retrieve_constraints(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("retrieve_constraints")
        ctx.tools.current_node = "retrieve_constraints"
        trip = TripContext.model_validate(state.get("trip_context") or {})
        resolved = [s for s in state.get("resolved_stops") or [] if s.get("resolved")]
        if not resolved:
            return {"retrieved_evidence": [], "evidence_block": "(no evidence retrieved)"}

        slugs = [s["place_slug"] for s in resolved]
        names = " ".join(s["display_name"] for s in resolved)
        transport_clause = "without a car on public transport" if trip.public_transport_only else ""
        query = f"{names} access last bus shuttle ferry booking closure {transport_clause}".strip()

        data = await ctx.tools.call_optional(
            "search_verified_evidence",
            {
                "query": query,
                "place_slugs": slugs,
                "topics": [
                    EvidenceTopic.TRANSPORT_ACCESS.value,
                    EvidenceTopic.BOOKING.value,
                    EvidenceTopic.SEASONAL.value,
                ],
                "month": trip.month,
                "limit": 8,
            },
        )
        evidence = (data or {}).get("evidence", [])

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
                    "region_code": e.get("region_code"),
                    "place_slug": e.get("place_slug"),
                    "topic": e.get("topic", EvidenceTopic.GENERAL.value),
                    "verified_at": e.get("verified_at"),
                    "is_demo": e.get("is_demo", True),
                    "score": e.get("score", 0.0),
                    "fused_score": e.get("score", 0.0),
                },
            )
            for e in evidence
        ]
        assembled = assemble_evidence_context(
            documents, token_budget=min(ctx.settings.context_token_budget // 2, 3000)
        )
        included = set(assembled.audit.included_ids)
        ctx.trace.record_retrieval(
            query=query,
            strategy=ctx.settings.retrieval_strategy,
            evidence_ids=list(included),
            latency_ms=0,
            quarantined=len(assembled.audit.quarantined),
        )
        return {
            "retrieved_evidence": [e for e in evidence if e["evidence_id"] in included],
            "evidence_block": assembled.block,
            "quarantined_evidence": [
                {"evidence_id": e, "rules": r} for e, r in assembled.audit.quarantined
            ],
            "context_audit": assembled.audit.to_dict(),
        }

    return retrieve_constraints


# ---------------------------------------------------------------------------
# 7. run_deterministic_checks
# ---------------------------------------------------------------------------
def make_run_deterministic_checks(ctx: AgentContext):
    async def run_deterministic_checks(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("run_deterministic_checks")
        ctx.tools.current_node = "run_deterministic_checks"
        trip = TripContext.model_validate(state.get("trip_context") or {})
        resolved = [s for s in state.get("resolved_stops") or [] if s.get("resolved")]
        if len(resolved) < 2:
            return {
                "issues": [],
                "health": RouteHealth.HEALTHY.value,
                "route": {},
                "travel_load": {},
            }

        data = await ctx.tools.call_optional(
            "check_route_constraints",
            {
                "place_slugs": [s["place_slug"] for s in resolved],
                "nights": [s["nights"] for s in resolved],
                "public_transport_only": trip.public_transport_only,
                "large_luggage": bool(trip.large_luggage),
                "pace": trip.pace.value if trip.pace else None,
                "arrival_city": trip.arrival_city,
                "departure_city": trip.departure_city,
                "month": trip.month,
            },
        )
        if not data:
            return {
                "issues": [],
                "health": RouteHealth.HEALTHY.value,
                "node_errors": ["run_deterministic_checks: rules engine unavailable"],
                "unknowns": [
                    "The route rules could not be evaluated; treat this analysis as incomplete."
                ],
                "analysis_gaps": [
                    "The route rules engine was unavailable, so no rule was applied."
                ],
            }

        route = _rebuild_route(state, resolved, trip)
        return {
            "issues": data.get("issues", []),
            "health": data.get("health", RouteHealth.HEALTHY.value),
            "travel_load": data.get("travel_load", {}),
            "route": route.model_dump(mode="json"),
        }

    return run_deterministic_checks


def _unresolved_fix(state: RouteCheckState) -> str:
    """Offer the near miss rather than a bare instruction.

    A name that failed to resolve often had a close candidate that was refused
    on purpose (see ``resolve_places``). Telling the traveller "did you mean
    Tokyo?" is far more useful than "re-enter it", and keeps the decision with
    the person instead of the matcher.
    """
    suggestions = [
        f"'{s['raw_name']}' → {s['suggestion']}?"
        for s in (state.get("resolved_stops") or [])
        if not s.get("resolved") and s.get("suggestion")
    ]
    base = "Re-enter those stops using the nearest station or town name."
    if not suggestions:
        return base
    return f"Did you mean {', '.join(suggestions[:3])} {base}"


def _rebuild_route(
    state: RouteCheckState, resolved: list[dict[str, Any]], trip: TripContext
) -> Route:
    """Reconstruct the domain Route from resolved stops + tool-supplied legs."""
    from jst_api.domain.enums import TransportMode

    stops = [
        RouteStop(
            order=i,
            raw_name=s["raw_name"],
            place_slug=s.get("place_slug"),
            display_name=s.get("display_name"),
            nights=s["nights"],
            region_code=s.get("region_code"),
            lat=s.get("lat"),
            lon=s.get("lon"),
            resolved=True,
            resolution_note=s.get("resolution_note"),
        )
        for i, s in enumerate(resolved)
    ]
    legs = (state.get("tool_results") or {}).get("legs", [])
    segments = [
        RouteSegment(
            from_order=i,
            to_order=i + 1,
            from_name=stops[i].name,
            to_name=stops[i + 1].name,
            mode=TransportMode(leg["mode"]),
            duration_minutes=leg["duration_minutes"],
            transfers=leg.get("transfers", 0),
            distance_km=leg.get("distance_km"),
            requires_car=leg.get("requires_car", False),
            last_departure_local=leg.get("last_departure_local"),
            final_leg_minutes=leg.get("final_leg_minutes"),
            provider=(leg.get("provider") or {}).get("provider", "demo"),
            is_estimate=leg.get("is_estimate", False),
            notes=leg.get("notes"),
        )
        for i, leg in enumerate(legs)
        if i + 1 < len(stops)
    ]
    return Route(
        stops=stops,
        segments=segments,
        arrival_city=trip.arrival_city or (stops[0].name if stops else None),
        departure_city=trip.departure_city or (stops[-1].name if stops else None),
    )


# ---------------------------------------------------------------------------
# 8. detect_route_issues  (enrich rule output with evidence + freshness)
# ---------------------------------------------------------------------------
def make_detect_route_issues(ctx: AgentContext):
    async def detect_route_issues(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("detect_route_issues")
        ctx.tools.current_node = "detect_route_issues"
        issues = list(state.get("issues") or [])
        evidence = state.get("retrieved_evidence") or []
        facts = state.get("structured_facts") or {}

        # Attach supporting evidence to each issue by place/topic overlap, so a
        # critique is never an unsupported assertion.
        by_place: dict[str, list[str]] = {}
        for item in evidence:
            if item.get("place_slug"):
                by_place.setdefault(item["place_slug"], []).append(item["evidence_id"])
        slug_by_name = {
            s["display_name"]: s.get("place_slug")
            for s in state.get("resolved_stops") or []
            if s.get("place_slug")
        }
        for issue in issues:
            if issue.get("evidence_ids"):
                continue
            segment = issue.get("segment") or ""
            matched: list[str] = []
            for name, slug in slug_by_name.items():
                if name and slug and name in segment:
                    matched.extend(by_place.get(slug, []))
            issue["evidence_ids"] = matched[:3]

        # Booking lead-time constraints become first-class issues.
        booking = facts.get("booking") or {}
        gaps = booking.get("english_booking_gaps") or []
        closed = booking.get("closed_in_month") or []
        max_lead = booking.get("max_lead_time_days")
        if closed:
            issues.append(
                {
                    "rule_id": "R20_seasonal_closure",
                    "issue_type": IssueType.SEASONAL_CLOSURE.value,
                    "severity": Severity.CRITICAL.value,
                    "segment": None,
                    "title": "Something on this route is closed in your travel month",
                    "explanation": f"Closed in the month you are travelling: {', '.join(closed)}.",
                    "deterministic_signal": {"closed_count": len(closed)},
                    "proposed_fix": "Move those dates, or replace the closed stop.",
                    "evidence_ids": [],
                }
            )
        if max_lead and max_lead >= 60:
            issues.append(
                {
                    "rule_id": "R21_booking_lead_time",
                    "issue_type": IssueType.BOOKING_LEAD_TIME.value,
                    "severity": Severity.WARNING.value,
                    "segment": None,
                    "title": f"Something here needs booking about {max_lead} days ahead",
                    "explanation": (
                        f"The longest booking lead time on this route is {max_lead} days."
                        + (f" Not bookable in English: {', '.join(gaps[:3])}." if gaps else "")
                    ),
                    "deterministic_signal": {
                        "max_lead_time_days": max_lead,
                        "english_gaps": len(gaps),
                    },
                    "proposed_fix": "Book the constrained stops before fixing the rest of the itinerary.",
                    "evidence_ids": [],
                }
            )

        # Stale critical evidence is itself an issue the traveller should see.
        verification = facts.get("verification") or {}
        stale_entries = [
            e for e in verification.get("entries", []) if e.get("requires_reverification")
        ]
        if stale_entries:
            issues.append(
                {
                    "rule_id": "R22_stale_evidence",
                    "issue_type": IssueType.STALE_EVIDENCE.value,
                    "severity": Severity.WARNING.value,
                    "segment": None,
                    "title": "Some operational facts here are out of date",
                    "explanation": (
                        f"{len(stale_entries)} verified fact(s) are past their re-check window: "
                        + ", ".join(
                            f"{e['subject']} ({e.get('verified_at', 'unknown')[:10]})"
                            for e in stale_entries[:3]
                        )
                    ),
                    "deterministic_signal": {"stale_count": len(stale_entries)},
                    "proposed_fix": "Confirm these directly with the operator before booking.",
                    "evidence_ids": [],
                }
            )

        unresolved = state.get("unresolved_places") or []
        if unresolved:
            issues.append(
                {
                    "rule_id": "R23_unresolved_stop",
                    "issue_type": IssueType.UNRESOLVED_STOP.value,
                    "severity": Severity.WARNING.value,
                    "segment": ", ".join(unresolved[:3]),
                    "title": "Some stops could not be identified",
                    "explanation": (
                        f"{', '.join(unresolved[:5])} are not in the place catalogue, so they were excluded "
                        "from the transport and rule checks rather than guessed at."
                    ),
                    "deterministic_signal": {"unresolved_count": len(unresolved)},
                    "proposed_fix": _unresolved_fix(state),
                    "evidence_ids": [],
                }
            )

        from jst_api.domain.enums import Severity as S

        criticals = sum(1 for i in issues if i["severity"] == S.CRITICAL.value)
        warnings = sum(1 for i in issues if i["severity"] == S.WARNING.value)
        health = (
            RouteHealth.HIGH_RISK.value
            if criticals >= 2
            else RouteHealth.NEEDS_IMPROVEMENT.value
            if criticals or warnings
            else RouteHealth.HEALTHY.value
        )
        log.info(
            "route_check.issues",
            total=len(issues),
            critical=criticals,
            warning=warnings,
            health=health,
        )
        return {"issues": issues, "health": health}

    return detect_route_issues


# ---------------------------------------------------------------------------
# 9. generate_candidate_fixes  (deterministic, then re-costed with real data)
# ---------------------------------------------------------------------------
def make_generate_candidate_fixes(ctx: AgentContext):
    async def generate_candidate_fixes(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("generate_candidate_fixes")
        ctx.tools.current_node = "generate_candidate_fixes"
        route_data = state.get("route") or {}
        if not route_data.get("stops"):
            return {"candidate_revisions": [], "chosen_revision": None}

        trip = TripContext.model_validate(state.get("trip_context") or {})
        route = Route.model_validate(route_data)
        backtracking = any(i["rule_id"] == "R03_backtracking" for i in state.get("issues") or [])
        candidates = generate_candidates(route, backtracking=backtracking)

        slug_by_name = {s.name: s.place_slug for s in route.stops if s.place_slug}
        costed: list[dict[str, Any]] = []
        # Every candidate is re-costed with real transport data. Ranking on the
        # geometric estimate alone would let a cheap-looking bypass win on a hop
        # that has no practical service.
        for candidate in candidates[:MAX_REVISION_CANDIDATES]:
            slugs = [slug_by_name.get(name) for name in candidate.stops]
            if any(s is None for s in slugs):
                continue
            # Re-cost with real transport data. A revision whose travel time was
            # guessed would be no better than the problem it claims to fix.
            load = await ctx.tools.call_optional(
                "calculate_travel_load",
                {
                    "place_slugs": slugs,
                    "nights": candidate.nights,
                    "allow_car": not trip.public_transport_only,
                },
            )
            if not load:
                continue
            from jst_api.domain.route import TravelLoad

            candidate.load = TravelLoad.model_validate(load)
            costed.append(
                {
                    "strategy": candidate.strategy,
                    "stops": candidate.stops,
                    "nights": candidate.nights,
                    "dropped": candidate.dropped,
                    "merged": candidate.merged,
                    "reordered": candidate.reordered,
                    "summary": candidate.describe(),
                    "travel_load": load,
                    "gained": _gains(state.get("travel_load") or {}, load),
                    "lost": [f"You no longer visit {name}." for name in candidate.dropped],
                }
            )

        best = choose_best([c for c in candidates if c.load is not None], route)
        chosen = None
        if best is not None:
            chosen = next((c for c in costed if c["strategy"] == best.strategy), None)
            if chosen:
                chosen["objective"] = best.objective

        # Order candidates by objective so the model sees the best one first.
        costed.sort(key=lambda c: (c["travel_load"]["transit_hours_per_night"], len(c["dropped"])))
        if chosen:
            costed = [chosen, *[c for c in costed if c is not chosen]]
        return {"candidate_revisions": costed, "chosen_revision": chosen}

    return generate_candidate_fixes


def _gains(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    gains: list[str] = []
    if not before:
        return gains
    saved = round(
        float(before.get("total_transit_hours", 0)) - float(after.get("total_transit_hours", 0)), 1
    )
    if saved > 0.3:
        gains.append(f"{saved}h less time in transit.")
    fewer = int(before.get("accommodation_changes", 0)) - int(after.get("accommodation_changes", 0))
    if fewer > 0:
        gains.append(f"{fewer} fewer hotel change(s).")
    fewer_singles = int(before.get("one_night_stays", 0)) - int(after.get("one_night_stays", 0))
    if fewer_singles > 0:
        gains.append(f"{fewer_singles} fewer single-night stop(s).")
    return gains


# ---------------------------------------------------------------------------
# 10. narrate_critique  (the one LLM call in this graph's analysis half)
# ---------------------------------------------------------------------------
def make_narrate_critique(ctx: AgentContext):
    async def narrate_critique(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("narrate_critique")
        ctx.tools.current_node = "narrate_critique"
        issues = state.get("issues") or []
        prompt = ctx.prompts.get("route_critique")
        route = Route.model_validate(state.get("route") or {"stops": [], "segments": []})
        trip = TripContext.model_validate(state.get("trip_context") or {})

        memory_block = (
            compact_memory(TripMemory.model_validate(state["memory"]).to_prompt_block())
            if state.get("memory")
            else "No prior trip memory."
        )
        trip_summary = (
            f"in/out {trip.arrival_city or '?'}/{trip.departure_city or '?'}, "
            f"month {trip.month or 'unknown'}, "
            f"{'public transport only' if trip.public_transport_only else 'car available'}, "
            f"pace {trip.pace.value if trip.pace else 'unstated'}, "
            f"large luggage {bool(trip.large_luggage)}. Memory: {memory_block}"
        )
        payload = {
            "issues": [{**i, "issue_key": issue_key(i)} for i in issues],
            "travel_load": state.get("travel_load") or {},
            "candidate_revisions": state.get("candidate_revisions") or [],
            "unknowns": state.get("unknowns") or [],
            "evidence_ids": [e["evidence_id"] for e in state.get("retrieved_evidence") or []],
        }
        user = (
            f"{prompt.render_user(trip_summary=trip_summary, route_summary=route.to_compact_text(), evidence_block=state.get('evidence_block', ''))}"
            f"\n\n{structured_block(payload)}"
        )

        try:
            critique, usages = await complete_with_repair(
                ctx.registry.llm,
                system=prompt.system,
                user=user,
                schema=CritiqueOutput,
                model=ctx.model_for(TaskClass.CRITIQUE),
                repair_model=ctx.model_for(TaskClass.REPAIR),
            )
        except Exception as exc:
            log.warning("route_check.critique_failed", error=str(exc)[:300])
            return {
                "critique": {},
                "node_errors": [f"narrate_critique: {exc}"],
                "unknowns": [
                    "The narration model failed; the deterministic findings are shown without prose."
                ],
            }

        for usage in usages:
            ctx.trace.record_usage(usage, prompt=prompt.label)

        data = critique.model_dump(mode="json")
        # Enforce the contract: the model may only return a revision it was given.
        allowed = {
            (tuple(c["stops"]), tuple(c["nights"])) for c in state.get("candidate_revisions") or []
        }
        proposed = (tuple(data.get("revised_stops") or []), tuple(data.get("revised_nights") or []))
        if proposed[0] and proposed not in allowed:
            log.warning("route_check.model_invented_route_discarded", proposed=proposed[0])
            chosen = state.get("chosen_revision")
            data["revised_stops"] = chosen["stops"] if chosen else []
            data["revised_nights"] = chosen["nights"] if chosen else []
            data.setdefault("unknowns", []).append(
                "A model-proposed reshaping was discarded because it was not one of the routes costed with real transport data."
            )
        return {"critique": data}

    return narrate_critique


# ---------------------------------------------------------------------------
# 11. grounding_check
# ---------------------------------------------------------------------------
def make_grounding_check(ctx: AgentContext):
    async def grounding_check(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("grounding_check")
        ctx.tools.current_node = "grounding_check"
        critique = state.get("critique") or {}
        evidence_raw = state.get("retrieved_evidence") or []
        evidence = [
            DomainEvidence.model_validate(
                {
                    "evidence_id": e["evidence_id"],
                    "source": {
                        "source_id": e["source_id"],
                        "title": e["source_title"],
                        "url": e.get("source_url"),
                        "source_type": e["source_type"],
                        "official_source": e.get("official_source", False),
                        "trust_level": e.get("trust_level", TrustLevel.SECONDARY.value),
                        "verified_at": e.get("verified_at"),
                        "is_demo": e.get("is_demo", True),
                    },
                    "content": e.get("snippet", ""),
                    "topic": e.get("topic", EvidenceTopic.GENERAL.value),
                    "region_code": e.get("region_code"),
                    "place_slug": e.get("place_slug"),
                    "freshness": e.get("freshness", "unverified"),
                    "verified_at": e.get("verified_at"),
                }
            )
            for e in evidence_raw
        ]

        prose = [critique.get("health_summary", ""), critique.get("revision_summary", "")]
        prose += list((critique.get("issue_narratives") or {}).values())
        prose += critique.get("gained", []) + critique.get("lost", [])

        deterministic_values: list[str] = []
        for issue in state.get("issues") or []:
            deterministic_values.append(issue.get("explanation", ""))
            deterministic_values.append(str(issue.get("deterministic_signal", {})))
        deterministic_values.append(str(state.get("travel_load") or {}))
        for leg in (state.get("tool_results") or {}).get("legs", []):
            deterministic_values.append(str(leg))

        relevant_slugs = {
            s["place_slug"] for s in state.get("resolved_stops") or [] if s.get("place_slug")
        }
        conflicts = await _detect_conflicts(
            ctx,
            relevant_slugs=relevant_slugs,
            evidence_ids={e["evidence_id"] for e in evidence_raw},
        )
        report = run_guardrails(
            prose_blocks=[p for p in prose if p],
            cited_ids=critique.get("evidence_ids", []),
            evidence=evidence,
            deterministic_values=deterministic_values,
            quarantined=[
                (q["evidence_id"], q["rules"]) for q in state.get("quarantined_evidence") or []
            ],
            min_evidence=1,  # a route critique is mostly deterministic; evidence enriches it
            conflicts_detected=bool(conflicts),
            analysis_gaps=state.get("analysis_gaps") or [],
        )
        return {"guardrail_report": report.to_dict(), "conflicts": conflicts}

    return grounding_check


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
# 12. confidence_check / human_review / result
# ---------------------------------------------------------------------------
def make_confidence_check(ctx: AgentContext):
    async def confidence_check(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("confidence_check")
        report = state.get("guardrail_report") or {}
        needs_review = bool(report.get("human_review_required"))
        return {
            "confidence": report.get("confidence", ConfidenceState.MEDIUM.value),
            "human_review_required": needs_review,
            "status": (
                AnalysisStatus.NEEDS_HUMAN_REVIEW.value
                if needs_review
                else AnalysisStatus.COMPLETE.value
            ),
        }

    return confidence_check


def route_after_confidence(state: RouteCheckState) -> str:
    return "human_review" if state.get("human_review_required") else "result"


def make_human_review(ctx: AgentContext):
    async def human_review(state: RouteCheckState) -> dict[str, Any]:
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
                f"Sources disagree on {field_name or 'this fact'} for {subject}: {', '.join(conflict['values'])}. "
                "This route depends on it. Confirm with the operator before the critique is shown."
            )
            values = conflict["values"]
            evidence_ids = conflict["evidence_ids"]
        else:
            subject = "route_check:" + (state.get("analysis_id") or "unknown")
            field_name = None
            question = (
                f"Route critique did not meet the confidence bar ({reason}). Findings: "
                + "; ".join(f["message"] for f in report.get("findings", [])[:4])
            )
            values = []
            evidence_ids = [e["evidence_id"] for e in state.get("retrieved_evidence") or []][:10]

        created = await ctx.tools.call_optional(
            "create_human_review_request",
            {
                "reason": reason,
                "subject": subject,
                "question": question,
                "field_name": field_name,
                "candidate_values": values,
                "evidence_ids": evidence_ids,
                "analysis_id": state.get("analysis_id"),
                "thread_id": state.get("thread_id"),
                "priority": "high" if conflicts else "normal",
            },
        )
        task_id = created.get("task_id") if created else None

        if ctx.interactive:
            from langgraph.types import interrupt

            resolution = interrupt(
                {
                    "task_id": task_id,
                    "reason": reason,
                    "subject": subject,
                    "question": question,
                    "candidate_values": values,
                }
            )
            return {"human_review_task_id": task_id, "human_resolution": resolution}
        return {"human_review_task_id": task_id}

    return human_review


def make_result(ctx: AgentContext):
    async def result(state: RouteCheckState) -> dict[str, Any]:
        ctx.trace.enter_node("result")
        ctx.tools.current_node = "result"
        critique = state.get("critique") or {}
        issues = state.get("issues") or []
        narratives = critique.get("issue_narratives") or {}
        report = state.get("guardrail_report") or {}
        stripped = set(report.get("stripped_claims") or [])
        evidence_by_id = {e["evidence_id"]: e for e in state.get("retrieved_evidence") or []}

        def render(issue: dict[str, Any]) -> dict[str, Any]:
            narrative = narratives.get(issue_key(issue)) or narratives.get(
                str(issue.get("rule_id") or ""), ""
            )
            if narrative and any(bad in narrative for bad in stripped):
                narrative = ""  # unsupported literal — fall back to the machine text
            return {
                "issue_type": issue["issue_type"],
                "severity": issue["severity"],
                "segment": issue.get("segment"),
                "title": issue["title"],
                "explanation": narrative or issue["explanation"],
                "deterministic_signal": issue.get("deterministic_signal", {}),
                "rule_id": issue.get("rule_id"),
                "evidence_ids": [i for i in issue.get("evidence_ids", []) if i in evidence_by_id],
                "proposed_fix": issue.get("proposed_fix"),
            }

        rendered = [render(i) for i in issues]
        chosen = state.get("chosen_revision")
        revised = None
        if chosen:
            revised = {
                "stops": chosen["stops"],
                "nights": chosen["nights"],
                "summary": critique.get("revision_summary") or chosen["summary"],
                "travel_load": chosen.get("travel_load"),
                "rationale": chosen["summary"],
            }

        citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for evidence_id, item in evidence_by_id.items():
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            citations.append(
                {
                    "evidence_id": evidence_id,
                    "source_id": item["source_id"],
                    "title": item["source_title"],
                    "url": item.get("source_url"),
                    "source_type": item["source_type"],
                    "official_source": item.get("official_source", False),
                    "verified_at": item.get("verified_at"),
                    "freshness": item.get("freshness", "unverified"),
                    "is_demo": item.get("is_demo", True),
                }
            )

        summary = critique.get("health_summary") or _fallback_summary(rendered)
        payload = {
            "analysis_id": state["analysis_id"],
            "trip_id": state.get("trip_id"),
            "status": state.get("status", AnalysisStatus.COMPLETE.value),
            "health": state.get("health", RouteHealth.HEALTHY.value),
            "health_summary": summary,
            "parsed_route": state.get("route") or None,
            "travel_load": state.get("travel_load") or None,
            "critical_issues": [i for i in rendered if i["severity"] == Severity.CRITICAL.value],
            "warnings": [i for i in rendered if i["severity"] == Severity.WARNING.value],
            "strengths": [i for i in rendered if i["severity"] == Severity.GOOD.value],
            "revised_route": revised,
            "proposed_fixes": [
                {
                    "summary": c["summary"],
                    "changed": c["dropped"] + c["merged"],
                    "gained": critique.get("gained") if c is chosen else c["gained"],
                    "lost": critique.get("lost") if c is chosen else c["lost"],
                    "evidence_ids": [],
                }
                for c in (state.get("candidate_revisions") or [])[:3]
            ],
            # ``dict.fromkeys`` and not ``set``: order is meaningful, and the
            # critique prompt is *given* the state unknowns, so a model that
            # repeats one back would otherwise show it to the user twice.
            "unknowns": list(
                dict.fromkeys([*(state.get("unknowns") or []), *critique.get("unknowns", [])])
            ),
            "unresolved_places": state.get("unresolved_places") or [],
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
            "citations": citations,
            "demo_mode": ctx.registry.any_demo,
            "rules_version": RULES_VERSION,
            "prompt_versions": ctx.trace.prompt_versions,
        }
        return {"result": payload, "status": payload["status"]}

    return result


def _fallback_summary(issues: list[dict[str, Any]]) -> str:
    criticals = [i for i in issues if i["severity"] == Severity.CRITICAL.value]
    warnings = [i for i in issues if i["severity"] == Severity.WARNING.value]
    if criticals:
        return f"{len(criticals)} critical problem(s) and {len(warnings)} warning(s). Worst: {criticals[0]['title']}."
    if warnings:
        return f"No blocking problems, but {len(warnings)} thing(s) would make this trip better."
    return "This itinerary holds up: travel load, stay lengths and connections are all inside sensible limits."
