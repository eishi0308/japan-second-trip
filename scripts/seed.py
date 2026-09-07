#!/usr/bin/env python
"""Seed the database with demo catalogue and evidence.

python scripts/seed.py            # seed
python scripts/seed.py --reset    # drop and recreate first (destructive)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))

from jst_api.core.config import get_settings
from jst_api.core.logging import configure_logging, get_logger
from jst_api.db import models  # noqa: F401
from jst_api.db.base import Base, build_engine, get_sessionmaker
from jst_api.providers.embeddings import build_embedding_provider
from jst_api.seed.loader import seed_all

log = get_logger("seed")


async def main(reset: bool) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    engine = build_engine(settings)

    if reset:
        log.warning("seed.reset_requested", url=settings.database_url.split("@")[-1])
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    embeddings_provider = build_embedding_provider(settings)
    from jst_api.knowledge.embeddings import ProviderEmbeddings

    embeddings = ProviderEmbeddings(embeddings_provider)

    async with get_sessionmaker()() as session:
        summary = await seed_all(session, embeddings, settings)
        await session.commit()

    log.info("seed.complete", **{k: v for k, v in summary.items() if not isinstance(v, dict)})
    print("\nSeed complete:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print(f"\nEmbedding provider: {embeddings_provider.name} (demo={embeddings_provider.is_demo})")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.reset)))
