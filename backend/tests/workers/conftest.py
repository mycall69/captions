"""워커 태스크 테스트 공통 fixture.

Celery 태스크가 사용하는 DB 세션을 테스트의 in-memory SQLite 세션으로 교체하여
태스크와 테스트가 동일한 데이터베이스를 바라보도록 설정한다.

StaticPool + check_same_thread=False: 새 스레드에서도 동일한 in-memory DB 접근 가능.
expire_on_commit=True: 커밋 후 세션 캐시를 비워 다른 세션의 변경이 반영되도록 한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.orm import Base


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """워커 테스트용 in-memory SQLite 엔진.

    check_same_thread=False + StaticPool: 새 스레드(run_async 내부)에서도
    동일한 in-memory 데이터베이스에 접근할 수 있도록 설정한다.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """워커 테스트용 DB 세션.

    expire_on_commit=True: 커밋 후 식별 맵 내 객체를 만료시켜
    다른 세션(태스크)이 커밋한 변경 사항을 다음 쿼리에서 반영한다.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=True)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _patch_celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Celery를 eager(동기) 모드로 실행한다 — 별도 worker 없이 인라인 실행."""
    from app.workers.celery_app import celery_app

    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )


@pytest.fixture(autouse=True)
def _inject_session_factory(db_engine: AsyncEngine) -> Iterator[None]:
    """태스크 세션 팩토리를 in-memory DB 엔진 팩토리로 교체한다.

    run_async()가 새 스레드에서 실행되더라도 StaticPool을 통해
    동일한 in-memory SQLite 데이터베이스에 접근한다.
    expire_on_commit=False: 태스크 세션은 커밋 후에도 객체를 계속 사용한다.
    """
    from app.workers.tasks._runtime import set_session_factory_for_test

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    set_session_factory_for_test(factory)
    try:
        yield
    finally:
        set_session_factory_for_test(None)
