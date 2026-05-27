"""T023: JobRepository Protocol — 서비스 계층이 의존하는 저장소 인터페이스.

구현체(SQLiteJobRepository 등)는 infrastructure/db/ 에 위치하며,
여기서는 도메인 모델 관점의 계약만 정의한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.states import JobStatus


class JobRepository(Protocol):
    """비디오 작업 저장소 추상 인터페이스.

    모든 메서드는 async이며 ORM이 아닌 도메인 모델(VideoJob)을 반환한다.
    """

    async def get(self, job_id: str) -> VideoJob | None:
        """job_id로 단일 작업을 조회한다. 없으면 None 반환."""
        ...

    async def get_by_youtube_video_id(self, video_id: str) -> VideoJob | None:
        """youtube_video_id로 가장 최근 작업을 조회한다. 없으면 None 반환.

        동일 URL 재요청 lookup(research §10)에서 사용.
        """
        ...

    async def list_recent(
        self,
        *,
        limit: int,
        cursor: str | None = None,
        status_filter: list[JobStatus] | None = None,
    ) -> tuple[list[VideoJob], str | None]:
        """최근 작업 목록을 커서 기반 페이지네이션으로 반환한다.

        Returns:
            (items, next_cursor): 다음 페이지가 없으면 next_cursor=None.
        """
        ...

    async def create(self, job: VideoJob) -> VideoJob:
        """새 작업을 저장하고 저장된 도메인 모델을 반환한다."""
        ...

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

        error_* 인자는 failed 전이 시에만 의미가 있다.
        completed_at은 종결 상태(completed/failed) 전이 시 설정한다.
        상태 전이 검증은 서비스 계층에서 수행 후 호출해야 한다.
        """
        ...

    async def update_metadata(self, job_id: str, metadata: VideoMetadata) -> VideoJob:
        """비디오 메타데이터를 갱신하고 갱신된 도메인 모델을 반환한다."""
        ...

    async def update_progress(self, job_id: str, progress: float) -> None:
        """현재 단계 진행률(0.0~1.0)을 갱신한다.

        빈번하게 호출되므로 반환값 없이 fire-and-forget으로 사용할 수 있다.
        """
        ...

    async def update_languages(
        self,
        job_id: str,
        source_language: str,
        target_language: str,
    ) -> VideoJob:
        """source_language / target_language 를 갱신하고 갱신된 도메인 모델을 반환한다.

        자막 추출 완료 후 언어 정보가 확정되는 시점에 호출된다.
        """
        ...
