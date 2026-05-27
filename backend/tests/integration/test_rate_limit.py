"""T120: 요청 빈도 제한 미들웨어 통합 테스트.

검증 항목:

1. ``settings.rate_limit_per_min`` (기본 10) 회 까지는 POST 가 통과한다.
2. 그 다음 요청(11번째) 은 429 + ``RATE_LIMITED`` 에러 코드를 반환한다.
3. GET 류(예: ``GET /v1/jobs``) 는 limit 을 소모하지 않으므로 같은 IP 에서
   limit 직전 또는 초과 후에도 정상 응답한다.

slowapi limiter 는 in-memory storage 를 사용하므로 fixture 마다 새 Limiter 인스턴스를
주입해 테스트 간 독립성을 확보한다.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"


@pytest.fixture
async def isolated_client(db_session: object) -> AsyncClient:  # noqa: ARG001
    """별도 Limiter 가 주입된 격리 클라이언트 — 다른 테스트 카운터와 섞이지 않는다.

    프로덕션 ``create_app()`` 은 모듈 import 시 ``app`` 싱글턴을 만들고 이를
    여러 테스트가 공유한다. rate limit 테스트는 카운터 격리가 필수이므로
    **이 fixture 안에서만** 별도 FastAPI 앱을 만들어 사용한다.
    """
    # 지연 import — create_app() 직접 호출 (모듈 레벨 싱글턴과 분리)
    from app.api.v1.dependencies import db_session as _real_db_session
    from app.api.v1.dependencies import event_bus as _real_event_bus
    from app.api.v1.dependencies import jobs_service as _real_jobs_service
    from app.api.v1.middleware.rate_limit import build_limiter
    from app.domain.jobs.models import VideoMetadata
    from app.domain.jobs.service import JobsService
    from app.infrastructure.db.repositories.job_repository import SqlJobRepository
    from app.main import create_app

    app = create_app()
    # rate limit storage 격리 — 새 Limiter 로 교체.
    fresh_limiter = build_limiter()
    app.state.limiter = fresh_limiter
    # 등록된 RateLimitMiddleware 인스턴스도 새 limiter 를 참조하도록 갱신한다.
    # Starlette 의 user_middleware 는 등록 순서대로 ``Middleware`` wrapper 를 보관.
    for mw in app.user_middleware:
        if mw.cls.__name__ == "RateLimitMiddleware":
            mw.kwargs["limiter"] = fresh_limiter

    async def _fake_fetch_metadata(video_id: str) -> VideoMetadata:
        return VideoMetadata(
            title=f"Test {video_id}",
            channel="ch",
            duration_sec=120,
            subtitle_source=None,
        )

    async def _override_db() -> object:
        yield db_session  # type: ignore[misc]

    def _override_jobs_service() -> JobsService:
        return JobsService(
            SqlJobRepository(db_session),  # type: ignore[arg-type]
            metadata_fetcher=_fake_fetch_metadata,
        )

    class _Bus:
        async def publish(self, channel: str, payload: dict[str, object]) -> None:  # noqa: ARG002
            return None

        def subscribe(self, channel: str, *, ready: object | None = None):  # noqa: ARG002
            async def _gen():
                if ready is not None:
                    ready.set()  # type: ignore[attr-defined]
                return
                yield {}

            return _gen()

    app.dependency_overrides[_real_db_session] = _override_db
    app.dependency_overrides[_real_jobs_service] = _override_jobs_service
    app.dependency_overrides[_real_event_bus] = lambda: _Bus()

    import os

    from app.core.config import get_settings

    get_settings.cache_clear()
    os.environ["DISABLE_CHAIN_DISPATCH"] = "true"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    os.environ.pop("DISABLE_CHAIN_DISPATCH", None)
    get_settings.cache_clear()


class TestRateLimit:
    """IP 기반 빈도 제한 검증."""

    async def test_eleventh_post_returns_429(self, isolated_client: AsyncClient) -> None:
        """기본 10 req/min — 11번째 POST 는 429 + RATE_LIMITED 를 반환해야 한다."""
        # 첫 10건은 정상 200/201 응답
        for i in range(10):
            resp = await isolated_client.post("/v1/jobs", json={"url": _VALID_URL})
            assert resp.status_code in (200, 201), f"#{i}: {resp.status_code} {resp.text}"

        # 11번째 — 429 RATE_LIMITED
        resp = await isolated_client.post("/v1/jobs", json={"url": _VALID_URL})
        assert resp.status_code == 429
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "RATE_LIMITED"
        # 한글 메시지 (헌법 V)
        assert "요청" in body["error"]["message"]
        # request_id envelope 보존
        assert "request_id" in body

    async def test_get_requests_are_not_rate_limited(
        self, isolated_client: AsyncClient
    ) -> None:
        """GET (안전 메서드) 은 limit 을 소모하지 않으므로 11회 이상 호출해도 정상."""
        for _ in range(15):
            resp = await isolated_client.get("/v1/jobs")
            # 라우터가 정상 동작하면 200, 미구현이라도 GET 자체가 429 면 안 된다.
            assert resp.status_code != 429
