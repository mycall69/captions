"""app.domain.subtitles.chunking — cue 경계 보존 청크 분할 유틸리티.

test_chunking.py (T047) 가 기대하는 `chunk_cues` 함수를 제공한다.
내부적으로 app.domain.translation.chunking.split_into_chunks 위에 구현되어
단일 청크 분할 로직을 재사용한다.

인자로 ChunkCue 목록을 받고 ChunkResult 목록을 반환하므로,
번역 언어 정보가 없는 컨텍스트에서도 호출 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.translation.provider import ChunkCue

DEFAULT_WINDOW_MS = 60_000
CONTEXT_CUE_COUNT = 3


@dataclass
class ChunkResult:
    """chunk_cues 반환 단위 — 번역 언어 정보 없이 순수 cue 경계 분할 결과."""

    cues: list[ChunkCue] = field(default_factory=list)
    """실제 번역 대상 cue 목록."""

    context_before: list[ChunkCue] = field(default_factory=list)
    """직전 최대 3 cue — context 참고용."""

    context_after: list[ChunkCue] = field(default_factory=list)
    """직후 최대 3 cue — context 참고용."""


def chunk_cues(
    cues: list[ChunkCue],
    *,
    window_ms: int = DEFAULT_WINDOW_MS,
    context_count: int = CONTEXT_CUE_COUNT,
) -> list[ChunkResult]:
    """ChunkCue 목록을 60초 윈도우 단위로 분할한다.

    Args:
        cues: 입력 cue 목록 (start_ms 오름차순 정렬 가정).
        window_ms: 청크 윈도우 크기 (기본 60,000ms = 60초).
        context_count: 각 청크 앞뒤에 붙일 context cue 수 (기본 3).

    Returns:
        ChunkResult 목록. cue가 없으면 빈 리스트를 반환한다.

    Notes:
        - cue 경계는 자르지 않는다 (partial cue 없음).
        - context cue는 원본 cue 목록에서만 가져온다 (합성 금지).
    """
    if not cues:
        return []

    # 1) 윈도우 그룹핑
    groups: list[list[int]] = []  # 각 그룹은 cues 인덱스 목록
    current: list[int] = []
    window_start_ms = cues[0].start_ms

    for idx, cue in enumerate(cues):
        if not current:
            current = [idx]
            window_start_ms = cue.start_ms
            continue
        if cue.start_ms - window_start_ms < window_ms:
            current.append(idx)
        else:
            groups.append(current)
            current = [idx]
            window_start_ms = cue.start_ms

    if current:
        groups.append(current)

    # 2) context 부여 + ChunkResult 생성
    results: list[ChunkResult] = []
    for group in groups:
        before_start = max(0, group[0] - context_count)
        context_before = cues[before_start : group[0]]

        after_end = min(len(cues), group[-1] + 1 + context_count)
        context_after = cues[group[-1] + 1 : after_end]

        results.append(
            ChunkResult(
                cues=[cues[i] for i in group],
                context_before=list(context_before),
                context_after=list(context_after),
            )
        )

    return results
