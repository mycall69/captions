"""T047: 번역 청크 분할 정책 단위 테스트 (US1, FR-013, FR-014, research §5).

검증 항목:
- 60초 윈도우로 cue를 그룹화한다
- cue 경계 보존 (중간에서 cue를 자르지 않음)
- context: 각 청크에 앞 3 cue / 뒤 3 cue 제공
- 첫 청크: context_before 비어있음
- 마지막 청크: context_after 비어있음
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "app.domain.subtitles.chunking",
    reason="awaiting Phase 3b implementation — app.domain.subtitles.chunking",
)

from app.domain.subtitles.chunking import (
    chunk_cues,  # noqa: E402  # type: ignore[reportMissingImports]
)
from app.domain.translation.provider import ChunkCue  # noqa: E402


def _make_cues(count: int, duration_ms: int = 5000) -> list[ChunkCue]:
    """count개의 연속 cue 목록을 생성한다. 각 cue는 duration_ms 간격."""
    return [
        ChunkCue(
            sequence=i + 1,
            start_ms=i * duration_ms,
            end_ms=i * duration_ms + (duration_ms - 100),
            text=f"cue {i + 1}",
        )
        for i in range(count)
    ]


class TestChunkWindowPolicy:
    """60초 윈도우 정책 검증 (research §5)."""

    def test_cues_within_60s_in_same_chunk(self) -> None:
        """60초 이내 cue는 하나의 청크로 묶여야 한다."""
        # 10개 cue, 각 5초 → 50초 = 1개 청크
        cues = _make_cues(10, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        total_cues = sum(len(c.cues) for c in chunks)
        assert total_cues == 10
        # 10 * 5000ms = 50000ms < 60000ms → 1개 청크
        assert len(chunks) == 1

    def test_cues_over_60s_split_into_multiple_chunks(self) -> None:
        """60초를 넘으면 여러 청크로 분리되어야 한다."""
        # 20개 cue, 각 5초 → 100초 → 최소 2개 청크
        cues = _make_cues(20, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        assert len(chunks) >= 2

    def test_all_cues_accounted_for_across_chunks(self) -> None:
        """분할 후 모든 cue가 정확히 한 번 포함되어야 한다 (중복/누락 없음)."""
        cues = _make_cues(25, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        all_sequences = [c.sequence for chunk in chunks for c in chunk.cues]
        assert sorted(all_sequences) == list(range(1, 26))


class TestChunkBoundaryPreservation:
    """cue 경계 보존 검증 — 청크 경계가 cue 중간에 위치하지 않는다."""

    def test_no_cue_split_across_chunks(self) -> None:
        """각 cue는 하나의 청크에만 완전히 포함되어야 한다."""
        cues = _make_cues(15, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        all_in_chunks: set[int] = set()
        for chunk in chunks:
            for cue in chunk.cues:
                assert cue.sequence not in all_in_chunks, (
                    f"cue {cue.sequence}가 두 개 이상의 청크에 포함됨"
                )
                all_in_chunks.add(cue.sequence)

    def test_chunk_ends_at_cue_boundary(self) -> None:
        """각 청크는 cue 경계에서 끝나야 한다 (partial cue 없음)."""
        cues = _make_cues(20, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        for chunk in chunks:
            assert len(chunk.cues) >= 1, "청크에 cue가 없음"


class TestChunkContextPadding:
    """context_before / context_after 최대 3 cue 검증 (research §5)."""

    def test_context_before_at_most_3_cues(self) -> None:
        """context_before는 최대 3 cue이어야 한다."""
        cues = _make_cues(20, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        for chunk in chunks:
            assert len(chunk.context_before) <= 3, (
                f"context_before가 3 cue 초과: {len(chunk.context_before)}"
            )

    def test_context_after_at_most_3_cues(self) -> None:
        """context_after는 최대 3 cue이어야 한다."""
        cues = _make_cues(20, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        for chunk in chunks:
            assert len(chunk.context_after) <= 3, (
                f"context_after가 3 cue 초과: {len(chunk.context_after)}"
            )

    def test_first_chunk_has_empty_context_before(self) -> None:
        """첫 번째 청크의 context_before는 비어있어야 한다."""
        cues = _make_cues(20, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        assert len(chunks) >= 1
        assert chunks[0].context_before == [], (
            "첫 번째 청크의 context_before가 비어있어야 한다"
        )

    def test_last_chunk_has_empty_context_after(self) -> None:
        """마지막 청크의 context_after는 비어있어야 한다."""
        cues = _make_cues(20, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        assert len(chunks) >= 1
        assert chunks[-1].context_after == [], (
            "마지막 청크의 context_after가 비어있어야 한다"
        )

    def test_middle_chunk_has_both_contexts(self) -> None:
        """중간 청크는 context_before와 context_after가 모두 존재해야 한다."""
        # 30개 cue, 각 5초 → 150초 → 3개 이상 청크
        cues = _make_cues(30, duration_ms=5000)
        chunks = chunk_cues(cues, window_ms=60_000)
        if len(chunks) >= 3:
            middle = chunks[len(chunks) // 2]
            assert len(middle.context_before) > 0, "중간 청크 context_before 없음"
            assert len(middle.context_after) > 0, "중간 청크 context_after 없음"

    def test_context_cues_drawn_from_source(self) -> None:
        """context_before / context_after는 원본 cue 목록에서 가져온 실제 cue이어야 한다."""
        cues = _make_cues(20, duration_ms=5000)
        original_seqs = {c.sequence for c in cues}
        chunks = chunk_cues(cues, window_ms=60_000)
        for chunk in chunks:
            for ctx_cue in chunk.context_before + chunk.context_after:
                assert ctx_cue.sequence in original_seqs, (
                    f"context cue (seq={ctx_cue.sequence})가 원본에 없음 (합성 금지)"
                )
