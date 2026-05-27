"""T059: 시간 기반 청크 정책 — 60초 윈도우 + cue 경계 보존 + 3 cue context.

research.md §5 (chunking policy) 기반 구현.
- 60초 윈도우 단위로 cue를 그룹화한다 (cue 경계는 자르지 않음).
- 각 청크에 직전 최대 3 cue / 직후 최대 3 cue를 context로 첨부한다.
- context cue는 번역 결과에 포함되지 않으며, provider에게 문맥 참고용으로 전달된다.

TODO: 이 모듈의 윈도우 그룹핑 로직이 app.domain.subtitles.chunking.chunk_cues 와
      중복된다. 향후 리팩토링에서 공통 코어 헬퍼로 통합할 예정이다
      (cross-ref: subtitles/chunking.py).
"""

from __future__ import annotations

from app.domain.jobs.models import Lang
from app.domain.subtitles.models import SubtitleCue
from app.domain.translation.provider import ChunkCue, TranslationChunk

DEFAULT_WINDOW_MS = 60_000
CONTEXT_CUE_COUNT = 3


def _to_chunk_cue(cue: SubtitleCue) -> ChunkCue:
    """SubtitleCue → ChunkCue 변환."""
    return ChunkCue(
        sequence=cue.sequence,
        start_ms=cue.start_ms,
        end_ms=cue.end_ms,
        text=cue.text,
    )


def split_into_chunks(
    cues: list[SubtitleCue],
    *,
    source_lang: Lang,
    target_lang: Lang,
    window_ms: int = DEFAULT_WINDOW_MS,
    context_count: int = CONTEXT_CUE_COUNT,
) -> list[TranslationChunk]:
    """cue 리스트를 60초 윈도우 단위로 묶어 TranslationChunk 목록을 반환한다.

    Args:
        cues: 입력 자막 cue 목록 (start_ms 오름차순 정렬 가정).
        source_lang: 원본 언어 코드.
        target_lang: 번역 대상 언어 코드.
        window_ms: 청크 윈도우 크기 (기본 60,000ms = 60초).
        context_count: 각 청크 앞뒤에 붙일 context cue 수 (기본 3).

    Returns:
        TranslationChunk 목록. cue가 없으면 빈 리스트를 반환한다.

    Notes:
        - cue 경계는 자르지 않는다. 하나의 cue는 항상 하나의 chunk에 완전히 포함된다.
        - context cue는 번역 요청 cue 목록(chunk.cues)과 중복되지 않는다.
    """
    if not cues:
        return []

    # 1) 윈도우 그룹핑: start_ms 기준으로 60초 윈도우마다 새 그룹 시작
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

    # 2) 각 그룹에 context cue를 부여하고 TranslationChunk 객체 생성
    chunks: list[TranslationChunk] = []
    for group in groups:
        before_start = max(0, group[0] - context_count)
        context_before = cues[before_start : group[0]]

        after_end = min(len(cues), group[-1] + 1 + context_count)
        context_after = cues[group[-1] + 1 : after_end]

        chunks.append(
            TranslationChunk(
                source_lang=source_lang,
                target_lang=target_lang,
                cues=[_to_chunk_cue(cues[i]) for i in group],
                context_before=[_to_chunk_cue(c) for c in context_before],
                context_after=[_to_chunk_cue(c) for c in context_after],
            )
        )

    return chunks
