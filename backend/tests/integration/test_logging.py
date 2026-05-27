"""T125: 구조화 로깅 필드 검증 테스트.

목적:

- 작업 lifecycle 핵심 로그가 **필수 메타데이터** (``request_id`` / ``job_id`` 등) 를
  포함하는지 회귀 방지로 검증한다.
- ``structlog.testing.capture_logs`` 로 in-memory 로그를 가로채고 deterministic 하게 assert.

검증 대상 로그 이벤트 (이름 → 필수 필드):

- ``job.created``           → ``job_id``, ``video_id``
- ``job.reused``            → ``job_id``, ``video_id``
- ``job.state_changed``     → ``job_id``, ``from``/``to`` (또는 등가 키)
- ``event.published`` (debug) → ``job_id``, ``event_type``, ``seq``

또한 API 경로 ``POST /v1/jobs`` 호출 후에는 ``contextvars`` 에 ``request_id`` 가 바인딩되어
모든 구조화 로그에 자동 포함돼야 한다 (``merge_contextvars`` 프로세서 검증).
"""

from __future__ import annotations

import pytest
import structlog
from httpx import AsyncClient

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"


class TestStructuredLoggingFields:
    """구조화 로깅 필드 회귀 방지."""

    async def test_job_created_log_includes_request_id_and_job_id(
        self, client: AsyncClient
    ) -> None:
        """``POST /v1/jobs`` 후 ``job.created`` 로그가 request_id, job_id, video_id 를 포함한다."""
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars],
        ) as captured:
            resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
            assert resp.status_code in (200, 201)

        created_logs = [r for r in captured if r.get("event") == "job.created"]
        assert created_logs, (
            f"job.created 로그를 찾지 못했습니다. 캡처된 이벤트: "
            f"{[r.get('event') for r in captured]}"
        )

        record = created_logs[0]
        # 필수 필드: job_id, video_id 는 호출 지점에서 직접 바인딩
        assert "job_id" in record
        assert record["job_id"], "job_id 가 비어 있습니다"
        assert "video_id" in record
        # contextvars 로 자동 주입되는 request_id (RequestIdMiddleware → bind_contextvars)
        assert "request_id" in record
        assert record["request_id"], "request_id 가 contextvars 로 주입되지 않았습니다"

    async def test_job_reused_log_includes_required_fields(
        self, client: AsyncClient
    ) -> None:
        """동일 URL 재요청 시 ``job.reused`` 로그가 필수 필드를 포함한다."""
        # 1) 신규 작업 생성 (capture 밖)
        first = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert first.status_code == 201

        # 2) 재요청 — 이 호출 동안만 캡처
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars],
        ) as captured:
            second = await client.post("/v1/jobs", json={"url": _VALID_URL})
            assert second.status_code == 200

        reused_logs = [r for r in captured if r.get("event") == "job.reused"]
        assert reused_logs, "job.reused 로그를 찾지 못했습니다"

        record = reused_logs[0]
        assert "job_id" in record
        assert "video_id" in record
        assert "existing_status" in record
        # request_id 는 contextvars 로 자동 부여
        assert "request_id" in record

    async def test_log_level_is_attached_to_records(self, client: AsyncClient) -> None:
        """capture_logs 가 log_level 메타데이터를 attach 하는지 sanity check.

        ``structlog.testing.capture_logs`` 는 모든 record 에 ``log_level`` 키를
        attach 한다 — 본 sanity check 가 실패하면 structlog 버전 변경의 시그널.
        """
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars],
        ) as captured:
            await client.post("/v1/jobs", json={"url": _VALID_URL})

        assert captured, "POST /v1/jobs 호출 동안 어떤 로그도 캡처되지 않았습니다"
        for r in captured:
            assert "log_level" in r, f"log_level 누락 record: {r}"

    async def test_contextvars_request_id_propagates_to_logs(
        self, client: AsyncClient
    ) -> None:
        """``RequestIdMiddleware`` 가 contextvars 에 바인딩한 ``request_id`` 가
        구조화 로그에 자동 포함되는지 확인한다."""
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars],
        ) as captured:
            resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
            assert resp.status_code in (200, 201)
            response_request_id = resp.headers.get("x-request-id")
            assert response_request_id, "응답 헤더에 x-request-id 가 없습니다"

        # 캡처된 로그 중 최소 1건은 응답의 request_id 와 동일한 값을 가져야 한다.
        matching = [r for r in captured if r.get("request_id") == response_request_id]
        assert matching, (
            "응답 헤더의 request_id 와 일치하는 구조화 로그가 없습니다 — "
            "contextvars 전파 실패."
        )
