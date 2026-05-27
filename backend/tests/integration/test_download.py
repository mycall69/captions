"""T039: GET /v1/jobs/{id}/download 컨트랙트 테스트 (US1, FR-017, FR-018).

검증 항목:
- 완료된 작업: ?format=srt → text/plain + Content-Disposition attachment *.srt
- 완료된 작업: ?format=vtt → text/vtt
- ?order=source-first vs target-first → 줄 순서 차이 확인
- 미완료 작업: 409 + envelope.error.code
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.ids import new_job_id  # noqa: E402
from app.infrastructure.db.orm import VideoAsset, VideoJob  # noqa: E402
from app.main import app  # noqa: E402  # type: ignore[reportMissingImports]

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"

# 최소 SRT 콘텐츠 (source-first 기준: 일본어\n한국어)
_SAMPLE_SRT_SOURCE_FIRST = """\
1
00:00:01,000 --> 00:00:04,000
こんにちは、世界。
안녕하세요, 세계.

"""

_SAMPLE_SRT_TARGET_FIRST = """\
1
00:00:01,000 --> 00:00:04,000
안녕하세요, 세계.
こんにちは、世界。

"""


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def completed_job_with_assets(
    db_session: object, tmp_path: Path  # type: ignore[type-arg]
) -> str:
    """completed 작업 + dual_srt / dual_vtt VideoAsset을 DB에 삽입한다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = db_session  # type: ignore[assignment]
    job_id = new_job_id()
    now = datetime.now(UTC)

    job = VideoJob(
        id=job_id,
        source_url=_VALID_URL,
        youtube_video_id="dQw4w9WgXcY",
        status="completed",
        source_language="ja",
        target_language="ko",
        subtitle_source="manual",
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    session.add(job)
    await session.flush()

    # 실제 파일 생성 (tmp_path 하위)
    srt_path = tmp_path / "dual.srt"
    vtt_path = tmp_path / "dual.vtt"
    srt_path.write_text(_SAMPLE_SRT_SOURCE_FIRST, encoding="utf-8")
    vtt_path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nこんにちは、世界。\n안녕하세요, 세계.\n", encoding="utf-8")

    session.add(VideoAsset(
        id=new_job_id(),
        job_id=job_id,
        kind="dual_srt",
        path=str(srt_path),
        mime_type="application/x-subrip",
        byte_size=srt_path.stat().st_size,
        created_at=now,
    ))
    session.add(VideoAsset(
        id=new_job_id(),
        job_id=job_id,
        kind="dual_vtt",
        path=str(vtt_path),
        mime_type="text/vtt",
        byte_size=vtt_path.stat().st_size,
        created_at=now,
    ))
    await session.commit()
    return job_id


@pytest.fixture
async def pending_job_id(db_session: object) -> str:  # type: ignore[type-arg]
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = db_session  # type: ignore[assignment]
    job_id = new_job_id()
    now = datetime.now(UTC)
    job = VideoJob(
        id=job_id,
        source_url=_VALID_URL,
        youtube_video_id="dQw4w9WgXcY",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.commit()
    return job_id


class TestDownloadSrt:
    """SRT 다운로드 테스트."""

    async def test_srt_format_returns_content_disposition(
        self, client: AsyncClient, completed_job_with_assets: str
    ) -> None:
        """?format=srt 요청 시 Content-Disposition: attachment; filename=*.srt를 반환해야 한다."""
        job_id = completed_job_with_assets
        resp = await client.get(f"/v1/jobs/{job_id}/download", params={"format": "srt"})
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".srt" in cd

    async def test_srt_response_has_correct_content_type(
        self, client: AsyncClient, completed_job_with_assets: str
    ) -> None:
        """SRT 다운로드 응답의 Content-Type이 text/plain 또는 application/x-subrip이어야 한다."""
        job_id = completed_job_with_assets
        resp = await client.get(f"/v1/jobs/{job_id}/download", params={"format": "srt"})
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "plain" in ct or "subrip" in ct or "octet-stream" in ct


class TestDownloadVtt:
    """VTT 다운로드 테스트."""

    async def test_vtt_format_returns_correct_content_type(
        self, client: AsyncClient, completed_job_with_assets: str
    ) -> None:
        """?format=vtt 요청 시 Content-Type이 text/vtt이어야 한다."""
        job_id = completed_job_with_assets
        resp = await client.get(f"/v1/jobs/{job_id}/download", params={"format": "vtt"})
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "vtt" in ct

    async def test_vtt_filename_in_content_disposition(
        self, client: AsyncClient, completed_job_with_assets: str
    ) -> None:
        """VTT 다운로드 Content-Disposition에 .vtt 파일명이 포함되어야 한다."""
        job_id = completed_job_with_assets
        resp = await client.get(f"/v1/jobs/{job_id}/download", params={"format": "vtt"})
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".vtt" in cd


class TestDownloadOrder:
    """order 파라미터에 따른 줄 순서 검증."""

    async def test_source_first_order(
        self, client: AsyncClient, completed_job_with_assets: str
    ) -> None:
        """?order=source-first: 원문 줄이 번역 줄보다 앞에 위치해야 한다."""
        job_id = completed_job_with_assets
        resp = await client.get(
            f"/v1/jobs/{job_id}/download",
            params={"format": "srt", "order": "source-first"},
        )
        assert resp.status_code == 200
        body = resp.text
        # source(일본어) 줄이 target(한국어) 줄보다 먼저 등장해야 함
        ja_pos = body.find("こんにちは")
        ko_pos = body.find("안녕하세요")
        assert ja_pos != -1 and ko_pos != -1
        assert ja_pos < ko_pos

    async def test_target_first_order(
        self, client: AsyncClient, completed_job_with_assets: str
    ) -> None:
        """?order=target-first: 번역 줄이 원문 줄보다 앞에 위치해야 한다."""
        job_id = completed_job_with_assets
        resp = await client.get(
            f"/v1/jobs/{job_id}/download",
            params={"format": "srt", "order": "target-first"},
        )
        assert resp.status_code == 200
        body = resp.text
        ja_pos = body.find("こんにちは")
        ko_pos = body.find("안녕하세요")
        assert ja_pos != -1 and ko_pos != -1
        assert ko_pos < ja_pos


class TestDownloadNotCompleted:
    """미완료 작업 다운로드 — 409 테스트."""

    async def test_pending_job_returns_409(
        self, client: AsyncClient, pending_job_id: str
    ) -> None:
        """pending 상태 작업에 대한 다운로드 요청은 409를 반환해야 한다."""
        resp = await client.get(
            f"/v1/jobs/{pending_job_id}/download", params={"format": "srt"}
        )
        assert resp.status_code == 409
        assert resp.json()["success"] is False
        error_code = resp.json().get("error", {}).get("code", "")
        assert isinstance(error_code, str) and error_code, (
            "에러 응답에 비어있지 않은 error.code 문자열이 있어야 한다 (예: CONFLICT 또는 JOB_NOT_READY)"
        )

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        """존재하지 않는 job_id는 404를 반환해야 한다."""
        resp = await client.get(
            "/v1/jobs/00000000000000000000000000/download", params={"format": "srt"}
        )
        assert resp.status_code == 404
