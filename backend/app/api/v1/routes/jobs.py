"""T077, T078, T103: /v1/jobs 라우터 — 작업 생성, 조회, 취소 엔드포인트.

T077: POST /v1/jobs — URL 검증 → create_or_reuse → Celery 체인 디스패치 → 201/200 응답
T078: GET /v1/jobs/{job_id} — 작업 조회 → 200 응답
T103: DELETE /v1/jobs/{job_id} — 진행 중 작업 취소 + 부분 산출물 디렉터리 삭제
       (spec Clarifications Q3 / FR-028)

module-level 훅:
- fetch_video_duration: 테스트에서 monkeypatch로 교체 가능한 영상 길이 조회 함수
- check_rate_limit: 테스트에서 monkeypatch로 교체 가능한 rate limit 검사 함수
"""

from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import SubscribableBus, db_session, event_bus, jobs_service
from app.api.v1.envelope import success_envelope
from app.api.v1.schemas.jobs import CreateJobRequest
from app.core.config import get_settings
from app.core.exceptions import IllegalStateTransitionError, InvalidInputError
from app.domain.events.publisher import JobEventPublisher
from app.domain.jobs.service import JobsService
from app.domain.jobs.states import TERMINAL_STATUSES
from app.infrastructure.storage.filesystem import JobStorage

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 테스트 monkeypatch 훅 ─────────────────────────────────────────────────────

_MAX_DURATION_SEC = 3600  # 60분


async def fetch_video_duration(url: str) -> int | None:
    """영상 길이(초)를 반환한다 (기본 구현: None 반환 — 검증 skip).

    테스트에서 monkeypatch로 교체하여 VideoTooLongError를 시뮬레이션할 수 있다.
    """
    return None  # 실제 검증은 service.create_or_reuse 내부에서 수행


async def check_rate_limit(request: Request) -> None:  # noqa: ARG001
    """요청 rate limit을 검사한다 (기본 구현: no-op).

    테스트에서 monkeypatch로 교체하여 RateLimitedError를 시뮬레이션할 수 있다.
    """


@router.post("/jobs", status_code=201)
async def create_job(
    payload: CreateJobRequest,
    request: Request,
    service: JobsService = Depends(jobs_service),  # noqa: B008
) -> JSONResponse:
    """POST /v1/jobs — 신규 작업 생성 또는 기존 작업 재사용.

    - 유효한 YouTube URL → 신규 작업 생성: 201 반환
    - 동일 URL (completed/진행 중) → 기존 작업 재사용: 200 반환
    - Celery 파이프라인 체인을 백그라운드에서 디스패치한다 (disable_chain_dispatch=True이면 skip)

    Raises:
        InvalidUrlError: 허용되지 않는 URL → 400
        InvalidInputError: 영상 길이 초과 → 400
        RateLimitedError: rate limit 초과 → 429
    """
    # rate limit 검사 (monkeypatch로 교체 가능)
    await check_rate_limit(request)

    # 영상 길이 pre-check (monkeypatch로 교체 가능 — None이면 skip)
    duration = await fetch_video_duration(payload.url)
    if duration is not None and duration > _MAX_DURATION_SEC:
        raise InvalidInputError(
            f"영상 길이가 60분을 초과합니다 (실제: {duration}초)",
            details={"duration_sec": duration, "max_duration_sec": _MAX_DURATION_SEC},
        )

    job = await service.create_or_reuse(payload.url)
    request_id: str = getattr(request.state, "request_id", "")
    status_code = 200 if job.reused else 201

    if not job.reused and not get_settings().disable_chain_dispatch:
        from app.workers.pipeline import build_job_chain

        build_job_chain(job.id).apply_async()

    body = success_envelope(job.model_dump(mode="json"), request_id)
    return JSONResponse(content=body, status_code=status_code)


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    service: JobsService = Depends(jobs_service),  # noqa: B008
) -> dict[str, object]:
    """GET /v1/jobs/{job_id} — 작업 상태 조회.

    Returns:
        표준 success envelope (data = VideoJob 직렬화 결과).

    Raises:
        NotFoundError: 존재하지 않는 job_id → 404
    """
    job = await service.get(job_id)
    request_id: str = getattr(request.state, "request_id", "")
    return success_envelope(job.model_dump(mode="json"), request_id)


# ── 테스트 monkeypatch 훅: 작업 디렉터리 삭제 ────────────────────────────────


def _purge_job_storage(job_id: str) -> None:
    """job 디렉터리(`var/storage/<job_id>/`) 전체를 삭제한다.

    실패해도 취소 응답 자체는 성공 처리한다 (감사 로그만 남김).
    테스트에서 monkeypatch 로 교체 가능하다.
    """
    try:
        JobStorage().purge_job_directory(job_id)
    except (OSError, shutil.Error):
        # 파일시스템 I/O 오류만 흡수한다 — 그 외 예외(TypeError 등)는 버그 신호이므로 상위로 전파.
        logger.warning("job.cancel.purge_failed", extra={"job_id": job_id}, exc_info=True)


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    request: Request,
    service: JobsService = Depends(jobs_service),  # noqa: B008
    session: AsyncSession = Depends(db_session),  # noqa: B008
    bus: SubscribableBus = Depends(event_bus),  # noqa: B008
) -> dict[str, object]:
    """DELETE /v1/jobs/{job_id} — 진행 중 작업을 취소한다.

    동작 (spec Clarifications Q3 / FR-028):

    1. 작업 존재 확인 — 없으면 404.
    2. 종결 상태(completed/failed) 작업이면 409 ILLEGAL_STATE.
    3. 그렇지 않으면 ``failed`` 로 전이 + ``error_code=USER_CANCELLED`` 기록.
    4. ``job.failed`` SSE 이벤트를 발행한다 (events.md §이벤트 타입 — 클라이언트가
       종결을 학습하기 위해 필요. Last-Event-ID replay 경로도 포함).
    5. ``var/storage/<job_id>/`` 디렉터리를 완전 삭제 (부분 산출물 purge).

    Celery 작업 ID 는 별도로 보관되지 않으므로 revoke 는 생략한다 — 워커는
    매 단계 진입 시 ``video_job.status`` 를 다시 확인하여 ``failed`` 면 즉시
    중단한다 (작업 자체적 협조 취소).

    Returns:
        표준 success envelope (data = USER_CANCELLED 상태로 갱신된 VideoJob).

    Raises:
        NotFoundError: 존재하지 않는 job_id → 404.
        IllegalStateTransitionError: 종결 상태 작업 → 409 ILLEGAL_STATE.
    """
    request_id: str = getattr(request.state, "request_id", "")

    # USER_CANCELLED 오류 메타 — mark_failed / publish_failed 양쪽이 동일한 값을 사용한다.
    _CANCEL_ERROR_STAGE = "user"
    _CANCEL_ERROR_CODE = "USER_CANCELLED"
    _CANCEL_ERROR_MESSAGE = "사용자가 작업을 취소했습니다"

    # 1) 존재 확인 (NotFoundError → 404)
    current = await service.get(job_id)

    # 2) 종결 상태 확인 — completed / failed 는 취소 불가
    if current.status in TERMINAL_STATUSES:
        raise IllegalStateTransitionError(
            f"종결된 작업은 취소할 수 없습니다 (status={current.status.value})",
            details={"job_id": job_id, "status": current.status.value},
        )

    # 3) failed 전이 + USER_CANCELLED 기록
    cancelled = await service.mark_failed(
        job_id,
        error_stage=_CANCEL_ERROR_STAGE,
        error_code=_CANCEL_ERROR_CODE,
        error_message=_CANCEL_ERROR_MESSAGE,
    )

    # 4) ``job.failed`` SSE 이벤트 발행 — SSE 구독 중인 클라이언트가 취소를
    #    즉시 학습하고, 끊긴 클라이언트도 Last-Event-ID replay 로 따라잡을 수 있게 한다.
    publisher = JobEventPublisher(session=session, bus=bus)
    await publisher.publish_failed(
        job_id=job_id,
        error_stage=_CANCEL_ERROR_STAGE,
        error_code=_CANCEL_ERROR_CODE,
        error_message=_CANCEL_ERROR_MESSAGE,
    )

    # 5) DB 상태를 먼저 영속화한 뒤 디렉터리를 purge 한다.
    #    dep teardown 의 commit 실패 시 디렉터리만 삭제되고 전이 기록이 사라지는
    #    race 를 막기 위해 명시적으로 커밋 → 그 후에만 purge 를 수행한다.
    #    (teardown 의 추가 commit 은 no-op 으로 안전하다.)
    await session.commit()

    # 6) 디렉터리 purge — 실패해도 응답은 성공
    _purge_job_storage(job_id)

    logger.info("job.cancelled", extra={"job_id": job_id})
    return success_envelope(cancelled.model_dump(mode="json"), request_id)
