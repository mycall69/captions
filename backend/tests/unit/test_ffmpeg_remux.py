"""T066: ffmpeg remux wrapper 단위 테스트.

검증 항목:
- args 리스트에 "-c", "copy" 포함
- args 리스트에 "-movflags", "+faststart" 포함
- args가 배열임을 보장 (shell=True 금지)
- 동일 경로(mp4→mp4 no-op) 시 subprocess 호출 없이 input_path 반환
- ffmpeg 미설치 → RenderFailedError
- ffmpeg 비정상 종료 → RenderFailedError
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import RenderFailedError
from app.domain.media.render import remux_to_mp4


def _make_mock_proc(returncode: int = 0) -> AsyncMock:
    mock_proc = AsyncMock()
    mock_proc.returncode = returncode
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    return mock_proc


@pytest.fixture
def input_mkv(tmp_path: Path) -> Path:
    p = tmp_path / "input.mkv"
    p.write_bytes(b"fake-mkv")
    return p


@pytest.fixture
def output_mp4(tmp_path: Path) -> Path:
    return tmp_path / "output.mp4"


class TestRemuxArgs:
    """ffmpeg 명령행 인자 검증."""

    async def test_includes_stream_copy_flags(self, input_mkv: Path, output_mp4: Path) -> None:
        """-c copy 플래그가 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        args = mock_exec.call_args.args
        assert "-c" in args
        assert "copy" in args

    async def test_includes_faststart_flag(self, input_mkv: Path, output_mp4: Path) -> None:
        """-movflags +faststart 플래그가 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        args = mock_exec.call_args.args
        assert "-movflags" in args
        assert "+faststart" in args

    async def test_args_is_list_not_shell_string(self, input_mkv: Path, output_mp4: Path) -> None:
        """args는 개별 문자열 항목 목록이어야 하며 단일 shell 문자열이 아니어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        args = mock_exec.call_args.args
        assert len(args) > 1, "단일 문자열 대신 개별 인자 목록이어야 합니다"
        for arg in args:
            assert isinstance(arg, str), f"각 인자는 문자열이어야 합니다: {arg!r}"

    async def test_input_and_output_paths_in_args(self, input_mkv: Path, output_mp4: Path) -> None:
        """입력·출력 경로가 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        args = mock_exec.call_args.args
        assert str(input_mkv) in args
        assert str(output_mp4) in args

    async def test_overwrite_flag_present(self, input_mkv: Path, output_mp4: Path) -> None:
        """-y(덮어쓰기) 플래그가 args에 포함되어야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        args = mock_exec.call_args.args
        assert "-y" in args


class TestRemuxNoOp:
    """동일 경로 no-op 시나리오."""

    async def test_same_mp4_path_returns_input_without_subprocess(self, tmp_path: Path) -> None:
        """input과 output이 동일한 .mp4 경로이면 ffmpeg를 호출하지 않고 input_path를 반환해야 한다."""
        mp4_file = tmp_path / "video.mp4"
        mp4_file.write_bytes(b"fake-mp4")

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await remux_to_mp4(input_path=mp4_file, output_path=mp4_file)

        mock_exec.assert_not_called()
        assert result == mp4_file

    async def test_different_paths_calls_ffmpeg(self, input_mkv: Path, output_mp4: Path) -> None:
        """입출력 경로가 다르면 ffmpeg를 호출해야 한다."""
        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec,
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        mock_exec.assert_called_once()


class TestRemuxFailures:
    """실패 시나리오."""

    async def test_no_ffmpeg_binary_raises_render_failed(
        self, input_mkv: Path, output_mp4: Path
    ) -> None:
        """ffmpeg 실행 파일이 없으면 RenderFailedError가 발생해야 한다."""
        with patch("shutil.which", return_value=None):  # noqa: SIM117
            with pytest.raises(RenderFailedError):
                await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

    async def test_nonzero_returncode_raises_render_failed(
        self, input_mkv: Path, output_mp4: Path
    ) -> None:
        """ffmpeg 비정상 종료 시 RenderFailedError가 발생해야 한다."""
        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc(returncode=1)),
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            with pytest.raises(RenderFailedError):
                await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

    async def test_render_failed_error_details_contain_stderr(
        self, input_mkv: Path, output_mp4: Path
    ) -> None:
        """RenderFailedError의 details에 stderr_tail이 포함되어야 한다."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error output"))

        with (  # noqa: SIM117
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            with pytest.raises(RenderFailedError) as exc_info:
                await remux_to_mp4(input_path=input_mkv, output_path=output_mp4)

        assert "stderr_tail" in exc_info.value.details

    async def test_uses_custom_ffmpeg_path(self, input_mkv: Path, output_mp4: Path) -> None:
        """ffmpeg_path 인자가 있으면 shutil.which 대신 해당 경로를 사용해야 한다."""
        custom_path = "/custom/ffmpeg"
        with patch("asyncio.create_subprocess_exec", return_value=_make_mock_proc()) as mock_exec:
            await remux_to_mp4(
                input_path=input_mkv,
                output_path=output_mp4,
                ffmpeg_path=custom_path,
            )

        args = mock_exec.call_args.args
        assert args[0] == custom_path
