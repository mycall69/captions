"""T060: 번역 캐시 단위 테스트 — fakeredis 기반.

검증 항목:
- set() 후 get() 이 동일한 TranslatedChunk를 반환한다.
- 존재하지 않는 키 조회 시 None 을 반환한다.
- chunk_cache_key 는 동일 입력에 대해 결정론적이다.
- chunk_cache_key 는 텍스트가 다르면 다른 키를 반환한다.
"""

from __future__ import annotations

import pytest
from fakeredis import FakeAsyncRedis

from app.domain.translation.cache import TranslationCache, chunk_cache_key
from app.domain.translation.provider import (
    ChunkCue,
    TranslatedChunk,
    TranslatedCue,
    TranslationChunk,
)


def _make_chunk(text: str = "안녕하세요") -> TranslationChunk:
    """테스트용 TranslationChunk 생성 헬퍼."""
    return TranslationChunk(
        source_lang="ko",
        target_lang="ja",
        cues=[
            ChunkCue(sequence=1, start_ms=0, end_ms=3000, text=text),
        ],
    )


def _make_translated_chunk(text: str = "こんにちは") -> TranslatedChunk:
    """테스트용 TranslatedChunk 생성 헬퍼."""
    return TranslatedChunk(
        cues=[
            TranslatedCue(sequence=1, start_ms=0, end_ms=3000, text=text),
        ],
        provider_id="fake:test",
        model="fake-1",
    )


@pytest.fixture()
def fake_redis() -> FakeAsyncRedis:
    """fakeredis 인스턴스를 반환한다."""
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture()
def cache(fake_redis: FakeAsyncRedis) -> TranslationCache:
    """fakeredis를 내부 Redis 클라이언트로 사용하는 TranslationCache 인스턴스."""
    c = TranslationCache.__new__(TranslationCache)
    c._redis = fake_redis  # type: ignore[attr-defined]
    c._ttl = 60  # 테스트용 짧은 TTL
    return c


class TestTranslationCacheSetGet:
    """set() / get() 기본 동작 검증."""

    @pytest.mark.asyncio
    async def test_set_then_get_returns_equal_chunk(self, cache: TranslationCache) -> None:
        """set() 후 get() 이 동일한 TranslatedChunk를 반환해야 한다."""
        chunk = _make_chunk()
        value = _make_translated_chunk()
        key = chunk_cache_key(chunk, provider_id="fake:test")

        await cache.set(key, value)
        result = await cache.get(key)

        assert result is not None
        assert result == value

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self, cache: TranslationCache) -> None:
        """존재하지 않는 키 조회 시 None 을 반환해야 한다."""
        result = await cache.get("translation:nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_deserializes_all_fields(self, cache: TranslationCache) -> None:
        """캐시에서 꺼낸 TranslatedChunk가 모든 필드를 정확히 복원해야 한다."""
        chunk = _make_chunk("테스트 자막")
        value = TranslatedChunk(
            cues=[TranslatedCue(sequence=1, start_ms=0, end_ms=5000, text="テスト字幕")],
            provider_id="claude:premium-seat",
            model="claude-opus-4-7-20250514",
        )
        key = chunk_cache_key(chunk, provider_id="claude:premium-seat")

        await cache.set(key, value)
        result = await cache.get(key)

        assert result is not None
        assert result.cues[0].text == "テスト字幕"
        assert result.provider_id == "claude:premium-seat"
        assert result.model == "claude-opus-4-7-20250514"


class TestChunkCacheKey:
    """chunk_cache_key 결정론성 및 고유성 검증."""

    def test_same_input_produces_same_key(self) -> None:
        """동일한 입력에 대해 항상 동일한 키를 반환해야 한다 (결정론적)."""
        chunk = _make_chunk("동일 텍스트")
        key1 = chunk_cache_key(chunk, provider_id="fake:test")
        key2 = chunk_cache_key(chunk, provider_id="fake:test")
        assert key1 == key2

    def test_different_text_produces_different_key(self) -> None:
        """cue 본문이 다르면 다른 키를 반환해야 한다."""
        chunk_a = _make_chunk("텍스트 A")
        chunk_b = _make_chunk("텍스트 B")
        key_a = chunk_cache_key(chunk_a, provider_id="fake:test")
        key_b = chunk_cache_key(chunk_b, provider_id="fake:test")
        assert key_a != key_b

    def test_different_provider_produces_different_key(self) -> None:
        """provider_id가 다르면 다른 키를 반환해야 한다."""
        chunk = _make_chunk()
        key1 = chunk_cache_key(chunk, provider_id="provider:a")
        key2 = chunk_cache_key(chunk, provider_id="provider:b")
        assert key1 != key2

    def test_different_lang_pair_produces_different_key(self) -> None:
        """source_lang / target_lang이 다르면 다른 키를 반환해야 한다."""
        chunk_ko_ja = TranslationChunk(
            source_lang="ko",
            target_lang="ja",
            cues=[ChunkCue(sequence=1, start_ms=0, end_ms=3000, text="안녕")],
        )
        chunk_ja_ko = TranslationChunk(
            source_lang="ja",
            target_lang="ko",
            cues=[ChunkCue(sequence=1, start_ms=0, end_ms=3000, text="안녕")],
        )
        key1 = chunk_cache_key(chunk_ko_ja, provider_id="fake:test")
        key2 = chunk_cache_key(chunk_ja_ko, provider_id="fake:test")
        assert key1 != key2

    def test_key_has_translation_prefix(self) -> None:
        """캐시 키는 'translation:' 접두사로 시작해야 한다."""
        chunk = _make_chunk()
        key = chunk_cache_key(chunk, provider_id="fake:test")
        assert key.startswith("translation:")
