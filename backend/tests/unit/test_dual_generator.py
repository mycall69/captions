"""T048: dual subtitle 생성기 단위 테스트 (US1, FR-017, FR-018, FR-019, research §8).

검증 항목:
- 두 트랙(source + translated) → 단일 VTT/SRT 출력
- 각 cue 본문은 두 줄 (source-first: 원문\n번역문)
- target-first: 번역문\n원문 순서
- SRT 형식: 시퀀스 번호, 타임스탬프(,형식), 빈 줄 구분자
- VTT 형식: WEBVTT 헤더, 타임스탬프(.형식)
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "app.domain.subtitles.dual_generator",
    reason="awaiting Phase 3b implementation — app.domain.subtitles.dual_generator",
)

from app.domain.subtitles.dual_generator import (  # noqa: E402  # type: ignore[reportMissingImports]
    generate_dual_srt,
    generate_dual_vtt,
)

from app.domain.translation.provider import ChunkCue  # noqa: E402


def _make_source_cues() -> list[ChunkCue]:
    return [
        ChunkCue(sequence=1, start_ms=1000, end_ms=4000, text="こんにちは、世界。"),
        ChunkCue(sequence=2, start_ms=4500, end_ms=8000, text="今日はいい天気ですね。"),
        ChunkCue(sequence=3, start_ms=8500, end_ms=12000, text="公園に行きませんか？"),
    ]


def _make_translated_cues() -> list[ChunkCue]:
    return [
        ChunkCue(sequence=1, start_ms=1000, end_ms=4000, text="안녕하세요, 세계."),
        ChunkCue(sequence=2, start_ms=4500, end_ms=8000, text="오늘 날씨 좋네요."),
        ChunkCue(sequence=3, start_ms=8500, end_ms=12000, text="공원에 가지 않을래요?"),
    ]


class TestGenerateDualSrt:
    """SRT 형식 dual subtitle 생성 검증."""

    def test_srt_has_sequence_numbers(self) -> None:
        """SRT 출력에 각 cue의 시퀀스 번호가 포함되어야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="source-first")
        assert "1\n" in srt
        assert "2\n" in srt
        assert "3\n" in srt

    def test_srt_timestamp_uses_comma(self) -> None:
        """SRT 타임스탬프는 쉼표(,)를 밀리초 구분자로 사용해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="source-first")
        # SRT 표준: 00:00:01,000 --> 00:00:04,000
        assert ",000 -->" in srt

    def test_srt_source_first_order(self) -> None:
        """source-first: 원문이 번역문보다 앞에 위치해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="source-first")
        ja_pos = srt.find("こんにちは")
        ko_pos = srt.find("안녕하세요")
        assert ja_pos != -1 and ko_pos != -1
        assert ja_pos < ko_pos

    def test_srt_target_first_order(self) -> None:
        """target-first: 번역문이 원문보다 앞에 위치해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="target-first")
        ja_pos = srt.find("こんにちは")
        ko_pos = srt.find("안녕하세요")
        assert ja_pos != -1 and ko_pos != -1
        assert ko_pos < ja_pos

    def test_srt_two_lines_per_cue(self) -> None:
        """각 cue 블록에 본문이 두 줄이어야 한다 (FR-019)."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="source-first")
        # 빈 줄로 블록 분리 후 각 블록 검사
        blocks = [b.strip() for b in srt.strip().split("\n\n") if b.strip()]
        assert len(blocks) == 3
        for block in blocks:
            lines = block.splitlines()
            text_lines = lines[2:]  # 시퀀스 + 타임스탬프 이후
            assert len(text_lines) >= 2, f"cue 본문이 2줄 미만: {text_lines}"

    def test_srt_blocks_separated_by_blank_line(self) -> None:
        """SRT cue 블록은 빈 줄로 구분되어야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="source-first")
        blocks = [b for b in srt.split("\n\n") if b.strip()]
        assert len(blocks) == 3

    def test_srt_cue_count_matches_input(self) -> None:
        """출력 cue 수가 입력 cue 수와 동일해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        srt = generate_dual_srt(src, tgt, order="source-first")
        blocks = [b for b in srt.strip().split("\n\n") if b.strip()]
        assert len(blocks) == len(src)


class TestGenerateDualVtt:
    """VTT 형식 dual subtitle 생성 검증."""

    def test_vtt_starts_with_webvtt_header(self) -> None:
        """VTT 출력은 'WEBVTT'로 시작해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        vtt = generate_dual_vtt(src, tgt, order="source-first")
        assert vtt.startswith("WEBVTT")

    def test_vtt_timestamp_uses_dot(self) -> None:
        """VTT 타임스탬프는 점(.)을 밀리초 구분자로 사용해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        vtt = generate_dual_vtt(src, tgt, order="source-first")
        # VTT 표준: 00:00:01.000 --> 00:00:04.000
        assert ".000 -->" in vtt

    def test_vtt_source_first_order(self) -> None:
        """source-first: 원문이 번역문보다 앞에 위치해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        vtt = generate_dual_vtt(src, tgt, order="source-first")
        ja_pos = vtt.find("こんにちは")
        ko_pos = vtt.find("안녕하세요")
        assert ja_pos != -1 and ko_pos != -1
        assert ja_pos < ko_pos

    def test_vtt_target_first_order(self) -> None:
        """target-first: 번역문이 원문보다 앞에 위치해야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        vtt = generate_dual_vtt(src, tgt, order="target-first")
        ja_pos = vtt.find("こんにちは")
        ko_pos = vtt.find("안녕하세요")
        assert ja_pos != -1 and ko_pos != -1
        assert ko_pos < ja_pos

    def test_vtt_two_lines_per_cue(self) -> None:
        """각 cue 블록에 본문이 두 줄이어야 한다 (FR-019)."""
        src = _make_source_cues()
        tgt = _make_translated_cues()
        vtt = generate_dual_vtt(src, tgt, order="source-first")
        # WEBVTT 헤더 이후 블록만 추출
        body = vtt.split("WEBVTT", 1)[1]
        blocks = [b.strip() for b in body.strip().split("\n\n") if b.strip()]
        assert len(blocks) == 3
        for block in blocks:
            lines = block.splitlines()
            # 타임스탬프 줄 이후가 본문
            text_lines = [line for line in lines[1:] if line.strip()]
            assert len(text_lines) >= 2, f"VTT cue 본문이 2줄 미만: {text_lines}"


class TestDualGeneratorEdgeCases:
    """엣지 케이스 테스트."""

    def test_empty_cue_list_raises_or_returns_empty(self) -> None:
        """빈 cue 목록 입력 시 예외 없이 빈 문자열 또는 헤더만 반환해야 한다."""
        try:
            srt = generate_dual_srt([], [], order="source-first")
            assert isinstance(srt, str)
        except ValueError:
            pass  # ValueError도 허용

    def test_mismatched_cue_count_raises(self) -> None:
        """source와 translated cue 수 불일치 시 ValueError를 발생시켜야 한다."""
        src = _make_source_cues()
        tgt = _make_translated_cues()[:2]  # 2개만
        with pytest.raises((ValueError, AssertionError)):
            generate_dual_srt(src, tgt, order="source-first")
