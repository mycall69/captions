"""T064: yt-dlp 자막 다운로드 wrapper 단위 테스트.

검증 항목:
- 수동 자막 발견 → source="manual" 반환
- 수동 자막 없고 자동 자막 발견 → source="auto" 반환
- 수동·자동 모두 없음 → SubtitleNotFoundError
- yt-dlp 미설치 → SubtitleNotFoundError
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import SubtitleNotFoundError
from app.infrastructure.youtube.subtitles import SubtitleDownloadResult, download_subtitles

VIDEO_ID = "abcdefghijk"


def _make_mock_proc(returncode: int = 0) -> AsyncMock:
    mock_proc = AsyncMock()
    mock_proc.returncode = returncode
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    return mock_proc


class TestManualSubtitleFound:
    """수동 자막 발견 시나리오."""

    async def test_returns_manual_source_when_ko_vtt_exists(self, tmp_path: Path) -> None:
        """수동 ko.vtt 파일이 있으면 source='manual'로 반환해야 한다."""
        # yt-dlp가 파일을 생성한 것처럼 시뮬레이션
        vtt_file = tmp_path / f"{VIDEO_ID}.ko.vtt"
        vtt_file.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n안녕하세요")

        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await download_subtitles(
                youtube_video_id=VIDEO_ID,
                output_dir=tmp_path,
                languages=("ko", "ja"),
            )

        assert isinstance(result, SubtitleDownloadResult)
        assert result.source == "manual"
        assert result.language == "ko"
        assert result.file_path == vtt_file
        assert result.format == "vtt"

    async def test_returns_manual_source_when_ja_vtt_exists(self, tmp_path: Path) -> None:
        """수동 ja.vtt 파일이 있으면 source='manual'로 반환해야 한다."""
        vtt_file = tmp_path / f"{VIDEO_ID}.ja.vtt"
        vtt_file.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nこんにちは")

        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await download_subtitles(
                youtube_video_id=VIDEO_ID,
                output_dir=tmp_path,
                languages=("ko", "ja"),
            )

        assert result.source == "manual"
        assert result.language == "ja"

    async def test_ko_prioritized_over_ja(self, tmp_path: Path) -> None:
        """ko와 ja 모두 있으면 ko가 우선되어야 한다 (languages 순서)."""
        (tmp_path / f"{VIDEO_ID}.ko.vtt").write_text("WEBVTT\n\nko content")
        (tmp_path / f"{VIDEO_ID}.ja.vtt").write_text("WEBVTT\n\nja content")

        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await download_subtitles(
                youtube_video_id=VIDEO_ID,
                output_dir=tmp_path,
                languages=("ko", "ja"),
            )

        assert result.language == "ko"  # noqa: SIM117 (awaiting above block)


class TestAutoSubtitleFallback:
    """자동 생성 자막 fallback 시나리오."""

    async def test_returns_auto_source_when_manual_missing(self, tmp_path: Path) -> None:
        """수동 자막 없고 자동 자막이 있으면 source='auto'로 반환해야 한다."""
        call_count = 0

        def _side_effect(*args: object, **kwargs: object) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            # 두 번째 호출(auto) 후 파일 생성
            if call_count == 2:
                vtt_file = tmp_path / f"{VIDEO_ID}.ko.vtt"
                vtt_file.write_text("WEBVTT\n\nauto subtitle")
            return _make_mock_proc()

        with (
            patch("asyncio.create_subprocess_exec", side_effect=_side_effect),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await download_subtitles(
                youtube_video_id=VIDEO_ID,
                output_dir=tmp_path,
                languages=("ko", "ja"),
            )

        assert result.source == "auto"
        assert result.language == "ko"

    async def test_calls_ytdlp_twice_on_manual_failure(self, tmp_path: Path) -> None:
        """수동 자막 실패 시 yt-dlp를 두 번(manual + auto) 호출해야 한다."""
        call_count = 0

        def _side_effect(*args: object, **kwargs: object) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                (tmp_path / f"{VIDEO_ID}.ko.vtt").write_text("WEBVTT\n\nauto")
            return _make_mock_proc()

        with (
            patch("asyncio.create_subprocess_exec", side_effect=_side_effect),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            await download_subtitles(
                youtube_video_id=VIDEO_ID,
                output_dir=tmp_path,
            )

        assert call_count == 2


class TestSubtitleNotFound:
    """자막 미발견 시나리오."""

    async def test_raises_subtitle_not_found_when_both_fail(self, tmp_path: Path) -> None:
        """수동·자동 모두 없으면 SubtitleNotFoundError가 발생해야 한다."""
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(SubtitleNotFoundError):
                await download_subtitles(
                    youtube_video_id=VIDEO_ID,
                    output_dir=tmp_path,
                )

    async def test_not_found_error_details_include_languages(self, tmp_path: Path) -> None:
        """SubtitleNotFoundError의 details에 languages_attempted가 포함되어야 한다."""
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(SubtitleNotFoundError) as exc_info:
                await download_subtitles(
                    youtube_video_id=VIDEO_ID,
                    output_dir=tmp_path,
                    languages=("ko", "ja"),
                )

        details = exc_info.value.details
        assert "languages_attempted" in details
        assert "ko" in details["languages_attempted"]

    async def test_no_ytdlp_binary_raises_subtitle_not_found(self, tmp_path: Path) -> None:
        """yt-dlp 실행 파일이 없으면 SubtitleNotFoundError가 발생해야 한다."""
        with patch("shutil.which", return_value=None):  # noqa: SIM117
            with pytest.raises(SubtitleNotFoundError):
                await download_subtitles(
                    youtube_video_id=VIDEO_ID,
                    output_dir=tmp_path,
                )
