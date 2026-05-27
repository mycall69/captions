"""테스트용 가짜 번역 Provider — 결정적 번역 + 컨텍스트 검사."""
from __future__ import annotations

from app.domain.translation.provider import (
    TranslatedChunk,
    TranslatedCue,
    TranslationChunk,
)


class FakeTranslationProvider:
    """결정적 mock 번역 Provider.

    - 번역 결과는 입력 cue text 앞에 [{target_lang}] 접두사를 붙인 형태.
    - 호출 이력(received_chunks)을 보존해 context_before/after 전달 여부 검증 가능.
    """

    def __init__(self, *, provider_id: str = "fake:test", model: str = "fake-1") -> None:
        self.provider_id = provider_id
        self.model = model
        self.received_chunks: list[TranslationChunk] = []
        self.call_count = 0

    async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:
        self.received_chunks.append(chunk)
        self.call_count += 1
        cues = [
            TranslatedCue(
                sequence=c.sequence,
                start_ms=c.start_ms,
                end_ms=c.end_ms,
                text=f"[{chunk.target_lang}] {c.text}",
            )
            for c in chunk.cues
        ]
        return TranslatedChunk(cues=cues, provider_id=self.provider_id, model=self.model)


class FailingTranslationProvider:
    """항상 ProviderTransientError를 발생시키는 mock — retry 테스트용."""

    def __init__(self) -> None:
        self.call_count = 0

    async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:  # noqa: ARG002
        from app.domain.translation.provider import ProviderTransientError

        self.call_count += 1
        raise ProviderTransientError("test transient")
