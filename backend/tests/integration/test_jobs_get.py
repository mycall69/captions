"""T037: GET /v1/jobs/{id} 컨트랙트 테스트 (US1, FR-024, FR-026).

검증 항목:
- 200 + envelope.data — 모든 필수 필드 존재
- 404 + envelope.error.code == NOT_FOUND (존재하지 않는 job_id)
- 상태 필드(status, created_at, updated_at 등) 존재 여부
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

pytest.importorskip(
    "app.api.v1.routes.jobs",
    reason="awaiting Phase 3h implementation — app.api.v1.routes.jobs",
)
pytest.importorskip(
    "app.main",
    reason="awaiting Phase 3h implementation — 라우터 배선",
)

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402  # type: ignore[reportMissingImports]

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def created_job_id(client: AsyncClient) -> str:
    """테스트용 작업을 생성하고 job id를 반환한다."""
    resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
    assert resp.status_code in (200, 201)
    return resp.json()["data"]["id"]  # type: ignore[no-any-return]


class TestGetJobSuccess:
    """GET /v1/jobs/{id} 정상 경로 테스트."""

    async def test_returns_200_with_envelope(
        self, client: AsyncClient, created_job_id: str
    ) -> None:
        """유효한 job_id로 조회 시 200 + envelope.data를 반환해야 한다."""
        resp = await client.get(f"/v1/jobs/{created_job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "request_id" in body

    async def test_response_has_required_job_fields(
        self, client: AsyncClient, created_job_id: str
    ) -> None:
        """응답 data에 openapi.yaml Job 스키마의 필수 필드가 모두 포함되어야 한다."""
        resp = await client.get(f"/v1/jobs/{created_job_id}")
        data = resp.json()["data"]
        required_fields = [
            "id",
            "source_url",
            "youtube_video_id",
            "status",
            "metadata",
            "created_at",
            "updated_at",
            "reused",
        ]
        for field in required_fields:
            assert field in data, f"필수 필드 누락: {field}"

    async def test_metadata_subfields_present(
        self, client: AsyncClient, created_job_id: str
    ) -> None:
        """metadata 서브 필드(title, channel, duration_sec, subtitle_source)가 존재해야 한다."""
        resp = await client.get(f"/v1/jobs/{created_job_id}")
        metadata = resp.json()["data"]["metadata"]
        assert "title" in metadata
        assert "channel" in metadata
        assert "duration_sec" in metadata
        assert "subtitle_source" in metadata

    async def test_status_is_valid_enum_value(
        self, client: AsyncClient, created_job_id: str
    ) -> None:
        """status 필드가 허용된 enum 값이어야 한다."""
        valid_statuses = {
            "pending", "downloading", "subtitle_processing",
            "translating", "rendering", "completed", "failed",
        }
        resp = await client.get(f"/v1/jobs/{created_job_id}")
        status = resp.json()["data"]["status"]
        assert status in valid_statuses


class TestGetJobNotFound:
    """GET /v1/jobs/{id} — 존재하지 않는 ID 처리."""

    async def test_unknown_id_returns_404(self, client: AsyncClient) -> None:
        """존재하지 않는 job_id 조회 시 404를 반환해야 한다."""
        fake_id = "00000000000000000000000000"  # 26자 ULID 형식
        resp = await client.get(f"/v1/jobs/{fake_id}")
        assert resp.status_code == 404

    async def test_unknown_id_error_code_is_not_found(self, client: AsyncClient) -> None:
        """404 응답의 error.code가 NOT_FOUND이어야 한다."""
        fake_id = "00000000000000000000000000"
        resp = await client.get(f"/v1/jobs/{fake_id}")
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"
