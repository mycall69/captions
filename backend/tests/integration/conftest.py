"""통합 테스트 공통 fixture.

FastAPI 앱을 in-memory DB와 함께 테스트하기 위한 httpx AsyncClient fixture 제공.
db_session 의존성을 테스트용 in-memory SQLite 세션으로 override하고,
jobs_service 의존성을 fake metadata fetcher와 함께 주입한다.

T082: /v1 라우터 배선 완료 후 client fixture가 실제 앱과 연결된다.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs.models import VideoMetadata


async def _fake_fetch_metadata(video_id: str) -> VideoMetadata:
    """테스트용 가짜 메타데이터 fetcher — yt-dlp를 호출하지 않는다."""
    return VideoMetadata(
        title=f"Test Video {video_id}",
        channel="Test Channel",
        duration_sec=180,
        subtitle_source=None,
    )


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """pytest-anyio 백엔드 지정."""
    return "asyncio"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[object]:
    """통합 테스트용 httpx AsyncClient.

    - app.api.v1.dependencies.db_session → in-memory SQLite 세션 override
    - app.api.v1.dependencies.jobs_service → fake metadata fetcher 주입
    - DISABLE_CHAIN_DISPATCH=true → Celery 디스패치 억제
    """
    try:
        import asyncio as _asyncio
        from collections.abc import AsyncGenerator as _AsyncGenerator
        from typing import Any as _Any

        from httpx import ASGITransport, AsyncClient

        from app.api.v1.dependencies import db_session as _real_db_session
        from app.api.v1.dependencies import event_bus as _real_event_bus
        from app.api.v1.dependencies import jobs_service as _real_jobs_service
        from app.core.config import get_settings
        from app.domain.jobs.service import JobsService
        from app.infrastructure.db.repositories.job_repository import SqlJobRepository
        from app.main import app as fastapi_app
    except ImportError:
        pytest.skip("app.main 미구현 — 통합 테스트 skip")
        return  # unreachable; type checker용

    async def _override_db() -> AsyncIterator[AsyncSession]:
        """테스트용 in-memory 세션을 주입한다."""
        yield db_session

    def _override_jobs_service() -> JobsService:
        """fake metadata fetcher가 주입된 JobsService를 반환한다."""
        return JobsService(
            SqlJobRepository(db_session),
            metadata_fetcher=_fake_fetch_metadata,
        )

    # SSE 핸들러용 EventBus override — 라이브 이벤트 없이 짧게 sleep 후 종료하는
    # 테스트 전용 스텁. 합성/replay 프레임을 모두 push 한 뒤 generator 가 자연
    # 종료되도록 한다. keepalive 테스트 (KEEPALIVE_INTERVAL_SEC=0.05) 에서도
    # 0.1초 동안은 활성 상태를 유지해 keepalive 프레임이 최소 1건 emit 된다.
    class _TestBus:
        async def publish(self, channel: str, payload: dict[_Any, _Any]) -> None:  # noqa: ARG002
            return None

        async def subscribe(
            self,
            channel: str,  # noqa: ARG002
            *,
            ready: _asyncio.Event | None = None,
        ) -> _AsyncGenerator[dict[str, _Any], None]:
            if ready is not None:
                ready.set()
            # 짧게 활성 상태 유지 — keepalive 테스트가 최소 1프레임을 수신할 수 있게
            # 함과 동시에 기본 keepalive(30s) 테스트가 hang 되지 않도록 종료한다.
            await _asyncio.sleep(0.1)
            if False:  # 타입 체커에 async generator 임을 알리기 위한 더미 yield
                yield {}
            return

    fake_bus = _TestBus()

    def _override_event_bus() -> object:
        return fake_bus

    # 의존성 override 등록
    fastapi_app.dependency_overrides[_real_db_session] = _override_db
    fastapi_app.dependency_overrides[_real_jobs_service] = _override_jobs_service
    fastapi_app.dependency_overrides[_real_event_bus] = _override_event_bus

    # Celery chain 디스패치 억제
    get_settings.cache_clear()
    os.environ["DISABLE_CHAIN_DISPATCH"] = "true"

    try:
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.clear()
        os.environ.pop("DISABLE_CHAIN_DISPATCH", None)
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def job_repo(db_session: AsyncSession) -> object:
    """SqlJobRepository 인스턴스 — in-memory SQLite 세션으로 초기화된다."""
    from app.infrastructure.db.repositories.job_repository import SqlJobRepository

    return SqlJobRepository(db_session)


@pytest_asyncio.fixture
async def subtitle_repo(db_session: AsyncSession) -> object:
    """SqlSubtitleRepository 인스턴스 — in-memory SQLite 세션으로 초기화된다."""
    from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository

    return SqlSubtitleRepository(db_session)


@pytest_asyncio.fixture
async def asset_repo(db_session: AsyncSession) -> object:
    """SqlVideoAssetRepository 인스턴스 — in-memory SQLite 세션으로 초기화된다."""
    from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository

    return SqlVideoAssetRepository(db_session)
