"""T056: SRT/VTT 자막 정규화 모듈.

pysrt (SRT)·webvtt-py (VTT) 파서를 감싸 SubtitleCue 목록을 반환한다.
정규화 단계:
  - 빈 텍스트 큐 제거 (text.strip() == "")
  - 겹치는 큐 클리핑: cue[i].end_ms > cue[i+1].start_ms 이면
    cue[i].end_ms = cue[i+1].start_ms 로 잘라낸다.
  - 클리핑 후 start_ms >= end_ms 가 되는 큐는 제거한다.
  - 시퀀스 번호를 1부터 재부여한다.
  - 텍스트 앞뒤 공백 제거 및 CRLF → LF 변환.
"""

from __future__ import annotations

import io
from pathlib import Path

import pysrt
import webvtt

from app.domain.subtitles.models import SubtitleCue


def _vtt_ts_to_ms(ts: str) -> int:
    """VTT 타임스탬프 문자열(HH:MM:SS.mmm)을 밀리초 정수로 변환한다."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s_ms = parts
    elif len(parts) == 2:
        h, m, s_ms = "0", parts[0], parts[1]
    else:
        raise ValueError(f"잘못된 VTT 타임스탬프 형식: {ts!r}")
    s, ms = s_ms.split(".")
    return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1_000 + int(ms)


def _normalize_text(text: str) -> str:
    """텍스트 앞뒤 공백 제거 및 CRLF → LF 변환."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _apply_normalization(raw_cues: list[SubtitleCue]) -> list[SubtitleCue]:
    """공통 정규화 파이프라인을 적용한다.

    1. 빈 텍스트 큐 제거
    2. 겹치는 큐 클리핑 (end_ms > next.start_ms → 자르기)
    3. 클리핑 후 유효하지 않은 큐 제거 (start_ms >= end_ms)
    4. 시퀀스 재부여 (1부터 연속)
    """
    # 1단계: 빈 텍스트 제거
    cues = [c for c in raw_cues if c.text.strip() != ""]

    # 2단계: 겹침 클리핑 — cue[i].end_ms > cue[i+1].start_ms 인 경우 클리핑
    for i in range(len(cues) - 1):
        if cues[i].end_ms > cues[i + 1].start_ms:
            # model_validator 우회를 위해 새 객체 생성
            clipped_end = cues[i + 1].start_ms
            cues[i] = SubtitleCue(
                sequence=cues[i].sequence,
                start_ms=cues[i].start_ms,
                end_ms=clipped_end,
                text=cues[i].text,
            )

    # 3단계: 클리핑 후 start_ms >= end_ms 큐 제거 (이미 SubtitleCue 생성 시 검증되지만 방어적 처리)
    cues = [c for c in cues if c.end_ms > c.start_ms]

    # 4단계: 시퀀스 재부여
    return [
        SubtitleCue(
            sequence=idx,
            start_ms=c.start_ms,
            end_ms=c.end_ms,
            text=c.text,
        )
        for idx, c in enumerate(cues, start=1)
    ]


def normalize_srt(content: str) -> list[SubtitleCue]:
    """SRT 문자열을 파싱하여 정규화된 SubtitleCue 목록을 반환한다.

    pysrt.from_string()을 사용해 파싱하며, ordinal 속성에서 밀리초 값을 얻는다.
    """
    subs = pysrt.from_string(content)
    raw: list[SubtitleCue] = []
    for sub in subs:
        text = _normalize_text(sub.text)
        raw.append(
            SubtitleCue(
                sequence=sub.index,
                start_ms=sub.start.ordinal,
                end_ms=sub.end.ordinal,
                text=text,
            )
        )
    return _apply_normalization(raw)


def normalize_vtt(content: str) -> list[SubtitleCue]:
    """VTT 문자열을 파싱하여 정규화된 SubtitleCue 목록을 반환한다.

    webvtt.read_buffer()를 사용해 파싱하며, 타임스탬프는 직접 파싱해 밀리초로 변환한다.
    """
    raw: list[SubtitleCue] = []
    for idx, cue in enumerate(webvtt.read_buffer(io.StringIO(content)), start=1):
        start_ms = _vtt_ts_to_ms(cue.start)
        end_ms = _vtt_ts_to_ms(cue.end)
        text = _normalize_text(cue.text)
        if end_ms <= start_ms:
            # 유효하지 않은 큐 — 정규화 단계에서 처리하지만 여기서 방어적으로 건너뜀
            continue
        raw.append(
            SubtitleCue(
                sequence=idx,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            )
        )
    return _apply_normalization(raw)


def parse_subtitle_file(path: Path) -> list[SubtitleCue]:
    """파일 확장자를 감지하여 SRT 또는 VTT 파서를 선택하고 큐 목록을 반환한다.

    지원 확장자: .srt, .vtt
    """
    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8")
    if suffix == ".srt":
        return normalize_srt(content)
    elif suffix == ".vtt":
        return normalize_vtt(content)
    else:
        raise ValueError(f"지원하지 않는 자막 파일 형식: {suffix!r} ({path})")
