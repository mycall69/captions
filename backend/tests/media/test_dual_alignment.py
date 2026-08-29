"""T051: dual subtitle 시간 정렬 검증 (SC-004 ±200ms).

검증 항목:
- sample.ja.srt + sample.ko.srt 두 트랙을 dual로 병합
- 각 병합된 cue에서 |source.start_ms - translated.start_ms| <= 200ms
- |source.end_ms - translated.end_ms| <= 200ms
- MVP 기준: 번역은 타임스탬프를 그대로 보존(FR-013)하므로 실제 오차는 ≤5ms

SC-004: dual subtitle의 시간축 정렬은 원문 자막의 cue 시점 대비 ±200ms 이내로 일치한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip(
    "app.domain.subtitles.normalize",
    reason="awaiting Phase 3b implementation — app.domain.subtitles.normalize",
)
pytest.importorskip(
    "app.domain.subtitles.dual_generator",
    reason="awaiting Phase 3b implementation — app.domain.subtitles.dual_generator",
)

from app.domain.subtitles.dual_generator import (
    generate_dual_srt,  # noqa: E402  # type: ignore[reportMissingImports]
)
from app.domain.subtitles.normalize import (
    normalize_srt,  # noqa: E402  # type: ignore[reportMissingImports]
)
from app.domain.translation.provider import ChunkCue  # noqa: E402

pytestmark = pytest.mark.media

FIXTURES = Path(__file__).parent.parent / "fixtures" / "subtitles"

_MAX_ALIGN_DELTA_MS = 200  # SC-004 허용 오차


@pytest.fixture
def ja_cues() -> list[ChunkCue]:
    """sample.ja.srt에서 정규화된 cue 목록을 반환한다."""
    return normalize_srt((FIXTURES / "sample.ja.srt").read_text(encoding="utf-8"))


@pytest.fixture
def ko_cues() -> list[ChunkCue]:
    """sample.ko.srt에서 정규화된 cue 목록을 반환한다."""
    return normalize_srt((FIXTURES / "sample.ko.srt").read_text(encoding="utf-8"))


class TestDualAlignmentSC004:
    """SC-004: dual subtitle 시간 정렬 ±200ms 검증."""

    def test_source_and_translated_same_cue_count(
        self, ja_cues: list[ChunkCue], ko_cues: list[ChunkCue]
    ) -> None:
        """source와 translated 트랙의 cue 수가 동일해야 한다."""
        assert len(ja_cues) == len(ko_cues), (
            f"cue 수 불일치: ja={len(ja_cues)}, ko={len(ko_cues)}"
        )

    def test_start_ms_alignment_within_200ms(
        self, ja_cues: list[ChunkCue], ko_cues: list[ChunkCue]
    ) -> None:
        """각 cue의 start_ms 차이가 200ms 이내이어야 한다 (SC-004)."""
        for i, (src, tgt) in enumerate(zip(ja_cues, ko_cues, strict=True)):
            delta = abs(src.start_ms - tgt.start_ms)
            assert delta <= _MAX_ALIGN_DELTA_MS, (
                f"cue {i+1} start_ms 정렬 오류: "
                f"|{src.start_ms} - {tgt.start_ms}| = {delta}ms > {_MAX_ALIGN_DELTA_MS}ms"
            )

    def test_end_ms_alignment_within_200ms(
        self, ja_cues: list[ChunkCue], ko_cues: list[ChunkCue]
    ) -> None:
        """각 cue의 end_ms 차이가 200ms 이내이어야 한다 (SC-004)."""
        for i, (src, tgt) in enumerate(zip(ja_cues, ko_cues, strict=True)):
            delta = abs(src.end_ms - tgt.end_ms)
            assert delta <= _MAX_ALIGN_DELTA_MS, (
                f"cue {i+1} end_ms 정렬 오류: "
                f"|{src.end_ms} - {tgt.end_ms}| = {delta}ms > {_MAX_ALIGN_DELTA_MS}ms"
            )

    def test_fixture_timestamps_identical(
        self, ja_cues: list[ChunkCue], ko_cues: list[ChunkCue]
    ) -> None:
        """fixture 파일은 동일한 타임스탬프를 가지므로 실제 오차가 0ms이어야 한다.

        번역 시 타임스탬프를 보존(FR-013)하면 MVP에서 delta == 0.
        """
        for i, (src, tgt) in enumerate(zip(ja_cues, ko_cues, strict=True)):
            assert src.start_ms == tgt.start_ms, (
                f"cue {i+1} start_ms 불일치: {src.start_ms} != {tgt.start_ms}"
            )
            assert src.end_ms == tgt.end_ms, (
                f"cue {i+1} end_ms 불일치: {src.end_ms} != {tgt.end_ms}"
            )

    def test_dual_generator_does_not_break_alignment(
        self, ja_cues: list[ChunkCue], ko_cues: list[ChunkCue]
    ) -> None:
        """dual SRT 생성 후 파싱해도 타임스탬프가 SC-004를 만족해야 한다.

        generate_dual_srt → 결과를 파싱 → 각 cue 타임스탬프 검증.
        """
        dual_srt = generate_dual_srt(ja_cues, ko_cues, order="source-first")
        assert dual_srt, "dual SRT 출력이 비어있음"

        # dual SRT를 파싱하여 타임스탬프 추출
        import re
        ts_pattern = re.compile(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s-->\s(\d{2}:\d{2}:\d{2},\d{3})"
        )

        def srt_to_ms(ts: str) -> int:
            h, m, s_ms = ts.split(":")
            s, ms = s_ms.split(",")
            return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1000 + int(ms)

        dual_ts = [(srt_to_ms(m.group(1)), srt_to_ms(m.group(2))) for m in ts_pattern.finditer(dual_srt)]

        assert len(dual_ts) == len(ja_cues), (
            f"파싱된 cue 수 불일치: {len(dual_ts)} != {len(ja_cues)}"
        )

        for i, ((d_start, d_end), src) in enumerate(zip(dual_ts, ja_cues, strict=True)):
            start_delta = abs(d_start - src.start_ms)
            end_delta = abs(d_end - src.end_ms)
            assert start_delta <= _MAX_ALIGN_DELTA_MS, (
                f"cue {i+1} dual start_ms 정렬 오류: delta={start_delta}ms"
            )
            assert end_delta <= _MAX_ALIGN_DELTA_MS, (
                f"cue {i+1} dual end_ms 정렬 오류: delta={end_delta}ms"
            )
