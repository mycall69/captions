"""T024 단위 테스트: TranslationProvider Protocol 및 DTO 검증.

Protocol 인터페이스 정합성과 Pydantic DTO 왕복 검증을 수행한다.
실제 provider 호출은 없으며, 인라인 FakeTranslationProvider로 Protocol 준수를 확인한다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.translation.provider import (
    ChunkCue,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderTransientError,
    TranslatedChunk,
    TranslatedCue,
    TranslationChunk,
    TranslationProvider,
)

# ── 인라인 FakeTranslationProvider ───────────────────────────────────────────

class FakeTranslationProvider:
    """Protocol 준수 여부 확인용 최소 구현체."""

    async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:
        """각 cue 텍스트에 '[번역]' 접두사를 붙여 반환한다."""
        translated_cues = [
            TranslatedCue(
                sequence=cue.sequence,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=f"[번역] {cue.text}",
            )
            for cue in chunk.cues
        ]
        return TranslatedChunk(
            cues=translated_cues,
            provider_id="fake:v1",
            model="fake-model",
        )


class TestTranslationProviderProtocol:
    """TranslationProvider Protocol 구조 검증."""

    def test_fake_provider_satisfies_protocol(self) -> None:
        """FakeTranslationProvider는 TranslationProvider Protocol을 만족해야 한다.

        Protocol은 runtime_checkable이 아니므로 메서드 존재 여부로 확인.
        """
        fake: TranslationProvider = FakeTranslationProvider()  # type: ignore[assignment]
        assert hasattr(fake, "translate_chunk")
        assert callable(fake.translate_chunk)

    @pytest.mark.asyncio
    async def test_fake_provider_returns_translated_chunk(self) -> None:
        """FakeTranslationProvider.translate_chunk는 TranslatedChunk를 반환해야 한다."""
        fake = FakeTranslationProvider()

        chunk = TranslationChunk(
            source_lang="ko",
            target_lang="ja",
            cues=[
                ChunkCue(sequence=1, start_ms=0, end_ms=2000, text="안녕하세요"),
                ChunkCue(sequence=2, start_ms=2500, end_ms=4000, text="반갑습니다"),
            ],
        )
        result = await fake.translate_chunk(chunk)

        assert isinstance(result, TranslatedChunk)
        assert len(result.cues) == 2
        assert result.cues[0].text == "[번역] 안녕하세요"
        assert result.cues[1].text == "[번역] 반갑습니다"
        assert result.provider_id == "fake:v1"
        assert result.model == "fake-model"


class TestChunkCue:
    """ChunkCue DTO 유효성 검사."""

    def test_valid_cue(self) -> None:
        cue = ChunkCue(sequence=1, start_ms=0, end_ms=2000, text="Hello")
        assert cue.sequence == 1
        assert cue.start_ms == 0
        assert cue.end_ms == 2000
        assert cue.text == "Hello"

    def test_sequence_must_be_ge_1(self) -> None:
        """sequence는 1 이상이어야 한다."""
        with pytest.raises(ValidationError):
            ChunkCue(sequence=0, start_ms=0, end_ms=1000, text="x")

    def test_start_ms_must_be_ge_0(self) -> None:
        """start_ms는 0 이상이어야 한다."""
        with pytest.raises(ValidationError):
            ChunkCue(sequence=1, start_ms=-1, end_ms=1000, text="x")

    def test_pydantic_roundtrip(self) -> None:
        """ChunkCue를 JSON으로 직렬화하고 다시 파싱할 수 있어야 한다."""
        original = ChunkCue(sequence=5, start_ms=1000, end_ms=3000, text="테스트")
        restored = ChunkCue.model_validate(original.model_dump())
        assert original == restored


class TestTranslationChunk:
    """TranslationChunk DTO 검증 — 묶음 단위 번역 요청."""

    def test_default_context_lists_empty(self) -> None:
        """context_before / context_after 기본값은 빈 리스트여야 한다."""
        chunk = TranslationChunk(
            source_lang="ko",
            target_lang="ja",
            cues=[ChunkCue(sequence=1, start_ms=0, end_ms=1000, text="테스트")],
        )
        assert chunk.context_before == []
        assert chunk.context_after == []

    def test_pydantic_roundtrip(self) -> None:
        """TranslationChunk를 직렬화하고 다시 파싱할 수 있어야 한다."""
        cue = ChunkCue(sequence=1, start_ms=0, end_ms=1000, text="A")
        cue_ctx = ChunkCue(sequence=1, start_ms=0, end_ms=500, text="ctx")
        chunk = TranslationChunk(
            source_lang="ja",
            target_lang="ko",
            cues=[cue],
            context_before=[cue_ctx],
        )
        restored = TranslationChunk.model_validate(chunk.model_dump())
        assert chunk == restored

    def test_lang_type_accepted(self) -> None:
        """Lang 타입(ko, ja)만 허용되어야 한다."""
        chunk = TranslationChunk(
            source_lang="ko",
            target_lang="ja",
            cues=[],
        )
        assert chunk.source_lang == "ko"
        assert chunk.target_lang == "ja"


class TestTranslatedChunk:
    """TranslatedChunk DTO 검증 — 번역 결과 묶음."""

    def test_pydantic_roundtrip(self) -> None:
        """TranslatedChunk를 직렬화하고 다시 파싱할 수 있어야 한다."""
        original = TranslatedChunk(
            cues=[
                TranslatedCue(sequence=1, start_ms=0, end_ms=2000, text="こんにちは"),
            ],
            provider_id="claude:claude-opus-4-7",
            model="claude-opus-4-7-20250514",
        )
        restored = TranslatedChunk.model_validate(original.model_dump())
        assert original == restored
        assert restored.cues[0].text == "こんにちは"


class TestProviderExceptions:
    """Provider 예외 계층 구조 검증."""

    def test_rate_limit_error_is_translation_failed(self) -> None:
        from app.core.exceptions import TranslationFailedError

        err = ProviderRateLimitError("rate limit 초과")
        assert isinstance(err, TranslationFailedError)
        assert err.code == "PROVIDER_RATE_LIMITED"
        assert err.http_status == 429

    def test_transient_error_is_translation_failed(self) -> None:
        from app.core.exceptions import TranslationFailedError

        err = ProviderTransientError("일시적 오류")
        assert isinstance(err, TranslationFailedError)
        assert err.code == "PROVIDER_TRANSIENT_ERROR"
        assert err.http_status == 503

    def test_permanent_error_is_translation_failed(self) -> None:
        from app.core.exceptions import TranslationFailedError

        err = ProviderPermanentError("복구 불가 오류")
        assert isinstance(err, TranslationFailedError)
        assert err.code == "PROVIDER_PERMANENT_ERROR"
        assert err.http_status == 500
