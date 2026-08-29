"""T070 단위 테스트: JobsService — create_or_reuse, get, transition_to, mark_failed.

FakeJobRepository(인메모리)와 FakeMetadataFetcher로 외부 의존성을 제거한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import (
    IllegalStateTransitionError,
    InvalidUrlError,
    NotFoundError,
)
from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.service import JobsService
from app.domain.jobs.states import JobStatus
from app.infrastructure.youtube.metadata import VideoTooLongError

# ── 테스트 헬퍼 ────────────────────────────────────────────────────────────────

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
_VIDEO_ID = "dQw4w9WgXcQ"

_DEFAULT_METADATA = VideoMetadata(
    title="Test Video",
    channel="Test Channel",
    duration_sec=300,
    subtitle_source=None,
)

_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _make_job(
    video_id: str = _VIDEO_ID,
    status: JobStatus = JobStatus.pending,
    *,
    error_stage: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> VideoJob:
    """테스트용 VideoJob을 생성한다."""
    return VideoJob(
        id="01ABCDEFGHJKMNPQRSTVWXYZ12",
        source_url=f"https://www.youtube.com/watch?v={video_id}",
        youtube_video_id=video_id,
        status=status,
        metadata=_DEFAULT_METADATA,
        created_at=_NOW,
        updated_at=_NOW,
        reused=False,
        error_stage=error_stage,
        error_code=error_code,
        error_message=error_message,
    )


# ── FakeJobRepository ──────────────────────────────────────────────────────────

class FakeJobRepository:
    """인메모리 JobRepository — Protocol을 충족하는 테스트 이중."""

    def __init__(self) -> None:
        self._store: dict[str, VideoJob] = {}
        self.create_call_count: int = 0

    async def get(self, job_id: str) -> VideoJob | None:
        return self._store.get(job_id)

    async def get_by_youtube_video_id(self, video_id: str) -> VideoJob | None:
        # 동일 video_id 중 가장 최근(updated_at 기준) 작업 반환
        matches = [j for j in self._store.values() if j.youtube_video_id == video_id]
        if not matches:
            return None
        return max(matches, key=lambda j: j.updated_at)

    async def list_recent(
        self,
        *,
        limit: int,
        cursor: str | None = None,
        status_filter: list[JobStatus] | None = None,
    ) -> tuple[list[VideoJob], str | None]:
        items = list(self._store.values())
        if status_filter:
            items = [j for j in items if j.status in status_filter]
        return items[:limit], None

    async def create(self, job: VideoJob) -> VideoJob:
        self.create_call_count += 1
        self._store[job.id] = job
        return job

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
        job = self._store[job_id]
        updated = job.model_copy(
            update={
                "status": status,
                "updated_at": datetime.now(UTC),
                "error_stage": error_stage,
                "error_code": error_code,
                "error_message": error_message,
                "completed_at": completed_at,
            }
        )
        self._store[job_id] = updated
        return updated

    async def update_metadata(self, job_id: str, metadata: VideoMetadata) -> VideoJob:
        job = self._store[job_id]
        updated = job.model_copy(update={"metadata": metadata, "updated_at": datetime.now(UTC)})
        self._store[job_id] = updated
        return updated

    async def update_progress(self, job_id: str, progress: float) -> None:
        if job_id in self._store:
            job = self._store[job_id]
            self._store[job_id] = job.model_copy(update={"progress": progress})

    # ── 편의 메서드 ──────────────────────────────────────────────────────────

    def seed(self, job: VideoJob) -> VideoJob:
        """사전 조건용 작업을 직접 저장소에 삽입한다."""
        self._store[job.id] = job
        return job


# ── FakeMetadataFetcher ────────────────────────────────────────────────────────

class FakeMetadataFetcher:
    """메타데이터 패처 테스트 이중.

    default_metadata: 정상 반환 메타데이터
    side_effect: None이면 default_metadata 반환; 예외 클래스이면 raise
    """

    def __init__(
        self,
        default_metadata: VideoMetadata | None = None,
        side_effect: type[Exception] | None = None,
    ) -> None:
        self._metadata = default_metadata or _DEFAULT_METADATA
        self._side_effect = side_effect
        self.call_count: int = 0

    async def __call__(self, video_id: str) -> VideoMetadata:
        self.call_count += 1
        if self._side_effect is not None:
            exc_cls = self._side_effect
            if exc_cls is VideoTooLongError:
                raise VideoTooLongError(
                    "영상 길이가 120분을 초과합니다",
                    details={"duration_sec": 8000, "max_duration_sec": 7200},
                )
            raise exc_cls("fake error")
        return self._metadata


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def repo() -> FakeJobRepository:
    return FakeJobRepository()


@pytest.fixture()
def fetcher() -> FakeMetadataFetcher:
    return FakeMetadataFetcher()


@pytest.fixture()
def service(repo: FakeJobRepository, fetcher: FakeMetadataFetcher) -> JobsService:
    return JobsService(repo, metadata_fetcher=fetcher)


# ── create_or_reuse 테스트 ─────────────────────────────────────────────────────

class TestCreateOrReuse:
    """create_or_reuse 메서드 검증."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_new_job(
        self,
        service: JobsService,
        repo: FakeJobRepository,
        fetcher: FakeMetadataFetcher,
    ) -> None:
        """신규 URL → 작업 생성, reused=False."""
        job = await service.create_or_reuse(_VALID_URL)

        assert job.youtube_video_id == _VIDEO_ID
        assert job.status == JobStatus.pending
        assert job.reused is False
        assert fetcher.call_count == 1
        assert repo.create_call_count == 1

    @pytest.mark.asyncio
    async def test_reuses_completed_job(
        self,
        service: JobsService,
        repo: FakeJobRepository,
        fetcher: FakeMetadataFetcher,
    ) -> None:
        """동일 영상 ID의 completed 작업이 있으면 재사용, reused=True."""
        existing = _make_job(status=JobStatus.completed)
        repo.seed(existing)

        job = await service.create_or_reuse(_VALID_URL)

        assert job.id == existing.id
        assert job.reused is True
        assert fetcher.call_count == 0
        assert repo.create_call_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "in_progress_status",
        [
            JobStatus.pending,
            JobStatus.downloading,
            JobStatus.subtitle_processing,
            JobStatus.translating,
            JobStatus.rendering,
        ],
    )
    async def test_reuses_in_progress_job(
        self,
        in_progress_status: JobStatus,
        service: JobsService,
        repo: FakeJobRepository,
        fetcher: FakeMetadataFetcher,
    ) -> None:
        """진행 중인 작업이 있으면 재사용, reused=True."""
        existing = _make_job(status=in_progress_status)
        repo.seed(existing)

        job = await service.create_or_reuse(_VALID_URL)

        assert job.id == existing.id
        assert job.reused is True
        assert fetcher.call_count == 0
        assert repo.create_call_count == 0

    @pytest.mark.asyncio
    async def test_creates_new_job_when_existing_is_failed(
        self,
        service: JobsService,
        repo: FakeJobRepository,
        fetcher: FakeMetadataFetcher,
    ) -> None:
        """기존 작업이 failed이면 신규 작업 생성."""
        existing = _make_job(status=JobStatus.failed)
        repo.seed(existing)

        job = await service.create_or_reuse(_VALID_URL)

        # 신규 작업 — ID가 달라야 함
        assert job.id != existing.id
        assert job.status == JobStatus.pending
        assert job.reused is False
        assert fetcher.call_count == 1
        assert repo.create_call_count == 1

    @pytest.mark.asyncio
    async def test_invalid_url_raises_invalid_url_error(
        self,
        service: JobsService,
    ) -> None:
        """유효하지 않은 URL → InvalidUrlError 발생."""
        with pytest.raises(InvalidUrlError):
            await service.create_or_reuse("https://not-youtube.com/watch?v=abc")

    @pytest.mark.asyncio
    async def test_video_too_long_propagates_and_job_not_created(
        self,
        repo: FakeJobRepository,
    ) -> None:
        """VideoTooLongError → 전파, 작업 미생성 (DB 미기록)."""
        too_long_fetcher = FakeMetadataFetcher(side_effect=VideoTooLongError)
        svc = JobsService(repo, metadata_fetcher=too_long_fetcher)

        with pytest.raises(VideoTooLongError):
            await svc.create_or_reuse(_VALID_URL)

        # repo.create가 절대 호출되지 않아야 함
        assert repo.create_call_count == 0


# ── get 테스트 ─────────────────────────────────────────────────────────────────

class TestGet:
    """get 메서드 검증."""

    @pytest.mark.asyncio
    async def test_returns_job_when_found(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """존재하는 job_id → VideoJob 반환."""
        existing = _make_job()
        repo.seed(existing)

        job = await service.get(existing.id)

        assert job.id == existing.id

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(
        self,
        service: JobsService,
    ) -> None:
        """존재하지 않는 job_id → NotFoundError."""
        with pytest.raises(NotFoundError) as exc_info:
            await service.get("01NONEXISTENT000000000000AB")

        assert exc_info.value.details["job_id"] == "01NONEXISTENT000000000000AB"


# ── transition_to 테스트 ───────────────────────────────────────────────────────

class TestTransitionTo:
    """transition_to 메서드 검증."""

    @pytest.mark.asyncio
    async def test_pending_to_downloading(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """pending → downloading 허용 전이."""
        job = _make_job(status=JobStatus.pending)
        repo.seed(job)

        updated = await service.transition_to(job.id, JobStatus.downloading)

        assert updated.status == JobStatus.downloading

    @pytest.mark.asyncio
    async def test_illegal_transition_raises(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """pending → completed 불허 전이 → IllegalStateTransitionError."""
        job = _make_job(status=JobStatus.pending)
        repo.seed(job)

        with pytest.raises(IllegalStateTransitionError):
            await service.transition_to(job.id, JobStatus.completed)

    @pytest.mark.asyncio
    async def test_terminal_transition_sets_completed_at_automatically(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """종결 전이 시 completed_at이 None이면 자동으로 설정된다."""
        # rendering → completed 경로
        job = _make_job(status=JobStatus.rendering)
        repo.seed(job)

        updated = await service.transition_to(job.id, JobStatus.completed)

        assert updated.completed_at is not None
        assert updated.status == JobStatus.completed

    @pytest.mark.asyncio
    async def test_terminal_transition_respects_provided_completed_at(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """completed_at을 명시적으로 전달하면 해당 값이 사용된다."""
        job = _make_job(status=JobStatus.rendering)
        repo.seed(job)

        explicit_ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        updated = await service.transition_to(
            job.id,
            JobStatus.completed,
            completed_at=explicit_ts,
        )

        assert updated.completed_at == explicit_ts


# ── mark_failed 테스트 ─────────────────────────────────────────────────────────

class TestMarkFailed:
    """mark_failed 메서드 검증."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "initial_status",
        [
            JobStatus.pending,
            JobStatus.downloading,
            JobStatus.subtitle_processing,
            JobStatus.translating,
            JobStatus.rendering,
        ],
    )
    async def test_mark_failed_from_non_terminal(
        self,
        initial_status: JobStatus,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """비종결 상태에서 mark_failed → failed 전이, 오류 정보 기록."""
        job = _make_job(status=initial_status)
        repo.seed(job)

        updated = await service.mark_failed(
            job.id,
            error_stage="download",
            error_code="DOWNLOAD_FAILED",
            error_message="네트워크 오류",
        )

        assert updated.status == JobStatus.failed
        assert updated.error_stage == "download"
        assert updated.error_code == "DOWNLOAD_FAILED"
        assert updated.error_message == "네트워크 오류"
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_mark_failed_from_completed_raises(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """completed → failed 불허 전이 → IllegalStateTransitionError."""
        job = _make_job(status=JobStatus.completed)
        repo.seed(job)

        with pytest.raises(IllegalStateTransitionError):
            await service.mark_failed(
                job.id,
                error_stage="render",
                error_code="RENDER_FAILED",
                error_message="예기치 않은 오류",
            )

    @pytest.mark.asyncio
    async def test_mark_failed_from_failed_is_idempotent_noop(
        self,
        service: JobsService,
        repo: FakeJobRepository,
    ) -> None:
        """failed → failed 중복 호출은 멱등 noop — 첫 실패 사유를 보존한다.

        chain abort 미흡 / Celery 체인 안에서 후속 link 가 동일 작업에 대해
        mark_failed 를 재시도하는 케이스에서 noise 없이 안전하게 무시되어야 한다.
        """
        first_failure = _make_job(
            status=JobStatus.failed,
            error_stage="subtitle_processing",
            error_code="SUBTITLE_NOT_FOUND",
            error_message="이 영상에는 한국어 / 일본어 자막이 없습니다.",
        )
        repo.seed(first_failure)

        result = await service.mark_failed(
            first_failure.id,
            error_stage="translating",
            error_code="PIPELINE_FAILED",
            error_message="후속 link 가 잘못된 시점에 호출됨",
        )

        # 멱등 noop: raise 없이 통과하고 첫 실패 사유가 그대로 보존된다.
        assert result.status == JobStatus.failed
        assert result.error_stage == "subtitle_processing"
        assert result.error_code == "SUBTITLE_NOT_FOUND"
        assert result.error_message == "이 영상에는 한국어 / 일본어 자막이 없습니다."
