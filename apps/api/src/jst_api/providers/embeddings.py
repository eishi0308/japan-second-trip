"""Embedding providers.

Two implementations behind one interface:

``DemoEmbeddingProvider``
    A deterministic *hashing vectoriser* — signed feature hashing over word
    unigrams, word bigrams and character 4-grams, with sub-linear term
    frequency and L2 normalisation, plus a small hand-authored travel concept
    lexicon that expands query/document tokens ("without a car" → "car-free",
    "no rental", "public transport"). It is not a neural embedding and is never
    presented as one, but it produces genuine, reproducible cosine similarity
    with morphology tolerance, which is what makes the offline retrieval
    benchmark in ``/evals`` meaningful rather than decorative.

``OpenAIEmbeddingProvider``
    The production path. Batched, retried, timed out, and cached by content
    hash so re-ingesting an unchanged document costs nothing.

Both emit vectors of ``settings.embedding_dim`` so the pgvector column type
never changes between modes.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections import Counter

import numpy as np

from jst_api.core.cache import Cache, cache_key
from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.core.resilience import CircuitBreaker, RetryPolicy, call_with_resilience

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+|[぀-ヿ一-鿿]")

#: Domain concept expansion. Deliberately small, hand-authored and inspectable.
#: This is the demo provider's stand-in for the semantic generalisation a real
#: embedding model gives you for free.
CONCEPT_LEXICON: dict[str, tuple[str, ...]] = {
    "car": ("rental", "drive", "driving", "vehicle"),
    "carfree": ("public", "transport", "train", "bus", "nocar"),
    "nocar": ("carfree", "public", "transport", "walkable"),
    "public": ("train", "bus", "rail", "carfree"),
    "onsen": ("hotspring", "bath", "ryokan", "spa", "yu"),
    "ryokan": ("onsen", "inn", "accommodation", "kaiseki"),
    "shuttle": ("bus", "transfer", "pickup", "connection"),
    "luggage": ("suitcase", "bags", "takkyubin", "forwarding", "coinlocker"),
    "booking": ("reservation", "reserve", "advance", "leadtime"),
    "difficult": ("hard", "tricky", "challenging", "awkward"),
    "snow": ("winter", "ski", "powder", "closure"),
    "hiking": ("trail", "trek", "walk", "mountain"),
    "food": ("cuisine", "seafood", "sake", "market", "eat"),
    "coast": ("sea", "seaside", "island", "ferry", "port"),
    "remote": ("rural", "isolated", "infrequent", "sparse"),
    "infrequent": ("sparse", "limited", "hourly", "remote"),
    "english": ("foreigner", "language", "translation", "signage"),
    "closed": ("closure", "suspended", "seasonal", "winter"),
    "expensive": ("cost", "price", "pricey", "budget"),
}


def _tokenise(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _expand(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for tok in tokens:
        out.extend(CONCEPT_LEXICON.get(tok, ()))
    return out


def _hash_index(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


def hashing_embed(text: str, dim: int) -> list[float]:
    """Signed feature hashing with sub-linear TF weighting and L2 norm."""
    tokens = _tokenise(text)
    if not tokens:
        return [0.0] * dim
    expanded = _expand(tokens)
    features: list[str] = list(expanded)
    features += [f"{a}_{b}" for a, b in itertools.pairwise(tokens)]
    for tok in tokens:
        if len(tok) > 4:
            features += [f"#{tok[i : i + 4]}" for i in range(len(tok) - 3)]

    counts = Counter(features)
    vec = np.zeros(dim, dtype=np.float64)
    for feature, tf in counts.items():
        idx, sign = _hash_index(feature, dim)
        vec[idx] += sign * (1.0 + math.log(tf))

    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return [0.0] * dim
    return (vec / norm).tolist()


class DemoEmbeddingProvider:
    name = "demo-hash"
    is_demo = True

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.model = f"demo-hash-{dim}"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [hashing_embed(t, self.dim) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return hashing_embed(text, self.dim)


class OpenAIEmbeddingProvider:
    """Live embeddings. Requires ``OPENAI_API_KEY``.

    Vectors are cached by ``sha256(model + text)``: ingestion is the only place
    that pays for embedding, and re-running it on unchanged content is free.
    """

    name = "openai"
    is_demo = False

    def __init__(self, settings: Settings, cache: Cache | None = None) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI embedding provider")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=settings.external_timeout_seconds
        )
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self._cache = cache
        self._breaker = CircuitBreaker("openai-embeddings")
        self._policy = RetryPolicy(max_attempts=settings.external_max_retries + 1)
        self._timeout = settings.external_timeout_seconds

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        async def _call() -> list[list[float]]:
            resp = await self._client.embeddings.create(
                model=self.model, input=texts, dimensions=self.dim
            )
            return [d.embedding for d in resp.data]

        return await call_with_resilience(
            _call,
            name="openai-embeddings",
            timeout=self._timeout * 2,
            policy=self._policy,
            breaker=self._breaker,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            key = cache_key("emb", {"m": self.model, "t": text})
            hit = await self._cache.get(key) if self._cache else None
            if hit is not None:
                results[i] = hit
            else:
                pending.append((i, text))

        for start in range(0, len(pending), 64):
            batch = pending[start : start + 64]
            vectors = await self._embed([t for _, t in batch])
            for (idx, text), vec in zip(batch, vectors, strict=True):
                results[idx] = vec
                if self._cache:
                    await self._cache.set(
                        cache_key("emb", {"m": self.model, "t": text}), vec, ttl=86400 * 30
                    )

        return [r if r is not None else [0.0] * self.dim for r in results]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def build_embedding_provider(settings: Settings, cache: Cache | None = None):
    if settings.embedding_provider == "openai":
        try:
            return OpenAIEmbeddingProvider(settings, cache)
        except Exception as exc:
            log.warning("embeddings.openai_unavailable_falling_back", error=str(exc))
    return DemoEmbeddingProvider(dim=settings.embedding_dim)
