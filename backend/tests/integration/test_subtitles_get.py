"""T038: GET /v1/jobs/{id}/subtitles 컨트랙트 테스트 (US1, FR-017, FR-026).

검증 항목:
- 완료된 작업: 200 + source_cues + translated_cues 배열
- 미완료 작업: 409 + envelope.error.code
- 페이지네이션: offset/limit 파라미터 반영, total 필드 존재
- 언어 필드(source_language, target_language) 분리 확인
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

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
from app.infrastructure.db.orm import (  # noqa: E402
    SubtitleCue,
    SubtitleTrack,
    VideoJob,
)
from app.main import app  # noqa: E402  # type: ignore[reportMissingImports]

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def completed_job_id(db_session: object) -> str:  # type: ignore[type-arg]
    """completed 상태 작업 + source/translated 트랙 + cue rows를 DB에 삽입하고 job_id를 반환한다."""
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

    src_track_id = new_job_id()
    tgt_track_id = new_job_id()

    src_track = SubtitleTrack(
        id=src_track_id,
        job_id=job_id,
        kind="source",
        language="ja",
        origin="manual",
        source_format="srt",
        cue_count=3,
        created_at=now,
    )
    tgt_track = SubtitleTrack(
        id=tgt_track_id,
        job_id=job_id,
        kind="translated",
        language="ko",
        origin="generated",
        cue_count=3,
        created_at=now,
    )
    session.add(src_track)
    session.add(tgt_track)
    await session.flush()

    for i in range(1, 4):
        session.add(SubtitleCue(
            track_id=src_track_id,
            sequence=i,
            start_ms=i * 1000,
            end_ms=i * 1000 + 500,
            text=f"こんにちは {i}",
        ))
        session.add(SubtitleCue(
            track_id=tgt_track_id,
            sequence=i,
            start_ms=i * 1000,
            end_ms=i * 1000 + 500,
            text=f"안녕하세요 {i}",
        ))
    await session.commit()
    return job_id


@pytest.fixture
async def pending_job_id(db_session: object) -> str:  # type: ignore[type-arg]
    """pending 상태 작업만 삽입하고 job_id를 반환한다."""
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


class TestGetSubtitlesCompleted:
    """완료된 작업의 자막 조회 테스트."""

    async def test_returns_200_with_cue_arrays(
        self, client: AsyncClient, completed_job_id: str
    ) -> None:
        """완료 작업 조회 시 200 + source_cues + translated_cues를 반환해야 한다."""
        resp = await client.get(f"/v1/jobs/{completed_job_id}/subtitles")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert "source_cues" in data
        assert "translated_cues" in data

    async def test_cue_arrays_have_correct_structure(
        self, client: AsyncClient, completed_job_id: str
    ) -> None:
        """각 cue는 sequence, start_ms, end_ms, text 필드를 가져야 한다."""
        resp = await client.get(f"/v1/jobs/{completed_job_id}/subtitles")
        data = resp.json()["data"]
        for cue in data["source_cues"]:
            assert "sequence" in cue
            assert "start_ms" in cue
            assert "end_ms" in cue
            assert "text" in cue

    async def test_response_has_language_fields(
        self, client: AsyncClient, completed_job_id: str
    ) -> None:
        """응답에 source_language, target_language, total, offset, limit이 포함되어야 한다."""
        resp = await client.get(f"/v1/jobs/{completed_job_id}/subtitles")
        data = resp.json()["data"]
        assert "source_language" in data
        assert "target_language" in data
        assert "total" in data
        assert "offset" in data
        assert "limit" in data

    async def test_pagination_offset_and_limit(
        self, client: AsyncClient, completed_job_id: str
    ) -> None:
        """offset/limit 파라미터가 응답에 반영되어야 한다."""
        resp = await client.get(
            f"/v1/jobs/{completed_job_id}/subtitles", params={"offset": 1, "limit": 2}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["offset"] == 1
        assert data["limit"] == 2
        # offset=1이면 3개 중 2개 이하 반환
        assert len(data["source_cues"]) <= 2

    async def test_total_reflects_full_count(
        self, client: AsyncClient, completed_job_id: str
    ) -> None:
        """total은 페이지네이션과 무관하게 전체 cue 수를 반환해야 한다."""
        resp = await client.get(
            f"/v1/jobs/{completed_job_id}/subtitles", params={"limit": 1}
        )
        data = resp.json()["data"]
        assert data["total"] == 3  # fixture에서 3개 삽입


class TestGetSubtitlesNotCompleted:
    """미완료 작업 자막 조회 — 409 Conflict 테스트."""

    async def test_pending_job_returns_409(
        self, client: AsyncClient, pending_job_id: str
    ) -> None:
        """pending 상태 작업 조회 시 409를 반환해야 한다."""
        resp = await client.get(f"/v1/jobs/{pending_job_id}/subtitles")
        assert resp.status_code == 409
        assert resp.json()["success"] is False
        error_code = resp.json().get("error", {}).get("code", "")
        assert isinstance(error_code, str) and error_code, (
            "에러 응답에 비어있지 않은 error.code 문자열이 있어야 한다 (예: CONFLICT 또는 JOB_NOT_READY)"
        )

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        """존재하지 않는 job_id는 404를 반환해야 한다."""
        resp = await client.get("/v1/jobs/00000000000000000000000000/subtitles")
        assert resp.status_code == 404
