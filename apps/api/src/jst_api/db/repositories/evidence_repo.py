"""Evidence retrieval SQL — the only place dialect differences live.

Two independent retrieval signals over the *same* rows:

**Dense** — cosine similarity over the ``embedding`` column. On PostgreSQL this
is pgvector's ``<=>`` operator backed by an HNSW index. On SQLite the filtered
candidate set is scored in NumPy. Same ordering semantics, different execution.

**Lexical** — on PostgreSQL, ``ts_rank_cd`` over a GIN-indexed ``tsvector``,
unioned with trigram similarity so proper nouns the English dictionary does not
know ("Ginzan", "Yamadera", "Hirosaki") still match. On SQLite, Okapi BM25 over
the filtered candidate set.

Hard metadata filters (region, place, topic, trust, verification age, season)
are applied *before* either search runs, so retrieval never has to rank away
rows that were structurally disqualified.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import ColumnElement, Select, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.db.models import EvidenceChunk, Source
from jst_api.domain.enums import TrustLevel

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Ceiling on rows pulled into memory for the SQLite scoring path. Keeps the
#: offline mode honest about being a development/test fallback.
SQLITE_CANDIDATE_CAP = 4000

BM25_K1 = 1.5
BM25_B = 0.75


@dataclass
class EvidenceFilters:
    """Structured pre-filters. Every field is optional; all supplied fields AND together."""

    region_codes: list[str] = field(default_factory=list)
    place_slugs: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    transport_modes: list[str] = field(default_factory=list)
    season_month: int | None = None
    min_trust: TrustLevel | None = None
    official_only: bool = False
    verified_within_days: int | None = None
    exclude_demo: bool = False

    def is_empty(self) -> bool:
        return not any(
            [
                self.region_codes,
                self.place_slugs,
                self.topics,
                self.transport_modes,
                self.season_month,
                self.min_trust,
                self.official_only,
                self.verified_within_days,
                self.exclude_demo,
            ]
        )

    def cache_payload(self) -> dict[str, object]:
        return {
            "region": sorted(self.region_codes),
            "place": sorted(self.place_slugs),
            "topic": sorted(self.topics),
            "mode": sorted(self.transport_modes),
            "month": self.season_month,
            "trust": self.min_trust.value if self.min_trust else None,
            "official": self.official_only,
            "within": self.verified_within_days,
            "no_demo": self.exclude_demo,
        }


@dataclass
class ScoredChunk:
    chunk: EvidenceChunk
    source: Source
    score: float
    rank: int


_TRUST_ORDER = {TrustLevel.UNVERIFIED: 0, TrustLevel.SECONDARY: 1, TrustLevel.PRIMARY: 2}


def _apply_filters(stmt: Select, filters: EvidenceFilters) -> Select:
    conditions: list[ColumnElement[bool]] = []
    if filters.region_codes:
        conditions.append(EvidenceChunk.region_code.in_(filters.region_codes))
    if filters.place_slugs:
        conditions.append(
            or_(
                EvidenceChunk.place_slug.in_(filters.place_slugs),
                EvidenceChunk.place_slug.is_(None),
            )
        )
    if filters.topics:
        conditions.append(EvidenceChunk.topic.in_(filters.topics))
    if filters.transport_modes:
        conditions.append(
            or_(
                EvidenceChunk.transport_mode.in_(filters.transport_modes),
                EvidenceChunk.transport_mode.is_(None),
            )
        )
    if filters.official_only:
        conditions.append(EvidenceChunk.official_source.is_(True))
    if filters.min_trust is not None:
        allowed = [
            t.value for t, order in _TRUST_ORDER.items() if order >= _TRUST_ORDER[filters.min_trust]
        ]
        conditions.append(EvidenceChunk.trust_level.in_(allowed))
    if filters.verified_within_days is not None:
        cutoff = datetime.now(tz=None) - timedelta(days=filters.verified_within_days)
        conditions.append(EvidenceChunk.verified_at.is_not(None))
        conditions.append(EvidenceChunk.verified_at >= cutoff)
    if filters.exclude_demo:
        conditions.append(EvidenceChunk.is_demo.is_(False))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _season_ok(chunk: EvidenceChunk, month: int | None) -> bool:
    """Season filtering is applied in Python because ``season_months`` is a JSON
    array and the semantics ("empty means all year") are the same on both
    dialects."""
    if month is None:
        return True
    months = chunk.season_months or []
    return not months or month in months


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._dialect = session.bind.dialect.name if session.bind is not None else "sqlite"

    @property
    def dialect(self) -> str:
        return self._dialect

    # -- dense --------------------------------------------------------------
    async def dense_search(
        self, embedding: list[float], *, k: int, filters: EvidenceFilters | None = None
    ) -> list[ScoredChunk]:
        filters = filters or EvidenceFilters()
        if self._dialect == "postgresql":
            return await self._dense_pg(embedding, k=k, filters=filters)
        return await self._dense_python(embedding, k=k, filters=filters)

    async def _dense_pg(
        self, embedding: list[float], *, k: int, filters: EvidenceFilters
    ) -> list[ScoredChunk]:
        distance = EvidenceChunk.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(EvidenceChunk, Source, distance)
            .join(Source, Source.id == EvidenceChunk.source_id)
            .where(EvidenceChunk.embedding.is_not(None))
        )
        stmt = _apply_filters(stmt, filters).order_by(distance).limit(k * 3)
        rows = (await self._session.execute(stmt)).all()
        out: list[ScoredChunk] = []
        for chunk, source, dist in rows:
            if not _season_ok(chunk, filters.season_month):
                continue
            out.append(ScoredChunk(chunk=chunk, source=source, score=1.0 - float(dist), rank=0))
            if len(out) >= k:
                break
        for i, item in enumerate(out, start=1):
            item.rank = i
        return out

    async def _dense_python(
        self, embedding: list[float], *, k: int, filters: EvidenceFilters
    ) -> list[ScoredChunk]:
        stmt = (
            select(EvidenceChunk, Source)
            .join(Source, Source.id == EvidenceChunk.source_id)
            .where(EvidenceChunk.embedding.is_not(None))
        )
        raw = (
            await self._session.execute(_apply_filters(stmt, filters).limit(SQLITE_CANDIDATE_CAP))
        ).all()
        rows: list[tuple[EvidenceChunk, Source]] = [
            (chunk, source) for chunk, source in raw if _season_ok(chunk, filters.season_month)
        ]
        if not rows:
            return []
        query = np.asarray(embedding, dtype=np.float64)
        qnorm = np.linalg.norm(query) or 1.0
        matrix = np.asarray([c.embedding for c, _ in rows], dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        scores = (matrix @ query) / (norms * qnorm)
        order = np.argsort(-scores)[:k]
        return [
            ScoredChunk(chunk=rows[i][0], source=rows[i][1], score=float(scores[i]), rank=rank)
            for rank, i in enumerate(order, start=1)
        ]

    # -- lexical ------------------------------------------------------------
    async def keyword_search(
        self, query: str, *, k: int, filters: EvidenceFilters | None = None
    ) -> list[ScoredChunk]:
        filters = filters or EvidenceFilters()
        if not query.strip():
            return []
        if self._dialect == "postgresql":
            return await self._keyword_pg(query, k=k, filters=filters)
        return await self._keyword_bm25(query, k=k, filters=filters)

    @staticmethod
    def _or_tsquery_text(query: str) -> str:
        """Build an OR tsquery from a natural-language question.

        ``plainto_tsquery`` ANDs every term, which is fatal here. "should I buy a
        rail pass for a single region" becomes ``buy & rail & pass & singl &
        region``, and a document missing any single word scores zero — measured
        on the golden set, ``ts_rank_cd`` returned 0 for *every* document on that
        query, so lexical search contributed nothing at all.

        ORing the terms lets partial matches through, and ``ts_rank_cd`` already
        ranks a document matching more terms higher. It also matches the
        SQLite BM25 fallback's semantics, bringing the two dialects into line.

        Tokens are reduced to alphanumerics before joining, so nothing reaching
        ``to_tsquery`` can be tsquery syntax.
        """
        tokens = [t for t in _TOKEN_RE.findall(query.lower()) if len(t) > 1]
        return " | ".join(dict.fromkeys(tokens))

    async def _keyword_pg(
        self, query: str, *, k: int, filters: EvidenceFilters
    ) -> list[ScoredChunk]:
        or_terms = self._or_tsquery_text(query)
        if not or_terms:
            return []
        tsquery = func.to_tsquery("english", or_terms)
        tsvector = func.to_tsvector("english", EvidenceChunk.search_text)
        rank = func.ts_rank_cd(tsvector, tsquery)
        # Proper nouns ("Ginzan", "Yamadera") often miss the English dictionary,
        # so trigram similarity is unioned in as a second lexical signal.
        similarity = func.similarity(EvidenceChunk.search_text, query)
        combined = (rank + similarity * 0.5).label("lexical_score")
        stmt = (
            select(EvidenceChunk, Source, combined)
            .join(Source, Source.id == EvidenceChunk.source_id)
            .where(or_(tsvector.op("@@")(tsquery), similarity > 0.08))
        )
        stmt = _apply_filters(stmt, filters).order_by(text("lexical_score DESC")).limit(k * 3)
        rows = (await self._session.execute(stmt)).all()
        out: list[ScoredChunk] = []
        for chunk, source, score in rows:
            if not _season_ok(chunk, filters.season_month):
                continue
            out.append(ScoredChunk(chunk=chunk, source=source, score=float(score), rank=0))
            if len(out) >= k:
                break
        for i, item in enumerate(out, start=1):
            item.rank = i
        return out

    async def _keyword_bm25(
        self, query: str, *, k: int, filters: EvidenceFilters
    ) -> list[ScoredChunk]:
        stmt = select(EvidenceChunk, Source).join(Source, Source.id == EvidenceChunk.source_id)
        raw = (
            await self._session.execute(_apply_filters(stmt, filters).limit(SQLITE_CANDIDATE_CAP))
        ).all()
        rows: list[tuple[EvidenceChunk, Source]] = [
            (chunk, source) for chunk, source in raw if _season_ok(chunk, filters.season_month)
        ]
        if not rows:
            return []

        docs = [_TOKEN_RE.findall(c.search_text.lower()) for c, _ in rows]
        n = len(docs)
        avgdl = sum(len(d) for d in docs) / n if n else 1.0
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(set(doc))

        q_terms = _TOKEN_RE.findall(query.lower())
        scored: list[tuple[float, int]] = []
        for i, doc in enumerate(docs):
            tf = Counter(doc)
            dl = len(doc) or 1
            score = 0.0
            for term in q_terms:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += (
                    idf * (f * (BM25_K1 + 1)) / (f + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl))
                )
            if score > 0:
                scored.append((score, i))

        scored.sort(key=lambda t: (-t[0], t[1]))
        return [
            ScoredChunk(chunk=rows[i][0], source=rows[i][1], score=score, rank=rank)
            for rank, (score, i) in enumerate(scored[:k], start=1)
        ]

    # -- direct lookups -----------------------------------------------------
    async def get_by_ids(self, evidence_ids: list[str]) -> list[tuple[EvidenceChunk, Source]]:
        if not evidence_ids:
            return []
        stmt = (
            select(EvidenceChunk, Source)
            .join(Source, Source.id == EvidenceChunk.source_id)
            .where(EvidenceChunk.id.in_(evidence_ids))
        )
        rows = (await self._session.execute(stmt)).all()
        return [(chunk, source) for chunk, source in rows]

    async def count(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(EvidenceChunk)) or 0)

    async def stale_evidence(
        self, *, older_than_days: int, limit: int = 100
    ) -> list[tuple[EvidenceChunk, Source]]:
        cutoff = datetime.now(tz=None) - timedelta(days=older_than_days)
        stmt = (
            select(EvidenceChunk, Source)
            .join(Source, Source.id == EvidenceChunk.source_id)
            .where(or_(EvidenceChunk.verified_at.is_(None), EvidenceChunk.verified_at < cutoff))
            .order_by(EvidenceChunk.verified_at.asc().nulls_first())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(chunk, source) for chunk, source in rows]
