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

# ── 어조 추론 정규식 ─────────────────────────────────────────────────────────────

_KO_POLITE_RE = re.compile(r"(습니다|입니다|십시오|세요|어요|예요|네요)\b")
_KO_PLAIN_RE = re.compile(r"(다\.|한다|이다|있다|없다|간다|온다|먹는다)")
_JA_POLITE_RE = re.compile(r"(です|ます|でした|ました|でしょう|ましょう)")
_JA_PLAIN_RE = re.compile(r"(だ。|である|だった|していた)")


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
        api_key: str,
        model: str,
        provider_id: str = "claude:premium-seat",
    ) -> None:
        """어댑터를 초기화한다.

        Args:
            api_key: Anthropic API 키.
            model: 호출할 Claude 모델 이름 (예: 'claude-opus-4-7-20250514').
            provider_id: TranslatedChunk.provider_id 에 기록되는 식별자.
        """
        self._client = AsyncAnthropic(api_key=api_key)
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
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except AnthropicRateLimitError as exc:
            raise ProviderRateLimitError("Claude rate limit 초과") from exc
        except APIConnectionError as exc:
            raise ProviderTransientError("Claude 연결 오류") from exc
        except (AuthenticationError, PermissionDeniedError, BadRequestError, NotFoundError) as exc:
            raise ProviderPermanentError(f"Claude 영구 오류: {type(exc).__name__}") from exc
        except APIStatusError as exc:
            if 500 <= exc.status_code < 600:
                raise ProviderTransientError(f"Claude 5xx 오류: {exc.status_code}") from exc
            raise ProviderPermanentError(f"Claude {exc.status_code} 오류") from exc
        except APIError as exc:
            raise ProviderTransientError("Claude API 오류") from exc

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

        if len(out) != len(chunk.cues):
            raise ProviderPermanentError(
                f"번역 cue 수 불일치: 수신 {len(out)}개, 기대 {len(chunk.cues)}개"
            )

        return TranslatedChunk(
            cues=out,
            provider_id=self._provider_id,
            model=self._model,
        )
