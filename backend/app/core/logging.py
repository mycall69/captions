"""T010 (logging 부분): structlog 설정.

- APP_ENV=local: 컬러 콘솔 렌더러
- 그 외: JSON 렌더러 (프로덕션, 로그 집계에 적합)
- request_id는 contextvars에 바인딩되어 모든 로그에 자동 포함
"""

import logging

import structlog

from app.core.config import get_settings


def configure_logging() -> None:
    """structlog 전역 설정을 초기화한다.

    lifespan 컨텍스트 시작 시 한 번 호출해야 한다.
    """
    settings = get_settings()
    is_local = settings.app_env == "local"

    # 공통 프로세서 체인
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.StackInfoRenderer(),
    ]

    if is_local:
        # 로컬: 컬러 콘솔 렌더러 (개발 편의)
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        # 프로덕션: JSON 줄 단위 출력
        renderer = structlog.processors.JSONRenderer()

    # structlog 자체 logger와 stdlib logger 모두 동일한 renderer로 통일하기 위해
    # LoggerFactory (stdlib bridge)를 사용하고 wrap_for_formatter로 dict를 넘긴다.
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

    # stdlib logger와 structlog 모두 동일한 ProcessorFormatter로 처리.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
