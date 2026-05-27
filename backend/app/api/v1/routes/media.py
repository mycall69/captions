"""T080, T081: /v1/jobs/{job_id}/download 및 /v1/jobs/{job_id}/video 라우터.

T080: GET /v1/jobs/{job_id}/download — 이중 자막 파일 다운로드 (SRT/VTT, source-first/target-first)
T081: GET /v1/jobs/{job_id}/video — HTTP Range 지원 동영상 스트리밍 (206 Partial Content)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.api.v1.dependencies import asset_repo, jobs_service, subtitles_service
from app.core.exceptions import InvalidInputError, JobNotReadyError, NotFoundError
from app.domain.jobs.service import JobsService
from app.domain.jobs.states import JobStatus
from app.domain.subtitles.service import SubtitlesService
from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository

router = APIRouter()


@router.get("/jobs/{job_id}/download")
async def download_subtitle(
    job_id: str,
    format: Literal["srt", "vtt"] = Query(..., description="다운로드 형식 (srt 또는 vtt)"),
    order: Literal["source-first", "target-first"] = Query(
        "source-first", description="큐 내 줄 순서"
    ),
    jobs: JobsService = Depends(jobs_service),  # noqa: B008
    subs: SubtitlesService = Depends(subtitles_service),  # noqa: B008
) -> Response:
    """GET /v1/jobs/{job_id}/download — 이중 자막 파일 다운로드.

    완료된 작업에 대해 원문+번역 합성 자막 파일을 생성하여 반환한다.
    format 파라미터로 SRT/VTT를 선택하고, order로 줄 순서를 지정한다.

    Returns:
        이중 자막 파일 (Content-Disposition: attachment).

    Raises:
        NotFoundError: 존재하지 않는 job_id → 404
        JobNotReadyError: 작업이 아직 completed 상태가 아님 → 409
    """
    job = await jobs.get(job_id)
    if job.status != JobStatus.completed:
        raise JobNotReadyError("자막이 아직 준비되지 않았습니다.")

    content = await subs.build_dual_subtitle(job_id, format=format, order=order)
    media_type = "application/x-subrip" if format == "srt" else "text/vtt"
    filename = f"{job_id}.dual.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/video")
async def stream_video(
    job_id: str,
    request: Request,
    repo: SqlVideoAssetRepository = Depends(asset_repo),  # noqa: B008
) -> Response:
    """GET /v1/jobs/{job_id}/video — HTTP Range 지원 동영상 스트리밍.

    Range 헤더가 있으면 206 Partial Content를, 없으면 200 전체 파일을 반환한다.
    Accept-Ranges: bytes 헤더를 항상 포함하여 클라이언트가 범위 요청을 지원함을 알린다.

    Returns:
        Range 없음: 200 + 전체 MP4 파일 (FileResponse)
        Range 있음: 206 Partial Content + Content-Range 헤더 (StreamingResponse)

    Raises:
        NotFoundError: 존재하지 않는 job_id 또는 video_mp4 자산 없음 → 404
        InvalidInputError: 잘못된 Range 헤더 형식 → 400
    """
    asset = await repo.get(job_id=job_id, kind="video_mp4")
    if asset is None:
        raise NotFoundError("영상 파일이 없습니다.", details={"job_id": job_id})

    file_path = Path(asset.path)
    if not file_path.exists():
        raise NotFoundError("영상 파일이 디스크에 없습니다.", details={"job_id": job_id})

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header is None:
        return FileResponse(
            str(file_path),
            media_type="video/mp4",
            headers={"Accept-Ranges": "bytes"},
        )

    # Range 헤더 파싱 — "bytes=start-end" 형식
    m = re.match(r"bytes=(\d+)-(\d*)", range_header.lower())
    if not m:
        raise InvalidInputError("잘못된 Range 헤더 형식입니다.")

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)

    if start > end:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = end - start + 1

    from collections.abc import Iterator

    def iter_chunk() -> Iterator[bytes]:
        """지정된 byte 범위를 8 KiB 청크 단위로 스트리밍한다."""
        with file_path.open("rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(8192, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_chunk(),
        status_code=206,
        media_type="video/mp4",
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
        },
    )
