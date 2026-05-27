"""T036: POST /v1/jobs 컨트랙트 테스트 (US1, FR-001, FR-002, FR-003, FR-004, FR-035).

검증 항목:
- 201 신규 작업 생성 (envelope.data.id, status == pending, reused == False)
- 200 동일 URL 재사용 (reused == True, 동일 job id)
- 400 잘못된 URL (envelope.error.code == INVALID_URL)
- 429 rate limit 초과 (envelope.error.code == RATE_LIMITED)
- 400 영상 길이 초과 (envelope.error.code == INVALID_INPUT, spec §16.2)
"""

from __future__ import annotations

import pytest

# 대상 모듈이 아직 미구현이므로 importorskip으로 수집은 성공시키되 실행은 skip한다.
jobs_routes = pytest.importorskip(
    "app.api.v1.routes.jobs",
    reason="awaiting Phase 3h implementation — app.api.v1.routes.jobs",
)
app_module = pytest.importorskip(
    "app.main",
    reason="awaiting Phase 3h implementation — app.main 라우터 배선",
)

from httpx import AsyncClient  # noqa: E402

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"
_INVALID_URL = "https://not-youtube.com/watch?v=dQw4w9WgXcY"


class TestPostJobsSuccess:
    """POST /v1/jobs 정상 경로 테스트."""

    async def test_creates_new_job_returns_201(self, client: AsyncClient) -> None:
        """유효한 URL로 신규 작업 생성 시 201 + envelope.data를 반환해야 한다."""
        resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["id"]
        assert len(data["id"]) == 26  # ULID 26자
        assert data["status"] == "pending"
        assert data["reused"] is False
        assert "request_id" in body

    async def test_new_job_envelope_has_metadata_fields(self, client: AsyncClient) -> None:
        """생성된 작업 응답에 metadata 필드가 포함되어야 한다."""
        resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "metadata" in data
        assert "source_url" in data
        assert "youtube_video_id" in data
        assert len(data["youtube_video_id"]) == 11


class TestPostJobsDuplicateUrl:
    """POST /v1/jobs — 동일 URL 재요청 처리 (research §10)."""

    async def test_duplicate_completed_job_returns_200_reused(
        self, client: AsyncClient
    ) -> None:
        """완료된 작업과 동일 URL 재요청 시 200 + reused == True를 반환해야 한다."""
        # 첫 번째 요청: 신규 생성
        r1 = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert r1.status_code == 201
        original_id = r1.json()["data"]["id"]

        # 두 번째 요청: 동일 URL
        r2 = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["success"] is True
        assert body2["data"]["reused"] is True
        assert body2["data"]["id"] == original_id

    async def test_duplicate_in_progress_job_returns_200_reused(
        self, client: AsyncClient
    ) -> None:
        """진행 중인 작업과 동일 URL 재요청 시 200 + reused == True를 반환해야 한다 (research §10)."""
        r1 = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert r1.status_code in (200, 201)
        original_id = r1.json()["data"]["id"]

        r2 = await client.post("/v1/jobs", json={"url": _VALID_URL})
        # 진행 중인 경우도 200 + reused
        assert r2.status_code == 200
        assert r2.json()["data"]["reused"] is True
        assert r2.json()["data"]["id"] == original_id


class TestPostJobsValidation:
    """POST /v1/jobs — 입력 검증 실패 케이스."""

    async def test_invalid_url_returns_400_invalid_url(self, client: AsyncClient) -> None:
        """YouTube가 아닌 URL은 400 + INVALID_URL 에러 코드를 반환해야 한다."""
        resp = await client.post("/v1/jobs", json={"url": _INVALID_URL})
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "INVALID_URL"

    async def test_playlist_url_returns_400_invalid_url(self, client: AsyncClient) -> None:
        """playlist URL은 400 + INVALID_URL을 반환해야 한다."""
        playlist_url = "https://www.youtube.com/playlist?list=PLxxxxx"
        resp = await client.post("/v1/jobs", json={"url": playlist_url})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_URL"

    async def test_missing_url_field_returns_422(self, client: AsyncClient) -> None:
        """url 필드 누락 시 422(Pydantic 검증 오류)를 반환해야 한다."""
        resp = await client.post("/v1/jobs", json={})
        assert resp.status_code == 422

    async def test_video_too_long_returns_400_invalid_input(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """영상 길이가 3600초 초과이면 400 + INVALID_INPUT을 반환해야 한다 (spec FR-003, §16.2)."""
        # 메타데이터 조회를 mock하여 duration_sec=7200 (2시간)으로 설정
        try:
            import app.api.v1.routes.jobs as _routes  # type: ignore[reportMissingImports]

            async def _fake_fetch_duration(_url: str) -> int:
                return 7200

            monkeypatch.setattr(_routes, "fetch_video_duration", _fake_fetch_duration, raising=False)
        except (ImportError, AttributeError):
            pytest.skip("fetch_video_duration hook not yet implemented")

        resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"


class TestPostJobsRateLimit:
    """POST /v1/jobs — rate limit 처리 (FR-035)."""

    async def test_rate_limited_returns_429(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rate limit 초과 시 429 + RATE_LIMITED 에러 코드를 반환해야 한다."""
        from app.core.exceptions import RateLimitedError

        # rate limiter를 강제로 trigger 시키는 방법: slowapi limiter mock 또는
        # 예외를 직접 발생시키는 dependency override
        try:
            import app.api.v1.routes.jobs as _routes  # type: ignore[reportMissingImports]

            async def _fake_rate_check(*_a: object, **_k: object) -> None:
                raise RateLimitedError("rate limit exceeded")

            monkeypatch.setattr(_routes, "check_rate_limit", _fake_rate_check, raising=False)
        except (ImportError, AttributeError):
            pytest.skip("check_rate_limit hook not yet implemented")

        resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMITED"
