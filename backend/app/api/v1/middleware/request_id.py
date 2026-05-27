"""T010 (미들웨어 부분): 요청 ID 미들웨어.

모든 요청에 고유 request_id를 부여하고:
1. structlog contextvars에 바인딩 → 요청 범위 내 모든 로그에 자동 포함
2. request.state.request_id에 저장 → 엔드포인트에서 직접 접근 가능
3. 응답 헤더에 포함 → 클라이언트가 요청 추적에 활용
"""

from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.ids import new_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """요청 ID를 생성/전파하는 Starlette 미들웨어."""

    def __init__(self, app: ASGIApp, header_name: str = "x-request-id") -> None:
        super().__init__(app)
        self.header_name = header_name.lower()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 인바운드 헤더에서 request_id 추출; 없으면 신규 생성
        request_id = request.headers.get(self.header_name) or new_request_id()

        # structlog contextvars에 바인딩 (요청 범위)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # request.state에 저장 (엔드포인트 / 응답 envelope에서 접근)
        request.state.request_id = request_id

        response = await call_next(request)

        # 응답 헤더에 request_id 포함
        response.headers[self.header_name] = request_id

        return response
