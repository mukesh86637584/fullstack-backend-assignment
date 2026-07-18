from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
import pytest_asyncio

from src.db.connection import close_pool, run_migrations


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/assignment",
    )


@pytest.fixture(scope="session")
def postgres_available(database_url: str) -> bool:
    async def _check() -> bool:
        try:
            conn = await asyncpg.connect(database_url, timeout=2)
            await conn.close()
            return True
        except (OSError, asyncpg.PostgresError):
            return False

    return asyncio.run(_check())


@pytest_asyncio.fixture
async def setup_db(database_url: str, postgres_available: bool, monkeypatch: pytest.MonkeyPatch):
    if not postgres_available:
        pytest.skip(f"Postgres not available at {database_url}")

    monkeypatch.setenv("DATABASE_URL", database_url)
    from src import config

    config.settings = config.Settings(database_url=database_url, use_mock_sources=True)
    await close_pool()
    await run_migrations()

    async def truncate():
        from src.db.connection import acquire

        async with acquire() as conn:
            await conn.execute(
                "TRUNCATE normalized_records, sync_cursors, normalized_transactions RESTART IDENTITY"
            )

    await truncate()
    yield
    await truncate()
    await close_pool()
