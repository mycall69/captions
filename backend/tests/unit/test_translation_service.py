"""T061: 번역 서비스 단위 테스트.

검증 항목:
- 캐시 히트 시 provider 호출을 건너뛴다.
- 캐시 미스 시 provider를 호출하고 결과를 캐시에 저장한다.
- ProviderRateLimitError 발생 시 최대 4회 재시도 후 성공 값 반환.
- 모든 재시도 소진 시 마지막 예외를 전파한다.
- ProviderPermanentError 발생 시 즉시 전파한다 (재시도 없음).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fakeredis import FakeAsyncRedis

from app.domain.translation.cache import TranslationCache, chunk_cache_key
from app.domain.translation.provider import (
    ChunkCue,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderTransientError,
    TranslatedChunk,
    TranslatedCue,
    TranslationChunk,
)
from app.domain.translation.service import RETRY_DELAYS, TranslationService
from tests.fixtures.fake_provider import (
    FailingTranslationProvider,
    FakeTranslationProvider,
    RateLimitedTranslationProvider,
)


def _make_chunk() -> TranslationChunk:
    """테스트용 TranslationChunk 생성 헬퍼."""
    return TranslationChunk(
        source_lang="ko",
        target_lang="ja",
        cues=[ChunkCue(sequence=1, start_ms=0, end_ms=3000, text="안녕하세요")],
    )


def _make_cache(fake_redis: FakeAsyncRedis) -> TranslationCache:
    """fakeredis를 사용하는 TranslationCache 인스턴스 생성."""
    c = TranslationCache.__new__(TranslationCache)
    c._redis = fake_redis  # type: ignore[attr-defined]
    c._ttl = 60
    return c


@pytest.fixture()
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


class TestTranslationServiceCacheHit:
    """캐시 히트 시 provider 호출을 건너뜀."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_provider(self, fake_redis: FakeAsyncRedis) -> None:
        """캐시에 저장된 결과가 있으면 provider를 호출하지 않아야 한다."""
        provider = FakeTranslationProvider()
        cache = _make_cache(fake_redis)
        service = TranslationService(provider, cache=cache)
        chunk = _make_chunk()

        # 캐시에 미리 저장
        pre_stored = TranslatedChunk(
            cues=[TranslatedCue(sequence=1, start_ms=0, end_ms=3000, text="こんにちは")],
            provider_id="cached:result",
            model="cached-model",
        )
        key = chunk_cache_key(chunk, provider_id="claude:premium-seat")
        await cache.set(key, pre_stored)

        result = await service.translate(chunk)

        # provider는 호출되지 않아야 함
        assert provider.call_count == 0
        assert result.provider_id == "cached:result"

    @pytest.mark.asyncio
    async def test_cache_hit_returns_stored_value(self, fake_redis: FakeAsyncRedis) -> None:
        """캐시 히트 시 저장된 TranslatedChunk가 그대로 반환되어야 한다."""
        provider = FakeTranslationProvider()
        cache = _make_cache(fake_redis)
        service = TranslationService(provider, cache=cache)
        chunk = _make_chunk()

        expected = TranslatedChunk(
            cues=[TranslatedCue(sequence=1, start_ms=0, end_ms=3000, text="テスト")],
            provider_id="cached:test",
            model="model-x",
        )
        key = chunk_cache_key(chunk, provider_id="claude:premium-seat")
        await cache.set(key, expected)

        result = await service.translate(chunk)

        assert result == expected


class TestTranslationServiceCacheMiss:
    """캐시 미스 시 provider 호출 후 결과 저장."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_provider(self, fake_redis: FakeAsyncRedis) -> None:
        """캐시 미스 시 provider.translate_chunk를 호출해야 한다."""
        provider = FakeTranslationProvider()
        cache = _make_cache(fake_redis)
        service = TranslationService(provider, cache=cache)
        chunk = _make_chunk()

        await service.translate(chunk)

        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result(self, fake_redis: FakeAsyncRedis) -> None:
        """캐시 미스 후 provider 결과가 캐시에 저장되어야 한다."""
        provider = FakeTranslationProvider()
        cache = _make_cache(fake_redis)
        service = TranslationService(provider, cache=cache)
        chunk = _make_chunk()

        result1 = await service.translate(chunk)
        # 두 번째 호출에서 캐시 히트 → provider 재호출 없음
        result2 = await service.translate(chunk)

        assert provider.call_count == 1  # 두 번째 호출은 캐시에서 반환
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_no_cache_always_calls_provider(self) -> None:
        """cache=None 이면 매번 provider를 호출해야 한다."""
        provider = FakeTranslationProvider()
        service = TranslationService(provider, cache=None)
        chunk = _make_chunk()

        await service.translate(chunk)
        await service.translate(chunk)

        assert provider.call_count == 2


class TestTranslationServiceRetry:
    """exponential backoff retry 동작 검증."""

    @pytest.mark.asyncio
    async def test_rate_limit_retries_up_to_4_times_then_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """처음 4번은 실패하고 5번째에 성공하는 경우, 결과를 반환해야 한다."""
        monkeypatch.setattr("app.domain.translation.service.asyncio.sleep", AsyncMock())
        call_count = 0

        class EventuallySuccessProvider:
            async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:
                nonlocal call_count
                call_count += 1
                if call_count < 5:
                    raise ProviderRateLimitError("일시적 rate limit")
                return TranslatedChunk(
                    cues=[TranslatedCue(sequence=1, start_ms=0, end_ms=3000, text="성공")],
                    provider_id="test",
                    model="test-model",
                )

        service = TranslationService(EventuallySuccessProvider(), cache=None)
        result = await service.translate(_make_chunk())

        assert result.cues[0].text == "성공"
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_raises_last_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5회 모두 실패 시 마지막 예외가 전파되어야 한다."""
        monkeypatch.setattr("app.domain.translation.service.asyncio.sleep", AsyncMock())
        provider = RateLimitedTranslationProvider()
        service = TranslationService(provider, cache=None)

        with pytest.raises(ProviderRateLimitError):
            await service.translate(_make_chunk())

        assert provider.call_count == len(RETRY_DELAYS) + 1  # 5회

    @pytest.mark.asyncio
    async def test_transient_error_also_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ProviderTransientError 도 재시도 대상이어야 한다."""
        monkeypatch.setattr("app.domain.translation.service.asyncio.sleep", AsyncMock())
        provider = FailingTranslationProvider()
        service = TranslationService(provider, cache=None)

        with pytest.raises(ProviderTransientError):
            await service.translate(_make_chunk())

        assert provider.call_count == len(RETRY_DELAYS) + 1  # 5회

    @pytest.mark.asyncio
    async def test_permanent_error_no_retry(self) -> None:
        """ProviderPermanentError는 재시도 없이 즉시 전파되어야 한다."""
        call_count = 0

        class PermanentProvider:
            async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:
                nonlocal call_count
                call_count += 1
                raise ProviderPermanentError("복구 불가 오류")

        service = TranslationService(PermanentProvider(), cache=None)

        with pytest.raises(ProviderPermanentError):
            await service.translate(_make_chunk())

        assert call_count == 1  # 재시도 없이 1회만 호출


class TestTranslationServiceRetryDelays:
    """backoff 딜레이 호출 검증."""

    @pytest.mark.asyncio
    async def test_retry_uses_exponential_backoff_delays(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """재시도 간격이 1s, 2s, 4s, 8s 순서로 asyncio.sleep 을 호출해야 한다."""
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("app.domain.translation.service.asyncio.sleep", fake_sleep)
        provider = RateLimitedTranslationProvider()
        service = TranslationService(provider, cache=None)

        with pytest.raises(ProviderRateLimitError):
            await service.translate(_make_chunk())

        assert sleep_calls == list(RETRY_DELAYS)

    @pytest.mark.asyncio
    async def test_retry_honours_retry_after_seconds_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ProviderRateLimitError 가 retry_after_seconds 를 노출하면 backoff 대신
        해당 값을 사용해야 한다 (Anthropic 429 의 retry-after 헤더 존중).
        """
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("app.domain.translation.service.asyncio.sleep", fake_sleep)

        class _HintedRateLimitProvider:
            async def translate_chunk(self, chunk: object) -> object:
                raise ProviderRateLimitError(
                    "rate limited", retry_after_seconds=12.5
                )

        service = TranslationService(_HintedRateLimitProvider(), cache=None)

        with pytest.raises(ProviderRateLimitError):
            await service.translate(_make_chunk())

        # 4회 retry 모두 헤더 hint(12.5s)를 사용해야 함 (RETRY_DELAYS 무시).
        assert sleep_calls == [12.5, 12.5, 12.5, 12.5]
