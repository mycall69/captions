"""T065: yt-dlp 메타데이터 추출 + 120분 길이 검증.

spec Clarifications Q2 (2026-05-27 60분 → 2026-05-28 120분으로 확장) / FR-003:
duration > 7200s → VideoTooLongError (INVALID_INPUT).
"""

from __future__ import annotations

import asyncio
import json
import shutil

import structlog

from app.core.config import get_settings
from app.core.exceptions import DomainError, InvalidInputError
from app.domain.jobs.models import VideoMetadata

logger = structlog.get_logger(__name__)

MAX_DURATION_SEC = 7200  # 120분 (spec Clarifications 2026-05-28)


class VideoTooLongError(InvalidInputError):
    """영상 길이가 120분을 초과하는 경우 (spec Clarifications 2026-05-28 / FR-003)."""

    code = "INVALID_INPUT"
    http_status = 400


async def fetch_metadata(
    youtube_video_id: str,
    *,
    yt_dlp_path: str | None = None,
) -> VideoMetadata:
    """yt-dlp로 메타데이터를 추출하고 길이 한도(120분)를 검증한다.

    Args:
        youtube_video_id: 11자 YouTube 영상 ID.
        yt_dlp_path: yt-dlp 실행 파일 경로 (None이면 PATH에서 찾음).

    Returns:
        VideoMetadata — title, channel, duration_sec 포함.

    Raises:
        VideoTooLongError: 영상 길이 > 7200초.
        DomainError: yt-dlp 실행 실패 또는 JSON 파싱 실패.
    """
    yt_dlp = yt_dlp_path or shutil.which("yt-dlp")
    if yt_dlp is None:
        raise DomainError("yt-dlp 실행 파일을 찾을 수 없습니다.")

    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    args: list[str] = [yt_dlp, "--dump-json", "--no-playlist"]
    # yt-dlp anti-bot 우회 — settings.yt_dlp_cookies_browser 가 지정되면
    # 로컬 브라우저 쿠키로 인증된 세션으로 호출 (헌법 IV, 로컬 호스트 전제).
    cookies_browser = get_settings().yt_dlp_cookies_browser.strip()
    if cookies_browser:
        args.extend(["--cookies-from-browser", cookies_browser])
    args.append(url)
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
            f"영상 길이가 120분을 초과합니다 (실제: {int(duration)}초)",
            details={"duration_sec": int(duration), "max_duration_sec": MAX_DURATION_SEC},
        )

    # 채널 URL — `channel_url` 우선, fallback 으로 `uploader_url`.
    channel_url_raw = data.get("channel_url") or data.get("uploader_url")
    channel_url = channel_url_raw if isinstance(channel_url_raw, str) and channel_url_raw else None

    return VideoMetadata(
        title=data.get("title"),
        channel=data.get("channel") or data.get("uploader"),
        channel_url=channel_url,
        duration_sec=int(duration) if isinstance(duration, (int, float)) else None,
        subtitle_source=None,  # 자막 다운로드 단계에서 결정됨
    )
