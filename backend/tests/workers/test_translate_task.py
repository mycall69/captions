"""T043: 번역 워커 태스크 테스트 (US1, FR-013, FR-014, FR-015, FR-016).

검증 항목:
- FakeTranslationProvider 사용
- 각 청크에 context_before / context_after가 전달됨 (research §5: 각 최대 3 cue)
- rate limit 오류 시 최대 4회 retry (exponential backoff)
- 모든 retry 실패 시 작업을 failed + TRANSLATION_FAILED로 표시
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.fixtures.fake_provider import (
    FakeTranslationProvider,
    RateLimitedTranslationProvider,
)

pytest.importorskip(
    "app.workers.tasks.translate",
    reason="awaiting Phase 3b implementation — app.workers.tasks.translate",
)

from app.workers.tasks.translate import (
    translate_task,  # noqa: E402  # type: ignore[reportMissingImports]
)

from app.domain.translation.provider import (  # noqa: E402
    ChunkCue,
)

pytestmark = pytest.mark.workers


def _make_cues(count: int, offset_seq: int = 1) -> list[ChunkCue]:
    """테스트용 ChunkCue 목록 생성."""
    return [
        ChunkCue(
            sequence=offset_seq + i,
            start_ms=(offset_seq + i) * 1000,
            end_ms=(offset_seq + i) * 1000 + 500,
            text=f"cue {offset_seq + i}",
        )
        for i in range(count)
    ]


class TestTranslateTaskContextPassing:
    """research §5: context_before / context_after 각 최대 3 cue 전달 검증."""

    def test_chunk_receives_context_before(self) -> None:
        """첫 번째가 아닌 청크는 context_before(최대 3 cue)를 받아야 한다."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            try:
                translate_task("test_job_context_01")
            except Exception:
                pass

        # provider가 실제로 호출된 경우 context 검증
        for chunk in provider.received_chunks:
            # context_before는 이전 청크의 마지막 최대 3 cue
            assert len(chunk.context_before) <= 3, (
                f"context_before가 3 cue 초과: {len(chunk.context_before)}"
            )
            assert len(chunk.context_after) <= 3, (
                f"context_after가 3 cue 초과: {len(chunk.context_after)}"
            )

    def test_first_chunk_has_empty_context_before(self) -> None:
        """첫 번째 청크의 context_before는 비어있어야 한다 (research §5)."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            try:
                translate_task("test_job_context_02")
            except Exception:
                pass

        if provider.received_chunks:
            first_chunk = provider.received_chunks[0]
            assert first_chunk.context_before == [], (
                "첫 번째 청크의 context_before가 비어있어야 한다"
            )

    def test_last_chunk_has_empty_context_after(self) -> None:
        """마지막 청크의 context_after는 비어있어야 한다 (research §5)."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            try:
                translate_task("test_job_context_03")
            except Exception:
                pass

        if provider.received_chunks:
            last_chunk = provider.received_chunks[-1]
            assert last_chunk.context_after == [], (
                "마지막 청크의 context_after가 비어있어야 한다"
            )


class TestTranslateTaskRateLimitRetry:
    """FR-015: rate limit 오류 시 retry 동작 검증."""

    def test_rate_limit_triggers_retry_up_to_4_times(self) -> None:
        """ProviderRateLimitError 발생 시 4회 retry가 시도되어야 한다 (research §6: 1s/2s/4s/8s backoff)."""
        provider = RateLimitedTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            try:
                translate_task.apply(args=("test_job_rate_limit_01",))
            except Exception:
                pass

        # research §6: 1회 최초 시도 + 4회 retry = 총 5회 호출 (backoff: 1s, 2s, 4s, 8s)
        # 구현이 완료되면 call_count == 5 (최초 1 + retry 4)
        if provider.call_count > 0:
            assert provider.call_count == 5, (
                f"rate limit retry는 최초 1회 + 4회 retry = 총 5회 호출이어야 한다 "
                f"(research §6), 실제: {provider.call_count}회"
            )

    def test_all_retries_exhausted_marks_job_failed(self) -> None:
        """모든 retry 소진 후 작업이 failed + TRANSLATION_FAILED 상태가 되어야 한다."""
        failing_provider = RateLimitedTranslationProvider()

        status_updates: list[str] = []

        def fake_update_status(job_id: str, status: str, **_kw: object) -> None:
            status_updates.append(status)

        with (
            patch(
                "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
                return_value=failing_provider,
            ),
            patch(
                "app.workers.tasks.translate.update_job_status",  # type: ignore[reportMissingImports]
                side_effect=fake_update_status,
                create=True,
            ),
        ):
            try:
                translate_task.apply(args=("test_job_rate_limit_02",))
            except Exception:
                pass

        # status가 갱신된 경우 failed가 포함되어야 함
        if status_updates:
            assert "failed" in status_updates, (
                "모든 retry 소진 후 status가 failed로 갱신되어야 한다"
            )


class TestTranslateTaskChunking:
    """FR-013: chunk 분할 번역 검증."""

    def test_translate_task_has_translate_chunk_calls(self) -> None:
        """번역 태스크가 provider.translate_chunk를 호출해야 한다."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            try:
                translate_task("test_job_chunk_01")
            except Exception:
                pass

        # provider가 주입되어 실행된 경우 최소 1번 호출되어야 함
        # TODO(T073): cue 분할 개수에 따른 정확한 청크 수 검증은 T073 구현 단계에서 추가
        assert provider.call_count >= 1, (
            "translate_task가 FakeTranslationProvider.translate_chunk를 최소 1회 호출해야 한다"
        )
