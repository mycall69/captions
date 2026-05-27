"""T066: ffmpeg 컨테이너 remux wrapper.

MVP는 soft subtitle 정책(research §7)이므로 burn-in 없음.
-c copy로 컨테이너만 변환하거나, 필요 없으면 원본 파일을 그대로 사용한다.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import structlog

from app.core.exceptions import RenderFailedError

logger = structlog.get_logger(__name__)


async def remux_to_mp4(
    *,
    input_path: Path,
    output_path: Path,
    ffmpeg_path: str | None = None,
) -> Path:
    """input을 mp4 컨테이너로 remux. 인코딩 없이 stream copy.

    이미 mp4 컨테이너이고 input_path와 output_path가 동일한 경우 input_path를
    그대로 반환한다 (no-op).

    Args:
        input_path: 입력 영상 파일 절대 경로.
        output_path: 출력 mp4 파일 절대 경로.
        ffmpeg_path: ffmpeg 실행 파일 경로 (None이면 PATH에서 찾음).

    Raises:
        RenderFailedError: ffmpeg 실행 파일 미발견 또는 ffmpeg 실패.
    """
    if input_path.suffix.lower() == ".mp4" and input_path.resolve() == output_path.resolve():
        return input_path

    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RenderFailedError("ffmpeg 실행 파일을 찾을 수 없습니다.")

    args = [
        ffmpeg,
        "-y",
        "-i", str(input_path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    logger.info("remux.start", input=str(input_path), output=str(output_path))
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.warning("remux.failed", stderr=stderr.decode()[-2000:])
        raise RenderFailedError(
            f"ffmpeg 종료 코드: {process.returncode}",
            details={"stderr_tail": stderr.decode()[-300:]},
        )
    logger.info("remux.complete", output=str(output_path))
    return output_path
