"""T064: yt-dlp 자막 다운로드 wrapper.

수동 자막을 먼저 시도하고, ko/ja 모두 없으면 자동 생성 자막으로 fallback.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

from app.core.exceptions import SubtitleNotFoundError
from app.domain.jobs.models import Lang

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SubtitleDownloadResult:
    """자막 다운로드 결과."""

    language: Lang
    source: Literal["manual", "auto"]
    file_path: Path
    format: Literal["vtt", "srt"]


async def download_subtitles(
    *,
    youtube_video_id: str,
    output_dir: Path,
    languages: tuple[Lang, ...] = ("ko", "ja"),
    yt_dlp_path: str | None = None,
) -> SubtitleDownloadResult:
    """ko/ja 자막을 다운로드. manual 우선, 실패 시 auto fallback.

    지정된 언어 목록 순서로 수동 자막을 우선 탐색하고, 하나도 없으면
    자동 생성 자막으로 재시도한다. 모두 실패하면 SubtitleNotFoundError를 발생시킨다.

    Args:
        youtube_video_id: 11자 YouTube 영상 ID.
        output_dir: 자막 파일을 저장할 디렉터리 절대 경로.
        languages: 탐색 언어 우선순위 튜플 (기본값: ko → ja).
        yt_dlp_path: yt-dlp 실행 파일 경로 (None이면 PATH에서 찾음).

    Returns:
        SubtitleDownloadResult — 다운로드 성공 시 언어·출처·경로·형식 정보.

    Raises:
        SubtitleNotFoundError: 수동 및 자동 자막 모두 찾을 수 없는 경우.
    """
    yt_dlp = yt_dlp_path or shutil.which("yt-dlp")
    if yt_dlp is None:
        raise SubtitleNotFoundError("yt-dlp 실행 파일을 찾을 수 없습니다.")

    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    sub_langs_arg = ",".join(languages)
    output_template = str(output_dir / "%(id)s.%(ext)s")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 시도 1: 수동 자막
    manual_args = [
        yt_dlp,
        "--skip-download",
        "--write-sub",
        "--sub-langs", sub_langs_arg,
        "--sub-format", "vtt",
        "--no-playlist",
        "-o", output_template,
        url,
    ]
    await _run_ytdlp(manual_args)
    for lang in languages:
        candidate = output_dir / f"{youtube_video_id}.{lang}.vtt"
        if candidate.exists():
            logger.info("subtitle.found", video_id=youtube_video_id, lang=lang, source="manual")
            return SubtitleDownloadResult(
                language=lang,
                source="manual",
                file_path=candidate,
                format="vtt",
            )

    # 시도 2: 자동 생성 자막
    auto_args = [
        yt_dlp,
        "--skip-download",
        "--write-auto-sub",
        "--sub-langs", sub_langs_arg,
        "--sub-format", "vtt",
        "--no-playlist",
        "-o", output_template,
        url,
    ]
    await _run_ytdlp(auto_args)
    for lang in languages:
        candidate = output_dir / f"{youtube_video_id}.{lang}.vtt"
        if candidate.exists():
            logger.info("subtitle.found", video_id=youtube_video_id, lang=lang, source="auto")
            return SubtitleDownloadResult(
                language=lang,
                source="auto",
                file_path=candidate,
                format="vtt",
            )

    raise SubtitleNotFoundError(
        "이 영상에는 한국어 / 일본어 자막이 없습니다.",
        details={"video_id": youtube_video_id, "languages_attempted": list(languages)},
    )


async def _run_ytdlp(args: list[str]) -> int:
    """yt-dlp 실행 — 실패해도 예외를 던지지 않고 returncode만 반환 (fallback flow 위해)."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.communicate()
    return process.returncode or 0
