"""T021: JobStatus 열거형 및 상태 전이 머신.

data-model.md §상태 머신의 전이 행렬을 구현한다.
허용되지 않는 전이는 IllegalStateTransitionError를 발생시킨다.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.exceptions import IllegalStateTransitionError


class JobStatus(StrEnum):
    """비디오 작업 처리 단계를 나타내는 열거형."""

    pending = "pending"
    downloading = "downloading"
    subtitle_processing = "subtitle_processing"
    translating = "translating"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"


# 종결 상태 — 자동 재시작 없음 (data-model.md §상태 머신)
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({
    JobStatus.completed,
    JobStatus.failed,
})

# 허용 전이 테이블 (data-model.md 전이 규칙)
_ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.pending: frozenset({JobStatus.downloading, JobStatus.failed}),
    JobStatus.downloading: frozenset({JobStatus.subtitle_processing, JobStatus.failed}),
    JobStatus.subtitle_processing: frozenset({JobStatus.translating, JobStatus.failed}),
    JobStatus.translating: frozenset({JobStatus.rendering, JobStatus.failed}),
    JobStatus.rendering: frozenset({JobStatus.completed, JobStatus.failed}),
    JobStatus.completed: frozenset(),
    JobStatus.failed: frozenset(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """현재 상태에서 목표 상태로 전이 가능한지 여부를 반환한다.

    순수 함수 — 부수 효과 없음.
    """
    return target in _ALLOWED[current]


def ensure_transition(current: JobStatus, target: JobStatus) -> None:
    """전이가 허용되지 않으면 IllegalStateTransitionError를 발생시킨다.

    Args:
        current: 현재 작업 상태.
        target: 전이하려는 목표 상태.

    Raises:
        IllegalStateTransitionError: 허용되지 않는 전이인 경우.
    """
    if not can_transition(current, target):
        raise IllegalStateTransitionError(
            f"'{current.value}' → '{target.value}' 전이는 허용되지 않습니다.",
            details={"current": current.value, "target": target.value},
        )
