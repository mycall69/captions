"""T070: VideoJob 서비스 계층 — 작업 생성, 상태 전이, 실패 처리.

연관 결정:
- research §10: 동일 URL 재요청 → 기존 작업 재사용 (completed: 200, 진행 중: 200)
- spec Q2 / FR-003: 영상 길이 > 60분 → 거절 (작업 미생성)
- 상태 전이 검증은 states.ensure_transition으로 위임 (헌법 II)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog

from app.core.exceptions import (
    NotFoundError,
)
from app.core.ids import new_job_id
from app.core.security import parse_youtube_url
from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.repository import JobRepository
from app.domain.jobs.states import TERMINAL_STATUSES, JobStatus, ensure_transition
from app.infrastructure.youtube.metadata import fetch_metadata

logger = structlog.get_logger(__name__)


# fetch_metadata 주입 타입 (테스트에서 fake로 교체 가능)
MetadataFetcher = Callable[[str], Awaitable[VideoMetadata]]


class JobsService:
    """VideoJob 작업의 생명주기를 관리한다."""

    def __init__(
        self,
        repo: JobRepository,
        *,
        metadata_fetcher: MetadataFetcher | None = None,
    ) -> None:
        self._repo = repo
        self._fetch_metadata = metadata_fetcher or fetch_metadata

    async def create_or_reuse(self, source_url: str) -> VideoJob:
        """URL을 받아 신규 작업을 생성하거나 기존 작업을 재사용한다.

        흐름:
        1) URL 검증 → 영상 ID 추출 (InvalidUrlError on fail)
        2) 동일 영상 ID의 기존 작업 lookup
           - completed: 재사용 (reused=True)
           - 진행 중: 재사용 (reused=True)
           - failed: 신규 생성
        3) 신규 생성 시: 메타데이터 fetch (60분 검증 포함 — VideoTooLongError 가능)
        4) DB INSERT, 도메인 모델 반환
        """
        video_id = parse_youtube_url(source_url)

        # 기존 작업 재사용 분기
        existing = await self._repo.get_by_youtube_video_id(video_id)
        if existing is not None and existing.status != JobStatus.failed:
            logger.info(
                "job.reused",
                job_id=existing.id,
                video_id=video_id,
                existing_status=existing.status.value,
            )
            return existing.model_copy(update={"reused": True})

        # 신규 — 메타데이터 fetch (60분 검증 포함; VideoTooLongError가 전파되면 DB 미기록)
        metadata = await self._fetch_metadata(video_id)

        now = datetime.now(UTC)
        job = VideoJob(
            id=new_job_id(),
            source_url=source_url,
            youtube_video_id=video_id,
            status=JobStatus.pending,
            metadata=metadata,
            created_at=now,
            updated_at=now,
            reused=False,
        )
        created = await self._repo.create(job)
        logger.info(
            "job.created",
            job_id=created.id,
            video_id=video_id,
            duration_sec=metadata.duration_sec,
        )
        return created.model_copy(update={"reused": False})

    async def get(self, job_id: str) -> VideoJob:
        """job_id로 작업을 조회한다. 없으면 NotFoundError."""
        job = await self._repo.get(job_id)
        if job is None:
            raise NotFoundError(
                f"작업을 찾을 수 없습니다: {job_id}",
                details={"job_id": job_id},
            )
        return job

    async def list_recent(
        self,
        *,
        limit: int,
        cursor: str | None = None,
        status_filter: list[JobStatus] | None = None,
    ) -> tuple[list[VideoJob], str | None]:
        """최근 작업 목록을 cursor 페이지네이션으로 조회한다.

        US3 / FR-029, FR-030 — 최근 작업 카드용 데이터 소스. repository 의
        list_recent 를 그대로 위임한다. (서비스 계층에서는 추가 정책 없음.)

        Returns:
            (items, next_cursor): repository 결과 그대로 전달.
        """
        return await self._repo.list_recent(
            limit=limit,
            cursor=cursor,
            status_filter=status_filter,
        )

    async def transition_to(
        self,
        job_id: str,
        target_status: JobStatus,
        *,
        completed_at: datetime | None = None,
    ) -> VideoJob:
        """작업 상태를 새 단계로 전이시킨다.

        ensure_transition으로 위법 전이를 거절한다 (IllegalStateTransitionError).
        completed_at은 종결 전이(completed/failed) 시에만 의미가 있다.
        """
        current = await self.get(job_id)
        ensure_transition(current.status, target_status)

        if target_status in TERMINAL_STATUSES and completed_at is None:
            completed_at = datetime.now(UTC)

        updated = await self._repo.update_status(
            job_id,
            target_status,
            completed_at=completed_at,
        )
        logger.info(
            "job.state_changed",
            job_id=job_id,
            previous_status=current.status.value,
            new_status=target_status.value,
        )
        return updated

    async def update_languages(
        self,
        job_id: str,
        source: str,
        target: str,
    ) -> VideoJob:
        """source_language / target_language 를 갱신한다.

        자막 추출 완료 후 언어 정보가 확정되면 호출된다.
        작업이 존재하지 않으면 NotFoundError를 발생시킨다.
        """
        await self.get(job_id)  # 존재 여부 검증
        return await self._repo.update_languages(job_id, source, target)

    async def mark_failed(
        self,
        job_id: str,
        *,
        error_stage: str,
        error_code: str,
        error_message: str,
    ) -> VideoJob:
        """작업을 실패 상태로 전이하고 실패 정보를 기록한다.

        상태 전이 머신에서 허용하는 경우에만 failed로 전이 가능.
        completed 등 종결 상태에서는 IllegalStateTransitionError를 발생시킨다.
        """
        current = await self.get(job_id)
        ensure_transition(current.status, JobStatus.failed)
        completed_at = datetime.now(UTC)
        updated = await self._repo.update_status(
            job_id,
            JobStatus.failed,
            error_stage=error_stage,
            error_code=error_code,
            error_message=error_message,
            completed_at=completed_at,
        )
        logger.warning(
            "job.failed",
            job_id=job_id,
            error_stage=error_stage,
            error_code=error_code,
            error_message=error_message,
        )
        return updated
