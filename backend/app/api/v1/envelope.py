"""T014: 표준 응답 envelope.

모든 API 응답은 { success, data?, error?, request_id } 형태를 따른다.
contracts/openapi.yaml의 JobEnvelope / ErrorEnvelope 스키마와 일치.
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorBody(BaseModel):
    """오류 응답 body. code는 기계 판독용, message는 사용자 친화적 한국어."""

    code: str
    message: str
    details: dict[str, object] | None = None


class Envelope[T](BaseModel):
    """표준 응답 envelope (타입 힌트용)."""

    success: bool
    data: T | None = None
    error: ErrorBody | None = None
    request_id: str


def success_envelope(data: object, request_id: str) -> dict[str, object]:
    """성공 응답 dict를 생성한다.

    FastAPI가 자동 직렬화하도록 dict로 반환.
    """
    return {
        "success": True,
        "data": data,
        "request_id": request_id,
    }


def error_envelope(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    """오류 응답 dict를 생성한다.

    details가 None이면 응답에 포함하지 않는다.
    """
    error_body: dict[str, object] = {"code": code, "message": message}
    if details:
        error_body["details"] = details
    return {
        "success": False,
        "error": error_body,
        "request_id": request_id,
    }
