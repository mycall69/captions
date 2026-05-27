"""T073: 번역 Celery 태스크.

FR-013: 청크 분할 번역.
FR-014: context_before / context_after (각 최대 3 cue) 전달.
FR-015: ProviderRateLimitError 발생 시 최대 4회 retry (1s/2s/4s/8s exponential backoff).
FR-016: 모든 retry 소진 후 작업을 failed + TRANSLATION_FAILED로 표시.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.domain.translation.provider import TranslationProvider
from app.workers.celery_app import celery_app
from app.workers.tasks._runtime import jobs_repo, run_async, subtitle_repo, task_session

logger = structlog.get_logger(__name__)

# 테스트 주입용 전역 override — monkeypatch로 교체 가능
_OVERRIDE_PROVIDER: TranslationProvider | None = None


def set_provider_for_test(provider: TranslationProvider | None) -> None:
    """테스트에서 번역 Provider를 주입하기 위한 헬퍼."""
    global _OVERRIDE_PROVIDER  # noqa: PLW0603
    _OVERRIDE_PROVIDER = provider


def get_translation_provider() -> TranslationProvider:
    """활성 번역 Provider 인스턴스를 반환한다.

    _OVERRIDE_PROVIDER가 설정된 경우(테스트) 해당 인스턴스를 반환하고,
    그렇지 않으면 설정에서 ClaudeTranslationAdapter를 생성한다.
    """
    if _OVERRIDE_PROVIDER is not None:
        return _OVERRIDE_PROVIDER

    from app.core.config import get_settings
    from app.infrastructure.providers.claude_adapter import ClaudeTranslationAdapter

    settings = get_settings()
    return ClaudeTranslationAdapter(
        api_key=settings.anthropic_api_key,
        model=settings.translation_model,
    )


def update_job_status(job_id: str, status: str, **kwargs: object) -> None:
    """작업 상태를 동기적으로 갱신한다 (retry 소진 후 failed 표시용).

    테스트에서 monkeypatch 가능하도록 모듈 수준 함수로 분리한다.
    """
    async def _update() -> None:
        async with task_session() as session:
            from app.domain.jobs.service import JobsService
            from app.domain.jobs.states import JobStatus

            service = JobsService(jobs_repo(session))
            if status == "failed":
                await service.mark_failed(
                    job_id,
                    error_stage=str(kwargs.get("error_stage", "translating")),
                    error_code=str(kwargs.get("error_code", "TRANSLATION_FAILED")),
                    error_message=str(kwargs.get("error_message", "번역 실패")),
                )
            else:
                await service.transition_to(job_id, JobStatus(status))

    run_async(_update())


async def _execute(job_id: str) -> str:
    """translate_task의 비동기 실행 본체."""
    async with task_session() as session:
        from app.core.exceptions import InvalidInputError, NotFoundError
        from app.core.ids import new_ulid
        from app.domain.jobs.service import JobsService
        from app.domain.jobs.states import JobStatus
        from app.domain.subtitles.models import SubtitleCue, SubtitleTrack
        from app.domain.translation.chunking import split_into_chunks
        from app.domain.translation.service import TranslationService

        jrepo = jobs_repo(session)
        srepo = subtitle_repo(session)
        service = JobsService(jrepo)
        # 멱등성: 이미 translating 상태이면 transition 건너뜀
        job = await service.get(job_id)
        if job.status != JobStatus.translating:
            await service.transition_to(job_id, JobStatus.translating)
            job = await service.get(job_id)

        source_track = await srepo.get_track(job_id, "source")
        if source_track is None:
            raise NotFoundError("source 트랙이 없습니다.", details={"job_id": job_id})

        source_cues = await srepo.load_all_cues(source_track.id)

        if job.source_language is None or job.target_language is None:
            raise InvalidInputError("작업에 source/target 언어가 설정되지 않았습니다.")

        chunks = split_into_chunks(
            source_cues,
            source_lang=job.source_language,
            target_lang=job.target_language,
        )

        provider = get_translation_provider()
        tservice = TranslationService(provider)

        all_translated_cues: list[SubtitleCue] = []
        for chunk in chunks:
            translated_chunk = await tservice.translate(chunk)
            for tcue in translated_chunk.cues:
                all_translated_cues.append(
                    SubtitleCue(
                        sequence=tcue.sequence,
                        start_ms=tcue.start_ms,
                        end_ms=tcue.end_ms,
                        text=tcue.text,
                    )
                )

        target_track = SubtitleTrack(
            id=new_ulid(),
            job_id=job_id,
            kind="translated",
            language=job.target_language,
            origin="generated",
            source_format=None,
            file_path=None,
            cue_count=len(all_translated_cues),
            cues=all_translated_cues,
        )
        await srepo.save_track(target_track)

        logger.info(
            "worker.translate.complete",
            job_id=job_id,
            cues=len(all_translated_cues),
        )
        return job_id


@celery_app.task(
    bind=True,
    name="app.workers.tasks.translate.translate_task",
)
def translate_task(self: Any, job_id: str) -> str:
    """소스 자막 청크를 번역하고 translated 트랙을 DB에 저장한다."""
    from app.domain.translation.provider import ProviderRateLimitError, ProviderTransientError

    try:
        return str(run_async(_execute(job_id)))
    except (ProviderRateLimitError, ProviderTransientError) as exc:
        # Celery retry — max_retries=4, 총 5회 호출 (1s/2s/4s/8s backoff)
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            # 모든 retry 소진 → failed 전이
            update_job_status(
                job_id,
                "failed",
                error_stage="translating",
                error_code="TRANSLATION_FAILED",
                error_message=str(exc),
            )
            raise
