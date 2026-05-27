"""Backend pytest 공통 fixture."""
from __future__ import annotations

import asyncio
import pathlib
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure.db.orm import Base

# backend/ 디렉터리를 경로에 추가
_BACKEND_DIR = pathlib.Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """In-memory SQLite engine — 테스트 격리용."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """In-memory DB 세션."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def fake_redis() -> Iterator[object]:
    """fakeredis FakeAsyncRedis 인스턴스."""
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis

    server = FakeServer()
    client = FakeRedis(server=server, decode_responses=True)
    try:
        yield client
    finally:
        async def _close() -> None:
            await client.aclose()

        asyncio.run(_close())


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """각 테스트 시작 시 get_settings lru_cache 비움 → env mutation 안전."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
