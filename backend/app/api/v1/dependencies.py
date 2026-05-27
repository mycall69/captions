"""FastAPI 의존성 주입 — repository / service 팩토리.

각 요청마다 새로운 AsyncSession을 생성하고 commit/rollback을 관리한다.
db_session은 통합 테스트에서 override 가능하도록 독립 함수로 분리되어 있다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs.service import JobsService
from app.domain.subtitles.service import SubtitlesService
from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository
from app.infrastructure.db.repositories.job_repository import SqlJobRepository
from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository
from app.infrastructure.db.session import get_sessionmaker


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
