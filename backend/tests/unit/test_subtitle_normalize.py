"""T046: 자막 정규화(normalizer) 단위 테스트 (US1, FR-010).

검증 항목:
- SRT/VTT 파싱 → 동일 cue 수 + 동일 텍스트 (sample.ja.srt vs sample.ja.vtt)
- overlapping.srt: 겹치는 cue 정리 (cue[i].end_ms <= cue[i+1].start_ms)
- with_empty.srt: 빈 cue 제거 + 시퀀스 보존
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip(
    "app.domain.subtitles.normalize",
    reason="awaiting Phase 3b implementation — app.domain.subtitles.normalize",
)

from app.domain.subtitles.normalize import (  # noqa: E402  # type: ignore[reportMissingImports]
    normalize_srt,
    normalize_vtt,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "subtitles"


class TestParseSrtAndVtt:
    """SRT / VTT 파싱 결과가 동일해야 한다 (cue 수, 텍스트 일치)."""

    def test_ja_srt_parse_returns_5_cues(self) -> None:
        """sample.ja.srt 파싱 결과는 5개 cue이어야 한다."""
        cues = normalize_srt((FIXTURES / "sample.ja.srt").read_text(encoding="utf-8"))
        assert len(cues) == 5

    def test_ja_vtt_parse_returns_5_cues(self) -> None:
        """sample.ja.vtt 파싱 결과는 5개 cue이어야 한다."""
        cues = normalize_vtt((FIXTURES / "sample.ja.vtt").read_text(encoding="utf-8"))
        assert len(cues) == 5

    def test_ko_srt_parse_returns_5_cues(self) -> None:
        """sample.ko.srt 파싱 결과는 5개 cue이어야 한다."""
        cues = normalize_srt((FIXTURES / "sample.ko.srt").read_text(encoding="utf-8"))
        assert len(cues) == 5

    def test_ko_vtt_parse_returns_5_cues(self) -> None:
        """sample.ko.vtt 파싱 결과는 5개 cue이어야 한다."""
        path = FIXTURES / "sample.ko.vtt"
        if not path.exists():
            pytest.skip("sample.ko.vtt fixture 없음")
        cues = normalize_vtt(path.read_text(encoding="utf-8"))
        assert len(cues) == 5

    def test_ja_srt_and_vtt_same_text(self) -> None:
        """sample.ja.srt와 sample.ja.vtt의 텍스트가 동일해야 한다."""
        srt_cues = normalize_srt((FIXTURES / "sample.ja.srt").read_text(encoding="utf-8"))
        vtt_cues = normalize_vtt((FIXTURES / "sample.ja.vtt").read_text(encoding="utf-8"))
        assert len(srt_cues) == len(vtt_cues)
        for s, v in zip(srt_cues, vtt_cues, strict=True):
            assert s.text == v.text, f"텍스트 불일치: SRT={s.text!r} VTT={v.text!r}"

    def test_cue_timestamps_positive(self) -> None:
        """모든 cue의 start_ms >= 0, end_ms > start_ms이어야 한다."""
        cues = normalize_srt((FIXTURES / "sample.ja.srt").read_text(encoding="utf-8"))
        for cue in cues:
            assert cue.start_ms >= 0
            assert cue.end_ms > cue.start_ms

    def test_cues_sequential_sequence_numbers(self) -> None:
        """정규화 후 cue sequence는 1부터 연속이어야 한다."""
        cues = normalize_srt((FIXTURES / "sample.ja.srt").read_text(encoding="utf-8"))
        for idx, cue in enumerate(cues, start=1):
            assert cue.sequence == idx


class TestNormalizeOverlapping:
    """overlapping.srt: 겹치는 cue 정리 검증."""

    def test_overlapping_srt_has_no_overlap_after_normalize(self) -> None:
        """normalize 후 인접 cue 사이에 겹침이 없어야 한다 (cue[i].end_ms <= cue[i+1].start_ms)."""
        cues = normalize_srt((FIXTURES / "overlapping.srt").read_text(encoding="utf-8"))
        for i in range(len(cues) - 1):
            assert cues[i].end_ms <= cues[i + 1].start_ms, (
                f"cue {i+1}과 {i+2} 사이에 겹침 발생: "
                f"end_ms={cues[i].end_ms} > start_ms={cues[i+1].start_ms}"
            )

    def test_overlapping_srt_cue_count_preserved(self) -> None:
        """overlapping.srt의 cue 수는 정규화 후에도 유지되어야 한다 (clip만 하고 삭제하지 않음)."""
        cues = normalize_srt((FIXTURES / "overlapping.srt").read_text(encoding="utf-8"))
        # fixture에는 3개 cue — 클리핑 후 모두 유지
        assert len(cues) == 3


class TestNormalizeWithEmpty:
    """with_empty.srt: 빈 cue 제거 검증."""

    def test_empty_cue_removed(self) -> None:
        """빈 텍스트 cue가 제거되어야 한다."""
        cues = normalize_srt((FIXTURES / "with_empty.srt").read_text(encoding="utf-8"))
        for cue in cues:
            assert cue.text.strip() != "", f"빈 cue가 남아있음: {cue}"

    def test_non_empty_cues_preserved(self) -> None:
        """정상 cue는 삭제되지 않아야 한다."""
        cues = normalize_srt((FIXTURES / "with_empty.srt").read_text(encoding="utf-8"))
        # fixture에는 4개 중 1개 빈 cue → 3개 남아야 함
        assert len(cues) == 3

    def test_sequence_renumbered_after_empty_removal(self) -> None:
        """빈 cue 제거 후 sequence가 1부터 연속이어야 한다."""
        cues = normalize_srt((FIXTURES / "with_empty.srt").read_text(encoding="utf-8"))
        for idx, cue in enumerate(cues, start=1):
            assert cue.sequence == idx
