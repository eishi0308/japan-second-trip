"""Background retry for chunks that were ingested while embeddings were down.

Ingestion never waits on an embedding outage: it stores the chunks without
vectors and moves on (see ``IngestionService.embed_pending``). This job comes
back for them on an interval. While the provider keeps failing the interval
doubles up to a ceiling, so an outage costs one cheap call per window rather
than a retry storm, and it drops back to normal on the first success.
"""

from __future__ import annotations

import asyncio
from typing import Any

from jst_api.core.config import Settings
from jst_api.core.logging import get_logger
from jst_api.knowledge.ingest import IngestionService

log = get_logger(__name__)


def next_delay(current: float, *, base: float, ceiling: float, failed: bool) -> float:
    """Back off while failing, reset after a success."""
    return min(current * 2, ceiling) if failed else base


async def embed_pending_once(
    session_factory: Any, embeddings: Any, settings: Settings
) -> dict[str, int]:
    """One pass, in its own transaction. Raises if the provider is still down."""
    async with session_factory() as session:
        try:
            result = await IngestionService(session, embeddings, settings).embed_pending()
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def reembed_forever(session_factory: Any, embeddings: Any, settings: Settings) -> None:
    """Run until cancelled. Started by the app lifespan when the interval is > 0."""
    base = float(settings.embedding_retry_interval_seconds)
    ceiling = float(max(settings.embedding_retry_max_interval_seconds, base))
    delay = base
    while True:
        await asyncio.sleep(delay)
        try:
            result = await embed_pending_once(session_factory, embeddings, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = next_delay(delay, base=base, ceiling=ceiling, failed=True)
            log.warning("reembed.failed", error=str(exc)[:300], retry_in_seconds=delay)
        else:
            delay = next_delay(delay, base=base, ceiling=ceiling, failed=False)
            if result["chunks_embedded"]:
                log.info("reembed.pass", **result)
