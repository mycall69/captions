"""T075: Celery chain — download → extract_subtitles → translate → render.

research §4: Celery chain + link_error 에러 전파.
build_job_chain(job_id)로 파이프라인을 구성하고 .apply() 또는 .delay()로 실행한다.
"""

from __future__ import annotations

from celery import chain

from app.workers.celery_app import celery_app  # noqa: F401  # celery_app 초기화 보장
from app.workers.error_handler import mark_failed_on_error
from app.workers.tasks import download, extract_subtitles, render, translate


def build_job_chain(job_id: str) -> chain:
    """download → extract_subtitles → translate → render 순서의 Celery chain을 반환한다.

    모든 단계는 .si(job_id)로 고정 인자 시그니처를 사용하여
    이전 단계의 반환값이 다음 단계로 전달되지 않도록 한다.
    (멱등성: 각 단계는 job_id만으로 동작)

    link_error: 체인 내 임의 단계 실패 시 mark_failed_on_error가 호출된다.

    Celery on_error 주의사항 (Celery 5.x):
    - .on_error(callback.s(extra_arg)) 형식으로 추가 인자를 바인딩한다.
    - 콜백은 (request, exc, traceback, *extra_args) 시그니처로 호출된다.

    Returns:
        실행 준비가 된 Celery chain 객체.
    """
    return chain(
        download.download_task.si(job_id),
        extract_subtitles.extract_subtitles_task.si(job_id),
        translate.translate_task.si(job_id),
        render.render_task.si(job_id),
    ).on_error(mark_failed_on_error.s(job_id))
