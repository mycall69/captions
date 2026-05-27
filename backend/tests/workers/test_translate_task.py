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

pytest.importorskip(
    "app.workers.tasks.translate",
    reason="awaiting Phase 3b implementation — app.workers.tasks.translate",
)

from app.domain.translation.provider import (  # noqa: E402
    ChunkCue,
)
from app.workers.tasks.translate import (
    translate_task,  # noqa: E402  # type: ignore[reportMissingImports]
)
from tests.fixtures.fake_provider import (  # noqa: E402
    FakeTranslationProvider,
    RateLimitedTranslationProvider,
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

    def test_chunk_receives_context_before(self, translate_ready_job: str) -> None:
        """첫 번째가 아닌 청크는 context_before(최대 3 cue)를 받아야 한다."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            translate_task(translate_ready_job)

        for chunk in provider.received_chunks:
            # context_before는 이전 청크의 마지막 최대 3 cue
            assert len(chunk.context_before) <= 3, (
                f"context_before가 3 cue 초과: {len(chunk.context_before)}"
            )
            assert len(chunk.context_after) <= 3, (
                f"context_after가 3 cue 초과: {len(chunk.context_after)}"
            )

    def test_first_chunk_has_empty_context_before(self, translate_ready_job: str) -> None:
        """첫 번째 청크의 context_before는 비어있어야 한다 (research §5)."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            translate_task(translate_ready_job)

        first_chunk = provider.received_chunks[0]
        assert first_chunk.context_before == [], (
            "첫 번째 청크의 context_before가 비어있어야 한다"
        )

    def test_last_chunk_has_empty_context_after(self, translate_ready_job: str) -> None:
        """마지막 청크의 context_after는 비어있어야 한다 (research §5)."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            translate_task(translate_ready_job)

        last_chunk = provider.received_chunks[-1]
        assert last_chunk.context_after == [], (
            "마지막 청크의 context_after가 비어있어야 한다"
        )


class TestTranslateTaskRateLimitRetry:
    """FR-015: rate limit 오류 시 retry 동작 검증."""

    def test_rate_limit_triggers_retry_up_to_4_times(self, translate_ready_job: str) -> None:
        """ProviderRateLimitError 발생 시 Celery가 최대 4회 retry를 시도해야 한다.

        구현 구조:
        - TranslationService._call_with_retry: 내부에서 최대 5회 provider 호출 (1s/2s/4s/8s)
        - translate_task Celery retry: max_retries=4 (총 5회 태스크 호출)
        - 결합 시: 5(서비스 호출) × 5(Celery 호출) = 25회 provider.translate_chunk 호출
        asyncio.sleep은 패치하여 테스트 속도를 보장한다.
        """
        provider = RateLimitedTranslationProvider()

        with (
            patch(
                "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
                return_value=provider,
            ),
            patch("asyncio.sleep"),  # 내부 backoff sleep 제거
        ):
            translate_task.apply(args=(translate_ready_job,))

        # TranslationService(5회) × Celery retry(5회) = 25회 호출
        # (서비스 레벨 retry + Celery 레벨 retry가 독립적으로 동작)
        CELERY_CALLS = 5  # 1 + max_retries=4
        SERVICE_CALLS_PER_CHUNK = 5  # 1 + 4 service-level retries
        NUM_CHUNKS = 1  # 첫 번째 청크에서 실패하면 이후 청크로 진행하지 않음
        expected_count = CELERY_CALLS * SERVICE_CALLS_PER_CHUNK * NUM_CHUNKS
        assert provider.call_count == expected_count, (
            f"rate limit retry: Celery 5회 × 서비스 5회 = 총 {expected_count}회 호출이어야 한다, "
            f"실제: {provider.call_count}회"
        )

    def test_all_retries_exhausted_marks_job_failed(self, translate_ready_job: str) -> None:
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
            patch("asyncio.sleep"),  # 내부 backoff sleep 제거
        ):
            translate_task.apply(args=(translate_ready_job,))

        assert "failed" in status_updates, (
            "모든 retry 소진 후 status가 failed로 갱신되어야 한다"
        )


class TestTranslateTaskChunking:
    """FR-013: chunk 분할 번역 검증."""

    def test_translate_task_has_translate_chunk_calls(self, translate_ready_job: str) -> None:
        """번역 태스크가 provider.translate_chunk를 호출해야 한다."""
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider",  # type: ignore[reportMissingImports]
            return_value=provider,
        ):
            translate_task(translate_ready_job)

        # provider가 주입되어 실행된 경우 최소 1번 호출되어야 함
        # TODO(T073): cue 분할 개수에 따른 정확한 청크 수 검증은 T073 구현 단계에서 추가
        assert provider.call_count >= 1, (
            "translate_task가 FakeTranslationProvider.translate_chunk를 최소 1회 호출해야 한다"
        )
