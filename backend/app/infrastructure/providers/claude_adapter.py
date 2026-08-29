"""T062: Claude 번역 어댑터 — Anthropic SDK 결합 유일 지점.

ADR 0001 — 본 모듈 외부에서는 anthropic 패키지 import 금지.
spec Clarifications Q1 / FR-014 — 어조(register) 추론 후 동일 어조로 출력 강제.

어조 추론 로직:
- KO: 정중체(합니다/입니다/세요 등) vs 평어/한다체(한다/이다 등) → 다수결
- JA: 丁寧体(です・ます調) vs 普通体(だ・である調) → 다수결
- 혼재(동수) 시 정중체로 판정한다.
- 추론 결과를 시스템 프롬프트에 명시해 동일 어조로 출력을 강제한다.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic import RateLimitError as AnthropicRateLimitError
from anthropic._exceptions import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
)

from app.domain.translation.provider import (
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderTransientError,
    TranslatedChunk,
    TranslatedCue,
    TranslationChunk,
)

logger = structlog.get_logger(__name__)

# 운영 디버깅에 가치 있는 anthropic 응답 헤더만 선별 로깅 (rate limit 진단용).
_RATE_LIMIT_HEADER_PREFIXES = ("anthropic-ratelimit-",)
_RATE_LIMIT_HEADER_KEYS = frozenset(
    {
        "retry-after",
        "retry-after-ms",
        "request-id",
        "anthropic-organization-id",
        "anthropic-version",
    }
)
# Authorization/x-api-key 등 시크릿 헤더는 값을 redact 한 사본으로 로그.
_SENSITIVE_HEADER_KEYS = frozenset(
    {"authorization", "x-api-key", "cookie", "set-cookie"}
)
_HEADER_MASK = "***REDACTED***"


def _redact_headers(headers: Any) -> dict[str, str]:
    """헤더 객체를 dict 로 변환하면서 시크릿 헤더 값을 마스킹한다.

    anthropic SDK 는 raw response 의 헤더를 ``httpx.Headers`` 로 노출한다.
    structlog 의 마스킹 processor 는 정확 일치 키만 처리하므로, ``x-api-key`` 같이
    하이픈을 포함한 헤더는 본 함수에서 명시적으로 redact 한 뒤 로깅한다.
    """
    if headers is None:
        return {}
    try:
        items = dict(headers).items()
    except (TypeError, ValueError):
        return {}
    out: dict[str, str] = {}
    for k, v in items:
        kl = str(k).lower()
        out[kl] = _HEADER_MASK if kl in _SENSITIVE_HEADER_KEYS else str(v)
    return out


def _select_rate_limit_headers(headers_dict: dict[str, str]) -> dict[str, str]:
    """anthropic rate limit / 진단 헤더만 선별한다 (debug 로그 부하 절감)."""
    out: dict[str, str] = {}
    for k, v in headers_dict.items():
        if k in _RATE_LIMIT_HEADER_KEYS or any(
            k.startswith(p) for p in _RATE_LIMIT_HEADER_PREFIXES
        ):
            out[k] = v
    return out

# ── 어조 추론 정규식 ─────────────────────────────────────────────────────────────

_KO_POLITE_RE = re.compile(r"[가-힣]+니다\b|(십시오|세요|어요|예요|네요)\b")
_KO_PLAIN_RE = re.compile(r"(한다|이다|있다|없다|간다|온다|먹는다)\b")
_JA_POLITE_RE = re.compile(r"(です|ます|でした|ました|でしょう|ましょう)")
_JA_PLAIN_RE = re.compile(r"(だ。|である|だった|していた)")


def _log_response_headers(headers: Any, *, status: str, model: str) -> None:
    """anthropic 응답 헤더에서 rate limit 진단 정보를 debug 레벨로 기록한다.

    LOG_LEVEL=DEBUG 일 때만 logs/backend/app.log 에 적재된다 (운영 기본은 INFO).
    """
    redacted = _redact_headers(headers)
    rate_only = _select_rate_limit_headers(redacted)
    logger.debug(
        "claude.api.response_headers",
        status=status,
        model=model,
        **rate_only,
    )


def _log_exception_headers(exc: APIError, *, status: str, model: str) -> None:
    """anthropic 예외 객체에 노출된 response 헤더를 같은 형식으로 기록한다."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if headers is None:
        return
    _log_response_headers(headers, status=status, model=model)


def _extract_retry_after_seconds(exc: AnthropicRateLimitError) -> float | None:
    """anthropic 429 응답의 retry-after 헤더를 초 단위 float 로 추출한다.

    우선순위: ``retry-after-ms`` (밀리초) → ``retry-after`` (초). 둘 다 없거나
    파싱 실패면 None 을 반환해 호출자가 자체 backoff 정책으로 fallback 한다.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    raw_ms = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
    if raw_ms is not None:
        try:
            return max(0.0, float(raw_ms) / 1000.0)
        except (TypeError, ValueError):
            pass
    raw_s = headers.get("retry-after") or headers.get("Retry-After")
    if raw_s is not None:
        try:
            return max(0.0, float(raw_s))
        except (TypeError, ValueError):
            pass
    return None


def _infer_register(lang: str, cues_text: list[str]) -> str:
    """cue 본문 전체에서 다수결로 어조를 추론한다.

    Args:
        lang: 언어 코드 ('ko' 또는 'ja').
        cues_text: 번역 대상 cue 본문 목록.

    Returns:
        'polite' (정중체) 또는 'plain' (평어/한다체). 동수 시 'polite' 반환.
    """
    polite = 0
    plain = 0
    for t in cues_text:
        if lang == "ko":
            polite += len(_KO_POLITE_RE.findall(t))
            plain += len(_KO_PLAIN_RE.findall(t))
        elif lang == "ja":
            polite += len(_JA_POLITE_RE.findall(t))
            plain += len(_JA_PLAIN_RE.findall(t))
    return "polite" if polite >= plain else "plain"


def _register_instruction(lang: str, register: str) -> str:
    """어조 라벨을 해당 언어의 설명 문자열로 변환한다.

    Args:
        lang: 번역 목표 언어 코드.
        register: 'polite' 또는 'plain'.

    Returns:
        시스템 프롬프트에 삽입할 어조 설명 문자열.
    """
    if lang == "ko":
        return "정중체(합니다/세요)" if register == "polite" else "평어/한다체(한다/이다)"
    if lang == "ja":
        return "丁寧体(です・ます調)" if register == "polite" else "普通体(だ・である調)"
    return register


def _build_prompt(chunk: TranslationChunk) -> tuple[str, str]:
    """system / user 메시지 페어를 생성한다.

    원문 cue 본문에서 어조를 추론하고, 번역 결과의 어조를 시스템 프롬프트에 명시한다.
    context_before / context_after는 user 메시지에 포함되어 model이 참고하지만
    번역 결과(cues)에는 포함되지 않는다.

    Args:
        chunk: 번역 요청 묶음.

    Returns:
        (system, user) 문자열 페어.
    """
    source_register = _infer_register(chunk.source_lang, [c.text for c in chunk.cues])
    target_reg_label = _register_instruction(chunk.target_lang, source_register)

    system = (
        f"당신은 영상 자막 번역 전문가입니다.\n"
        f"원본 언어: {chunk.source_lang}, 번역 언어: {chunk.target_lang}.\n"
        f"원문의 어조를 보존하여 번역 결과는 반드시 {target_reg_label}로 작성하세요.\n"
        "JSON으로만 응답하세요. 각 cue는 {\"sequence\": <int>, \"text\": <string>} 형식으로 "
        "출력하고, 최상위 키는 \"cues\"로 감싸주세요."
    )

    cues_json = [{"sequence": c.sequence, "text": c.text} for c in chunk.cues]
    ctx_before = [{"sequence": c.sequence, "text": c.text} for c in chunk.context_before]
    ctx_after = [{"sequence": c.sequence, "text": c.text} for c in chunk.context_after]

    user = json.dumps(
        {
            "context_before": ctx_before,
            "cues": cues_json,
            "context_after": ctx_after,
        },
        ensure_ascii=False,
    )
    return system, user


class ClaudeTranslationAdapter:
    """Claude API 기반 번역 provider 구현체.

    anthropic SDK 결합의 유일한 지점이다. 본 클래스 외부에서 SDK를 import하면 ADR 0001 위반.

    translate_chunk() 의 반환값은 TranslatedChunk 이며,
    Claude 응답 JSON의 cue 수가 입력과 불일치하면 ProviderPermanentError를 발생시킨다.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        oauth_token: str = "",
        model: str,
        provider_id: str = "claude:premium-seat",
    ) -> None:
        """어댑터를 초기화한다.

        Args:
            api_key: Anthropic API 키 (`x-api-key` 헤더로 전송).
            oauth_token: Claude Code OAuth 토큰 (`Authorization: Bearer` 헤더로 전송).
                값이 있으면 api_key보다 우선한다. 둘 다 비어 있으면 ValueError.
            model: 호출할 Claude 모델 이름 (예: 'claude-opus-4-7-20250514').
            provider_id: TranslatedChunk.provider_id 에 기록되는 식별자.

        Raises:
            ValueError: api_key와 oauth_token이 모두 비어 있을 때.
        """
        # max_retries=0 — SDK 자체 retry 비활성화. 429/5xx 재시도는 Celery
        # translate_task (FR-015: 1s/2s/4s/8s backoff) 단일 계층에 위임한다.
        # SDK 내부 retry 가 활성화되면 한 번의 _execute 동안 0.4~0.9s 간격으로
        # 다발성 호출이 발생해 Anthropic rate limit 회복 윈도우를 잠식하고,
        # Celery countdown 의도를 무효화한다.
        if oauth_token:
            self._client = AsyncAnthropic(
                auth_token=oauth_token, api_key=None, max_retries=0
            )
        elif api_key:
            self._client = AsyncAnthropic(api_key=api_key, max_retries=0)
        else:
            raise ValueError(
                "Claude 인증 정보가 없습니다: ANTHROPIC_API_KEY 또는 "
                "CLAUDE_CODE_OAUTH_TOKEN 중 하나는 설정되어야 합니다."
            )
        self._model = model
        self._provider_id = provider_id

    async def translate_chunk(self, chunk: TranslationChunk) -> TranslatedChunk:
        """단일 청크를 Claude API로 번역한다.

        Args:
            chunk: 번역 요청 묶음.

        Returns:
            번역된 cue 목록과 provider/model 정보를 담은 TranslatedChunk.

        Raises:
            ProviderRateLimitError: Claude rate limit 초과 (재시도 가능).
            ProviderTransientError: 네트워크 오류, 5xx 오류 등 일시적 오류 (재시도 가능).
            ProviderPermanentError: 인증 실패, 잘못된 요청, 응답 파싱 실패 등 복구 불가 오류.
        """
        system, user = _build_prompt(chunk)
        # 호출 진입 시 의도(요청 메타)를 debug 로 남긴다 — request 헤더 자체는
        # SDK 내부에서 조립되므로 외부에서 직접 접근하지 않고 모델/길이 정도만 기록.
        logger.debug(
            "claude.api.request",
            model=self._model,
            max_tokens=4096,
            source_lang=chunk.source_lang,
            target_lang=chunk.target_lang,
            cue_count=len(chunk.cues),
            user_payload_chars=len(user),
        )
        try:
            # with_raw_response — 응답 헤더(anthropic-ratelimit-*, retry-after, request-id)
            # 에 접근하기 위해 raw API 사용. parse() 로 기존 Message 객체와 동일하게 처리.
            raw = await self._client.messages.with_raw_response.create(
                model=self._model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except AnthropicRateLimitError as exc:
            _log_exception_headers(exc, status="rate_limited", model=self._model)
            raise ProviderRateLimitError(
                "Claude rate limit 초과",
                retry_after_seconds=_extract_retry_after_seconds(exc),
            ) from exc
        except APIConnectionError as exc:
            raise ProviderTransientError("Claude 연결 오류") from exc
        except (AuthenticationError, PermissionDeniedError, BadRequestError, NotFoundError) as exc:
            _log_exception_headers(exc, status="permanent_error", model=self._model)
            raise ProviderPermanentError(f"Claude 영구 오류: {type(exc).__name__}") from exc
        except APIStatusError as exc:
            _log_exception_headers(exc, status=f"http_{exc.status_code}", model=self._model)
            if 500 <= exc.status_code < 600:
                raise ProviderTransientError(f"Claude 5xx 오류: {exc.status_code}") from exc
            raise ProviderPermanentError(f"Claude {exc.status_code} 오류") from exc
        except APIError as exc:
            raise ProviderTransientError("Claude API 오류") from exc

        # 정상 응답 — 헤더에서 rate limit 잔여 정보 등 debug 로깅 후 parse().
        _log_response_headers(raw.headers, status="ok", model=self._model)
        response = raw.parse()

        # 응답 파싱
        text_block = response.content[0]
        if text_block.type != "text":
            raise ProviderPermanentError(
                f"Claude 응답 블록 타입 불일치: {text_block.type!r}"
            )

        try:
            parsed = json.loads(text_block.text)
            # 'cues' 또는 'translated_cues' 키를 허용
            translated_seq: list[dict[str, object]] = (
                parsed.get("cues") or parsed.get("translated_cues") or []
            )
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise ProviderPermanentError("Claude 응답 JSON 파싱 실패") from exc

        cue_lookup = {c.sequence: c for c in chunk.cues}
        out: list[TranslatedCue] = []
        try:
            for item in translated_seq:
                raw_seq = item["sequence"]
                seq = int(raw_seq) if isinstance(raw_seq, (int, float, str)) else 0
                src = cue_lookup.get(seq)
                if src is None:
                    continue
                out.append(
                    TranslatedCue(
                        sequence=seq,
                        start_ms=src.start_ms,
                        end_ms=src.end_ms,
                        text=str(item["text"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderPermanentError("Malformed translation response") from exc

        if len(out) != len(chunk.cues):
            raise ProviderPermanentError(
                f"번역 cue 수 불일치: 수신 {len(out)}개, 기대 {len(chunk.cues)}개"
            )

        return TranslatedChunk(
            cues=out,
            provider_id=self._provider_id,
            model=self._model,
        )
