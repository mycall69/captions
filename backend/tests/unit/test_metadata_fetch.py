"""T065: yt-dlp 메타데이터 추출 + 영상 길이 검증 단위 테스트.

검증 항목:
- 정상 경로: title·channel·duration_sec 파싱
- duration > 3600 → VideoTooLongError (code=INVALID_INPUT)
- duration == 3600 → 허용 (경계값)
- duration == 3601 → 거절 (T065 spec)
- duration 없음 → duration_sec=None 반환
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.jobs.models import VideoMetadata
from app.infrastructure.youtube.metadata import MAX_DURATION_SEC, VideoTooLongError, fetch_metadata

VIDEO_ID = "abcdefghijk"


def _make_mock_proc(stdout: bytes = b"", returncode: int = 0) -> AsyncMock:
    mock_proc = AsyncMock()
    mock_proc.returncode = returncode
    mock_proc.communicate = AsyncMock(return_value=(stdout, b""))
    return mock_proc


def _ytdlp_json(**kwargs: object) -> bytes:
    """yt-dlp --dump-json 형식의 최소 JSON 바이트 생성."""
    data: dict[str, object] = {
        "id": VIDEO_ID,
        "title": "테스트 영상",
        "channel": "테스트 채널",
        "duration": 1800,
    }
    data.update(kwargs)
    return json.dumps(data).encode()


class TestFetchMetadataHappyPath:
    """정상 경로 — 메타데이터 파싱 검증."""

    async def test_parses_title(self) -> None:
        """title 필드가 VideoMetadata에 올바르게 매핑되어야 한다."""
        payload = _ytdlp_json(title="멋진 영상")
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.title == "멋진 영상"

    async def test_parses_channel(self) -> None:
        """channel 필드가 VideoMetadata에 올바르게 매핑되어야 한다."""
        payload = _ytdlp_json(channel="멋진 채널")
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.channel == "멋진 채널"

    async def test_falls_back_to_uploader_when_channel_missing(self) -> None:
        """channel 없을 때 uploader 값으로 fallback되어야 한다."""
        payload = json.dumps(
            {"id": VIDEO_ID, "title": "t", "uploader": "업로더", "duration": 100}
        ).encode()
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.channel == "업로더"

    async def test_parses_duration_sec(self) -> None:
        """duration 필드가 duration_sec(int)으로 매핑되어야 한다."""
        payload = _ytdlp_json(duration=1234)
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.duration_sec == 1234

    async def test_returns_video_metadata_instance(self) -> None:
        """반환값이 VideoMetadata 인스턴스여야 한다."""
        payload = _ytdlp_json()
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert isinstance(result, VideoMetadata)

    async def test_subtitle_source_is_none(self) -> None:
        """subtitle_source는 None이어야 한다 (자막 단계에서 결정)."""
        payload = _ytdlp_json()
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.subtitle_source is None


class TestDurationValidation:
    """영상 길이 검증 — 60분 상한."""

    async def test_duration_3601_raises_video_too_long(self) -> None:
        """duration=3601 → VideoTooLongError 발생 (T065 spec)."""
        payload = _ytdlp_json(duration=3601)
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(VideoTooLongError) as exc_info:
                await fetch_metadata(VIDEO_ID)

        assert exc_info.value.code == "INVALID_INPUT"
        assert "3601" in exc_info.value.message

    async def test_duration_3601_error_message_contains_actual_duration(self) -> None:
        """에러 메시지에 실제 영상 길이(초)가 포함되어야 한다."""
        payload = _ytdlp_json(duration=3601)
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(VideoTooLongError) as exc_info:
                await fetch_metadata(VIDEO_ID)

        assert "3601" in exc_info.value.message

    async def test_duration_3600_is_allowed(self) -> None:
        """duration=3600 (정확히 60분) → 허용 (경계값)."""
        payload = _ytdlp_json(duration=3600)
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.duration_sec == MAX_DURATION_SEC

    async def test_duration_over_3600_raises(self) -> None:
        """duration > 3600이면 VideoTooLongError가 발생해야 한다."""
        payload = _ytdlp_json(duration=7200)
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(VideoTooLongError):
                await fetch_metadata(VIDEO_ID)

    async def test_duration_missing_returns_none(self) -> None:
        """duration 필드 없으면 duration_sec=None 반환해야 한다."""
        payload = json.dumps({"id": VIDEO_ID, "title": "t", "channel": "c"}).encode()
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await fetch_metadata(VIDEO_ID)

        assert result.duration_sec is None

    async def test_error_details_include_duration_sec(self) -> None:
        """VideoTooLongError의 details에 duration_sec이 포함되어야 한다."""
        payload = _ytdlp_json(duration=3601)
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(stdout=payload)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(VideoTooLongError) as exc_info:
                await fetch_metadata(VIDEO_ID)

        assert exc_info.value.details.get("duration_sec") == 3601
        assert exc_info.value.details.get("max_duration_sec") == MAX_DURATION_SEC


class TestFetchMetadataFailures:
    """실패 시나리오."""

    async def test_ytdlp_nonzero_rc_raises_domain_error(self) -> None:
        """yt-dlp 비정상 종료 시 DomainError가 발생해야 한다."""
        from app.core.exceptions import DomainError

        with (  # noqa: SIM117
            patch(
                "asyncio.create_subprocess_exec",
                return_value=_make_mock_proc(stdout=b"", returncode=1),
            ),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(DomainError):
                await fetch_metadata(VIDEO_ID)

    async def test_invalid_json_raises_domain_error(self) -> None:
        """JSON 파싱 실패 시 DomainError가 발생해야 한다."""
        from app.core.exceptions import DomainError

        with (  # noqa: SIM117
            patch(
                "asyncio.create_subprocess_exec",
                return_value=_make_mock_proc(stdout=b"not-json"),
            ),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(DomainError):
                await fetch_metadata(VIDEO_ID)

    async def test_no_ytdlp_binary_raises_domain_error(self) -> None:
        """yt-dlp 실행 파일 미발견 시 DomainError가 발생해야 한다."""
        from app.core.exceptions import DomainError

        with patch("shutil.which", return_value=None):  # noqa: SIM117
            with pytest.raises(DomainError):
                await fetch_metadata(VIDEO_ID)
