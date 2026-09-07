"""Chunking, via LangChain text splitters.

Two strategies, chosen by document shape:

* ``RecursiveCharacterTextSplitter`` for prose — splits on paragraph, then
  sentence, then word boundaries, so a chunk rarely ends mid-fact.
* A heading-aware pre-split for structured pages, so an "Access" section and a
  "Booking" section never end up in the same chunk. Mixing them is what produces
  the classic RAG failure where a booking rule is attributed to the wrong leg.

Metadata is attached at chunk level, not document level, because retrieval
filters on it: region, place, topic, transport mode, applicable months, trust,
official flag and verification date all travel with the chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from jst_api.domain.enums import EvidenceTopic, TrustLevel

CHUNK_SIZE = 900
CHUNK_OVERLAP = 140

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,4}\s+.+|[A-Z][A-Za-z /&'-]{3,60}:)\s*$", re.MULTILINE)

#: Heading keyword -> topic. Lets the chunker label sections without an LLM call.
TOPIC_HINTS: list[tuple[re.Pattern[str], EvidenceTopic]] = [
    (
        re.compile(r"\b(access|getting there|transport|train|bus|shuttle|ferry|drive|car)\b", re.I),
        EvidenceTopic.TRANSPORT_ACCESS,
    ),
    (re.compile(r"\b(book|booking|reserv|advance|ticket|pass)\b", re.I), EvidenceTopic.BOOKING),
    (
        re.compile(r"\b(season|winter|summer|autumn|spring|snow|closed|closure|festival)\b", re.I),
        EvidenceTopic.SEASONAL,
    ),
    (re.compile(r"\b(luggage|suitcase|baggage|takkyubin|locker)\b", re.I), EvidenceTopic.LUGGAGE),
    (
        re.compile(r"\b(accessib|barrier[- ]free|step[- ]free|wheelchair|elevator)\b", re.I),
        EvidenceTopic.ACCESSIBILITY,
    ),
    (re.compile(r"\b(price|cost|fare|yen|¥|budget)\b", re.I), EvidenceTopic.COST),
]

MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
SEASON_MONTHS = {
    "winter": [12, 1, 2],
    "spring": [3, 4, 5],
    "summer": [6, 7, 8],
    "autumn": [9, 10, 11],
    "fall": [9, 10, 11],
}


@dataclass
class ChunkMetadata:
    source_id: str
    region_code: str | None = None
    place_slug: str | None = None
    topic: EvidenceTopic = EvidenceTopic.GENERAL
    transport_mode: str | None = None
    season_months: list[int] = field(default_factory=list)
    trust_level: TrustLevel = TrustLevel.SECONDARY
    official_source: bool = False
    verified_at: datetime | None = None
    is_demo: bool = True
    document_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "document_id": self.document_id,
            "region_code": self.region_code,
            "place_slug": self.place_slug,
            "topic": self.topic.value,
            "transport_mode": self.transport_mode,
            "season_months": self.season_months,
            "trust_level": self.trust_level.value,
            "official_source": self.official_source,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "is_demo": self.is_demo,
        }


def infer_topic(text: str, default: EvidenceTopic = EvidenceTopic.GENERAL) -> EvidenceTopic:
    scores: dict[EvidenceTopic, int] = {}
    for pattern, topic in TOPIC_HINTS:
        hits = len(pattern.findall(text))
        if hits:
            scores[topic] = scores.get(topic, 0) + hits
    if not scores:
        return default
    return max(scores.items(), key=lambda kv: kv[1])[0]


def infer_season_months(text: str) -> list[int]:
    lowered = text.lower()
    months: set[int] = set()
    for name, num in MONTH_NAMES.items():
        if re.search(rf"\b{name}\b", lowered):
            months.add(num)
    for season, nums in SEASON_MONTHS.items():
        if re.search(rf"\b{season}\b", lowered):
            months.update(nums)
    return sorted(months)


def split_by_headings(text: str) -> list[str]:
    """Split on headings, keeping the heading with its section."""
    matches = list(_HEADING_RE.finditer(text))
    if len(matches) < 2:
        return [text]
    sections: list[str] = []
    if matches[0].start() > 0:
        sections.append(text[: matches[0].start()])
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(text[match.start() : end])
    return [s.strip() for s in sections if s.strip()]


def build_splitter(
    chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", "。", "! ", "? ", "; ", ", ", " ", ""],
        length_function=len,
        keep_separator=True,
    )


def chunk_document(
    text: str,
    metadata: ChunkMetadata,
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Document]:
    """Heading-aware split, then recursive character split inside each section."""
    splitter = build_splitter(chunk_size, overlap)
    documents: list[Document] = []
    index = 0
    for section in split_by_headings(text):
        section_topic = infer_topic(section, metadata.topic)
        section_months = infer_season_months(section) or metadata.season_months
        for piece in splitter.split_text(section):
            body = piece.strip()
            if len(body) < 40:
                continue
            md = metadata.as_dict()
            md.update(
                {
                    "topic": section_topic.value,
                    "season_months": section_months,
                    "chunk_index": index,
                }
            )
            documents.append(Document(page_content=body, metadata=md))
            index += 1
    return documents


def build_search_text(content: str, metadata: dict[str, object]) -> str:
    """The lexical surface indexed for full-text/BM25 search.

    Region, place and topic are appended so a keyword query like "Tohoku
    shuttle" matches a chunk whose body never spells out the region name.
    """
    extras = [
        str(metadata.get("region_code") or ""),
        str(metadata.get("place_slug") or "").replace("-", " "),
        str(metadata.get("topic") or ""),
        str(metadata.get("transport_mode") or ""),
    ]
    return " ".join([content, *[e for e in extras if e]])
