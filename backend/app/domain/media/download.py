"""T063: yt-dlp 비디오 다운로드 wrapper.

헌법 보안 FR-033 — subprocess 인자 배열 사용, shell 인터폴레이션 금지.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import structlog

from app.core.exceptions import DownloadFailedError

logger = structlog.get_logger(__name__)

YTDLP_FORMAT = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"


async def download_video(
    *,
    youtube_video_id: str,
    output_path: Path,
    yt_dlp_path: str | None = None,
) -> Path:
    """YouTube 영상을 mp4로 다운로드.

    Args:
        youtube_video_id: 11자 영상 ID (URL이 아닌 ID만).
        output_path: 저장할 절대 경로 (예: var/storage/{job_id}/video.mp4).
        yt_dlp_path: yt-dlp 실행 파일 경로 (None이면 PATH에서 찾음).

    Raises:
        DownloadFailedError: yt-dlp 실패 또는 출력 파일 생성 실패.
    """
    yt_dlp = yt_dlp_path or shutil.which("yt-dlp")
    if yt_dlp is None:
        raise DownloadFailedError("yt-dlp 실행 파일을 찾을 수 없습니다.")

    # 영상 ID로 URL 구성 (외부 입력 금지 — 정규화된 ID만 사용)
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"

    args = [
        yt_dlp,
        "-f", YTDLP_FORMAT,
        "--no-playlist",
        "--restrict-filenames",
        "-o", str(output_path),
        url,
    ]
    logger.info("video.download.start", video_id=youtube_video_id, output=str(output_path))
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.warning(
            "video.download.failed",
            video_id=youtube_video_id,
            stderr=stderr.decode()[-2000:],
        )
        raise DownloadFailedError(
            f"yt-dlp 종료 코드: {process.returncode}",
            details={"video_id": youtube_video_id, "stderr_tail": stderr.decode()[-500:]},
        )
    if not output_path.exists():
        raise DownloadFailedError(
            "yt-dlp가 종료했지만 출력 파일이 없습니다.",
            details={"video_id": youtube_video_id},
        )
    logger.info(
        "video.download.complete",
        video_id=youtube_video_id,
        bytes=output_path.stat().st_size,
    )
    return output_path
