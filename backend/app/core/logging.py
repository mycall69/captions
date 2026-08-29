"""T010 (logging 부분): structlog 설정.

- APP_ENV=local: 컬러 콘솔 렌더러 + JSON 파일 sink
- 그 외: JSON 콘솔 + JSON 파일 sink
- request_id는 contextvars에 바인딩되어 모든 로그에 자동 포함
- 헌법 VI(Always-On Logging) — `logs/backend/app.log` 파일 sink 항상 활성.
  daily rotation(`TimedRotatingFileHandler` midnight, backup 14일).
- 시크릿(api_key, oauth_token, authorization 헤더 등)은 적재 전 마스킹한다.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import structlog

from app.core.config import get_settings

# 헌법 VI — 로그에서 마스킹할 키 (대소문자 무시).
# 값이 dict의 value 또는 문자열 내 "<key>=...." 형태로 등장하는 두 경우 모두 처리.
_SECRET_KEY_RE = re.compile(
    r"(?i)\b(api[_-]?key|oauth[_-]?token|authorization|password|secret|token)\b"
)
# 로깅 적재 전 dict payload에서 redact 처리할 정확 일치 키 (소문자 비교).
_SECRET_DICT_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "anthropic_api_key",
        "claude_code_oauth_token",
        "oauth_token",
        "authorization",
        "password",
        "secret",
        "token",
    }
)
_MASK = "***REDACTED***"


def _mask_secrets(
    _logger: Any,
    _name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    """이벤트 dict 내 시크릿 키 값을 ``***REDACTED***`` 로 치환한다.

    - 정확 일치 키 (api_key, oauth_token, authorization, ...) → 값 마스킹
    - 중첩 dict 도 재귀 처리
    """

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (_MASK if isinstance(k, str) and k.lower() in _SECRET_DICT_KEYS else _walk(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        return obj

    walked = _walk(dict(event_dict))
    assert isinstance(walked, dict)
    return walked


def _ensure_log_dir(log_dir: Path) -> Path:
    """`logs/backend/` 디렉토리를 생성하고 경로를 반환한다."""
    backend_log_dir = log_dir / "backend"
    backend_log_dir.mkdir(parents=True, exist_ok=True)
    return backend_log_dir


def configure_logging() -> None:
    """structlog 전역 설정을 초기화한다.

    lifespan 컨텍스트 시작 시 한 번 호출해야 한다.
    헌법 VI — 콘솔 sink와 파일 sink(`logs/backend/app.log`)를 동시에 활성화.
    """
    settings = get_settings()
    is_local = settings.app_env == "local"

    # 공통 프로세서 체인 (마스킹은 가장 마지막 단계에 적용)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.StackInfoRenderer(),
        _mask_secrets,
    ]

    if is_local:
        console_renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        console_renderer = structlog.processors.JSONRenderer()
    # 파일 sink는 환경 무관 JSON (헌법 VI — 집계/검색 친화).
    file_renderer: structlog.types.Processor = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=console_renderer,
        foreign_pre_chain=shared_processors,
    )
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=file_renderer,
        foreign_pre_chain=shared_processors,
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)

    # 헌법 VI — 파일 sink 항상 활성. daily rotation.
    backend_log_dir = _ensure_log_dir(Path(settings.log_dir))
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=backend_log_dir / "app.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(file_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(settings.log_level.upper())
