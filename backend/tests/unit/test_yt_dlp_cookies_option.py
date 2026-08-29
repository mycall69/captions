"""Settings.yt_dlp_cookies_browser 가 yt-dlp 호출 인자에 반영되는지 검증.

spec 후속 결정(2026-05-28): YouTube anti-bot 게이트("Sign in to confirm
you're not a bot") 우회를 위해 로컬 브라우저 쿠키를 사용하는 옵션을 제공한다.

본 테스트는 호출 인자 구조만 검증한다 (실제 yt-dlp 호출은 monkeypatch 로 가로챔).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Any:
    """Settings 는 lru_cache 로 캐싱되므로 매 테스트마다 초기화한다."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestExtractSubtitlesCookiesArgs:
    """download_manual_subtitles / download_auto_subtitles 의 --cookies-from-browser 동작."""

    def test_manual_includes_cookies_when_env_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """YT_DLP_COOKIES_BROWSER=firefox 일 때 manual 호출에 옵션이 포함되어야 한다."""
        monkeypatch.setenv("YT_DLP_COOKIES_BROWSER", "firefox")
        from app.workers.tasks.extract_subtitles import download_manual_subtitles

        recorded: dict[str, list[str]] = {}

        def _spy_run(args: list[str], **_kwargs: object) -> Any:
            recorded["args"] = args

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        with (
            patch("subprocess.run", side_effect=_spy_run),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            download_manual_subtitles(youtube_video_id="abcdefghijk", output_dir=tmp_path)

        args = recorded["args"]
        assert "--cookies-from-browser" in args
        assert args[args.index("--cookies-from-browser") + 1] == "firefox"

    def test_auto_includes_cookies_when_env_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """YT_DLP_COOKIES_BROWSER=safari 일 때 auto 호출에 옵션이 포함되어야 한다."""
        monkeypatch.setenv("YT_DLP_COOKIES_BROWSER", "safari")
        from app.workers.tasks.extract_subtitles import download_auto_subtitles

        recorded: dict[str, list[str]] = {}

        def _spy_run(args: list[str], **_kwargs: object) -> Any:
            recorded["args"] = args

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        with (
            patch("subprocess.run", side_effect=_spy_run),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            download_auto_subtitles(youtube_video_id="abcdefghijk", output_dir=tmp_path)

        args = recorded["args"]
        assert "--cookies-from-browser" in args
        assert args[args.index("--cookies-from-browser") + 1] == "safari"

    def test_omits_cookies_when_env_unset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """YT_DLP_COOKIES_BROWSER 미설정 시 옵션이 추가되지 않아야 한다 (기본 동작 유지)."""
        monkeypatch.delenv("YT_DLP_COOKIES_BROWSER", raising=False)
        from app.workers.tasks.extract_subtitles import download_manual_subtitles

        recorded: dict[str, list[str]] = {}

        def _spy_run(args: list[str], **_kwargs: object) -> Any:
            recorded["args"] = args

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        with (
            patch("subprocess.run", side_effect=_spy_run),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            download_manual_subtitles(youtube_video_id="abcdefghijk", output_dir=tmp_path)

        assert "--cookies-from-browser" not in recorded["args"]


class TestDownloadTaskCookiesArgs:
    """_run_yt_dlp(영상 다운로드) 의 --cookies-from-browser 동작.

    이전엔 자막 다운로드 3곳에만 쿠키 옵션이 적용되어 있었고, 영상 본체 다운로드는
    여전히 anti-bot 게이트에 막혀 PIPELINE_FAILED 가 발생했던 케이스의 회귀 방지.
    """

    def test_download_includes_cookies_when_env_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """YT_DLP_COOKIES_BROWSER=firefox 일 때 download 호출에 옵션이 포함되어야 한다."""
        monkeypatch.setenv("YT_DLP_COOKIES_BROWSER", "firefox")
        from app.workers.tasks.download import _run_yt_dlp

        recorded: dict[str, list[str]] = {}

        def _spy_run(args: list[str], **_kwargs: object) -> Any:
            recorded["args"] = args

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        output_path = str(tmp_path / "video.mp4")
        with (
            patch("subprocess.run", side_effect=_spy_run),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            _run_yt_dlp(youtube_video_id="abcdefghijk", output_path=output_path)

        args = recorded["args"]
        assert "--cookies-from-browser" in args
        assert args[args.index("--cookies-from-browser") + 1] == "firefox"

    def test_download_omits_cookies_when_env_unset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """YT_DLP_COOKIES_BROWSER 미설정 시 옵션이 추가되지 않아야 한다."""
        monkeypatch.delenv("YT_DLP_COOKIES_BROWSER", raising=False)
        from app.workers.tasks.download import _run_yt_dlp

        recorded: dict[str, list[str]] = {}

        def _spy_run(args: list[str], **_kwargs: object) -> Any:
            recorded["args"] = args

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        output_path = str(tmp_path / "video.mp4")
        with (
            patch("subprocess.run", side_effect=_spy_run),
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
        ):
            _run_yt_dlp(youtube_video_id="abcdefghijk", output_path=output_path)

        assert "--cookies-from-browser" not in recorded["args"]
