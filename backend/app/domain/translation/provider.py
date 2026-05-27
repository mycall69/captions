"""T024: TranslationProvider Protocol 및 관련 DTO.

research.md §6 및 ADR 0001-translation-provider-abstraction.md 준수.
도메인·Celery task는 이 Protocol에만 의존하고,
Anthropic SDK는 infrastructure/providers/claude_adapter.py에만 존재한다.

언어 타입(Lang)은 app.domain.jobs.models가 canonical 정의이며, 여기서 재수출한다.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.core.exceptions import TranslationFailedError
from app.domain.jobs.models import Lang  # canonical 정의 — 재수출

__all__ = [
    "Lang",
    "ChunkCue",
    "TranslatedCue",
    "TranslationChunk",
    "TranslatedChunk",
    "TranslationProvider",
    "ProviderRateLimitError",
    "ProviderTransientError",
    "ProviderPermanentError",
]


# ── 입력 / 출력 DTO ────────────────────────────────────────────────────────────

class ChunkCue(BaseModel):
    """번역 입력 단위 — 단일 자막 cue.

    sequence는 트랙 내 1-based 순서, start_ms/end_ms는 ms 단위 타임스탬프.
    """

    sequence: int = Field(ge=1)
    """트랙 내 1부터 시작하는 순서 번호."""

    start_ms: int = Field(ge=0)
    """cue 시작 시각 (밀리초)."""

    end_ms: int
    """cue 종료 시각 (밀리초, start_ms 초과 필요)."""

    text: str
    """정규화된 자막 본문 (개행 LF)."""


class TranslatedCue(BaseModel):
    """번역 출력 단위 — 대상 언어로 번역된 단일 cue.

    sequence / start_ms / end_ms는 입력과 동일하게 보존된다.
    """

    sequence: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int
    text: str
    """대상 언어로 번역된 자막 본문."""


class TranslationChunk(BaseModel):
    """번역 요청 묶음 — 60초 윈도우 단위(research §5).

    context_before / context_after는 번역 결과에 포함되지 않지만,
    화자 일관성·문맥 보존을 위해 provider에 함께 전달된다(연속 각 3 cue).
    """

    source_lang: Lang
    """원본 언어."""

    target_lang: Lang
    """번역 목표 언어."""

    cues: list[ChunkCue]
    """실제 번역 대상 cue 목록."""

    context_before: list[ChunkCue] = Field(default_factory=list)
    """직전 최대 3 cue — 문맥용, 번역 결과에는 제외."""

    context_after: list[ChunkCue] = Field(default_factory=list)
    """직후 최대 3 cue — 문맥용, 번역 결과에는 제외."""


class TranslatedChunk(BaseModel):
    """번역 응답 묶음.

    cues는 TranslationChunk.cues와 동일한 개수·순서.
    """

    cues: list[TranslatedCue]
    """번역된 cue 목록 (TranslationChunk.cues와 1:1 대응)."""

    provider_id: str
    """사용된 provider 식별자 (예: 'claude:claude-opus-4-7')."""

    model: str
    """실제 호출한 모델 이름."""


# ── Protocol ──────────────────────────────────────────────────────────────────

class TranslationProvider(Protocol):
    """번역 Provider 추상 인터페이스.

    ADR 0001 및 헌법 §Translation Provider Abstraction NON-NEGOTIABLE 준수.
    구현체: app/infrastructure/providers/claude_adapter.py
    테스트 대역: app/infrastructure/providers/fake_adapter.py
    """

    async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:
        """단일 번역 청크를 번역해 TranslatedChunk를 반환한다.

        Args:
            chunk: 번역 요청 묶음 (source_lang, target_lang, cues, context).

        Returns:
            번역된 cue 목록과 provider/model 정보를 담은 TranslatedChunk.

        Raises:
            ProviderRateLimitError: rate limit 초과 — 대기 후 재시도 가능.
            ProviderTransientError: 일시적 오류 — 재시도 가능.
            ProviderPermanentError: 복구 불가 오류 — 재시도 불필요.
        """
        ...


# ── Provider 예외 ──────────────────────────────────────────────────────────────

class ProviderRateLimitError(TranslationFailedError):
    """번역 Provider rate limit 초과 — 대기 후 재시도 가능."""

    code = "PROVIDER_RATE_LIMITED"
    http_status = 429


class ProviderTransientError(TranslationFailedError):
    """번역 Provider 일시적 오류 (네트워크, 타임아웃 등) — 재시도 가능."""

    code = "PROVIDER_TRANSIENT_ERROR"
    http_status = 503


class ProviderPermanentError(TranslationFailedError):
    """번역 Provider 복구 불가 오류 (인증 실패, 모델 미지원 등) — 재시도 불필요."""

    code = "PROVIDER_PERMANENT_ERROR"
    http_status = 500
