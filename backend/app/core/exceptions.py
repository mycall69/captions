"""T013: 도메인 예외 계층 및 FastAPI 예외 핸들러.

contracts/openapi.yaml의 ErrorBody code 값과 1:1 대응.
install_exception_handlers()로 FastAPI 앱에 일괄 등록.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ── 기본 도메인 예외 ──────────────────────────────────────────────────────────

class DomainError(Exception):
    """모든 도메인 예외의 기반 클래스."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ── 입력 검증 오류 (4xx) ──────────────────────────────────────────────────────

class InvalidUrlError(DomainError):
    """허용하지 않는 URL이거나 영상 ID를 추출할 수 없는 경우."""

    code = "INVALID_URL"
    http_status = 400


class InvalidInputError(DomainError):
    """입력값이 비즈니스 규칙을 위반하는 경우 (영상 길이 초과 등)."""

    code = "INVALID_INPUT"
    http_status = 400


class InvalidPathError(DomainError):
    """경로 보안 검증 실패 (path traversal 등) — 클라이언트 잘못된 입력."""

    code = "INVALID_INPUT"
    http_status = 400


# ── 리소스 상태 오류 (4xx) ────────────────────────────────────────────────────

class NotFoundError(DomainError):
    """요청한 리소스가 존재하지 않는 경우."""

    code = "NOT_FOUND"
    http_status = 404


class ConflictError(DomainError):
    """리소스 충돌 (중복 작업 등)."""

    code = "CONFLICT"
    http_status = 409


class IllegalStateTransitionError(DomainError):
    """허용되지 않는 상태 전이 시도 (완료 작업 취소 등)."""

    code = "ILLEGAL_STATE"
    http_status = 409


class UserCancelledError(DomainError):
    """사용자에 의해 작업이 취소된 경우."""

    code = "USER_CANCELLED"
    http_status = 409


class JobNotReadyError(DomainError):
    """작업이 아직 완료되지 않아 자막을 사용할 수 없는 경우 (처리 중)."""

    code = "JOB_NOT_READY"
    http_status = 409


class RateLimitedError(DomainError):
    """요청 빈도가 임계치를 초과한 경우."""

    code = "RATE_LIMITED"
    http_status = 429


# ── 자막 관련 오류 (4xx/5xx) ──────────────────────────────────────────────────

class SubtitleNotFoundError(DomainError):
    """영상에서 자막을 찾을 수 없는 경우."""

    code = "SUBTITLE_NOT_FOUND"
    http_status = 422


class SubtitleLanguageUnsupportedError(DomainError):
    """지원하지 않는 자막 언어인 경우."""

    code = "SUBTITLE_LANGUAGE_UNSUPPORTED"
    http_status = 422


# ── 처리 실패 오류 (5xx) ──────────────────────────────────────────────────────

class DownloadFailedError(DomainError):
    """영상 또는 자막 다운로드 실패."""

    code = "DOWNLOAD_FAILED"
    http_status = 500


class TranslationFailedError(DomainError):
    """번역 처리 실패."""

    code = "TRANSLATION_FAILED"
    http_status = 500


class RenderFailedError(DomainError):
    """자막 렌더링 실패."""

    code = "RENDER_FAILED"
    http_status = 500


# ── FastAPI 핸들러 등록 ───────────────────────────────────────────────────────

def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """DomainError를 ErrorEnvelope JSON으로 변환."""
    # request.state에 request_id가 있으면 포함, 없으면 빈 문자열
    request_id: str = getattr(request.state, "request_id", "")
    body: dict[str, object] = {
        "success": False,
        "error": {
            "code": exc.code,
            "message": exc.message,
            **({"details": exc.details} if exc.details else {}),
        },
        "request_id": request_id,
    }
    return JSONResponse(status_code=exc.http_status, content=body)


def install_exception_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 도메인 예외 핸들러를 일괄 등록한다."""
    app.add_exception_handler(DomainError, _domain_error_handler)  # type: ignore[arg-type]
