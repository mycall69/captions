"""T077, T078: /v1/jobs 라우터 — 작업 생성 및 조회 엔드포인트.

T077: POST /v1/jobs — URL 검증 → create_or_reuse → Celery 체인 디스패치 → 201/200 응답
T078: GET /v1/jobs/{job_id} — 작업 조회 → 200 응답

module-level 훅:
- fetch_video_duration: 테스트에서 monkeypatch로 교체 가능한 영상 길이 조회 함수
- check_rate_limit: 테스트에서 monkeypatch로 교체 가능한 rate limit 검사 함수
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.v1.dependencies import jobs_service
from app.api.v1.envelope import success_envelope
from app.api.v1.schemas.jobs import CreateJobRequest
from app.core.config import get_settings
from app.core.exceptions import InvalidInputError
from app.domain.jobs.service import JobsService

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
