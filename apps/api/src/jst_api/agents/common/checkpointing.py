"""Graph checkpointing.

Two backends behind one factory:

``MemorySaver``
    Process-local. Correct for tests, evals and single-process development.

``AsyncPostgresSaver``
    Durable and shared. This is what makes LangGraph's ``interrupt()`` /
    ``Command(resume=...)`` usable across processes: a graph can pause for human
    review on one worker and be resumed on another, or after a deploy.

The application still resumes blocked analyses by **re-execution** with the
verified fact injected (see ``services/review_service.py`` and
docs/adr/0007-human-in-the-loop.md), because that path is robust whether or not
a checkpointer is configured and does not depend on a checkpoint surviving a
schema change. The Postgres checkpointer is what makes the *interrupt* path
production-viable as well, and both are exercised by the test suite.

The checkpointer owns its own tables (``checkpoints``, ``checkpoint_blobs``,
``checkpoint_writes``), created by ``setup()``. They are deliberately not in the
Alembic chain: they belong to LangGraph, and their schema moves with that
library rather than with this application's migrations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from jst_api.core.config import Settings
from jst_api.core.logging import get_logger

log = get_logger(__name__)


def to_psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy async URL into the libpq DSN psycopg expects.

    The app talks to PostgreSQL through asyncpg; the checkpointer uses psycopg.
    Rather than configure the connection twice, the one DATABASE_URL is
    translated here.
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@asynccontextmanager
async def checkpointer_for(settings: Settings) -> AsyncIterator[Any]:
    """Yield the best available checkpointer for this configuration.

    Falls back to ``MemorySaver`` when the database is not PostgreSQL, when
    durable checkpointing is switched off, or when the Postgres saver cannot be
    set up. A checkpointer failure must never take down an analysis — the graphs
    run correctly with a process-local one, they just cannot be resumed
    elsewhere.
    """
    if not settings.durable_checkpoints or settings.is_sqlite:
        yield MemorySaver()
        return

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:  # pragma: no cover - optional dependency
        log.warning("checkpointer.postgres_unavailable_using_memory")
        yield MemorySaver()
        return

    try:
        async with AsyncPostgresSaver.from_conn_string(
            to_psycopg_dsn(settings.database_url)
        ) as saver:
            await saver.setup()  # idempotent
            log.debug("checkpointer.postgres_ready")
            yield saver
            return
    except Exception as exc:  # pragma: no cover - requires a broken database
        log.warning("checkpointer.postgres_failed_using_memory", error=str(exc)[:300])

    yield MemorySaver()
