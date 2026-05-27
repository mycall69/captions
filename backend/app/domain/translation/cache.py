"""T060: Redis 기반 번역 결과 캐시.

키: sha256(provider_id + source_lang + target_lang + normalized_chunk_text) → JSON 직렬화 TranslatedChunk.
TTL: 7일 (기본 604,800초 — settings.translation_cache_ttl_sec 으로 외부 노출 예정).

캐시 키 계산 시 context_before / context_after는 제외한다 (번역 결과와 무관).
"""

from __future__ import annotations

import hashlib

import redis.asyncio as aioredis

from app.domain.translation.provider import TranslatedChunk, TranslationChunk

CACHE_TTL_SEC_DEFAULT = 60 * 60 * 24 * 7  # 7일 = 604,800초


def chunk_cache_key(chunk: TranslationChunk, *, provider_id: str) -> str:
    """TranslationChunk 에 대한 결정론적 캐시 키를 계산한다.

    provider_id, source_lang, target_lang, 각 cue의 sequence·start_ms·end_ms·text를
    순서대로 sha256으로 해시하여 'translation:{hex}' 형식 문자열을 반환한다.

    Args:
        chunk: 번역 요청 묶음.
        provider_id: provider 식별자 (예: 'claude:premium-seat').

    Returns:
        'translation:{sha256_hex}' 형식의 캐시 키.
    """
    h = hashlib.sha256()
    h.update(provider_id.encode("utf-8"))
    h.update(b"|")
    h.update(chunk.source_lang.encode("utf-8"))
    h.update(b"|")
    h.update(chunk.target_lang.encode("utf-8"))
    h.update(b"|")
    for c in chunk.cues:
        h.update(f"{c.sequence}:{c.start_ms}:{c.end_ms}:".encode())
        h.update(c.text.encode())
        h.update(b"\n")
    return f"translation:{h.hexdigest()}"


class TranslationCache:
    """Redis 기반 번역 결과 캐시.

    번역이 완료된 TranslatedChunk를 JSON 직렬화하여 Redis에 저장하고,
    동일 입력 chunk에 대해 캐시 히트 시 provider 호출을 건너뛴다.
    """

    def __init__(self, redis_url: str, *, ttl_sec: int = CACHE_TTL_SEC_DEFAULT) -> None:
        """캐시 인스턴스를 초기화한다.

        Args:
            redis_url: Redis 연결 URL (예: 'redis://localhost:6379/0').
            ttl_sec: 캐시 항목 TTL (초 단위, 기본 7일).
        """
        self._redis: aioredis.Redis[str] = aioredis.from_url(
            redis_url, decode_responses=True
        )
        self._ttl = ttl_sec

    async def get(self, key: str) -> TranslatedChunk | None:
        """캐시에서 TranslatedChunk를 조회한다.

        Args:
            key: chunk_cache_key() 로 생성한 캐시 키.

        Returns:
            캐시 히트 시 TranslatedChunk, 미스 시 None.
        """
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return TranslatedChunk.model_validate_json(raw)

    async def set(self, key: str, value: TranslatedChunk) -> None:
        """TranslatedChunk를 캐시에 저장한다.

        Args:
            key: 저장할 캐시 키.
            value: 직렬화할 TranslatedChunk.
        """
        await self._redis.setex(key, self._ttl, value.model_dump_json())

    async def close(self) -> None:
        """Redis 연결을 닫는다."""
        await self._redis.aclose()  # type: ignore[attr-defined]
