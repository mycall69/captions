"""T026: Celery 앱 설정 — 브로커, 결과 백엔드, 재시도 기본값 구성.

research §1: Redis를 브로커 + 결과 백엔드로 사용.
research §4: Celery chain(download → extract_subtitles → translate → render) 파이프라인.
include 목록은 Phase 3g 전까지 비워두어 미존재 모듈 import 오류를 방지한다.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings


def make_celery() -> Celery:
    """설정에서 브로커/백엔드 URL을 읽어 Celery 인스턴스를 구성하고 반환한다.

    task_acks_late=True + worker_prefetch_multiplier=1 조합으로
    단계별 멱등성을 보장하고 메시지 손실 위험을 낮춘다 (research §4).
    """
    settings = get_settings()

    app = Celery(
        "captions",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        # Phase 3g에서 tasks 모듈 추가 후 include 목록 채움
        include=[],
    )

    app.conf.update(
        # 직렬화
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],

        # 시간대
        timezone="UTC",
        enable_utc=True,

        # 실행 추적 — started 상태 기록
        task_track_started=True,

        # 안정성: worker가 task를 완료한 뒤 ACK 전송
        task_acks_late=True,

        # 동시 처리: prefetch 1로 과부하 방지
        worker_prefetch_multiplier=1,

        # 재시도 기본값 (task 데코레이터에서 override 가능)
        task_default_retry_delay=2,       # 초
        task_default_max_retries=3,

        # 시작 시 브로커 연결 재시도 허용
        broker_connection_retry_on_startup=True,
    )

    return app


# 모듈 레벨 싱글턴 — `celery -A app.workers.celery_app worker` 진입점
celery_app = make_celery()
