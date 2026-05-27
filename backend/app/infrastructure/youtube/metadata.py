"""T065: yt-dlp 메타데이터 추출 + 60분 길이 검증.

spec Clarifications Q2 / FR-003: duration > 3600s → VideoTooLongError (INVALID_INPUT).
"""

from __future__ import annotations

import asyncio
import json
import shutil

import structlog

from app.core.exceptions import DomainError, InvalidInputError
from app.domain.jobs.models import VideoMetadata

logger = structlog.get_logger(__name__)

MAX_DURATION_SEC = 3600  # 60분


class VideoTooLongError(InvalidInputError):
    """영상 길이가 60분을 초과하는 경우 (spec Clarifications Q2 / FR-003)."""

    code = "INVALID_INPUT"
    http_status = 400


async def fetch_metadata(
    youtube_video_id: str,
    *,
    yt_dlp_path: str | None = None,
) -> VideoMetadata:
    """yt-dlp로 메타데이터를 추출하고 길이 한도(60분)를 검증한다.

    Args:
        youtube_video_id: 11자 YouTube 영상 ID.
        yt_dlp_path: yt-dlp 실행 파일 경로 (None이면 PATH에서 찾음).

    Returns:
        VideoMetadata — title, channel, duration_sec 포함.

    Raises:
        VideoTooLongError: 영상 길이 > 3600초.
        DomainError: yt-dlp 실행 실패 또는 JSON 파싱 실패.
    """
    yt_dlp = yt_dlp_path or shutil.which("yt-dlp")
    if yt_dlp is None:
        raise DomainError("yt-dlp 실행 파일을 찾을 수 없습니다.")

    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    args = [yt_dlp, "--dump-json", "--no-playlist", url]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise DomainError(
            f"yt-dlp metadata fetch failed (rc={process.returncode})",
            details={"video_id": youtube_video_id, "stderr_tail": stderr.decode()[-300:]},
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DomainError(
            "yt-dlp JSON 파싱 실패",
            details={"video_id": youtube_video_id},
        ) from exc

    duration = data.get("duration")
    if isinstance(duration, (int, float)) and duration > MAX_DURATION_SEC:
        raise VideoTooLongError(
            f"영상 길이가 60분을 초과합니다 (실제: {int(duration)}초)",
            details={"duration_sec": int(duration), "max_duration_sec": MAX_DURATION_SEC},
        )

    return VideoMetadata(
        title=data.get("title"),
        channel=data.get("channel") or data.get("uploader"),
        duration_sec=int(duration) if isinstance(duration, (int, float)) else None,
        subtitle_source=None,  # 자막 다운로드 단계에서 결정됨
    )
