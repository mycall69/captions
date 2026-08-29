"""T077, T078, T103, T115: /v1/jobs 라우터 — 작업 생성, 목록, 조회, 취소 엔드포인트.

T077: POST /v1/jobs — URL 검증 → create_or_reuse → Celery 체인 디스패치 → 201/200 응답
T078: GET /v1/jobs/{job_id} — 작업 조회 → 200 응답
T103: DELETE /v1/jobs/{job_id} — 작업 취소 또는 영구 삭제.
       진행 중 → cancel (FR-028, USER_CANCELLED 마킹, DB row 보존).
       종결(completed/failed) → hard delete (FR-030a, storage + DB row 영구 제거).
T115: GET /v1/jobs — 최근 작업 목록 (cursor 페이지네이션, status 필터, US3)

module-level 훅:
- fetch_video_duration: 테스트에서 monkeypatch로 교체 가능한 영상 길이 조회 함수
- check_rate_limit: 테스트에서 monkeypatch로 교체 가능한 rate limit 검사 함수
"""

from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import SubscribableBus, db_session, event_bus, jobs_service
from app.api.v1.envelope import success_envelope
from app.api.v1.schemas.jobs import CreateJobRequest
from app.core.config import get_settings
from app.core.exceptions import InvalidInputError
from app.domain.events.publisher import JobEventPublisher
from app.domain.jobs.service import JobsService
from app.domain.jobs.states import TERMINAL_STATUSES, JobStatus
from app.infrastructure.storage.filesystem import JobStorage

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 테스트 monkeypatch 훅 ─────────────────────────────────────────────────────

_MAX_DURATION_SEC = 7200  # 120분 (spec Clarifications 2026-05-28)


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
            f"영상 길이가 120분을 초과합니다 (실제: {duration}초)",
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


@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=50, description="페이지 당 최대 항목 수"),
    cursor: str | None = Query(None, description="다음 페이지 cursor (created_at 기반)"),
    status: list[JobStatus] | None = Query(  # noqa: B008
        None, description="상태 필터 (반복 지정 가능)"
    ),
    service: JobsService = Depends(jobs_service),  # noqa: B008
) -> dict[str, object]:
    """GET /v1/jobs — 최근 작업 목록 (US3, FR-029, FR-030).

    cursor 기반 페이지네이션 — created_at DESC 정렬, 다음 페이지가 있으면
    ``data.next_cursor`` 가 포함된다. 빈 결과의 경우 ``items=[], next_cursor=null``.

    Args:
        limit: 페이지 당 최대 항목 수 (1~50, 기본 20).
        cursor: 이전 응답의 ``next_cursor`` 값 (없으면 첫 페이지).
        status: 상태 필터 — 반복 지정으로 여러 상태를 허용한다.

    Returns:
        표준 success envelope (data = {items, next_cursor}).
    """
    items, next_cursor = await service.list_recent(
        limit=limit,
        cursor=cursor,
        status_filter=list(status) if status else None,
    )
    request_id: str = getattr(request.state, "request_id", "")
    data: dict[str, object] = {
        "items": [j.model_dump(mode="json") for j in items],
        "next_cursor": next_cursor,
    }
    return success_envelope(data, request_id)


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
async def cancel_or_delete_job(
    job_id: str,
    request: Request,
    service: JobsService = Depends(jobs_service),  # noqa: B008
    session: AsyncSession = Depends(db_session),  # noqa: B008
    bus: SubscribableBus = Depends(event_bus),  # noqa: B008
) -> dict[str, object]:
    """DELETE /v1/jobs/{job_id} — 작업 취소 또는 영구 삭제.

    상태별 분기 (단일 엔드포인트로 클라이언트가 분기 처리 불필요):

    - **진행 중** (pending/downloading/subtitle_processing/translating/rendering):
      cancel 시맨틱 — failed/USER_CANCELLED 마킹 + storage purge.
      DB row 는 감사 목적으로 보존. SSE ``job.failed`` 이벤트 발행.
      spec Clarifications 2026-05-27 / FR-028 매핑.
    - **종결** (completed/failed): hard delete — storage purge + DB row 영구 제거.
      cascade 로 SubtitleTrack/Cue/Asset/JobEvent 등도 함께 제거.
      spec Clarifications 2026-05-28 / FR-030a 매핑.

    응답 envelope ``data.action`` 으로 어떤 동작이 일어났는지 구분 가능:
    ``"cancelled"`` 또는 ``"deleted"``.
    그 외 ``data`` 키는 VideoJob 필드(id/status/...) 와 동일 (backward compatible).

    Returns:
        표준 success envelope. data = {...VideoJob, action}.
        - cancelled: data.status="failed", data.error_code="USER_CANCELLED", action="cancelled".
        - deleted:   data = 삭제 직전 VideoJob 스냅샷 + action="deleted".

    Raises:
        NotFoundError: 존재하지 않는 job_id → 404.
    """
    request_id: str = getattr(request.state, "request_id", "")

    # 1) 존재 확인 (NotFoundError → 404)
    current = await service.get(job_id)

    # 2) 종결 상태 → hard delete 경로
    if current.status in TERMINAL_STATUSES:
        snapshot = await service.delete_terminal(job_id)
        # DB 커밋을 먼저 영속화 → 그 후 storage purge (실패해도 응답 성공)
        await session.commit()
        _purge_job_storage(job_id)
        logger.info("job.deleted", extra={"job_id": job_id})
        return success_envelope(
            {**snapshot.model_dump(mode="json"), "action": "deleted"},
            request_id,
        )

    # 3) 진행 중 → cancel 경로 (기존 동작)
    _CANCEL_ERROR_STAGE = "user"
    _CANCEL_ERROR_CODE = "USER_CANCELLED"
    _CANCEL_ERROR_MESSAGE = "사용자가 작업을 취소했습니다"

    cancelled = await service.mark_failed(
        job_id,
        error_stage=_CANCEL_ERROR_STAGE,
        error_code=_CANCEL_ERROR_CODE,
        error_message=_CANCEL_ERROR_MESSAGE,
    )

    publisher = JobEventPublisher(session=session, bus=bus)
    await publisher.publish_failed(
        job_id=job_id,
        error_stage=_CANCEL_ERROR_STAGE,
        error_code=_CANCEL_ERROR_CODE,
        error_message=_CANCEL_ERROR_MESSAGE,
    )

    # DB 상태 영속화 후 storage purge (race 방지: 기존 로직 그대로)
    await session.commit()
    _purge_job_storage(job_id)

    logger.info("job.cancelled", extra={"job_id": job_id})
    return success_envelope(
        {**cancelled.model_dump(mode="json"), "action": "cancelled"},
        request_id,
    )
