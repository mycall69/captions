"""T057: 이중 자막(Dual Subtitle) 생성기.

원문(source)과 번역문(translated) 두 SubtitleCue 목록을 받아
큐별 두 줄(원문+번역문) 형태의 SRT 또는 VTT 문자열을 반환한다.

FR-017: source-first / target-first 순서 옵션 지원
FR-018: SRT(,) / VTT(.) 타임스탬프 형식 구분
FR-019: 큐당 두 줄 본문
"""

from __future__ import annotations

from typing import Literal

from app.domain.subtitles.models import SubtitleCue


def _format_srt_time(ms: int) -> str:
    """밀리초를 SRT 타임스탬프 형식(HH:MM:SS,mmm)으로 변환한다."""
    total_s, millis = divmod(ms, 1000)
    total_m, secs = divmod(total_s, 60)
    hours, mins = divmod(total_m, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def _format_vtt_time(ms: int) -> str:
    """밀리초를 VTT 타임스탬프 형식(HH:MM:SS.mmm)으로 변환한다."""
    total_s, millis = divmod(ms, 1000)
    total_m, secs = divmod(total_s, 60)
    hours, mins = divmod(total_m, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}.{millis:03d}"


def _build_lines(
    src_text: str,
    tgt_text: str,
    order: Literal["source-first", "target-first"],
) -> str:
    """순서 옵션에 따라 두 줄 본문을 구성한다."""
    if order == "source-first":
        return f"{src_text}\n{tgt_text}"
    else:
        return f"{tgt_text}\n{src_text}"


def generate_dual_srt(
    source: list[SubtitleCue],
    translated: list[SubtitleCue],
    *,
    order: Literal["source-first", "target-first"] = "source-first",
) -> str:
    """두 큐 목록을 병합하여 이중 자막 SRT 문자열을 반환한다.

    Args:
        source: 원문 큐 목록 (SubtitleCue).
        translated: 번역 큐 목록. source와 길이가 같아야 한다.
        order: 'source-first'이면 원문이 위, 'target-first'이면 번역문이 위.

    Returns:
        SRT 형식 문자열. 빈 입력이면 빈 문자열 반환.

    Raises:
        ValueError: source와 translated의 길이가 다른 경우.
    """
    if len(source) != len(translated):
        raise ValueError(
            f"source({len(source)})와 translated({len(translated)}) 큐 수가 다르다."
        )
    if not source:
        return ""

    blocks: list[str] = []
    for i, (src, tgt) in enumerate(zip(source, translated, strict=True), start=1):
        ts_line = f"{_format_srt_time(src.start_ms)} --> {_format_srt_time(src.end_ms)}"
        body = _build_lines(src.text, tgt.text, order)
        blocks.append(f"{i}\n{ts_line}\n{body}")

    return "\n\n".join(blocks) + "\n"


def generate_dual_vtt(
    source: list[SubtitleCue],
    translated: list[SubtitleCue],
    *,
    order: Literal["source-first", "target-first"] = "source-first",
) -> str:
    """두 큐 목록을 병합하여 이중 자막 VTT 문자열을 반환한다.

    Args:
        source: 원문 큐 목록 (SubtitleCue).
        translated: 번역 큐 목록. source와 길이가 같아야 한다.
        order: 'source-first'이면 원문이 위, 'target-first'이면 번역문이 위.

    Returns:
        VTT 형식 문자열. 빈 입력이면 'WEBVTT\\n\\n' 반환.

    Raises:
        ValueError: source와 translated의 길이가 다른 경우.
    """
    if len(source) != len(translated):
        raise ValueError(
            f"source({len(source)})와 translated({len(translated)}) 큐 수가 다르다."
        )
    if not source:
        return "WEBVTT\n\n"

    blocks: list[str] = ["WEBVTT"]
    for src, tgt in zip(source, translated, strict=True):
        ts_line = f"{_format_vtt_time(src.start_ms)} --> {_format_vtt_time(src.end_ms)}"
        body = _build_lines(src.text, tgt.text, order)
        blocks.append(f"{ts_line}\n{body}")

    return "\n\n".join(blocks) + "\n"
