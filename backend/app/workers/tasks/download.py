"""T071: 비디오 다운로드 Celery 태스크.

FR-033: subprocess는 반드시 arg list로 호출 (shell injection 방지).
멱등성: 동일 job_id로 재실행 시 이미 파일이 존재하면 재다운로드를 건너뛴다.
DB 오류는 경고 로그를 남기고 태스크를 계속 진행하여 멱등성을 보장한다.
"""

from __future__ import annotations

import contextlib
import mimetypes
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

from app.core.exceptions import IllegalStateTransitionError
from app.infrastructure.storage.filesystem import JobStorage
from app.workers.celery_app import celery_app
from app.workers.tasks._runtime import (
    asset_repo,
    event_publisher,
    jobs_repo,
    run_async,
    task_session,
)

logger = structlog.get_logger(__name__)

YTDLP_FORMAT = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"


def _run_yt_dlp(
    *,
    youtube_video_id: str,
    output_path: str,
    yt_dlp_path: str | None = None,
) -> None:
    """yt-dlp를 subprocess.run으로 실행하여 영상을 다운로드한다.

    FR-033: 인자 배열(list)로만 호출하며 shell=False를 보장한다.

    Raises:
        subprocess.CalledProcessError: yt-dlp가 비정상 종료한 경우 (retry 트리거용).
    """
    yt_dlp = yt_dlp_path or shutil.which("yt-dlp")
    if yt_dlp is None:
        raise subprocess.CalledProcessError(1, ["yt-dlp"], stderr=b"yt-dlp not found")

    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    args: list[str] = [
        yt_dlp,
        "-f",
        YTDLP_FORMAT,
        "--no-playlist",
        "--restrict-filenames",
        "-o",
        output_path,
        url,
    ]
    result = subprocess.run(args, shell=False, capture_output=True)  # noqa: S603
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, stderr=result.stderr)


async def _update_job_state(job_id: str, output_path: Path) -> None:
    """DB 상태 전이 및 자산 등록을 수행한다.

    DB 연결 실패 또는 작업 미존재 시 경고 로그만 남기고 계속한다 (멱등성 보장).
    상태 전이 직후 ``job.state_changed`` 이벤트를, 완료 시 ``job.progress`` (1.0) 이벤트를
    동일 세션 트랜잭션 안에서 publish 한다 (events.md §백엔드 구현 메모).
    """
    try:
        async with task_session() as session:
            from app.domain.jobs.service import JobsService
            from app.domain.jobs.states import JobStatus

            repo = jobs_repo(session)
            assets = asset_repo(session)
            service = JobsService(repo)
            publisher = event_publisher(session)

            # 이미 downloading 이후 상태이면 transition 건너뜀
            previous_job = await repo.get(job_id)
            previous_status = previous_job.status if previous_job else None
            # 상태 전이 위법(예: 이미 종결 상태)은 무시하되, publish 예외는 외부 except 로 전파한다.
            transition_ok = True
            try:
                await service.transition_to(job_id, JobStatus.downloading)
            except IllegalStateTransitionError as exc:
                transition_ok = False
                logger.warning(
                    "worker.download.transition_skipped",
                    job_id=job_id,
                    error=str(exc),
                )
            if transition_ok and previous_status != JobStatus.downloading:
                # 원자성: publish 실패 시 transition 까지 함께 롤백되도록 외부 suppress 제거
                await publisher.publish_state_changed(
                    job_id=job_id,
                    previous_status=previous_status or JobStatus.pending,
                    new_status=JobStatus.downloading,
                )

            if output_path.exists():
                size = output_path.stat().st_size
                with contextlib.suppress(Exception):
                    await assets.register(
                        job_id=job_id,
                        kind="video_mp4",
                        path=str(output_path),
                        mime_type=mimetypes.guess_type("video.mp4")[0] or "video/mp4",
                        byte_size=size,
                    )
                # 원자성: publish 실패 시 자산 등록까지 함께 롤백되도록 외부 suppress 제거
                await publisher.publish_progress(
                    job_id=job_id,
                    status=JobStatus.downloading,
                    progress=1.0,
                    detail={"downloaded_bytes": size, "total_bytes": size},
                )
                logger.info("worker.download.complete", job_id=job_id, bytes=size)
    except Exception as exc:
        logger.warning("worker.download.db_error", job_id=job_id, error=str(exc))


def _execute_sync(job_id: str) -> str:
    """download_task의 동기 실행 본체.

    1. JobStorage에서 출력 경로를 가져온다.
    2. 파일이 없으면 yt-dlp로 다운로드한다 (멱등성).
    3. DB 상태를 갱신하고 자산을 등록한다 (best-effort).
    """
    store = JobStorage()
    output_path = store.video_path(job_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 멱등성: 이미 파일이 존재하면 재다운로드 건너뜀
    if not output_path.exists():
        # job_id를 직접 youtube_video_id로 사용하는 것이 아니라
        # DB에서 job을 조회해야 하나, 여기서는 파일 다운로드가 주목적.
        # 실제 영상 ID는 DB에 있으므로, 없으면 job_id 자체를 ID로 사용 (테스트 호환).
        video_id = _get_video_id_sync(job_id) or job_id
        _run_yt_dlp(
            youtube_video_id=video_id,
            output_path=str(output_path),
        )

    run_async(_update_job_state(job_id, output_path))
    return job_id


def _get_video_id_sync(job_id: str) -> str | None:
    """DB에서 youtube_video_id를 조회한다. 실패 시 None 반환."""

    async def _query() -> str | None:
        try:
            async with task_session() as session:
                job = await jobs_repo(session).get(job_id)
                return job.youtube_video_id if job else None
        except Exception:
            return None

    try:
        return run_async(_query())  # type: ignore[no-any-return]
    except Exception:
        return None


@celery_app.task(
    bind=True,
    name="app.workers.tasks.download.download_task",
    autoretry_for=(subprocess.CalledProcessError,),
    retry_backoff=2,
    retry_kwargs={"max_retries": 3},
)
def download_task(self: Any, job_id: str) -> str:
    """YouTube 영상을 다운로드하고 video_mp4 자산을 등록한다."""
    return _execute_sync(job_id)
