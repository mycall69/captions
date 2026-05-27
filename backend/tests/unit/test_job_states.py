"""T021 단위 테스트: JobStatus 열거형 및 상태 전이 머신.

data-model.md §상태 머신의 모든 허용·거부 전이를 파라미터화 테스트로 검증한다.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import IllegalStateTransitionError
from app.domain.jobs.states import (
    TERMINAL_STATUSES,
    JobStatus,
    can_transition,
    ensure_transition,
)

# ── 허용 전이 목록 (data-model.md 전이 규칙) ─────────────────────────────────

LEGAL_TRANSITIONS = [
    (JobStatus.pending, JobStatus.downloading),
    (JobStatus.pending, JobStatus.failed),
    (JobStatus.downloading, JobStatus.subtitle_processing),
    (JobStatus.downloading, JobStatus.failed),
    (JobStatus.subtitle_processing, JobStatus.translating),
    (JobStatus.subtitle_processing, JobStatus.failed),
    (JobStatus.translating, JobStatus.rendering),
    (JobStatus.translating, JobStatus.failed),
    (JobStatus.rendering, JobStatus.completed),
    (JobStatus.rendering, JobStatus.failed),
]

# ── 거부 전이 목록 (허용 목록에 없는 전이) ───────────────────────────────────

ILLEGAL_TRANSITIONS = [
    # 단계 건너뜀
    (JobStatus.pending, JobStatus.translating),
    (JobStatus.pending, JobStatus.rendering),
    (JobStatus.pending, JobStatus.completed),
    (JobStatus.downloading, JobStatus.translating),
    (JobStatus.downloading, JobStatus.completed),
    # 역방향
    (JobStatus.subtitle_processing, JobStatus.downloading),
    (JobStatus.translating, JobStatus.subtitle_processing),
    (JobStatus.rendering, JobStatus.translating),
    # 종결 상태에서의 모든 전이
    (JobStatus.completed, JobStatus.pending),
    (JobStatus.completed, JobStatus.downloading),
    (JobStatus.completed, JobStatus.failed),
    (JobStatus.failed, JobStatus.pending),
    (JobStatus.failed, JobStatus.downloading),
    (JobStatus.failed, JobStatus.completed),
    # 동일 상태 전이
    (JobStatus.pending, JobStatus.pending),
    (JobStatus.downloading, JobStatus.downloading),
    # 종결 상태에서 중간 상태로의 전이 (terminal outgoing)
    (JobStatus.completed, JobStatus.subtitle_processing),
    (JobStatus.completed, JobStatus.translating),
    (JobStatus.completed, JobStatus.rendering),
    (JobStatus.failed, JobStatus.subtitle_processing),
    (JobStatus.failed, JobStatus.translating),
    (JobStatus.failed, JobStatus.rendering),
    # 중간 상태 자기 전이 (self-transitions)
    (JobStatus.subtitle_processing, JobStatus.subtitle_processing),
    (JobStatus.translating, JobStatus.translating),
    (JobStatus.rendering, JobStatus.rendering),
    (JobStatus.completed, JobStatus.completed),
    (JobStatus.failed, JobStatus.failed),
]


class TestJobStatusEnum:
    """JobStatus 열거형 기본 검증."""

    def test_string_values(self) -> None:
        """JobStatus가 str의 서브클래스여야 한다 (직렬화 호환)."""
        assert JobStatus.pending == "pending"
        assert JobStatus.downloading == "downloading"
        assert JobStatus.subtitle_processing == "subtitle_processing"
        assert JobStatus.translating == "translating"
        assert JobStatus.rendering == "rendering"
        assert JobStatus.completed == "completed"
        assert JobStatus.failed == "failed"

    def test_terminal_statuses(self) -> None:
        """종결 상태는 completed와 failed만 포함해야 한다."""
        assert JobStatus.completed in TERMINAL_STATUSES
        assert JobStatus.failed in TERMINAL_STATUSES
        assert len(TERMINAL_STATUSES) == 2

    def test_non_terminal_statuses_not_in_terminal(self) -> None:
        """진행 중 상태는 종결 상태 집합에 포함되지 않아야 한다."""
        non_terminal = {
            JobStatus.pending,
            JobStatus.downloading,
            JobStatus.subtitle_processing,
            JobStatus.translating,
            JobStatus.rendering,
        }
        assert non_terminal.isdisjoint(TERMINAL_STATUSES)


class TestCanTransition:
    """can_transition 순수 함수 검증."""

    @pytest.mark.parametrize("current,target", LEGAL_TRANSITIONS)
    def test_legal_transitions_return_true(
        self, current: JobStatus, target: JobStatus
    ) -> None:
        """허용된 전이는 True를 반환해야 한다."""
        assert can_transition(current, target) is True

    @pytest.mark.parametrize("current,target", ILLEGAL_TRANSITIONS)
    def test_illegal_transitions_return_false(
        self, current: JobStatus, target: JobStatus
    ) -> None:
        """허용되지 않는 전이는 False를 반환해야 한다."""
        assert can_transition(current, target) is False

    def test_is_pure_no_side_effects(self) -> None:
        """can_transition은 순수 함수 — 동일 입력에 동일 출력."""
        result1 = can_transition(JobStatus.pending, JobStatus.downloading)
        result2 = can_transition(JobStatus.pending, JobStatus.downloading)
        assert result1 == result2 == True  # noqa: E712

        result3 = can_transition(JobStatus.completed, JobStatus.failed)
        result4 = can_transition(JobStatus.completed, JobStatus.failed)
        assert result3 == result4 == False  # noqa: E712


class TestEnsureTransition:
    """ensure_transition 예외 발생 검증."""

    @pytest.mark.parametrize("current,target", LEGAL_TRANSITIONS)
    def test_legal_transitions_do_not_raise(
        self, current: JobStatus, target: JobStatus
    ) -> None:
        """허용된 전이는 예외를 발생시키지 않아야 한다."""
        ensure_transition(current, target)  # 예외 없이 통과

    @pytest.mark.parametrize("current,target", ILLEGAL_TRANSITIONS)
    def test_illegal_transitions_raise_error(
        self, current: JobStatus, target: JobStatus
    ) -> None:
        """허용되지 않는 전이는 IllegalStateTransitionError를 발생시켜야 한다."""
        with pytest.raises(IllegalStateTransitionError) as exc_info:
            ensure_transition(current, target)

        err = exc_info.value
        assert err.details["current"] == current.value
        assert err.details["target"] == target.value

    def test_error_message_contains_state_names(self) -> None:
        """에러 메시지에 현재/목표 상태 이름이 포함되어야 한다."""
        with pytest.raises(IllegalStateTransitionError) as exc_info:
            ensure_transition(JobStatus.completed, JobStatus.pending)

        assert "completed" in str(exc_info.value)
        assert "pending" in str(exc_info.value)
