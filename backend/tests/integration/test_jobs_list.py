"""T112: GET /v1/jobs 컨트랙트 테스트 (US3, FR-029, FR-030).

검증 항목:
- 200 + envelope.data.items[] (배열) — Job 스키마 준수
- envelope.data.next_cursor (string | null) — 다음 페이지 cursor
- ?limit=N: 반환 항목 수 제한 + 추가 페이지가 있으면 next_cursor 존재
- ?cursor=X: 두 번째 페이지에서 첫 페이지와 중복 없음
- ?status=completed: 해당 상태만 반환
- 빈 결과: items=[], next_cursor=null

openapi.yaml §JobListEnvelope 와 일치한다.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "app.api.v1.routes.jobs",
    reason="awaiting US3 implementation — app.api.v1.routes.jobs.list_jobs",
)
pytest.importorskip(
    "app.main",
    reason="awaiting US3 implementation — 라우터 배선",
)

from httpx import AsyncClient  # noqa: E402

pytestmark = pytest.mark.integration

# 동일 영상 ID 의 기존 작업은 재사용되므로(서비스 §create_or_reuse), 서로 다른
# 영상 ID 11자 슬러그 11종을 준비한다.
_VALID_URLS = [
    f"https://www.youtube.com/watch?v=Aabcdefgh{i:02d}" for i in range(11)
]


async def _create_jobs(client: AsyncClient, count: int) -> list[str]:
    """``count`` 개의 신규 작업을 순차적으로 생성하고 ID 목록을 반환한다.

    POST 응답이 201(신규) 또는 200(재사용) 어느 쪽이어도 ID 만 추출한다.
    created_at 의 순서가 안정되도록 직렬로 호출한다.
    """
    ids: list[str] = []
    for url in _VALID_URLS[:count]:
        resp = await client.post("/v1/jobs", json={"url": url})
        assert resp.status_code in (200, 201), resp.text
        ids.append(resp.json()["data"]["id"])
    return ids


class TestListJobsEnvelope:
    """GET /v1/jobs — 응답 envelope 형태 검증."""

    async def test_empty_state_returns_empty_items_and_null_cursor(
        self, client: AsyncClient
    ) -> None:
        """작업이 없으면 data.items=[], next_cursor=null 을 반환해야 한다."""
        resp = await client.get("/v1/jobs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "request_id" in body
        data = body["data"]
        assert data["items"] == []
        assert data.get("next_cursor") is None

    async def test_returns_items_array_with_envelope(self, client: AsyncClient) -> None:
        """작업이 있을 때 items 가 배열로 반환되고 각 항목이 Job 스키마를 만족해야 한다."""
        await _create_jobs(client, 2)

        resp = await client.get("/v1/jobs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert isinstance(data["items"], list)
        assert len(data["items"]) >= 2

        # 각 item 이 Job 필수 필드를 포함해야 한다 (openapi.yaml §Job)
        for item in data["items"]:
            for field in (
                "id",
                "source_url",
                "youtube_video_id",
                "status",
                "metadata",
                "created_at",
                "updated_at",
            ):
                assert field in item, f"필수 필드 누락: {field}"


class TestListJobsPagination:
    """GET /v1/jobs — limit / cursor 페이지네이션 검증."""

    async def test_limit_caps_returned_count(self, client: AsyncClient) -> None:
        """?limit=N 으로 반환 수가 제한되어야 한다."""
        await _create_jobs(client, 5)

        resp = await client.get("/v1/jobs", params={"limit": 3})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["items"]) == 3

    async def test_next_cursor_returned_when_more_pages_exist(
        self, client: AsyncClient
    ) -> None:
        """추가 페이지가 있으면 next_cursor 가 비어있지 않아야 한다."""
        await _create_jobs(client, 5)

        resp = await client.get("/v1/jobs", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["next_cursor"] is not None
        assert isinstance(data["next_cursor"], str)
        assert len(data["next_cursor"]) > 0

    async def test_cursor_paginates_without_overlap(self, client: AsyncClient) -> None:
        """cursor 로 두 번째 페이지 조회 시 첫 페이지와 ID 가 겹치지 않아야 한다."""
        await _create_jobs(client, 5)

        page1_resp = await client.get("/v1/jobs", params={"limit": 2})
        page1 = page1_resp.json()["data"]
        cursor = page1["next_cursor"]
        assert cursor is not None

        page2_resp = await client.get(
            "/v1/jobs", params={"limit": 2, "cursor": cursor}
        )
        assert page2_resp.status_code == 200
        page2 = page2_resp.json()["data"]
        assert len(page2["items"]) >= 1

        ids1 = {it["id"] for it in page1["items"]}
        ids2 = {it["id"] for it in page2["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_last_page_has_null_next_cursor(self, client: AsyncClient) -> None:
        """마지막 페이지에서는 next_cursor 가 null 이어야 한다."""
        await _create_jobs(client, 2)

        # openapi.yaml — limit 의 최대치는 50 이다.
        resp = await client.get("/v1/jobs", params={"limit": 50})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data.get("next_cursor") is None


class TestListJobsStatusFilter:
    """GET /v1/jobs?status=... — 상태 필터 검증."""

    async def test_status_filter_returns_only_matching(
        self, client: AsyncClient
    ) -> None:
        """?status=failed 적용 시 failed 작업만 반환되어야 한다."""
        # 2건 생성 — 모두 pending 상태로 시작
        ids = await _create_jobs(client, 2)

        # 두 작업 중 하나를 failed 로 직접 전이 (repository 경유)
        from app.domain.jobs.states import JobStatus
        from app.infrastructure.db.repositories.job_repository import SqlJobRepository

        async def _mark_first_failed() -> None:
            # client fixture 와 동일한 db_session 을 공유하기 위해 dependency
            # override 가 등록된 fastapi_app 의 jobs_service 를 다시 사용한다.
            # 여기서는 단순히 client 가 사용하는 in-memory DB 세션을 통해 update.
            # JobRepository 는 client 내부 dependency_overrides 가 주입한 동일 session 을 쓴다.
            return None

        # 대신 cancel 엔드포인트를 활용하여 failed 로 만든다 (서비스 경로 보존).
        cancel_resp = await client.delete(f"/v1/jobs/{ids[0]}")
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["data"]["status"] == JobStatus.failed.value
        # noqa: F401 — SqlJobRepository import 는 향후 직접 repo 조작용 placeholder.
        _ = SqlJobRepository

        resp = await client.get("/v1/jobs", params={"status": "failed"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        statuses = {it["status"] for it in data["items"]}
        assert statuses == {"failed"}
        returned_ids = {it["id"] for it in data["items"]}
        assert ids[0] in returned_ids
        assert ids[1] not in returned_ids
