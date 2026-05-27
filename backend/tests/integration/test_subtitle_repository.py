"""T068: SqlSubtitleRepository 통합 테스트.

in-memory SQLite db_session 위에서 트랙/큐 저장 및 페이지네이션을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.states import JobStatus
from app.domain.subtitles.models import SubtitleCue, SubtitleTrack
from app.infrastructure.db.repositories.job_repository import SqlJobRepository
from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository

pytestmark = pytest.mark.integration


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _jid(tag: str) -> str:
    """26자 테스트 job ID를 생성한다."""
    return f"01JSUBJOB{tag}".ljust(26, "0")[:26]


def _tid(tag: str) -> str:
    """26자 테스트 track ID를 생성한다."""
    return f"01JSUBTRAK{tag}".ljust(26, "0")[:26]


def _make_track(
    track_id: str,
    job_id: str,
    kind: str = "source",
    cues: list[SubtitleCue] | None = None,
) -> SubtitleTrack:
    """테스트용 SubtitleTrack 도메인 모델을 생성한다."""
    assert len(track_id) == 26
    assert len(job_id) == 26
    return SubtitleTrack(
        id=track_id,
        job_id=job_id,
        kind=kind,  # type: ignore[arg-type]
        language="ko",
        origin="manual",
        cues=cues or [],
    )


def _make_cues(n: int, start_offset: int = 0) -> list[SubtitleCue]:
    """n개의 연속된 SubtitleCue 목록을 생성한다."""
    cues = []
    for i in range(n):
        seq = start_offset + i + 1
        start = (seq - 1) * 1000
        cues.append(
            SubtitleCue(
                sequence=seq,
                start_ms=start,
                end_ms=start + 900,
                text=f"자막 {seq}",
            )
        )
    return cues


async def _create_job(job_repo: SqlJobRepository, job_id: str) -> None:
    """테스트용 VideoJob을 DB에 저장한다."""
    assert len(job_id) == 26
    now = datetime.now(tz=UTC)
    job = VideoJob(
        id=job_id,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",  # type: ignore[arg-type]
        youtube_video_id="dQw4w9WgXcY",
        status=JobStatus.pending,
        metadata=VideoMetadata(),
        created_at=now,
        updated_at=now,
    )
    await job_repo.create(job)


# ── 테스트 클래스 ─────────────────────────────────────────────────────────────


class TestSubtitleRepositorySaveTrack:
    """save_track 동작 검증."""

    async def test_save_track_persists_track_and_cues(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """save_track 호출 시 트랙과 모든 큐가 DB에 저장되어야 한다."""
        job_id = _jid("SAVE001")
        await _create_job(job_repo, job_id)

        track_id = _tid("SAVE001")
        cues = _make_cues(3)
        track = _make_track(track_id, job_id, cues=cues)

        saved = await subtitle_repo.save_track(track)

        assert saved.id == track_id
        assert saved.cue_count == 3

        # DB에서 큐 직접 확인
        all_cues = await subtitle_repo.load_all_cues(track_id)
        assert len(all_cues) == 3

    async def test_save_track_without_cues(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """cues가 비어있어도 트랙 메타데이터는 정상 저장되어야 한다."""
        job_id = _jid("SAVE002")
        await _create_job(job_repo, job_id)

        track_id = _tid("SAVE002")
        track = _make_track(track_id, job_id, cues=[])

        saved = await subtitle_repo.save_track(track)

        assert saved.cue_count == 0


class TestSubtitleRepositoryGetTrack:
    """get_track 동작 검증."""

    async def test_get_track_returns_track_with_empty_cues(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """get_track은 트랙 메타데이터를 반환하고 cues=[]로 설정해야 한다."""
        job_id = _jid("GTRK001")
        await _create_job(job_repo, job_id)

        track_id = _tid("GTRK001")
        cues = _make_cues(2)
        track = _make_track(track_id, job_id, kind="source", cues=cues)
        await subtitle_repo.save_track(track)

        fetched = await subtitle_repo.get_track(job_id, "source")

        assert fetched is not None
        assert fetched.id == track_id
        assert fetched.cues == []
        assert fetched.cue_count == 2

    async def test_get_track_returns_none_for_missing(
        self, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """존재하지 않는 트랙 조회 시 None을 반환해야 한다."""
        result = await subtitle_repo.get_track(_jid("NOEXIST0"), "source")

        assert result is None


class TestSubtitleRepositoryListCues:
    """list_cues 페이지네이션 검증."""

    async def test_list_cues_pagination(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """list_cues는 offset/limit 페이지네이션이 올바르게 동작해야 한다."""
        job_id = _jid("LCUES001")
        await _create_job(job_repo, job_id)

        track_id = _tid("LCUES001")
        cues = _make_cues(10)
        track = _make_track(track_id, job_id, cues=cues)
        await subtitle_repo.save_track(track)

        # 첫 페이지: offset=0, limit=4
        page1, total = await subtitle_repo.list_cues(track_id, offset=0, limit=4)
        assert len(page1) == 4
        assert total == 10
        assert page1[0].sequence == 1
        assert page1[3].sequence == 4

        # 두 번째 페이지: offset=4, limit=4
        page2, total2 = await subtitle_repo.list_cues(track_id, offset=4, limit=4)
        assert len(page2) == 4
        assert total2 == 10
        assert page2[0].sequence == 5

    async def test_list_cues_total_count_is_accurate(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """list_cues의 total은 실제 큐 수와 정확히 일치해야 한다."""
        job_id = _jid("LCUES002")
        await _create_job(job_repo, job_id)

        track_id = _tid("LCUES002")
        cues = _make_cues(7)
        track = _make_track(track_id, job_id, cues=cues)
        await subtitle_repo.save_track(track)

        _, total = await subtitle_repo.list_cues(track_id, offset=0, limit=3)

        assert total == 7


class TestSubtitleRepositoryLoadAllCues:
    """load_all_cues 동작 검증."""

    async def test_load_all_cues_returns_in_sequence_order(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """load_all_cues는 sequence 오름차순으로 전체 큐를 반환해야 한다."""
        job_id = _jid("LACUES01")
        await _create_job(job_repo, job_id)

        track_id = _tid("LACUES01")
        cues = _make_cues(5)
        track = _make_track(track_id, job_id, cues=cues)
        await subtitle_repo.save_track(track)

        all_cues = await subtitle_repo.load_all_cues(track_id)

        assert len(all_cues) == 5
        sequences = [c.sequence for c in all_cues]
        assert sequences == sorted(sequences)
        assert sequences == [1, 2, 3, 4, 5]

    async def test_load_all_cues_empty_for_no_cues(
        self, db_session, job_repo: SqlJobRepository, subtitle_repo: SqlSubtitleRepository
    ) -> None:
        """큐가 없는 트랙에서 load_all_cues 호출 시 빈 목록을 반환해야 한다."""
        job_id = _jid("LACUES02")
        await _create_job(job_repo, job_id)

        track_id = _tid("LACUES02")
        track = _make_track(track_id, job_id, cues=[])
        await subtitle_repo.save_track(track)

        all_cues = await subtitle_repo.load_all_cues(track_id)

        assert all_cues == []
