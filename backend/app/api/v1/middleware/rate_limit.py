"""T120: IP 기반 요청 빈도 제한 미들웨어.

`slowapi.Limiter` 를 활용해 동일 IP 의 쓰기 요청(POST/PUT/PATCH/DELETE) 빈도를 제한한다.
설계 결정:

1. **기본 정책**: ``settings.rate_limit_per_min`` 회 / 분 / IP (기본값 10).
2. **적용 범위**: HTTP method 가 안전(safe) 메서드(GET/HEAD/OPTIONS) 가 **아닌** 경우에만
   limiter 를 호출한다. 이는 SSE 스트림(``GET /v1/jobs/{id}/events``) 과 작업 조회
   (``GET /v1/jobs``) 가 길게 유지되거나 빈번하게 호출되어도 limit 을 소모하지 않게 한다.
3. **응답 envelope**: 초과 시 :class:`RateLimitedError` 를 throw → 도메인 예외 핸들러가
   기존 ``{success:false, error:{code:'RATE_LIMITED', message}, request_id}`` 포맷으로
   직렬화한다. 한글 메시지 "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요." 사용.
4. **client identifier**: ``slowapi.util.get_remote_address`` 를 사용해 ``request.client.host``
   를 키로 삼는다. 프록시 뒤에서 운용한다면 ``X-Forwarded-For`` 헤더 처리는 별도 인프라
   (예: uvicorn ``--proxy-headers``) 에 위임한다.

테스트는 ``rate_limit_per_min=10`` 기준으로 11번째 요청에서 429 가 반환되는지 검증한다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.v1.envelope import error_envelope
from app.core.config import get_settings
from app.core.exceptions import RateLimitedError

# RFC 7231 — limit 을 적용하지 않는 안전(safe) 메서드 집합.
_SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

# 한글 사용자 노출 메시지 — 헌법 V (한국어 산출물).
_RATE_LIMIT_MESSAGE: Final[str] = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."


def build_limiter() -> Limiter:
    """rate limit 검사용 :class:`Limiter` 를 생성한다.

    in-memory storage 를 기본으로 사용한다 — 멀티 프로세스 배포 시에는
    ``storage_uri="redis://..."`` 로 교체할 수 있도록 후일 확장 가능한 구조.
    """
    settings = get_settings()
    return Limiter(
        key_func=get_remote_address,
        default_limits=[f"{settings.rate_limit_per_min}/minute"],
        headers_enabled=False,
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """쓰기 요청에 한해 IP 기반 rate limit 을 강제하는 미들웨어.

    - GET/HEAD/OPTIONS 은 limiter 를 호출하지 않는다 (SSE / 조회 보호).
    - 초과 시 :class:`RateLimitedError` 를 throw → 도메인 핸들러가 envelope 직렬화.
    - limiter 인스턴스는 ``app.state.limiter`` 에도 노출되어 별도 데코레이터를 적용한
      라우트(향후 확장) 와 storage 를 공유할 수 있다.
    """

    def __init__(self, app: ASGIApp, *, limiter: Limiter | None = None) -> None:
        super().__init__(app)
        self.limiter = limiter or build_limiter()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 안전 메서드는 limit 을 소모하지 않는다 — SSE / GET /jobs 의 부담을 피하기 위해.
        if request.method.upper() in _SAFE_METHODS:
            return await call_next(request)

        # slowapi 의 default limit 을 수동으로 평가한다.
        # ``limiter.limit`` 데코레이터를 라우트마다 붙이는 대신, 미들웨어에서
        # 동일한 ``default_limits`` 정책을 적용해 보일러플레이트를 줄인다.
        key = self.limiter._key_func(request)
        exceeded = False
        try:
            # ``_default_limits`` 는 ``LimitGroup`` list — iter 하면 실제 ``Limit`` 이 나온다.
            for limit_group in self.limiter._default_limits:
                for limit in limit_group:
                    # ``limiter._limiter`` (limits.strategies) 가 실제 카운팅을 담당한다.
                    if not self.limiter._limiter.hit(limit.limit, key):
                        exceeded = True
                        break
                if exceeded:
                    break
        except RateLimitExceeded:
            # slowapi 가 자체적으로 RateLimitExceeded 를 던질 수도 있다 — 동일하게 처리.
            exceeded = True

        if exceeded:
            # ``BaseHTTPMiddleware`` 에서 raise 한 예외는 FastAPI 의 exception_handler
            # 에 도달하지 못하므로, 표준 envelope 를 직접 직렬화해 반환한다.
            request_id: str = getattr(request.state, "request_id", "")
            body = error_envelope(
                code=RateLimitedError.code,
                message=_RATE_LIMIT_MESSAGE,
                request_id=request_id,
            )
            return JSONResponse(content=body, status_code=RateLimitedError.http_status)

        return await call_next(request)


__all__ = ["RateLimitMiddleware", "build_limiter"]
