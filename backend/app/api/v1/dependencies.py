"""FastAPI 의존성 주입 — repository / service 팩토리.

각 요청마다 새로운 AsyncSession을 생성하고 commit/rollback을 관리한다.
db_session은 통합 테스트에서 override 가능하도록 독립 함수로 분리되어 있다.

event_bus 는 SSE 핸들러용 EventBus 싱글턴을 반환한다. 통합 테스트는
이 의존성을 fakeredis 또는 no-op 스텁으로 override 한다 (T101).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.events.bus import EventBus
from app.domain.jobs.service import JobsService
from app.domain.subtitles.service import SubtitlesService
from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository
from app.infrastructure.db.repositories.job_repository import SqlJobRepository
from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository
from app.infrastructure.db.session import get_sessionmaker


class SubscribableBus(Protocol):
    """SSE 핸들러가 사용하는 publish/subscribe 모두 지원하는 Bus 인터페이스.

    ``EventBus`` 의 실제 시그니처와 일치하며, 테스트 스텁도 동일 형태로 구현한다.
    """

    async def publish(self, channel: str, payload: dict[str, Any]) -> None: ...

    def subscribe(
        self,
        channel: str,
        *,
        ready: asyncio.Event | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]: ...


async def db_session() -> AsyncIterator[AsyncSession]:
    """요청 범위 비동기 DB 세션 — commit/rollback을 자동 관리한다."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def jobs_service(session: AsyncSession = Depends(db_session)) -> JobsService:  # noqa: B008
    """JobsService 인스턴스를 주입한다."""
    return JobsService(SqlJobRepository(session))


def subtitles_service(session: AsyncSession = Depends(db_session)) -> SubtitlesService:  # noqa: B008
    """SubtitlesService 인스턴스를 주입한다."""
    return SubtitlesService(SqlSubtitleRepository(session))


def asset_repo(session: AsyncSession = Depends(db_session)) -> SqlVideoAssetRepository:  # noqa: B008
    """SqlVideoAssetRepository 인스턴스를 주입한다."""
    return SqlVideoAssetRepository(session)


# ── EventBus 싱글턴 (SSE 핸들러 전용) ────────────────────────────────────────
# 통합 테스트는 ``fastapi_app.dependency_overrides[event_bus]`` 로
# fakeredis 또는 no-op 스텁을 주입한다.

_event_bus_singleton: EventBus | None = None


def event_bus() -> SubscribableBus:
    """SSE 핸들러용 EventBus 싱글턴을 반환한다.

    settings.redis_url 기반으로 lazy 초기화한다. publish/subscribe 모두 지원해야
    하므로 ``SubscribableBus`` 프로토콜에 부합하는 실제 ``EventBus`` 를 반환한다.
    통합 테스트는 dependency override 로 stub 으로 교체한다.
    """
    global _event_bus_singleton  # noqa: PLW0603
    if _event_bus_singleton is None:
        settings = get_settings()
        _event_bus_singleton = EventBus(redis_url=settings.redis_url)
    return _event_bus_singleton
