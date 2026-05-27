"""통합 테스트 공통 fixture.

FastAPI 앱을 in-memory DB와 함께 테스트하기 위한 httpx AsyncClient fixture 제공.
DB 의존성 주입(get_db)은 T082에서 앱에 배선되므로, 여기서 override를 준비만 해둔다.

T067–T069: 저장소 구현체 fixture 추가.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """pytest-anyio 백엔드 지정."""
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[object]:
    """통합 테스트용 httpx AsyncClient — app.main이 임포트 가능할 때만 활성화된다."""
    try:
        from httpx import ASGITransport, AsyncClient

        from app.main import app  # type: ignore[reportMissingImports]
    except ImportError:
        pytest.skip("app.main 미구현 — 통합 테스트 skip")
        return  # unreachable; satisfies type checker

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def job_repo(db_session):  # type: ignore[no-untyped-def]
    """SqlJobRepository 인스턴스 — in-memory SQLite 세션으로 초기화된다."""
    from app.infrastructure.db.repositories.job_repository import SqlJobRepository

    return SqlJobRepository(db_session)


@pytest_asyncio.fixture
async def subtitle_repo(db_session):  # type: ignore[no-untyped-def]
    """SqlSubtitleRepository 인스턴스 — in-memory SQLite 세션으로 초기화된다."""
    from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository

    return SqlSubtitleRepository(db_session)


@pytest_asyncio.fixture
async def asset_repo(db_session):  # type: ignore[no-untyped-def]
    """SqlVideoAssetRepository 인스턴스 — in-memory SQLite 세션으로 초기화된다."""
    from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository

    return SqlVideoAssetRepository(db_session)
