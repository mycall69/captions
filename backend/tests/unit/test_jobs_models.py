"""T022 단위 테스트: VideoJob 및 VideoMetadata Pydantic 도메인 모델.

openapi.yaml 스키마 제약과의 정합성 및 유효성 검사 규칙을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.states import JobStatus

# ── 공통 fixture ─────────────────────────────────────────────────────────────

_NOW = datetime.now(tz=UTC)

_VALID_JOB_DATA: dict = {
    "id": "01JXXXXXXXXXXXXXXXXXXXXXXX",  # 26자 ULID
    "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
    "youtube_video_id": "abcdefghijk",  # 11자
    "status": JobStatus.pending,
    "metadata": {},
    "created_at": _NOW,
    "updated_at": _NOW,
}


def _make_job(**overrides) -> VideoJob:
    return VideoJob(**{**_VALID_JOB_DATA, **overrides})


class TestVideoMetadata:
    """VideoMetadata 모델 검증."""

    def test_all_fields_optional_default_none(self) -> None:
        """모든 필드가 Optional이므로 인자 없이 생성 가능해야 한다."""
        meta = VideoMetadata()
        assert meta.title is None
        assert meta.channel is None
        assert meta.duration_sec is None
        assert meta.subtitle_source is None

    def test_valid_subtitle_source_values(self) -> None:
        """subtitle_source는 'manual' 또는 'auto'만 허용해야 한다."""
        m1 = VideoMetadata(subtitle_source="manual")
        assert m1.subtitle_source == "manual"

        m2 = VideoMetadata(subtitle_source="auto")
        assert m2.subtitle_source == "auto"

    def test_invalid_subtitle_source_raises(self) -> None:
        """허용되지 않는 subtitle_source 값은 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            VideoMetadata(subtitle_source="generated")


class TestVideoJobId:
    """VideoJob id 필드 검증 — 26자 ULID."""

    def test_valid_26_char_id_accepted(self) -> None:
        """26자 id는 유효하게 통과해야 한다."""
        job = _make_job(id="A" * 26)
        assert job.id == "A" * 26

    def test_short_id_raises(self) -> None:
        """25자 미만 id는 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(id="A" * 25)

    def test_long_id_raises(self) -> None:
        """27자 초과 id는 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(id="A" * 27)


class TestVideoJobYoutubeId:
    """VideoJob youtube_video_id 필드 검증 — 정확히 11자."""

    def test_valid_11_char_id_accepted(self) -> None:
        """11자 youtube_video_id는 유효하게 통과해야 한다."""
        job = _make_job(youtube_video_id="dQw4w9WgXcQ")
        assert job.youtube_video_id == "dQw4w9WgXcQ"

    def test_short_youtube_id_raises(self) -> None:
        """10자 youtube_video_id는 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(youtube_video_id="dQw4w9WgXc")

    def test_long_youtube_id_raises(self) -> None:
        """12자 youtube_video_id는 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(youtube_video_id="dQw4w9WgXcQQ")


class TestVideoJobSourceUrl:
    """VideoJob source_url 필드 검증 — HttpUrl."""

    def test_valid_http_url_accepted(self) -> None:
        """유효한 HTTP URL은 통과해야 한다."""
        job = _make_job(source_url="https://www.youtube.com/watch?v=abcdefghijk")
        assert str(job.source_url).startswith("https://")

    def test_invalid_url_raises(self) -> None:
        """URL 형식이 아닌 값은 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(source_url="not-a-url")


class TestVideoJobProgress:
    """VideoJob progress 필드 범위 검증 — 0.0 ≤ progress ≤ 1.0."""

    def test_progress_none_by_default(self) -> None:
        """progress 기본값은 None이어야 한다."""
        job = _make_job()
        assert job.progress is None

    def test_progress_zero_accepted(self) -> None:
        job = _make_job(progress=0.0)
        assert job.progress == 0.0

    def test_progress_one_accepted(self) -> None:
        job = _make_job(progress=1.0)
        assert job.progress == 1.0

    def test_progress_midpoint_accepted(self) -> None:
        job = _make_job(progress=0.46)
        assert job.progress == pytest.approx(0.46)

    def test_progress_below_zero_raises(self) -> None:
        """0 미만 progress는 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(progress=-0.01)

    def test_progress_above_one_raises(self) -> None:
        """1 초과 progress는 ValidationError를 발생시켜야 한다."""
        with pytest.raises(ValidationError):
            _make_job(progress=1.01)


class TestVideoJobMetadata:
    """VideoJob metadata 필드 — 중첩 VideoMetadata."""

    def test_metadata_from_dict(self) -> None:
        """빈 dict로도 VideoMetadata 중첩 생성이 가능해야 한다."""
        job = _make_job(metadata={})
        assert isinstance(job.metadata, VideoMetadata)

    def test_metadata_with_values(self) -> None:
        """메타데이터 필드값이 올바르게 전달되어야 한다."""
        job = _make_job(
            metadata={
                "title": "테스트 영상",
                "channel": "테스트 채널",
                "duration_sec": 300,
                "subtitle_source": "manual",
            }
        )
        assert job.metadata.title == "테스트 영상"
        assert job.metadata.channel == "테스트 채널"
        assert job.metadata.duration_sec == 300
        assert job.metadata.subtitle_source == "manual"


class TestVideoJobOptionalFields:
    """VideoJob 선택 필드 기본값 검증."""

    def test_optional_fields_default_none(self) -> None:
        """source_language, target_language, error_* 필드는 기본값이 None이어야 한다."""
        job = _make_job()
        assert job.source_language is None
        assert job.target_language is None
        assert job.error_stage is None
        assert job.error_code is None
        assert job.error_message is None
        assert job.completed_at is None

    def test_reused_default_false(self) -> None:
        """reused 기본값은 False이어야 한다."""
        job = _make_job()
        assert job.reused is False

    def test_status_field_accepts_enum(self) -> None:
        """status 필드는 JobStatus 열거형을 직접 받아야 한다."""
        job = _make_job(status=JobStatus.downloading)
        assert job.status == JobStatus.downloading

    def test_status_field_accepts_string(self) -> None:
        """status 필드는 문자열도 JobStatus로 파싱해야 한다."""
        job = _make_job(status="translating")
        assert job.status == JobStatus.translating
