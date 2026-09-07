"""LangChain ``Embeddings`` adapter over the application's embedding provider.

LangChain owns the retrieval layer in this codebase, so the provider has to
present LangChain's interface. Everything downstream (retrievers, ingestion,
the LCEL RAG chains) depends on this class rather than on a concrete vendor.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.embeddings import Embeddings


class ProviderEmbeddings(Embeddings):
    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @property
    def model(self) -> str:
        return getattr(self._provider, "model", "unknown")

    @property
    def dim(self) -> int:
        return int(getattr(self._provider, "dim", 384))

    @property
    def is_demo(self) -> bool:
        return bool(getattr(self._provider, "is_demo", True))

    # LangChain requires the sync surface; the app is async end-to-end, so the
    # sync methods bridge rather than duplicating provider logic.
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return asyncio.run(self._provider.embed_documents(texts))

    def embed_query(self, text: str) -> list[float]:
        return asyncio.run(self._provider.embed_query(text))

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._provider.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await self._provider.embed_query(text)
