"""Test fixtures.

Every test runs against a real database with the real schema and the real seed
data, on demo providers. Two rules:

* **SQLite by default.** ``JST_TEST_DATABASE_URL`` points the same suite at
  PostgreSQL, which CI does for the dialect-sensitive retrieval tests. Running
  the default suite must not require a database server.
* **No mocked internals.** Only genuinely external things (HTTP calls) are
  mocked. Mocking the retriever or the rules engine would test the mock.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "ERROR")
os.environ.setdefault("LLM_PROVIDER", "demo")
os.environ.setdefault("EMBEDDING_PROVIDER", "demo")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")

TEST_DB_URL = os.environ.get("JST_TEST_DATABASE_URL", "")


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    if TEST_DB_URL:
        return TEST_DB_URL
    path = tmp_path_factory.mktemp("db") / "test.db"
    return f"sqlite+aiosqlite:///{path}"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(database_url: str):
    os.environ["DATABASE_URL"] = database_url
    from jst_api.core.config import get_settings
    from jst_api.db import models  # noqa: F401
    from jst_api.db.base import Base, build_engine

    get_settings.cache_clear()
    # The application's factory, not a bare create_async_engine: it installs
    # ``PRAGMA foreign_keys=ON`` for SQLite. Without it the default leg of the
    # matrix silently accepts rows PostgreSQL rejects, so a foreign-key bug only
    # shows up in the PostgreSQL leg — which is how one got this far.
    engine = build_engine(get_settings())
    async with engine.begin() as conn:
        if database_url.startswith("postgresql"):
            from sqlalchemy import text

            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded(session_factory) -> bool:
    """Seed once per session through the real ingestion pipeline."""
    from jst_api.core.config import get_settings
    from jst_api.knowledge.embeddings import ProviderEmbeddings
    from jst_api.providers.embeddings import DemoEmbeddingProvider
    from jst_api.seed.loader import seed_all

    settings = get_settings()
    embeddings = ProviderEmbeddings(DemoEmbeddingProvider(dim=settings.embedding_dim))
    async with session_factory() as session:
        await seed_all(session, embeddings, settings)
        await session.commit()
    return True


@pytest_asyncio.fixture(loop_scope="session")
async def session(session_factory, seeded) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture(scope="session")
def settings():
    from jst_api.core.config import get_settings

    return get_settings()


@pytest.fixture
def registry(session_factory, settings):
    from jst_api.providers.registry import build_demo_registry

    return build_demo_registry(session_factory, settings)


@pytest.fixture
def backend(session_factory, registry, settings, seeded):
    from jst_api.services.mcp_backend import JstTravelBackend

    return JstTravelBackend(session_factory, registry, settings)


@pytest.fixture
def analysis_service(session_factory, registry, settings, seeded):
    from jst_api.services.analysis_service import AnalysisService

    return AnalysisService(session_factory, registry, settings)


@pytest_asyncio.fixture(loop_scope="session")
async def client(session_factory, registry, settings, seeded) -> AsyncIterator[AsyncClient]:
    """A real ASGI client against the real app, with the demo registry injected."""
    from jst_api.main import create_app
    from jst_api.security.ratelimit import RateLimiter
    from jst_api.services.analysis_service import AnalysisService
    from jst_api.services.mcp_backend import JstTravelBackend

    app = create_app(settings)
    app.router.lifespan_context = _noop_lifespan
    app.state.session_factory = session_factory
    app.state.registry = registry
    app.state.backend = JstTravelBackend(session_factory, registry, settings)
    app.state.analysis_service = AnalysisService(session_factory, registry, settings)
    app.state.rate_limiter = RateLimiter(limit=10_000)

    from jst_api.db import base as db_base

    async def _override_session():
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[db_base.get_session] = _override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _noop_lifespan(app):  # type: ignore[no-untyped-def]
    class _Ctx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    return _Ctx()


@pytest.fixture
def admin_headers(settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.admin_token}"}


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
