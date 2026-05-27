"""T061: 번역 서비스 — chunk dispatch + cache 조회 + exponential backoff retry.

research §6: 최초 1회 + 4회 retry = 최대 5회 호출 (backoff: 1s, 2s, 4s, 8s).
ProviderPermanentError는 재시도하지 않고 즉시 전파한다.
"""

from __future__ import annotations

import asyncio

from app.domain.translation.cache import TranslationCache, chunk_cache_key
from app.domain.translation.provider import (
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderTransientError,
    TranslatedChunk,
    TranslationChunk,
    TranslationProvider,
)

# research §6: exponential backoff 딜레이 — 4회 retry (총 5회 호출)
RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)


class TranslationService:
    """번역 서비스 — provider, cache, retry 정책을 조합한다.

    외부에서 TranslationProvider 구현체를 주입받아 사용하므로,
    도메인 코드는 anthropic SDK에 의존하지 않는다 (헌법 §Translation Provider Abstraction).
    """

    def __init__(
        self,
        provider: TranslationProvider,
        *,
        cache: TranslationCache | None = None,
        provider_id: str = "claude:premium-seat",
    ) -> None:
        """서비스를 초기화한다.

        Args:
            provider: TranslationProvider 구현체 (Claude adapter 또는 테스트 대역).
            cache: Redis 캐시 인스턴스. None이면 캐시를 사용하지 않는다.
            provider_id: 캐시 키 계산에 사용하는 provider 식별자.
        """
        self._provider = provider
        self._cache = cache
        self._provider_id = provider_id

    async def translate(self, chunk: TranslationChunk) -> TranslatedChunk:
        """단일 청크를 번역한다: cache 조회 → provider 호출 → cache 저장.

        Args:
            chunk: 번역 요청 묶음.

        Returns:
            번역 결과 TranslatedChunk (캐시 히트 시 저장된 결과 반환).

        Raises:
            ProviderRateLimitError: 모든 retry 소진 후에도 rate limit 오류인 경우.
            ProviderTransientError: 모든 retry 소진 후에도 일시적 오류인 경우.
            ProviderPermanentError: provider가 복구 불가 오류를 발생시킨 경우 (재시도 없음).
        """
        key = chunk_cache_key(chunk, provider_id=self._provider_id)

        if self._cache is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                return cached

        result = await self._call_with_retry(chunk)

        if self._cache is not None:
            await self._cache.set(key, result)

        return result

    async def _call_with_retry(self, chunk: TranslationChunk) -> TranslatedChunk:
        """exponential backoff 재시도 로직 (최대 5회 호출).

        ProviderRateLimitError / ProviderTransientError 발생 시 최대 4회 재시도.
        ProviderPermanentError는 즉시 전파한다.

        Args:
            chunk: 번역 요청 묶음.

        Returns:
            번역 성공 시 TranslatedChunk.

        Raises:
            ProviderRateLimitError | ProviderTransientError: 모든 재시도 소진.
            ProviderPermanentError: 재시도 없이 즉시 전파.
        """
        last_exc: Exception | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):  # 0..4 포함 = 5회
            try:
                return await self._provider.translate_chunk(chunk)
            except (ProviderRateLimitError, ProviderTransientError) as exc:
                last_exc = exc
                if attempt >= len(RETRY_DELAYS):
                    break
                await asyncio.sleep(RETRY_DELAYS[attempt])
            except ProviderPermanentError:
                raise

        assert last_exc is not None
        raise last_exc
