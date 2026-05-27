"""T079: /v1/jobs/{job_id}/subtitles 라우터 — 자막 조회 엔드포인트.

완료된 작업에 대해 원문 + 번역 자막 큐를 동시에 페이지네이션하여 반환한다.
미완료 작업에 대해서는 409 JOB_NOT_READY를 반환한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.dependencies import jobs_service, subtitles_service
from app.api.v1.envelope import success_envelope
from app.api.v1.schemas.subtitles import SubtitleBundleResponse
from app.core.exceptions import JobNotReadyError
from app.domain.jobs.service import JobsService
from app.domain.jobs.states import JobStatus
from app.domain.subtitles.service import SubtitlesService

router = APIRouter()


@router.get("/jobs/{job_id}/subtitles")
async def get_subtitles(
    job_id: str,
    request: Request,
    offset: int = Query(0, ge=0, description="건너뛸 큐 수 (0-based)"),
    limit: int = Query(200, ge=1, le=500, description="반환할 최대 큐 수"),
    jobs: JobsService = Depends(jobs_service),  # noqa: B008
    subs: SubtitlesService = Depends(subtitles_service),  # noqa: B008
) -> dict[str, object]:
    """GET /v1/jobs/{job_id}/subtitles — 원문 + 번역 자막 큐 조회.

    작업이 completed 상태일 때만 자막을 반환한다.
    offset/limit으로 페이지네이션을 지원하며 source_cues와 translated_cues를 동시에 반환한다.

    Returns:
        SubtitleBundleResponse를 감싼 success envelope.

    Raises:
        NotFoundError: 존재하지 않는 job_id → 404
        JobNotReadyError: 작업이 아직 completed 상태가 아님 → 409
    """
    job = await jobs.get(job_id)
    if job.status != JobStatus.completed:
        raise JobNotReadyError("자막이 아직 준비되지 않았습니다.")

    source_cues, total_source = await subs.list_cues(
        job_id, "source", offset=offset, limit=limit
    )
    translated_cues, _ = await subs.list_cues(
        job_id, "translated", offset=offset, limit=limit
    )

    # source_language / target_language은 completed 상태에서 항상 존재
    assert job.source_language is not None  # noqa: S101
    assert job.target_language is not None  # noqa: S101
    bundle = SubtitleBundleResponse(
        job_id=job_id,
        source_language=job.source_language,
        target_language=job.target_language,
        source_cues=source_cues,
        translated_cues=translated_cues,
        total=total_source,
        offset=offset,
        limit=limit,
    )
    request_id: str = getattr(request.state, "request_id", "")
    return success_envelope(bundle.model_dump(mode="json"), request_id)
