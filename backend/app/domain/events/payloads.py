"""T098: SSE 이벤트 payload 빌더.

contracts/events.md 가 정의한 5종 이벤트(``job.state_changed``, ``job.progress``,
``job.completed``, ``job.failed``, ``job.info``) 의 JSON payload 를 만든다.

모든 빌더는 dict 를 반환하며 다음 공통 키를 포함한다.

- ``event_id``: 26자 Crockford Base32 ULID (events.md §공통 규칙)
- ``seq``: ``job_event`` 테이블 PK 와 동일한 단조 증가 정수
- ``job_id``: 26자 ULID
- ``event_type``: ``job.*`` 5종 중 하나
- ``published_at``: ISO 8601 UTC timestamp 문자열
- ``at``: ``published_at`` 과 동일 값 — events.md 의 명시적 필드명 보존

``message`` / ``error_message`` 등 사용자에게 노출되는 텍스트는 한국어로 작성한다 (헌법 V).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

# events.md §이벤트 타입 — 5종 식별자
EventType = Literal[
    "job.state_changed",
    "job.progress",
    "job.completed",
    "job.failed",
    "job.info",
]


def _now_iso() -> str:
    """현재 시각을 ISO 8601 UTC 문자열로 반환한다 (`Z` 표기)."""
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _base(
    *,
    job_id: str,
    seq: int,
    event_id: str,
    event_type: EventType,
    now: str | None = None,
) -> dict[str, Any]:
    """모든 이벤트가 공유하는 공통 필드를 만든다."""
    ts = now or _now_iso()
    return {
        "event_id": event_id,
        "seq": seq,
        "job_id": job_id,
        "event_type": event_type,
        "published_at": ts,
        "at": ts,
    }


def build_state_changed_event(
    *,
    job_id: str,
    seq: int,
    event_id: str,
    previous_status: str,
    new_status: str,
) -> dict[str, Any]:
    """``job.state_changed`` payload — 상태가 새 단계로 전이될 때 발행."""
    payload = _base(
        job_id=job_id,
        seq=seq,
        event_id=event_id,
        event_type="job.state_changed",
    )
    payload.update(
        {
            "previous_status": previous_status,
            "status": new_status,
            "stage": new_status,
        }
    )
    return payload


def build_progress_event(
    *,
    job_id: str,
    seq: int,
    event_id: str,
    status: str,
    progress: float,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``job.progress`` payload — 같은 단계 내 진행률 갱신.

    ``progress`` 는 0.0 ~ 1.0 사이의 float 이며 단계 시작 시 0.0, 종료 시 1.0.
    ``detail`` schema 는 events.md §`job.progress` — 모르는 키는 무시한다.
    """
    payload = _base(
        job_id=job_id,
        seq=seq,
        event_id=event_id,
        event_type="job.progress",
    )
    clamped = max(0.0, min(1.0, float(progress)))
    payload.update(
        {
            "status": status,
            "stage": status,
            "progress": clamped,
            "detail": detail or {},
        }
    )
    return payload


def build_completed_event(
    *,
    job_id: str,
    seq: int,
    event_id: str,
    assets: dict[str, str] | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """``job.completed`` payload — 성공적으로 종결됐을 때 발행.

    ``assets`` 는 ``video_mp4`` / ``dual_srt`` / ``dual_vtt`` URL 매핑이다 — 비어 있어도 된다.
    """
    ts = completed_at or _now_iso()
    payload = _base(
        job_id=job_id,
        seq=seq,
        event_id=event_id,
        event_type="job.completed",
        now=ts,
    )
    payload.update(
        {
            "status": "completed",
            "completed_at": ts,
            "assets": assets or {},
        }
    )
    return payload


def build_failed_event(
    *,
    job_id: str,
    seq: int,
    event_id: str,
    error_stage: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    """``job.failed`` payload — 처리 실패 종결.

    ``error_message`` 는 한국어로 작성한다 (헌법 V).
    """
    payload = _base(
        job_id=job_id,
        seq=seq,
        event_id=event_id,
        event_type="job.failed",
    )
    payload.update(
        {
            "status": "failed",
            "error_stage": error_stage,
            "error_code": error_code,
            "error_message": error_message,
        }
    )
    return payload


def build_info_event(
    *,
    job_id: str,
    seq: int,
    event_id: str,
    code: str,
    message: str,
) -> dict[str, Any]:
    """``job.info`` payload — 비차단성 알림 (자동 자막 fallback 등).

    ``message`` 는 한국어로 작성한다 (헌법 V).
    """
    payload = _base(
        job_id=job_id,
        seq=seq,
        event_id=event_id,
        event_type="job.info",
    )
    payload.update(
        {
            "code": code,
            "message": message,
        }
    )
    return payload


__all__ = [
    "EventType",
    "build_state_changed_event",
    "build_progress_event",
    "build_completed_event",
    "build_failed_event",
    "build_info_event",
]
