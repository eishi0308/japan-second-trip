"""Document loading and cleaning, on LangChain's ``Document`` abstraction.

Sources are admin-supplied and allowlisted. Nothing crawls, nothing follows
links, and robots/ToS compliance is the admin's declaration at the point of
adding a source. Three loaders:

``UrlLoader``    fetch one approved https URL, extract readable text
``TextLoader``   an admin-pasted note or an operator email transcript
``SeedLoader``   the bundled demo corpus, marked ``is_demo`` at every layer
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from langchain_core.documents import Document

from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.core.resilience import RetryPolicy, call_with_resilience
from jst_api.security.allowlist import assert_ingestable, domain_of
from jst_api.security.injection import neutralise, scan_for_injection

log = get_logger(__name__)

_WS_RE = re.compile(r"[ \t]+")
_BLANKS_RE = re.compile(r"\n{3,}")

DROP_TAGS = (
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "noscript",
    "iframe",
    "svg",
)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_html(html: str) -> tuple[str, str | None]:
    """Return (readable text, page title)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(DROP_TAGS)):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None

    parts: list[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "dd", "dt"]):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name in {"h1", "h2", "h3", "h4"}:
            parts.append(f"\n## {text}\n")
        elif element.name == "li":
            parts.append(f"- {text}")
        else:
            parts.append(text)
    body = "\n".join(parts) if parts else soup.get_text("\n", strip=True)
    return normalise_whitespace(body), title


def normalise_whitespace(text: str) -> str:
    return _BLANKS_RE.sub("\n\n", _WS_RE.sub(" ", text)).strip()


@dataclass
class LoadedDocument:
    document: Document
    raw: str
    cleaned: str
    hash: str
    title: str | None
    domain: str | None
    injection_flags: list[str]


class UrlLoader:
    """Fetch one approved URL. Never follows links, never crawls."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._policy = RetryPolicy(max_attempts=settings.external_max_retries + 1)

    async def load(self, url: str, *, metadata: dict[str, Any] | None = None) -> LoadedDocument:
        domain = assert_ingestable(url, self._settings.ingest_domain_allowlist)

        async def _fetch() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self._settings.external_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "JapanSecondTrip/0.1 (+admin-approved ingestion)"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp

        response = await call_with_resilience(
            _fetch,
            name=f"ingest:{domain}",
            timeout=self._settings.external_timeout_seconds,
            policy=self._policy,
        )
        raw = response.text
        cleaned, title = clean_html(raw)
        scan = scan_for_injection(cleaned)
        if scan.suspicious:
            log.warning("ingest.suspicious_content", url=url, rules=scan.matched_rules)
            cleaned = neutralise(cleaned)

        md = {
            "source_url": url,
            "domain": domain,
            "title": title,
            "fetched_at": datetime.now(UTC).isoformat(),
            **(metadata or {}),
        }
        return LoadedDocument(
            document=Document(page_content=cleaned, metadata=md),
            raw=raw,
            cleaned=cleaned,
            hash=content_hash(cleaned),
            title=title,
            domain=domain,
            injection_flags=scan.matched_rules,
        )


class TextLoader:
    """An admin-pasted note, operator reply, or manually transcribed timetable."""

    async def load(
        self, text: str, *, title: str, metadata: dict[str, Any] | None = None
    ) -> LoadedDocument:
        cleaned = normalise_whitespace(text)
        scan = scan_for_injection(cleaned)
        if scan.suspicious:
            cleaned = neutralise(cleaned)
        md = {"title": title, "fetched_at": datetime.now(UTC).isoformat(), **(metadata or {})}
        return LoadedDocument(
            document=Document(page_content=cleaned, metadata=md),
            raw=text,
            cleaned=cleaned,
            hash=content_hash(cleaned),
            title=title,
            domain=domain_of(str(md.get("source_url", ""))) or None,
            injection_flags=scan.matched_rules,
        )
