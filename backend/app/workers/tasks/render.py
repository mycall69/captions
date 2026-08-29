"""T074: 이중 자막 렌더링 Celery 태스크.

FR-017: source-first 순서로 dual SRT + dual VTT 생성.
FR-018: SRT(,) / VTT(.) 타임스탬프 형식 구분.
FR-019: 큐당 두 줄 본문 (원문 + 번역문).
"""

from __future__ import annotations

from typing import Any

import structlog

from app.infrastructure.storage.filesystem import JobStorage
from app.workers.celery_app import celery_app
from app.workers.tasks._runtime import (
    asset_repo,
    event_publisher,
    jobs_repo,
    run_async,
    subtitle_repo,
    task_session,
)

logger = structlog.get_logger(__name__)


def save_video_asset(
    *,
    job_id: str,
    kind: str,
    path: str,
    mime_type: str,
    byte_size: int,
) -> None:
    """VideoAsset 행을 DB에 저장하는 모듈 수준 함수.

    테스트에서 monkeypatch 가능하도록 노출한다.
    _execute() 내부의 asset_repo.register()와 동일한 동작을 수행한다.
    """

    async def _save() -> None:
        async with task_session() as session:
            await asset_repo(session).register(
                job_id=job_id,
                kind=kind,
                path=path,
                mime_type=mime_type,
                byte_size=byte_size,
            )

    run_async(_save())


async def _execute(job_id: str) -> str:
    """render_task의 비동기 실행 본체."""
    async with task_session() as session:
        from app.core.exceptions import NotFoundError
        from app.domain.jobs.service import JobsService
        from app.domain.jobs.states import TERMINAL_STATUSES, JobStatus
        from app.domain.subtitles.dual_generator import generate_dual_srt, generate_dual_vtt

        jrepo = jobs_repo(session)
        srepo = subtitle_repo(session)
        arepo = asset_repo(session)
        service = JobsService(jrepo)
        publisher = event_publisher(session)

        # 멱등성: 이미 rendering 상태이면 transition 건너뜀
        current_job = await service.get(job_id)
        # Chain abort: 이전 단계가 mark_failed 처리 후 정상 종료한 경우 종결 상태
        # 작업에 대해서는 즉시 종료한다 (translate.py 와 동일 패턴).
        if current_job.status in TERMINAL_STATUSES:
            logger.info(
                "worker.render.skipped_terminal_status",
                job_id=job_id,
                status=current_job.status.value,
            )
            return job_id
        if current_job.status != JobStatus.rendering:
            previous_status = current_job.status
            await service.transition_to(job_id, JobStatus.rendering)
            # 원자성: publish 실패 시 transition 까지 함께 롤백되도록 suppress 제거
            await publisher.publish_state_changed(
                job_id=job_id,
                previous_status=previous_status,
                new_status=JobStatus.rendering,
            )

        source_track = await srepo.get_track(job_id, "source")
        translated_track = await srepo.get_track(job_id, "translated")

        if source_track is None or translated_track is None:
            raise NotFoundError(
                "자막 트랙이 없습니다.",
                details={
                    "job_id": job_id,
                    "source_missing": source_track is None,
                    "translated_missing": translated_track is None,
                },
            )

        source_cues = await srepo.load_all_cues(source_track.id)
        translated_cues = await srepo.load_all_cues(translated_track.id)

        store = JobStorage()
        srt_content = generate_dual_srt(source_cues, translated_cues)
        vtt_content = generate_dual_vtt(source_cues, translated_cues)

        srt_path = store.subtitle_path(job_id, "dual.srt")
        vtt_path = store.subtitle_path(job_id, "dual.vtt")
        srt_path.write_text(srt_content, encoding="utf-8")
        vtt_path.write_text(vtt_content, encoding="utf-8")

        await arepo.register(
            job_id=job_id,
            kind="dual_srt",
            path=str(srt_path),
            mime_type="application/x-subrip",
            byte_size=srt_path.stat().st_size,
        )
        await arepo.register(
            job_id=job_id,
            kind="dual_vtt",
            path=str(vtt_path),
            mime_type="text/vtt",
            byte_size=vtt_path.stat().st_size,
        )

        # 종결 전이 + ``job.completed`` 이벤트 발행 (동일 트랜잭션)
        await service.transition_to(job_id, JobStatus.completed)
        # 원자성: publish 실패 시 completed 전이 + 자산 INSERT 가 함께 롤백되도록 suppress 제거
        await publisher.publish_completed(
            job_id=job_id,
            assets={
                "video_mp4": f"/v1/jobs/{job_id}/video",
                "dual_srt": f"/v1/jobs/{job_id}/download?format=srt",
                "dual_vtt": f"/v1/jobs/{job_id}/download?format=vtt",
            },
        )
        logger.info("worker.render.complete", job_id=job_id)
        return job_id


@celery_app.task(
    bind=True,
    name="app.workers.tasks.render.render_task",
)
def render_task(self: Any, job_id: str) -> str:
    """source/translated 트랙으로 dual SRT + VTT 파일을 생성하고 자산을 등록한다."""
    return str(run_async(_execute(job_id)))
