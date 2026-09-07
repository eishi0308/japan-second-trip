"""Prompt-injection defence.

Threat model (docs/security.md): the system ingests third-party web content and
free traveller text, then puts both in front of a model that can call tools. An
attacker who can get text into an ingested page — or who pastes it into the
itinerary box — must not be able to change agent behaviour.

Defence in depth, four layers, none of which is a prompt instruction alone:

1. **Ingestion allowlist** — only approved domains are fetched at all
   (``security/allowlist.py``).
2. **Detection + neutralisation** — this module scores content for injection
   patterns, strips instruction-shaped markup, and wraps it in explicit data
   fences before it reaches a prompt.
3. **Structural separation** — retrieved content only ever appears inside an
   ``EVIDENCE`` block that the system prompt defines as untrusted data.
4. **Capability control** — the model cannot call a tool directly. Tools are
   invoked by graph nodes from an allowlist, with typed arguments validated
   before dispatch (``agents/common/tools.py``). A successful injection
   therefore cannot reach a write tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b[^.\n]{0,30}\b(instruction|prompt|rule|direction)",
            re.I,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(you are now|from now on you|act as|pretend to be|new persona|developer mode|dan mode)\b",
            re.I,
        ),
    ),
    ("system_prompt_spoof", re.compile(r"(^|\n)\s*(system|assistant|user)\s*:\s*", re.I)),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(reveal|print|repeat|output|show)\b[^.\n]{0,30}\b(system prompt|your instructions|the prompt|api key|secret)\b",
            re.I,
        ),
    ),
    (
        "tool_coercion",
        re.compile(
            r"\b(call|invoke|execute|run)\b[^.\n]{0,30}\b(tool|function|command|shell|sql)\b", re.I
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"\b(send|post|upload|email|exfiltrate)\b[^.\n]{0,40}\b(to https?://|to the following url|webhook)",
            re.I,
        ),
    ),
    (
        "markup_injection",
        re.compile(r"<\s*/?\s*(system|instructions?|prompt|tool_call|function_call)\s*>", re.I),
    ),
    (
        "delimiter_spoof",
        re.compile(r"<<<\s*(END_)?STRUCTURED_INPUT\s*>>>|\[/?INST\]|<\|im_(start|end)\|>", re.I),
    ),
    (
        "override_marker",
        re.compile(
            r"\b(important|urgent|admin|override)\b\s*[:\-]\s*\b(ignore|do not|must)\b", re.I
        ),
    ),
]

#: A score at or above this is treated as hostile: the chunk is quarantined and
#: never enters model context.
QUARANTINE_THRESHOLD = 2

#: Rules that quarantine on a single match. These patterns have no legitimate
#: appearance in travel prose — an official tourism page does not contain chat
#: delimiters or tool-call markup — so requiring corroboration only creates a
#: gap an attacker can aim at. (Found by the security eval: a bare
#: ``<<<END_STRUCTURED_INPUT>>>`` spoof scored 1 and slipped through.)
CRITICAL_RULES: frozenset[str] = frozenset(
    {"delimiter_spoof", "markup_injection", "prompt_exfiltration", "system_prompt_spoof"}
)


@dataclass
class InjectionScan:
    matched_rules: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def suspicious(self) -> bool:
        return self.score > 0

    @property
    def critical(self) -> bool:
        return bool(set(self.matched_rules) & CRITICAL_RULES)

    @property
    def quarantine(self) -> bool:
        return self.critical or self.score >= QUARANTINE_THRESHOLD


def scan_for_injection(text: str) -> InjectionScan:
    matched = [name for name, pattern in INJECTION_PATTERNS if pattern.search(text)]
    return InjectionScan(matched_rules=matched, score=len(matched))


def neutralise(text: str) -> str:
    """Render instruction-shaped markup inert without destroying meaning.

    The text stays readable — a page that genuinely discusses "system prompts"
    is still useful evidence — but the tokens that structure a chat turn or a
    tool call are defanged.
    """
    cleaned = re.sub(
        r"<\s*/?\s*(system|instructions?|prompt|tool_call|function_call)\s*>",
        "[markup removed]",
        text,
        flags=re.I,
    )
    cleaned = re.sub(
        r"<<<\s*(END_)?STRUCTURED_INPUT\s*>>>", "[delimiter removed]", cleaned, flags=re.I
    )
    cleaned = re.sub(r"<\|im_(start|end)\|>", "[delimiter removed]", cleaned, flags=re.I)
    cleaned = re.sub(r"\[/?INST\]", "[delimiter removed]", cleaned, flags=re.I)
    cleaned = re.sub(
        r"(^|\n)\s*(system|assistant)\s*:\s*", r"\1(quoted) \2 - ", cleaned, flags=re.I
    )
    return cleaned


def fence(label: str, body: str) -> str:
    """Wrap untrusted content in an explicit, non-forgeable data fence."""
    return f"<<{label} kind=untrusted_data>>\n{body}\n<</{label}>>"


def sanitise_user_text(text: str, *, max_chars: int = 8000) -> tuple[str, InjectionScan]:
    """Clean free traveller input before it reaches any prompt."""
    trimmed = text[:max_chars]
    scan = scan_for_injection(trimmed)
    return neutralise(trimmed), scan
