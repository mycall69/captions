"""T067: SQLAlchemy 기반 JobRepository 구현.

JobRepository Protocol(app/domain/jobs/repository.py)의 모든 7개 메서드를 구현한다.
ORM ↔ 도메인 변환은 _to_domain 헬퍼를 통해 수행한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.states import JobStatus
from app.infrastructure.db.orm import VideoJob as OrmVideoJob

logger = logging.getLogger(__name__)

# ULID 알파벳 — created_at 기반 커서 인코딩에 사용 (0-9A-Z, Crockford)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_cursor(dt: datetime) -> str:
    """datetime → ULID 타임스탬프 부분 10자리 문자열로 인코딩.

    커서는 `created_at < cursor_dt` 조건의 페이지네이션에 사용된다.
    """
    ms = int(dt.timestamp() * 1000)
    chars: list[str] = []
    for _ in range(10):
        chars.append(_CROCKFORD[ms & 0x1F])
        ms >>= 5
    return "".join(reversed(chars))


def _decode_cursor(cursor: str) -> datetime:
    """커서 문자열 → datetime 복원.

    Args:
        cursor: _encode_cursor()가 반환한 10자리 Crockford 인코딩 문자열.

    Returns:
        UTC datetime.

    Raises:
        ValueError: 커서가 올바른 형식이 아닌 경우.
    """
    if len(cursor) != 10:
        raise ValueError(f"잘못된 커서 길이: {len(cursor)} (기대: 10)")
    ms = 0
    for ch in cursor:
        idx = _CROCKFORD.find(ch.upper())
        if idx == -1:
            raise ValueError(f"잘못된 커서 문자: {ch!r}")
        ms = ms * 32 + idx
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def _to_domain(orm: OrmVideoJob) -> VideoJob:
    """ORM VideoJob 행 → Pydantic VideoJob 도메인 모델 변환.

    video_title / video_channel / video_duration_sec / subtitle_source는
    VideoMetadata 서브 모델로 매핑한다.
    """
    metadata = VideoMetadata(
        title=orm.video_title,
        channel=orm.video_channel,
        duration_sec=orm.video_duration_sec,
        subtitle_source=orm.subtitle_source,
    )

    # created_at / updated_at가 timezone-naive인 경우 UTC로 강제 변환
    created_at = orm.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    updated_at = orm.updated_at
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)

    completed_at = orm.completed_at
    if completed_at is not None and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)

    return VideoJob(
        id=orm.id,
        source_url=orm.source_url,
        youtube_video_id=orm.youtube_video_id,
        source_language=orm.source_language,
        target_language=orm.target_language,
        status=JobStatus(orm.status),
        error_stage=orm.error_stage,
        error_code=orm.error_code,
        error_message=orm.error_message,
        metadata=metadata,
        created_at=created_at,
        updated_at=updated_at,
        completed_at=completed_at,
    )


class SqlJobRepository:
    """SQLAlchemy AsyncSession 기반 JobRepository 구현체.

    모든 메서드는 async이며 도메인 모델(VideoJob)을 반환한다.
    상태 전이 검증은 서비스 계층에서 수행하며, 여기서는 DB 조작만 담당한다.
    """

    def __init__(self, session: AsyncSession) -> None:
        """AsyncSession을 주입받아 저장한다."""
        self._session = session

    async def get(self, job_id: str) -> VideoJob | None:
        """job_id로 단일 작업을 조회한다. 없으면 None 반환."""
        stmt = select(OrmVideoJob).where(OrmVideoJob.id == job_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _to_domain(orm)

    async def get_by_youtube_video_id(self, video_id: str) -> VideoJob | None:
        """youtube_video_id로 가장 최근 작업을 조회한다. 없으면 None 반환.

        created_at DESC 정렬 후 LIMIT 1을 적용하여 가장 최신 작업을 반환한다.
        """
        stmt = (
            select(OrmVideoJob)
            .where(OrmVideoJob.youtube_video_id == video_id)
            .order_by(OrmVideoJob.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _to_domain(orm)

    async def list_recent(
        self,
        *,
        limit: int,
        cursor: str | None = None,
        status_filter: list[JobStatus] | None = None,
    ) -> tuple[list[VideoJob], str | None]:
        """최근 작업 목록을 커서 기반 페이지네이션으로 반환한다.

        커서는 created_at을 Crockford Base32로 인코딩한 10자리 문자열이다.
        다음 페이지가 없으면 next_cursor=None을 반환한다.

        Args:
            limit: 반환할 최대 작업 수.
            cursor: 이전 페이지의 마지막 항목 커서 (없으면 첫 페이지).
            status_filter: 필터링할 상태 목록 (없으면 전체).

        Returns:
            (작업 목록, 다음 페이지 커서) 튜플.
        """
        stmt = select(OrmVideoJob).order_by(OrmVideoJob.created_at.desc())

        if cursor is not None:
            try:
                cursor_dt = _decode_cursor(cursor)
                stmt = stmt.where(OrmVideoJob.created_at < cursor_dt)
            except ValueError:
                logger.warning("잘못된 커서 값: %r — 무시하고 첫 페이지로 처리", cursor)

        if status_filter:
            stmt = stmt.where(OrmVideoJob.status.in_([s.value for s in status_filter]))

        # limit + 1 조회하여 다음 페이지 존재 여부 확인
        stmt = stmt.limit(limit + 1)

        result = await self._session.execute(stmt)
        rows = list(result.scalars())

        has_next = len(rows) > limit
        items = rows[:limit]
        domains = [_to_domain(r) for r in items]

        next_cursor: str | None = None
        if has_next and items:
            last_created_at = items[-1].created_at
            if last_created_at.tzinfo is None:
                last_created_at = last_created_at.replace(tzinfo=UTC)
            next_cursor = _encode_cursor(last_created_at)

        return domains, next_cursor

    async def create(self, job: VideoJob) -> VideoJob:
        """새 작업을 저장하고 저장된 도메인 모델을 반환한다.

        source_url은 HttpUrl 인스턴스이므로 str()로 변환하여 저장한다.
        """
        orm = OrmVideoJob(
            id=job.id,
            source_url=str(job.source_url),
            youtube_video_id=job.youtube_video_id,
            source_language=job.source_language,
            target_language=job.target_language,
            status=job.status.value,
            error_stage=job.error_stage,
            error_code=job.error_code,
            error_message=job.error_message,
            video_title=job.metadata.title,
            video_channel=job.metadata.channel,
            video_duration_sec=job.metadata.duration_sec,
            subtitle_source=job.metadata.subtitle_source,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
        )
        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)
        return _to_domain(orm)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error_stage: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> VideoJob:
        """작업 상태를 갱신하고 갱신된 도메인 모델을 반환한다.

        failed / completed 전이 시 completed_at과 error_* 필드를 함께 갱신한다.
        """
        values: dict[str, object] = {
            "status": status.value,
            "updated_at": datetime.now(tz=UTC),
        }
        if error_stage is not None:
            values["error_stage"] = error_stage
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if completed_at is not None:
            values["completed_at"] = completed_at

        stmt = (
            update(OrmVideoJob)
            .where(OrmVideoJob.id == job_id)
            .values(**values)
        )
        await self._session.execute(stmt)
        await self._session.flush()

        # 갱신된 행 재조회
        fetch = await self._session.execute(
            select(OrmVideoJob).where(OrmVideoJob.id == job_id)
        )
        orm = fetch.scalar_one()
        return _to_domain(orm)

    async def update_metadata(self, job_id: str, metadata: VideoMetadata) -> VideoJob:
        """비디오 메타데이터(title/channel/duration/source)를 갱신한다."""
        stmt = (
            update(OrmVideoJob)
            .where(OrmVideoJob.id == job_id)
            .values(
                video_title=metadata.title,
                video_channel=metadata.channel,
                video_duration_sec=metadata.duration_sec,
                subtitle_source=metadata.subtitle_source,
                updated_at=datetime.now(tz=UTC),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

        fetch = await self._session.execute(
            select(OrmVideoJob).where(OrmVideoJob.id == job_id)
        )
        orm = fetch.scalar_one()
        return _to_domain(orm)

    async def update_languages(
        self,
        job_id: str,
        source_language: str,
        target_language: str,
    ) -> VideoJob:
        """source_language / target_language 열을 갱신하고 갱신된 도메인 모델을 반환한다.

        자막 추출 완료 후 언어 정보가 확정되는 시점에 호출된다.
        """
        stmt = (
            update(OrmVideoJob)
            .where(OrmVideoJob.id == job_id)
            .values(
                source_language=source_language,
                target_language=target_language,
                updated_at=datetime.now(tz=UTC),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

        fetch = await self._session.execute(
            select(OrmVideoJob).where(OrmVideoJob.id == job_id)
        )
        orm = fetch.scalar_one()
        return _to_domain(orm)

    async def update_progress(self, job_id: str, progress: float) -> None:
        """진행률 갱신 — DB 컬럼 없음(video_job에 progress 컬럼 미존재).

        progress는 SSE를 통한 실시간 전달 전용 임시 상태이며 DB에 저장되지 않는다.
        빈번한 호출을 허용하기 위해 no-op으로 처리하고 debug 로그만 기록한다.
        """
        logger.debug(
            "update_progress no-op: job_id=%r, progress=%.3f (DB 미저장)", job_id, progress
        )
