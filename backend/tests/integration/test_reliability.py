"""Reliability: timeouts, retries, fallbacks, caching and provider degradation.

These use a fake failing provider rather than a mocked internal, so the actual
resilience wrapper is exercised.
"""

from __future__ import annotations

import asyncio

import pytest

from jst_api.core.errors import ProviderError, ProviderTimeoutError
from jst_api.core.resilience import CircuitBreaker, RetryPolicy, call_with_resilience

pytestmark = pytest.mark.asyncio


class TestRetries:
    async def test_a_transient_failure_is_retried_then_succeeds(self):
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("reset")
            return "ok"

        result = await call_with_resilience(
            flaky, name="flaky", timeout=2.0, policy=RetryPolicy(max_attempts=4, base_delay=0.001)
        )
        assert result == "ok"
        assert attempts["n"] == 3

    async def test_retries_are_bounded(self):
        attempts = {"n": 0}

        async def always_fails():
            attempts["n"] += 1
            raise ConnectionError("down")

        with pytest.raises(ProviderError):
            await call_with_resilience(
                always_fails,
                name="dead",
                timeout=2.0,
                policy=RetryPolicy(max_attempts=3, base_delay=0.001),
            )
        assert attempts["n"] == 3, "an unbounded retry loop is an outage, not resilience"

    async def test_a_permanent_error_is_not_retried(self):
        attempts = {"n": 0}

        async def bad_request():
            attempts["n"] += 1
            raise ValueError("malformed")

        with pytest.raises(ValueError):
            await call_with_resilience(
                bad_request,
                name="bad",
                timeout=2.0,
                policy=RetryPolicy(max_attempts=3, base_delay=0.001),
            )
        assert attempts["n"] == 1, "retrying a 400 just wastes the budget"

    async def test_a_hang_is_cut_off_by_the_timeout(self):
        async def hangs():
            await asyncio.sleep(5)

        with pytest.raises(ProviderTimeoutError):
            await call_with_resilience(
                hangs,
                name="slow",
                timeout=0.05,
                policy=RetryPolicy(max_attempts=1, base_delay=0.001),
            )


class TestCircuitBreaker:
    async def test_it_opens_after_repeated_failures_and_short_circuits(self):
        breaker = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=60)
        attempts = {"n": 0}

        async def failing():
            attempts["n"] += 1
            raise ConnectionError("down")

        for _ in range(2):
            with pytest.raises(ProviderError):
                await call_with_resilience(
                    failing,
                    name="t",
                    timeout=1.0,
                    policy=RetryPolicy(max_attempts=1, base_delay=0.001),
                    breaker=breaker,
                )
        assert breaker.is_open

        before = attempts["n"]
        with pytest.raises(ProviderError, match="temporarily unavailable"):
            await call_with_resilience(failing, name="t", timeout=1.0, breaker=breaker)
        assert attempts["n"] == before, "an open circuit must not call the dependency"

    async def test_success_closes_it_again(self):
        breaker = CircuitBreaker("t", failure_threshold=2)
        breaker.record_failure()
        breaker.record_success()
        assert not breaker.is_open


class TestLLMFallback:
    async def test_a_failing_primary_falls_back_and_is_flagged(self, settings):
        from jst_api.domain.results import ExtractedItinerary
        from jst_api.providers.llm import DemoLLMProvider, FallbackLLMProvider, structured_block

        class Broken:
            name = "broken"
            is_demo = False

            async def complete_structured(self, **kwargs):
                raise ProviderError("primary is down")

            async def complete_text(self, **kwargs):
                raise ProviderError("primary is down")

        provider = FallbackLLMProvider(Broken(), DemoLLMProvider(settings))
        result, usage = await provider.complete_structured(
            system="s",
            user=structured_block({"raw_text": "Tokyo 3 nights, Sendai 2 nights"}),
            schema=ExtractedItinerary,
        )
        assert len(result.stops) == 2
        assert usage.fell_back is True, "a fallback must be visible in the trace"


class TestSchemaRepair:
    async def test_repair_is_attempted_once_then_gives_up(self, settings):
        from jst_api.core.errors import SchemaRepairFailed
        from jst_api.domain.results import ExtractedItinerary
        from jst_api.providers.llm import complete_with_repair

        attempts = {"n": 0}

        class AlwaysInvalid:
            name = "invalid"
            is_demo = True

            async def complete_structured(self, **kwargs):
                attempts["n"] += 1
                raise SchemaRepairFailed("no parsed output")

        with pytest.raises(SchemaRepairFailed):
            await complete_with_repair(
                AlwaysInvalid(),
                system="s",
                user="u",
                schema=ExtractedItinerary,
                model=None,
                max_repairs=1,
            )
        assert attempts["n"] == 2, "one repair attempt, then stop — not a cost incident"


class TestCaching:
    async def test_repeated_lookups_hit_the_cache(self):
        from jst_api.core.cache import InMemoryCache, cache_key

        cache = InMemoryCache(max_entries=10, default_ttl=60)
        key = cache_key("test", {"a": 1})
        assert await cache.get(key) is None
        await cache.set(key, {"value": 42})
        assert (await cache.get(key))["value"] == 42
        assert cache.stats["hits"] == 1 and cache.stats["misses"] == 1

    async def test_the_cache_is_bounded(self):
        from jst_api.core.cache import InMemoryCache

        cache = InMemoryCache(max_entries=3, default_ttl=60)
        for i in range(6):
            await cache.set(f"k{i}", i)
        assert cache.stats["entries"] == 3, "an unbounded cache is a memory leak"
        assert await cache.get("k0") is None, "the oldest entry is evicted"

    async def test_entries_expire(self):
        from jst_api.core.cache import InMemoryCache

        cache = InMemoryCache(default_ttl=60)
        await cache.set("k", "v", ttl=-1)
        assert await cache.get("k") is None

    async def test_keys_are_content_addressed_and_order_independent(self):
        from jst_api.core.cache import cache_key

        assert cache_key("n", {"a": 1, "b": 2}) == cache_key("n", {"b": 2, "a": 1})
        assert cache_key("n", {"a": 1}) != cache_key("n", {"a": 2})


class TestProviderDegradation:
    async def test_an_optional_tool_failure_does_not_fail_the_request(self, backend, monkeypatch):
        """A weather outage should cost a sentence of colour, not the analysis."""
        from jst_api.agents.common.tools import ToolBelt, ToolBudget
        from jst_api.observability.tracing import RunTrace
        from travel_mcp.session import TravelMcpSession

        async def broken(*args, **kwargs):
            raise ProviderError("weather provider unavailable")

        monkeypatch.setattr(backend, "get_weather_context", broken)

        async with TravelMcpSession(backend) as mcp:
            trace = RunTrace(graph_name="t", thread_id="t")
            belt = ToolBelt(session=mcp, consumer="where_next", trace=trace, budget=ToolBudget())
            result = await belt.call_optional(
                "get_weather_context", {"place_slug": "sendai", "month": 10}
            )

        assert result is None
        assert any("tool_skipped" in f for f in trace.fallbacks_used), (
            "the degradation must be traced"
        )

    async def test_the_whole_analysis_survives_a_provider_outage(
        self, analysis_service, registry, monkeypatch
    ):
        async def broken(*args, **kwargs):
            raise ProviderError("transport provider unavailable")

        monkeypatch.setattr(registry.transport, "search_transport", broken)

        run = await analysis_service.run_where_next(
            {"regional_nights": 4, "arrival_city": "Tokyo", "interests": ["food"]}
        )
        assert run.result["recommended"] is not None, (
            "the deterministic ranking does not need the provider"
        )
        assert run.result["status"] in {"complete", "needs_human_review"}


class TestIngestionEmbeddingFailure:
    """An embedding outage must cost vectors for a while, never the document."""

    TITLE = "Embedding outage fixture"
    TEXT = "The last bus from Oishida to Ginzan Onsen leaves in the late afternoon. " * 6

    @staticmethod
    def down_embeddings(attempts: dict[str, int]):
        class DownEmbeddings:
            model = "down"

            async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
                async def upstream() -> list[list[float]]:
                    attempts["n"] += 1
                    raise ConnectionError("embedding API unreachable")

                return await call_with_resilience(
                    upstream,
                    name="embeddings",
                    timeout=2.0,
                    policy=RetryPolicy(max_attempts=3, base_delay=0.001),
                )

        return DownEmbeddings()

    async def _stored(self, session_factory) -> dict[str, object]:
        from sqlalchemy import func, select

        from jst_api.db.models import EvidenceChunk, Source

        async with session_factory() as s:
            source = await s.scalar(select(Source).where(Source.title == self.TITLE))
            if source is None:
                return {"source": None}
            total = await s.scalar(
                select(func.count())
                .select_from(EvidenceChunk)
                .where(EvidenceChunk.source_id == source.id)
            )
            pending = await s.scalar(
                select(func.count())
                .select_from(EvidenceChunk)
                .where(EvidenceChunk.source_id == source.id, EvidenceChunk.embedding.is_(None))
            )
            return {"source": source, "chunks": int(total or 0), "pending": int(pending or 0)}

    async def _cleanup(self, session_factory) -> None:
        from sqlalchemy import delete, select

        from jst_api.db.models import EvidenceChunk, Source, SourceDocument

        async with session_factory() as s:
            source_id = await s.scalar(select(Source.id).where(Source.title == self.TITLE))
            if source_id:
                for model in (EvidenceChunk, SourceDocument):
                    await s.execute(delete(model).where(model.source_id == source_id))
                await s.execute(delete(Source).where(Source.id == source_id))
                await s.commit()

    async def test_the_document_is_kept_and_its_vectors_filled_in_later(
        self, session_factory, registry, settings, seeded
    ):
        from jst_api.db.repositories.evidence_repo import EvidenceRepository
        from jst_api.domain.enums import SourceType
        from jst_api.knowledge.embeddings import ProviderEmbeddings
        from jst_api.knowledge.ingest import PENDING_EMBEDDING, IngestionService
        from jst_api.knowledge.reembed import embed_pending_once

        attempts = {"n": 0}
        try:
            async with session_factory() as s:
                result = await IngestionService(
                    s, self.down_embeddings(attempts), settings
                ).ingest_text(self.TEXT, title=self.TITLE, source_type=SourceType.DEMO_SEED)
                await s.commit()

            assert attempts["n"] == 3, "the provider retries, and the retries are bounded"
            assert result.embedding_pending and result.chunks_written > 0
            stored = await self._stored(session_factory)
            assert stored["source"].status == PENDING_EMBEDDING
            assert stored["pending"] == stored["chunks"] == result.chunks_written

            # Findable by keyword straight away; invisible to dense search until it has vectors.
            async with session_factory() as s:
                hits = await EvidenceRepository(s).keyword_search("Oishida Ginzan last bus", k=20)
            assert any(hit.chunk.source_id == result.source_id for hit in hits)

            # A pass while the provider is still down changes nothing and raises.
            with pytest.raises(ProviderError):
                await embed_pending_once(session_factory, self.down_embeddings(attempts), settings)
            assert (await self._stored(session_factory))["pending"] == result.chunks_written

            # Once it is back, the next pass fills every vector and clears the status.
            filled = await embed_pending_once(
                session_factory, ProviderEmbeddings(registry.embeddings), settings
            )
            assert filled["chunks_embedded"] >= result.chunks_written
            stored = await self._stored(session_factory)
            assert stored["pending"] == 0
            assert stored["source"].status == "active"
        finally:
            await self._cleanup(session_factory)

    async def test_the_admin_can_retry_now(self, client, admin_headers):
        body = (
            await client.post("/api/v1/admin/sources/embeddings/retry", headers=admin_headers)
        ).json()
        assert set(body) == {"chunks_embedded", "sources_completed", "still_pending"}
        assert body["still_pending"] == 0


class TestReembedBackoff:
    async def test_the_interval_doubles_while_failing_and_resets_on_success(self):
        from jst_api.knowledge.reembed import next_delay

        delay = 300.0
        delays = []
        for _ in range(6):
            delay = next_delay(delay, base=300, ceiling=3600, failed=True)
            delays.append(delay)
        assert delays == [600, 1200, 2400, 3600, 3600, 3600], "bounded, never a retry storm"
        assert next_delay(delay, base=300, ceiling=3600, failed=False) == 300
