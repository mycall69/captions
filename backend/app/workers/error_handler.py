"""Celery chain 오류 핸들러 — 파이프라인 실패 시 작업을 failed로 전이한다.

on_error 콜백 시그니처 (Celery 5.x):
    mark_failed_on_error(request, exc, traceback, job_id)
    - request: 실패한 task 요청 객체
    - exc: 발생한 예외 인스턴스
    - traceback: 스택 트레이스 문자열
    - job_id: .s(job_id) 로 바인딩된 추가 인자
"""

from __future__ import annotations

import structlog

from app.workers.celery_app import celery_app
from app.workers.tasks._runtime import jobs_repo, run_async, task_session

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.workers.error_handler.mark_failed_on_error")
def mark_failed_on_error(
    request: object,
    exc: BaseException,
    traceback: object,
    job_id: str,
) -> None:
    """파이프라인 체인에서 예외 발생 시 작업을 failed 상태로 전이한다.

    Celery on_error 콜백으로 등록되며, chain 내 임의 태스크 실패 시 호출된다.
    DB 오류는 경고 로그를 남기고 무시한다 (이 핸들러 자체가 실패하면 안 된다).
    """
    async def _mark() -> None:
        try:
            async with task_session() as session:
                from app.domain.jobs.service import JobsService

                service = JobsService(jobs_repo(session))
                await service.mark_failed(
                    job_id,
                    error_stage="unknown",
                    error_code="PIPELINE_FAILED",
                    error_message=str(exc),
                )
                logger.warning(
                    "pipeline.failed",
                    job_id=job_id,
                    exc=str(exc),
                )
        except Exception as handler_exc:
            logger.error(
                "pipeline.error_handler.failed",
                job_id=job_id,
                error=str(handler_exc),
            )

    run_async(_mark())
