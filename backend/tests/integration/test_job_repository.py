"""T067: SqlJobRepository 통합 테스트.

in-memory SQLite db_session 위에서 CRUD 및 페이지네이션 동작을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.states import JobStatus
from app.infrastructure.db.repositories.job_repository import SqlJobRepository

pytestmark = pytest.mark.integration

# ── 공통 테스트 픽스처 헬퍼 ────────────────────────────────────────────────────

# 정확히 26자인 ID 상수들
_JOB_IDS = {
    f"K{i:02d}": f"01JTESTJOB{i:016d}"[:26] for i in range(100)
}

# 실제로 26자인지 검증
for _k, _v in _JOB_IDS.items():
    assert len(_v) == 26, f"{_k}: {_v!r} is {len(_v)} chars"


def _make_job(
    job_id: str,
    *,
    youtube_video_id: str = "dQw4w9WgXcY",
    status: JobStatus = JobStatus.pending,
    source_url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcY",
    created_at: datetime | None = None,
) -> VideoJob:
    """테스트용 VideoJob 도메인 모델을 생성한다.

    job_id는 정확히 26자여야 한다.
    """
    assert len(job_id) == 26, f"job_id는 26자여야 함: {job_id!r} ({len(job_id)}자)"
    now = created_at or datetime.now(tz=UTC)
    return VideoJob(
        id=job_id,
        source_url=source_url,  # type: ignore[arg-type]
        youtube_video_id=youtube_video_id,
        status=status,
        metadata=VideoMetadata(),
        created_at=now,
        updated_at=now,
    )


def _job_id(tag: str) -> str:
    """26자 테스트 job ID를 생성한다."""
    return f"01JTST{tag}".ljust(26, "0")[:26]


# ── 테스트 클래스 ─────────────────────────────────────────────────────────────


class TestJobRepositoryCreateGet:
    """create + get 라운드트립 검증."""

    async def test_create_and_get_roundtrip(self, job_repo: SqlJobRepository) -> None:
        """create로 저장한 작업을 get으로 조회할 수 있어야 한다."""
        jid = _job_id("CRTGT001000000000")
        job = _make_job(jid)
        created = await job_repo.create(job)

        fetched = await job_repo.get(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.youtube_video_id == "dQw4w9WgXcY"
        assert fetched.status == JobStatus.pending

    async def test_get_unknown_id_returns_none(self, job_repo: SqlJobRepository) -> None:
        """존재하지 않는 job_id 조회 시 None을 반환해야 한다."""
        result = await job_repo.get("01JUNKNOWNID00000000000000")

        assert result is None


class TestJobRepositoryGetByYoutubeVideoId:
    """get_by_youtube_video_id 동작 검증."""

    async def test_returns_most_recent_job(self, job_repo: SqlJobRepository) -> None:
        """동일 youtube_video_id의 두 작업 중 더 최근 작업을 반환해야 한다."""
        video_id = "TestVideo001"[:11]

        now = datetime.now(tz=UTC)
        old_time = now - timedelta(seconds=10)

        old_jid = _job_id("YTOLD0000000000000")
        new_jid = _job_id("YTNEW0000000000000")

        old_job = _make_job(old_jid, youtube_video_id=video_id, created_at=old_time)
        new_job = _make_job(new_jid, youtube_video_id=video_id, created_at=now)

        await job_repo.create(old_job)
        await job_repo.create(new_job)

        result = await job_repo.get_by_youtube_video_id(video_id)

        assert result is not None
        assert result.id == new_jid

    async def test_returns_none_when_not_found(self, job_repo: SqlJobRepository) -> None:
        """등록되지 않은 youtube_video_id 조회 시 None을 반환해야 한다."""
        result = await job_repo.get_by_youtube_video_id("NotExistYYY")

        assert result is None


class TestJobRepositoryListRecent:
    """list_recent 페이지네이션 및 필터 검증."""

    async def test_list_recent_with_limit(self, job_repo: SqlJobRepository) -> None:
        """limit을 지정하면 최신 순으로 해당 수만큼 반환해야 한다."""
        base = datetime.now(tz=UTC)
        for i in range(5):
            jid = _job_id(f"LMLIM{i:014d}")
            job = _make_job(jid, created_at=base + timedelta(seconds=i))
            await job_repo.create(job)

        items, next_cursor = await job_repo.list_recent(limit=3)

        assert len(items) == 3
        assert next_cursor is not None

    async def test_list_recent_cursor_pagination(self, job_repo: SqlJobRepository) -> None:
        """커서로 다음 페이지를 가져올 수 있어야 한다."""
        base = datetime.now(tz=UTC)
        created_ids: list[str] = []
        for i in range(4):
            jid = _job_id(f"LMPAG{i:014d}")
            job = _make_job(jid, created_at=base + timedelta(seconds=i))
            saved = await job_repo.create(job)
            created_ids.append(saved.id)

        page1, cursor1 = await job_repo.list_recent(limit=2)
        assert len(page1) == 2
        assert cursor1 is not None

        page2, cursor2 = await job_repo.list_recent(limit=2, cursor=cursor1)
        assert len(page2) == 2

        # 두 페이지의 ID가 겹치면 안 됨
        ids1 = {j.id for j in page1}
        ids2 = {j.id for j in page2}
        assert ids1.isdisjoint(ids2)

    async def test_list_recent_no_next_cursor_on_last_page(self, job_repo: SqlJobRepository) -> None:
        """마지막 페이지에서는 next_cursor가 None이어야 한다."""
        base = datetime.now(tz=UTC)
        for i in range(2):
            jid = _job_id(f"LMLST{i:014d}")
            job = _make_job(jid, created_at=base + timedelta(seconds=i))
            await job_repo.create(job)

        items, next_cursor = await job_repo.list_recent(limit=100)

        assert len(items) >= 2
        assert next_cursor is None

    async def test_list_recent_with_status_filter(self, job_repo: SqlJobRepository) -> None:
        """status_filter를 적용하면 해당 상태의 작업만 반환해야 한다."""
        pending_jid = _job_id("LMFLT001000000000")
        failed_jid = _job_id("LMFLT002000000000")

        pending_job = _make_job(pending_jid, status=JobStatus.pending)
        failed_job = _make_job(failed_jid, status=JobStatus.pending)

        await job_repo.create(pending_job)
        await job_repo.create(failed_job)

        # failed_job을 failed 상태로 업데이트
        await job_repo.update_status(
            failed_jid,
            JobStatus.failed,
            completed_at=datetime.now(tz=UTC),
        )

        items, _ = await job_repo.list_recent(
            limit=10, status_filter=[JobStatus.failed]
        )

        assert all(j.status == JobStatus.failed for j in items)
        job_ids = {j.id for j in items}
        assert failed_jid in job_ids
        assert pending_jid not in job_ids


class TestJobRepositoryUpdateStatus:
    """update_status 상태 전이 검증."""

    async def test_update_status_transitions(self, job_repo: SqlJobRepository) -> None:
        """pending → downloading 전이 후 조회 시 상태가 반영되어야 한다."""
        jid = _job_id("USTS001000000000000")
        job = _make_job(jid)
        await job_repo.create(job)

        updated = await job_repo.update_status(jid, JobStatus.downloading)

        assert updated.status == JobStatus.downloading
        fetched = await job_repo.get(jid)
        assert fetched is not None
        assert fetched.status == JobStatus.downloading

    async def test_update_status_sets_completed_at_on_terminal(
        self, job_repo: SqlJobRepository
    ) -> None:
        """completed 전이 시 completed_at이 저장되어야 한다."""
        jid = _job_id("USTS002000000000000")
        job = _make_job(jid)
        await job_repo.create(job)
        now = datetime.now(tz=UTC)

        updated = await job_repo.update_status(
            jid, JobStatus.completed, completed_at=now
        )

        assert updated.completed_at is not None

    async def test_update_status_sets_error_fields_on_failed(
        self, job_repo: SqlJobRepository
    ) -> None:
        """failed 전이 시 error_* 필드가 저장되어야 한다."""
        jid = _job_id("USTS003000000000000")
        job = _make_job(jid)
        await job_repo.create(job)

        updated = await job_repo.update_status(
            jid,
            JobStatus.failed,
            error_stage="downloading",
            error_code="DOWNLOAD_FAILED",
            error_message="네트워크 오류",
            completed_at=datetime.now(tz=UTC),
        )

        assert updated.error_stage == "downloading"
        assert updated.error_code == "DOWNLOAD_FAILED"
        assert updated.error_message == "네트워크 오류"


class TestJobRepositoryUpdateMetadata:
    """update_metadata 동작 검증."""

    async def test_update_metadata_persists_fields(self, job_repo: SqlJobRepository) -> None:
        """메타데이터 갱신 후 조회 시 모든 필드가 반영되어야 한다."""
        jid = _job_id("UMETA001000000000000")
        job = _make_job(jid)
        await job_repo.create(job)

        metadata = VideoMetadata(
            title="리코쳐 로켓맨",
            channel="테스트 채널",
            duration_sec=300,
            subtitle_source="manual",
        )
        updated = await job_repo.update_metadata(jid, metadata)

        assert updated.metadata.title == "리코쳐 로켓맨"
        assert updated.metadata.channel == "테스트 채널"
        assert updated.metadata.duration_sec == 300
        assert updated.metadata.subtitle_source == "manual"


class TestJobRepositoryUpdateProgress:
    """update_progress no-op 동작 검증."""

    async def test_update_progress_is_noop(self, job_repo: SqlJobRepository) -> None:
        """update_progress 호출이 예외 없이 완료되어야 한다 (DB 저장 없음)."""
        jid = _job_id("Uprog001000000000000")
        job = _make_job(jid)
        await job_repo.create(job)

        # 예외 없이 완료되면 통과
        await job_repo.update_progress(jid, 0.42)

        # DB 변경 없음 — status 그대로
        fetched = await job_repo.get(jid)
        assert fetched is not None
        assert fetched.status == JobStatus.pending
