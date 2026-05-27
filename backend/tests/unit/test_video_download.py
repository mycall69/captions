"""T063: yt-dlp 비디오 다운로드 wrapper 단위 테스트.

검증 항목:
- args 리스트에 포맷 플래그 포함 여부
- args 리스트에 --no-playlist 포함 여부
- args가 배열(list)임을 보장 (shell=True 금지)
- 비정상 종료 코드 → DownloadFailedError
- 출력 파일 미생성 시 → DownloadFailedError
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import DownloadFailedError
from app.domain.media.download import YTDLP_FORMAT, download_video


@pytest.fixture
def fake_output(tmp_path: Path) -> Path:
    """가짜 출력 파일 (yt-dlp가 생성한 것처럼 시뮬레이션)."""
    p = tmp_path / "video.mp4"
    p.write_bytes(b"fake-video-data")
    return p


def _make_mock_proc(returncode: int = 0) -> AsyncMock:
    mock_proc = AsyncMock()
    mock_proc.returncode = returncode
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    return mock_proc


class TestDownloadVideoArgs:
    """다운로드 명령행 인자 검증."""

    async def test_uses_format_flag(self, fake_output: Path) -> None:
        """-f 플래그와 YTDLP_FORMAT 값이 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            await download_video(youtube_video_id="abcdefghijk", output_path=fake_output)

        args = mock_exec.call_args.args
        assert "-f" in args
        assert YTDLP_FORMAT in args

    async def test_includes_no_playlist(self, fake_output: Path) -> None:
        """--no-playlist 플래그가 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            await download_video(youtube_video_id="abcdefghijk", output_path=fake_output)

        args = mock_exec.call_args.args
        assert "--no-playlist" in args

    async def test_args_is_list_not_string(self, fake_output: Path) -> None:
        """args는 튜플/리스트여야 하며 단일 문자열이 아닌 개별 항목으로 전달되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            await download_video(youtube_video_id="abcdefghijk", output_path=fake_output)

        # create_subprocess_exec는 개별 인자로 호출되어야 함 (shell=True 불가)
        args = mock_exec.call_args.args
        assert len(args) > 1, "단일 문자열 대신 개별 인자 목록이어야 합니다"
        for arg in args:
            assert isinstance(arg, str), f"각 인자는 문자열이어야 합니다: {arg!r}"

    async def test_output_path_in_args(self, fake_output: Path) -> None:
        """-o 플래그와 output_path 값이 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            await download_video(youtube_video_id="abcdefghijk", output_path=fake_output)

        args = mock_exec.call_args.args
        assert "-o" in args
        assert str(fake_output) in args

    async def test_url_contains_video_id(self, fake_output: Path) -> None:
        """URL에 영상 ID가 포함되어야 한다."""
        video_id = "abcdefghijk"
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            await download_video(youtube_video_id=video_id, output_path=fake_output)

        args = mock_exec.call_args.args
        assert any(video_id in arg for arg in args), "URL에 영상 ID가 포함되어야 합니다"


class TestDownloadVideoFailures:
    """실패 시나리오 검증."""

    async def test_nonzero_returncode_raises_download_failed(self, tmp_path: Path) -> None:
        """yt-dlp 비정상 종료 시 DownloadFailedError가 발생해야 한다."""
        output = tmp_path / "video.mp4"
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(returncode=1)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(DownloadFailedError):
                await download_video(youtube_video_id="abcdefghijk", output_path=output)

    async def test_missing_output_file_raises_download_failed(self, tmp_path: Path) -> None:
        """yt-dlp 성공 종료 후 출력 파일이 없으면 DownloadFailedError가 발생해야 한다."""
        output = tmp_path / "video.mp4"
        # 파일을 생성하지 않음 — output.exists()가 False
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(returncode=0)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(DownloadFailedError):
                await download_video(youtube_video_id="abcdefghijk", output_path=output)

    async def test_no_ytdlp_binary_raises_download_failed(self, tmp_path: Path) -> None:
        """yt-dlp 실행 파일이 없으면 DownloadFailedError가 발생해야 한다."""
        output = tmp_path / "video.mp4"
        with patch("shutil.which", return_value=None):  # noqa: SIM117
            with pytest.raises(DownloadFailedError):
                await download_video(youtube_video_id="abcdefghijk", output_path=output)

    async def test_error_details_include_video_id(self, tmp_path: Path) -> None:
        """DownloadFailedError의 details에 video_id가 포함되어야 한다."""
        output = tmp_path / "video.mp4"
        video_id = "abcdefghijk"
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(returncode=1)),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            with pytest.raises(DownloadFailedError) as exc_info:
                await download_video(youtube_video_id=video_id, output_path=output)
        assert exc_info.value.details.get("video_id") == video_id


class TestDownloadVideoSuccess:
    """성공 시나리오 검증."""

    async def test_returns_output_path(self, fake_output: Path) -> None:
        """성공 시 output_path를 반환해야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            result = await download_video(youtube_video_id="abcdefghijk", output_path=fake_output)

        assert result == fake_output

    async def test_uses_custom_ytdlp_path(self, fake_output: Path) -> None:
        """yt_dlp_path 인자가 있으면 shutil.which 대신 해당 경로를 사용해야 한다."""
        custom_path = "/custom/yt-dlp"
        with patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec:
            await download_video(
                youtube_video_id="abcdefghijk",
                output_path=fake_output,
                yt_dlp_path=custom_path,
            )

        args = mock_exec.call_args.args
        assert args[0] == custom_path
