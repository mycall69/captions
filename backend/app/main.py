"""T009: FastAPI 앱 팩토리.

미들웨어 순서 (Starlette는 add_middleware가 역순으로 실행됨):
- 마지막으로 추가된 미들웨어가 가장 바깥쪽 레이어 (인바운드 최초 진입).
- 여기서는 CORS를 마지막에 추가 → CORS가 가장 바깥쪽.
- RequestIdMiddleware는 CORS 안쪽 → 모든 통과 요청(OPTIONS preflight 포함)에
  request_id가 부여되어 내부 로그에 항상 포함됨.

/v1 라우터 마운트는 T082에서 수행 (현재는 placeholder).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter

from app.api.v1.middleware.rate_limit import RateLimitMiddleware, build_limiter
from app.api.v1.middleware.request_id import RequestIdMiddleware
from app.core.config import get_settings
from app.core.exceptions import install_exception_handlers
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """앱 lifecycle — 시작 시 로깅을 초기화하고 종료 시 EventBus 싱글턴을 닫는다.

    EventBus 싱글턴은 Redis async client connection pool 을 들고 있으므로,
    프로세스 종료 시 명시적으로 닫지 않으면 connection leak warning 이 남는다.
    """
    configure_logging()
    try:
        yield
    finally:
        # SSE 핸들러용 EventBus 싱글턴을 닫는다 (lazy 초기화된 경우에만 동작).
        from app.api.v1.dependencies import shutdown_event_bus

        await shutdown_event_bus()


def create_app() -> FastAPI:
    """FastAPI 앱 인스턴스를 생성하고 미들웨어/핸들러를 등록한다."""
    settings = get_settings()

    app = FastAPI(
        title="Bilingual Subtitle Studio",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 도메인 예외 → ErrorEnvelope 변환 핸들러 등록
    install_exception_handlers(app)

    # 미들웨어 등록 (add_middleware는 역순으로 실행됨 — 마지막 추가 = 가장 바깥쪽)
    # 1. RateLimitMiddleware 가장 먼저 추가 → 가장 안쪽 (RequestId 다음 단계)
    #    → 모든 통과 요청에 request_id 가 이미 부여된 뒤 limit 검사 → 로그 추적 가능
    limiter = build_limiter()
    app.state.limiter = limiter  # SlowAPI 표준 위치 — 향후 데코레이터 확장 호환
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    # 2. RequestIdMiddleware → CORS 안쪽 + RateLimit 바깥쪽에서 실행
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)

    # 3. CORSMiddleware 나중에 추가 → 가장 바깥쪽에서 실행 (인바운드 최초 진입)
    #    OPTIONS preflight도 RequestIdMiddleware까지 도달하므로 request_id 부여됨
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # T082 / T101: /v1 라우터 마운트 — jobs, subtitles, media, events 라우터 등록
    from app.api.v1.routes import events, jobs, media, subtitles

    api_v1_router = APIRouter(prefix="/v1")
    api_v1_router.include_router(jobs.router, tags=["jobs"])
    api_v1_router.include_router(subtitles.router, tags=["subtitles"])
    api_v1_router.include_router(media.router, tags=["media"])
    api_v1_router.include_router(events.router, tags=["events"])
    app.include_router(api_v1_router)

    return app


app = create_app()
