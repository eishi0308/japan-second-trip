"""LLM providers, model routing and structured-output plumbing.

Three implementations behind ``LLMProvider``:

``DemoLLMProvider``
    Deterministic, offline, zero-cost. It reads the machine-readable block that
    every prompt carries (``<<<STRUCTURED_INPUT>>> … <<<END_STRUCTURED_INPUT>>>``)
    and composes a schema-valid object from it. A real model reads the same
    block as *data*; the demo provider parses it. This is what lets every user
    flow work end-to-end without credentials — and every result it produces is
    flagged ``demo_mode`` so it is never mistaken for a live answer.

``AnthropicLLMProvider``
    Production path via the official ``anthropic`` SDK using native structured
    outputs (``messages.parse``).

``OpenAILLMProvider``
    Alternate production path, so the product is not hostage to one vendor.

``FallbackLLMProvider`` wraps a primary and a secondary: if the primary fails
after its bounded retries, the secondary runs and the result is tagged
``fell_back=True`` for observability.

Model routing (docs/adr/0009-model-routing.md): cheap model for extraction,
classification and schema repair; strong model only where multi-constraint
reasoning materially changes the answer.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from jst_api.core.config import Settings
from jst_api.core.errors import ProviderError, SchemaRepairFailed
from jst_api.core.logging import get_logger
from jst_api.core.resilience import CircuitBreaker, RetryPolicy, call_with_resilience
from jst_api.providers.base import LLMResult, LLMUsage

log = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

STRUCTURED_OPEN = "<<<STRUCTURED_INPUT>>>"
STRUCTURED_CLOSE = "<<<END_STRUCTURED_INPUT>>>"


class TaskClass:
    """Named task classes used by the router."""

    EXTRACTION = "extraction"
    COMPARISON = "comparison"
    CRITIQUE = "critique"
    RERANK = "rerank"
    GROUNDING = "grounding"
    REPAIR = "repair"
    ADMIN = "admin"


#: task class -> "fast" | "reasoning". Documented, not implicit.
ROUTING_POLICY: dict[str, str] = {
    TaskClass.EXTRACTION: "fast",
    TaskClass.RERANK: "fast",
    TaskClass.REPAIR: "fast",
    TaskClass.GROUNDING: "fast",
    TaskClass.ADMIN: "fast",
    TaskClass.COMPARISON: "reasoning",
    TaskClass.CRITIQUE: "reasoning",
}

#: USD per 1M tokens (input, output). Used for cost accounting in traces.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "demo": (0.0, 0.0),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = MODEL_PRICING.get(model, (0.0, 0.0))
    return round((prompt_tokens / 1_000_000) * inp + (completion_tokens / 1_000_000) * out, 6)


def approx_tokens(text: str) -> int:
    """~4 characters per token. Only used for budgeting and demo accounting;
    live providers report real usage."""
    return max(1, len(text) // 4)


def structured_block(payload: dict[str, Any]) -> str:
    """Render the machine-readable data block appended to prompts."""
    body = json.dumps(payload, ensure_ascii=False, default=str, indent=None, sort_keys=True)
    return f"{STRUCTURED_OPEN}\n{body}\n{STRUCTURED_CLOSE}"


def parse_structured_block(user_message: str) -> dict[str, Any]:
    start = user_message.find(STRUCTURED_OPEN)
    end = user_message.find(STRUCTURED_CLOSE)
    if start == -1 or end == -1:
        return {}
    raw = user_message[start + len(STRUCTURED_OPEN) : end].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Demo provider
# ---------------------------------------------------------------------------
_NIGHTS_RE = re.compile(
    r"(?P<name>[A-Za-zÀ-ÿ'’\-\. ]{2,60}?)\s*[-—–:,]?\s*(?P<n>\d{1,2})\s*(?:n|nights?|nts?|泊)\b",
    re.IGNORECASE,
)
_BARE_STOP_RE = re.compile(r"^[A-Za-zÀ-ÿ'’\-\. ]{2,60}$")
#: Connective and travel-verb words that precede a stop name. Each must be a
#: whole word followed by whitespace, or "Tokyo" gets its leading "To" eaten.
_LEAD_IN_RE = re.compile(
    r"^(?:(?:and|then|finally|next|after|afterwards|back|onward|onwards|on|returning|return"
    r"|from|to|via|fly|flying|flights?|train|arrive|arriving|arrival|depart|departing|departure"
    r"|into|in|out|of|start|starting|begin|beginning|head|heading|stay|staying|spend|spending"
    r"|overnight|night|nights)\b\s+)+",
    re.IGNORECASE,
)
#: Trailing filler left over once the night count is stripped ("Yufuin for 1 night").
_TRAIL_RE = re.compile(r"\s+(?:for|there|here|next|then|and|of|in|on|at|to|with)$", re.IGNORECASE)
#: Segment separators. "and" and "then" both introduce a new stop in practice.
_SEGMENT_SPLIT_RE = re.compile(r"[\n,;→>]+|\s+then\s+|\s+and\s+|\s+->\s+|\s+—\s+then\s+")

#: "2 nights Ginzan Onsen", "2N Kanazawa" — the night count *before* the place.
#: The trailing form ("Ginzan Onsen 2 nights") is by far the less common way
#: people actually write itineraries, and supporting only it meant whole
#: segments were silently dropped.
_LEADING_NIGHTS_RE = re.compile(
    r"^(?P<n>\d{1,2})\s*(?:nights?|nts?|n|泊)\s*(?:(?:in|at)\s+)?(?P<name>.+)$",
    re.IGNORECASE,
)
#: "Day 1-2 Sendai", "Days 3 to 5 Hakone" — day ranges rather than night counts.
_DAY_RANGE_RE = re.compile(
    r"^days?\s*(?P<a>\d{1,2})\s*(?:[-—–]|\s+to\s+)\s*(?P<b>\d{1,2})\s*[:,\-–—]?\s*(?P<name>.+)$",
    re.IGNORECASE,
)
#: "Day 5 Tokyo".
_DAY_SINGLE_RE = re.compile(
    r"^day\s*(?P<a>\d{1,2})\s*[:,\-–—]?\s*(?P<name>.+)$",
    re.IGNORECASE,
)
#: Words that are grammatically a destination but not a place in any catalogue.
#: Matched only when they are the *entire* cleaned name, so "Narita Airport"
#: and "Hotel Okura" are untouched.
_NON_PLACE_NAMES = frozenset(
    {"home", "hotel", "the hotel", "airport", "the airport", "house", "work", "office", "abroad"}
)


class DemoLLMProvider:
    """Deterministic offline stand-in. Never fabricates operational facts."""

    name = "demo"
    is_demo = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[BaseModel, LLMUsage]:
        started = time.perf_counter()
        data = parse_structured_block(user)
        handler = _DEMO_HANDLERS.get(schema.__name__)
        if handler is None:
            raise ProviderError(
                f"Demo provider has no handler for schema {schema.__name__}. "
                "Add one, or configure a live LLM provider.",
                details={"schema": schema.__name__},
            )
        obj = handler(data, schema)
        usage = LLMUsage(
            model="demo",
            provider="demo",
            prompt_tokens=approx_tokens(system) + approx_tokens(user),
            completion_tokens=approx_tokens(obj.model_dump_json()),
            estimated_cost_usd=0.0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return obj, usage

    async def complete_text(
        self, *, system: str, user: str, model: str | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        data = parse_structured_block(user)
        text = data.get("demo_text") or (
            "Demo mode: this narrative is generated deterministically from the structured inputs above. "
            "Configure LLM_PROVIDER to get model-written prose."
        )
        return LLMResult(
            text=str(text),
            usage=LLMUsage(
                model="demo",
                provider="demo",
                prompt_tokens=approx_tokens(system) + approx_tokens(user),
                completion_tokens=approx_tokens(str(text)),
            ),
        )


# -- demo handlers ----------------------------------------------------------
def _clean_name(name: str) -> str:
    """Strip the connectives and trailing filler around a place name."""
    name = _LEAD_IN_RE.sub("", name.strip(" .-—–")).strip()
    previous = None
    while previous != name:  # trailing filler can stack: "for there"
        previous = name
        name = _TRAIL_RE.sub("", name).strip()
    return name


def _parse_segment(line: str) -> tuple[str, int, str | None] | None:
    """Read one itinerary segment into ``(name, nights, ambiguity_note)``.

    Four phrasings, tried most-specific first. Day ranges are converted to a
    night count and the inference is *recorded* rather than hidden: "Day 1-2
    Sendai" almost certainly means two nights, but the traveller never said so.

    Returns ``None`` for a segment that names no place at all — "fly home" is
    grammatically a destination but is not somewhere the catalogue can cost.
    """

    def done(name: str, nights: int, note: str | None = None) -> tuple[str, int, str | None] | None:
        name = _clean_name(name)
        if len(name) < 2 or name.lower() in _NON_PLACE_NAMES:
            return None
        return name, min(nights, 30), note

    if m := _DAY_RANGE_RE.match(line):
        first, last = int(m.group("a")), int(m.group("b"))
        span = max(last - first + 1, 1) if last >= first else 1
        name = _clean_name(m.group("name"))
        return done(
            name, span, f"'{line}' gives days, not nights; read as {span} night(s) at {name}."
        )

    if m := _LEADING_NIGHTS_RE.match(line):
        return done(m.group("name"), int(m.group("n")))

    if m := _NIGHTS_RE.search(line):
        return done(m.group("name"), int(m.group("n")))

    if m := _DAY_SINGLE_RE.match(line):
        name = _clean_name(m.group("name"))
        return done(name, 1, f"'{line}' gives a day, not nights; read as 1 night at {name}.")

    if _BARE_STOP_RE.match(line):
        name = _clean_name(line)
        return done(name, 0, f"No night count given for '{name}'; treated as a pass-through stop.")

    return None


def _demo_extracted_itinerary(data: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    raw = str(data.get("raw_text", ""))
    ambiguities: list[str] = []
    stops: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line in _SEGMENT_SPLIT_RE.split(raw):
        line = line.strip(" .\t-—–")
        if not line:
            continue
        parsed = _parse_segment(line)
        if parsed is None:
            continue
        name, nights, note = parsed
        if note:
            ambiguities.append(note)
        key = name.lower()
        # Only consecutive repeats are noise. A trip that ends where it started
        # ("… then back to Tokyo") legitimately names the same place twice, and
        # dropping the return leg silently understates the whole itinerary.
        if stops and stops[-1]["name"].lower() == key:
            continue
        seen.add(key)
        stops.append({"name": name, "nights": nights, "note": None})

    arrival = data.get("arrival_city") or (stops[0]["name"] if stops else None)
    departure = data.get("departure_city") or (stops[-1]["name"] if stops else None)
    return schema.model_validate(
        {
            "stops": stops[:30],
            "arrival_city": arrival,
            "departure_city": departure,
            "total_nights": sum(s["nights"] for s in stops) or None,
            "ambiguities": ambiguities[:10],
        }
    )


def _first_sentence(text: str, *, max_chars: int = 220) -> str:
    """One readable sentence from an evidence chunk.

    The demo provider has no language model to summarise with, so it extracts
    rather than paraphrases — headings and fragments are skipped so a tradeoff
    never renders as a wall of markdown.
    """
    for raw in text.replace("\n", " ").split(". "):
        line = raw.strip(" #-–—•\t")
        if len(line) < 40 or line.startswith("##"):
            continue
        sentence = line if line.endswith(".") else line + "."
        return sentence[:max_chars]
    return ""


def _demo_comparison(data: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    candidates = data.get("candidates") or []
    explanations = []
    for cand in candidates[:8]:
        components = sorted(
            cand.get("components", []), key=lambda c: -float(c.get("contribution", 0))
        )
        strongest = [c for c in components if float(c.get("value", 0)) >= 0.65][:3]
        weakest = [c for c in components if float(c.get("value", 0)) < 0.5][:3]
        hard = cand.get("hard_failures", [])

        reasons = [c["explanation"] for c in strongest]
        if not reasons:
            reasons = [c["explanation"] for c in components[:2]]
        tradeoffs = [c["explanation"] for c in weakest]
        # Cite only the evidence actually used. Citing everything retrieved
        # inflates apparent grounding and makes the guardrails' cited-vs-retrieved
        # distinction meaningless.
        evidence: list[str] = []
        for ev in cand.get("evidence", [])[:2]:
            caveat = _first_sentence(str(ev.get("summary", "")))
            if caveat:
                tradeoffs.append(caveat)
                if ev.get("evidence_id"):
                    evidence.append(ev["evidence_id"])

        rejected = [h["explanation"] for h in hard]
        label = str(cand.get("fit_label", "good")).replace("_", " ")
        headline = (
            f"{cand.get('region_name')} — {label} fit ({float(cand.get('score', 0)):.0f}/100) for "
            f"{data.get('regional_nights', '?')} regional nights from {data.get('arrival_city') or 'your arrival city'}."
        )
        explanations.append(
            {
                "region_code": cand.get("region_code"),
                "headline": headline[:240],
                "reasons": reasons[:6],
                "tradeoffs": tradeoffs[:6],
                "rejected_reasons": rejected[:6],
                "evidence_ids": evidence,
            }
        )

    route = data.get("suggested_route") or {}
    return schema.model_validate(
        {
            "explanations": explanations,
            "suggested_route_summary": route.get("summary"),
            "suggested_route_stops": route.get("stops", [])[:10],
            "suggested_route_nights": route.get("nights", [])[:10],
            "unknowns": data.get("unknowns", [])[:8],
        }
    )


def _demo_critique(data: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    issues = data.get("issues") or []
    narratives = {
        str(i.get("issue_key") or i.get("rule_id")): str(i.get("explanation", ""))[:600]
        for i in issues
        if i.get("rule_id")
    }
    revision = data.get("candidate_revisions", [{}])
    chosen = revision[0] if revision else {}
    criticals = [i for i in issues if i.get("severity") == "critical"]
    warnings = [i for i in issues if i.get("severity") == "warning"]

    if criticals:
        summary = (
            f"{len(criticals)} critical problem(s) and {len(warnings)} warning(s). "
            f"The biggest is: {criticals[0].get('title')}."
        )
    elif warnings:
        summary = f"No blocking problems, but {len(warnings)} thing(s) would make this trip better."
    else:
        summary = "This itinerary holds up: travel load, stay lengths and connections are all inside sensible limits."

    return schema.model_validate(
        {
            "health_summary": summary[:600],
            "issue_narratives": narratives,
            "revised_stops": chosen.get("stops", [])[:15],
            "revised_nights": chosen.get("nights", [])[:15],
            "revision_summary": str(chosen.get("summary", ""))[:600],
            "gained": chosen.get("gained", [])[:6],
            "lost": chosen.get("lost", [])[:6],
            "unknowns": data.get("unknowns", [])[:8],
            "evidence_ids": data.get("evidence_ids", [])[:15],
        }
    )


def _demo_grounding(data: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    available = set(data.get("available_evidence_ids", []))
    cited = set(data.get("cited_evidence_ids", []))
    dangling = sorted(cited - available)
    return schema.model_validate(
        {
            "grounded": not dangling,
            "unsupported_claims": [],
            "missing_citations": dangling[:10],
            "notes": "Deterministic citation check only (demo LLM judge).",
        }
    )


def _demo_rerank(data: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    items = data.get("evidence") or []
    ordered = [e.get("evidence_id") for e in items if e.get("evidence_id")]
    return schema.model_validate(
        {"ranked_evidence_ids": ordered[:40], "reasoning": "Demo reranker preserved fusion order."}
    )


def _demo_admin_answer(data: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    findings = data.get("findings") or []
    lines = [f"- {f.get('subject')}: {f.get('issue')}" for f in findings[:20]]
    return schema.model_validate(
        {
            "summary": (
                f"{len(findings)} record(s) need attention."
                if findings
                else "No stale or conflicting records matched that query."
            ),
            "findings": findings[:20],
            "suggested_actions": [
                "Open each record in the evidence inspector and confirm against the official source.",
                "Record the verified value with today's date so the freshness clock resets.",
            ]
            if findings
            else [],
            "detail": "\n".join(lines)[:2000],
        }
    )


_DEMO_HANDLERS = {
    "ExtractedItinerary": _demo_extracted_itinerary,
    "ComparisonOutput": _demo_comparison,
    "CritiqueOutput": _demo_critique,
    "GroundingVerdict": _demo_grounding,
    "RerankVerdict": _demo_rerank,
    "AdminAssistantAnswer": _demo_admin_answer,
}


# ---------------------------------------------------------------------------
# Live providers
# ---------------------------------------------------------------------------
class AnthropicLLMProvider:
    """Anthropic Messages API with native structured output."""

    name = "anthropic"
    is_demo = False

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for the Anthropic provider")
        import anthropic

        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )
        self._settings = settings
        self._breaker = CircuitBreaker("anthropic")
        self._policy = RetryPolicy(max_attempts=settings.llm_max_retries + 1)

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[BaseModel, LLMUsage]:
        model = model or self._settings.llm_model_reasoning
        started = time.perf_counter()

        async def _call():
            return await self._client.messages.parse(
                model=model,
                max_tokens=max_tokens or 16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )

        resp = await call_with_resilience(
            _call,
            name="anthropic",
            timeout=self._settings.llm_timeout_seconds,
            policy=self._policy,
            breaker=self._breaker,
        )
        parsed = resp.parsed_output
        if parsed is None:
            raise SchemaRepairFailed(
                "Anthropic returned no parsed output", details={"model": model}
            )
        usage = LLMUsage(
            model=model,
            provider=self.name,
            prompt_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        usage.estimated_cost_usd = estimate_cost_usd(
            model, usage.prompt_tokens, usage.completion_tokens
        )
        return parsed, usage

    async def complete_text(
        self, *, system: str, user: str, model: str | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        model = model or self._settings.llm_model_fast
        started = time.perf_counter()

        async def _call():
            return await self._client.messages.create(
                model=model,
                max_tokens=max_tokens or 4000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

        resp = await call_with_resilience(
            _call,
            name="anthropic",
            timeout=self._settings.llm_timeout_seconds,
            policy=self._policy,
            breaker=self._breaker,
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        usage = LLMUsage(
            model=model,
            provider=self.name,
            prompt_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        usage.estimated_cost_usd = estimate_cost_usd(
            model, usage.prompt_tokens, usage.completion_tokens
        )
        return LLMResult(text=text, usage=usage)


class OpenAILLMProvider:
    """OpenAI Chat Completions with JSON-schema structured output."""

    name = "openai"
    is_demo = False

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds
        )
        self._settings = settings
        self._breaker = CircuitBreaker("openai")
        self._policy = RetryPolicy(max_attempts=settings.llm_max_retries + 1)

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[BaseModel, LLMUsage]:
        model = model or self._settings.llm_model_reasoning
        started = time.perf_counter()

        async def _call():
            return await self._client.beta.chat.completions.parse(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=schema,
                temperature=temperature
                if temperature is not None
                else self._settings.llm_temperature,
                max_tokens=max_tokens or 8000,
            )

        resp = await call_with_resilience(
            _call,
            name="openai",
            timeout=self._settings.llm_timeout_seconds,
            policy=self._policy,
            breaker=self._breaker,
        )
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            raise SchemaRepairFailed("OpenAI returned no parsed output", details={"model": model})
        usage = LLMUsage(
            model=model,
            provider=self.name,
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        usage.estimated_cost_usd = estimate_cost_usd(
            model, usage.prompt_tokens, usage.completion_tokens
        )
        return parsed, usage

    async def complete_text(
        self, *, system: str, user: str, model: str | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        model = model or self._settings.llm_model_fast
        started = time.perf_counter()

        async def _call():
            return await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens or 2000,
            )

        resp = await call_with_resilience(
            _call,
            name="openai",
            timeout=self._settings.llm_timeout_seconds,
            policy=self._policy,
            breaker=self._breaker,
        )
        usage = LLMUsage(
            model=model,
            provider=self.name,
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        usage.estimated_cost_usd = estimate_cost_usd(
            model, usage.prompt_tokens, usage.completion_tokens
        )
        return LLMResult(text=resp.choices[0].message.content or "", usage=usage)


class FallbackLLMProvider:
    """Primary provider with an automatic secondary.

    A failure of the primary after its own bounded retries is not a request
    failure: the secondary runs and the usage record is tagged ``fell_back``.
    """

    is_demo = False

    def __init__(self, primary: Any, secondary: Any) -> None:
        self._primary = primary
        self._secondary = secondary
        self.name = f"{primary.name}->{secondary.name}"
        self.is_demo = bool(getattr(primary, "is_demo", False))

    async def complete_structured(self, **kwargs: Any) -> tuple[BaseModel, LLMUsage]:
        try:
            return await self._primary.complete_structured(**kwargs)
        except Exception as exc:
            log.warning(
                "llm.primary_failed_falling_back", primary=self._primary.name, error=str(exc)
            )
            obj, usage = await self._secondary.complete_structured(**kwargs)
            usage.fell_back = True
            return obj, usage

    async def complete_text(self, **kwargs: Any) -> LLMResult:
        try:
            return await self._primary.complete_text(**kwargs)
        except Exception as exc:
            log.warning(
                "llm.primary_failed_falling_back", primary=self._primary.name, error=str(exc)
            )
            result = await self._secondary.complete_text(**kwargs)
            result.usage.fell_back = True
            return result


# ---------------------------------------------------------------------------
# routing + schema repair
# ---------------------------------------------------------------------------
class ModelRouter:
    """Chooses a model per task class, per the documented routing policy."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def model_for(self, task: str) -> str:
        tier = ROUTING_POLICY.get(task, "fast")
        return (
            self._settings.llm_model_reasoning
            if tier == "reasoning"
            else self._settings.llm_model_fast
        )

    def tier_for(self, task: str) -> str:
        return ROUTING_POLICY.get(task, "fast")


async def complete_with_repair(
    provider: Any,
    *,
    system: str,
    user: str,
    schema: type[SchemaT],
    model: str | None,
    repair_model: str | None = None,
    max_repairs: int = 1,
) -> tuple[SchemaT, list[LLMUsage]]:
    """Call the model, and on schema-validation failure retry *once* with the
    validation error appended. Bounded on purpose — an endless repair loop is a
    cost incident, not resilience.
    """
    usages: list[LLMUsage] = []
    last_error: Exception | None = None
    attempt_user = user
    for attempt in range(max_repairs + 1):
        try:
            obj, usage = await provider.complete_structured(
                system=system,
                user=attempt_user,
                schema=schema,
                model=model if attempt == 0 else (repair_model or model),
            )
            usages.append(usage)
            return cast("SchemaT", obj), usages
        except (ValidationError, SchemaRepairFailed) as exc:
            last_error = exc
            log.warning(
                "llm.schema_invalid",
                schema=schema.__name__,
                attempt=attempt + 1,
                error=str(exc)[:400],
            )
            attempt_user = (
                f"{user}\n\nYour previous response did not validate against the required schema.\n"
                f"Validation error:\n{str(exc)[:1500]}\n"
                "Return ONLY a valid instance of the schema. Do not add fields."
            )
    raise SchemaRepairFailed(
        f"{schema.__name__} could not be produced after {max_repairs + 1} attempts",
        details={"schema": schema.__name__, "cause": str(last_error)[:500]},
    )


def build_llm_provider(settings: Settings) -> Any:
    demo = DemoLLMProvider(settings)
    primary: Any
    if settings.llm_provider == "anthropic":
        try:
            primary = AnthropicLLMProvider(settings)
        except Exception as exc:
            log.warning("llm.anthropic_unavailable_falling_back", error=str(exc))
            return demo
    elif settings.llm_provider == "openai":
        try:
            primary = OpenAILLMProvider(settings)
        except Exception as exc:
            log.warning("llm.openai_unavailable_falling_back", error=str(exc))
            return demo
    else:
        return demo

    secondary: Any = demo
    if settings.llm_fallback_provider == "anthropic" and settings.anthropic_api_key:
        try:
            secondary = AnthropicLLMProvider(settings)
        except Exception:
            secondary = demo
    elif settings.llm_fallback_provider == "openai" and settings.openai_api_key:
        try:
            secondary = OpenAILLMProvider(settings)
        except Exception:
            secondary = demo
    return FallbackLLMProvider(primary, secondary)
