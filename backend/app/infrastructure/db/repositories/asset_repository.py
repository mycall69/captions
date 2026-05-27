"""T069: SQLAlchemy 기반 VideoAssetRepository 구현.

video_asset 테이블에 대한 CRUD 연산을 제공한다.
id는 UUID4 기반 26자 hex 접두사로 생성한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs.models import VideoAsset
from app.infrastructure.db.orm import VideoAsset as OrmVideoAsset


def _new_id() -> str:
    """새 자산 식별자를 생성한다.

    UUID4를 hex 문자열로 변환한 후 앞 26자를 취하여 ULID 길이에 맞춘다.
    """
    return uuid.uuid4().hex[:26].upper()


def _to_domain(orm: OrmVideoAsset) -> VideoAsset:
    """ORM VideoAsset 행 → Pydantic VideoAsset 도메인 모델 변환."""
    created_at = orm.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return VideoAsset(
        id=orm.id,
        job_id=orm.job_id,
        kind=orm.kind,
        path=orm.path,
        mime_type=orm.mime_type,
        byte_size=orm.byte_size,
        created_at=created_at,
    )


class SqlVideoAssetRepository:
    """SQLAlchemy AsyncSession 기반 VideoAsset 저장소 구현체.

    register: 새 video_asset 행을 삽입하고 생성된 id를 반환한다.
    list_for_job: 특정 job의 모든 자산 목록을 반환한다.
    get: 특정 job의 특정 kind 자산 중 가장 최신 것을 반환한다.
    """

    def __init__(self, session: AsyncSession) -> None:
        """AsyncSession을 주입받아 저장한다."""
        self._session = session

    async def register(
        self,
        *,
        job_id: str,
        kind: str,
        path: str,
        mime_type: str,
        byte_size: int,
    ) -> str:
        """새 video_asset 행을 삽입하고 생성된 id를 반환한다.

        Args:
            job_id: 소속 VideoJob의 26자 ULID.
            kind: 자산 종류 (video_mp4 | dual_srt | dual_vtt | original_subtitle | thumbnail).
            path: var/storage/... 상대 경로.
            mime_type: 파일 MIME 타입.
            byte_size: 파일 바이트 크기.

        Returns:
            생성된 자산의 26자 id.
        """
        asset_id = _new_id()
        orm = OrmVideoAsset(
            id=asset_id,
            job_id=job_id,
            kind=kind,
            path=path,
            mime_type=mime_type,
            byte_size=byte_size,
            created_at=datetime.now(tz=UTC),
        )
        self._session.add(orm)
        await self._session.flush()
        return asset_id

    async def list_for_job(self, job_id: str) -> list[VideoAsset]:
        """특정 job에 등록된 모든 자산을 created_at 오름차순으로 반환한다.

        Args:
            job_id: VideoJob의 26자 ULID.

        Returns:
            VideoAsset 도메인 모델 목록 (빈 목록 가능).
        """
        stmt = (
            select(OrmVideoAsset)
            .where(OrmVideoAsset.job_id == job_id)
            .order_by(OrmVideoAsset.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars()]

    async def get(self, *, job_id: str, kind: str) -> VideoAsset | None:
        """특정 job의 특정 kind 자산 중 가장 최근에 등록된 것을 반환한다.

        Args:
            job_id: VideoJob의 26자 ULID.
            kind: 자산 종류.

        Returns:
            VideoAsset 도메인 모델. 해당 자산이 없으면 None 반환.
        """
        stmt = (
            select(OrmVideoAsset)
            .where(
                OrmVideoAsset.job_id == job_id,
                OrmVideoAsset.kind == kind,
            )
            .order_by(OrmVideoAsset.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _to_domain(orm)
