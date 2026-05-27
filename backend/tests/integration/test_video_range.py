"""T040: GET /v1/jobs/{id}/video HTTP Range 테스트 (US1, FR-020).

검증 항목:
- Range 헤더 없음: 200 + 전체 파일
- Range: bytes=0-1023 → 206 Partial Content + Content-Range 헤더 + 1024바이트
- Range: bytes=1024-{FILE_SIZE-1} → 206 + 나머지 바이트 (닫힌 범위)
- 정상적인 206 케이스 검증 (416은 openapi.yaml 미정의이므로 제외)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip(
    "app.api.v1.routes.jobs",
    reason="awaiting Phase 3h implementation",
)
pytest.importorskip(
    "app.main",
    reason="awaiting Phase 3h implementation",
)

from httpx import AsyncClient  # noqa: E402

from app.core.ids import new_job_id  # noqa: E402
from app.infrastructure.db.orm import VideoAsset, VideoJob  # noqa: E402

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"
_FILE_SIZE = 4096  # bytes


@pytest.fixture
async def job_with_video(
    db_session: object, tmp_path: Path  # type: ignore[type-arg]
) -> str:
    """completed 작업 + video_mp4 VideoAsset을 DB에 삽입하고 job_id를 반환한다.

    실제 mp4 바이너리 대신 `b'\\x00' * _FILE_SIZE` 더미 파일을 사용한다.
    Range semantics는 byte 기반이므로 MIME 타입은 무관하다.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = db_session  # type: ignore[assignment]
    job_id = new_job_id()
    now = datetime.now(UTC)

    job = VideoJob(
        id=job_id,
        source_url=_VALID_URL,
        youtube_video_id="dQw4w9WgXcY",
        status="completed",
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    session.add(job)
    await session.flush()

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"\x00" * _FILE_SIZE)

    session.add(VideoAsset(
        id=new_job_id(),
        job_id=job_id,
        kind="video_mp4",
        path=str(video_file),
        mime_type="video/mp4",
        byte_size=_FILE_SIZE,
        created_at=now,
    ))
    await session.commit()
    return job_id


class TestVideoFullRequest:
    """Range 헤더 없이 전체 파일 요청."""

    async def test_no_range_returns_200(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """Range 헤더 없는 요청은 200 + 전체 파일을 반환해야 한다."""
        resp = await client.get(f"/v1/jobs/{job_with_video}/video")
        assert resp.status_code == 200

    async def test_no_range_returns_full_content(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """Range 헤더 없이 요청 시 전체 파일 크기를 반환해야 한다."""
        resp = await client.get(f"/v1/jobs/{job_with_video}/video")
        assert resp.status_code == 200
        assert len(resp.content) == _FILE_SIZE


class TestVideoRangeRequest:
    """HTTP Range 헤더 Partial Content 테스트."""

    async def test_range_returns_206(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """Range: bytes=0-1023 요청 시 206 Partial Content를 반환해야 한다."""
        resp = await client.get(
            f"/v1/jobs/{job_with_video}/video",
            headers={"Range": "bytes=0-1023"},
        )
        assert resp.status_code == 206

    async def test_range_returns_content_range_header(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """206 응답에 Content-Range 헤더가 포함되어야 한다."""
        resp = await client.get(
            f"/v1/jobs/{job_with_video}/video",
            headers={"Range": "bytes=0-1023"},
        )
        assert resp.status_code == 206
        assert "content-range" in resp.headers

    async def test_range_0_to_1023_returns_1024_bytes(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """Range: bytes=0-1023 → 응답 본문이 1024바이트이어야 한다."""
        resp = await client.get(
            f"/v1/jobs/{job_with_video}/video",
            headers={"Range": "bytes=0-1023"},
        )
        assert resp.status_code == 206
        assert len(resp.content) == 1024

    async def test_range_from_1024_returns_remainder(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """Range: bytes=1024-{FILE_SIZE-1} → 남은 3072바이트를 반환해야 한다 (닫힌 범위)."""
        resp = await client.get(
            f"/v1/jobs/{job_with_video}/video",
            headers={"Range": f"bytes=1024-{_FILE_SIZE - 1}"},
        )
        assert resp.status_code == 206
        assert len(resp.content) == _FILE_SIZE - 1024

    async def test_content_range_header_format(
        self, client: AsyncClient, job_with_video: str
    ) -> None:
        """Content-Range 헤더가 'bytes 시작-끝/전체' 형식이어야 한다."""
        resp = await client.get(
            f"/v1/jobs/{job_with_video}/video",
            headers={"Range": "bytes=0-1023"},
        )
        assert resp.status_code == 206
        cr = resp.headers.get("content-range", "")
        assert cr.startswith("bytes ")
        assert f"/{_FILE_SIZE}" in cr


class TestVideoNotFound:
    """비디오 스트리밍 — 존재하지 않는 작업."""

    async def test_unknown_job_returns_404(self, client: AsyncClient) -> None:
        """존재하지 않는 job_id는 404를 반환해야 한다."""
        resp = await client.get("/v1/jobs/00000000000000000000000000/video")
        assert resp.status_code == 404
