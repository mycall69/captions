"""T062: Claude 어댑터 순수 헬퍼 단위 테스트 — SDK 호출 없음.

검증 항목:
- _infer_register: JA 정중체/평어, KO 정중체/평어, 혼재(다수결), 동수(정중체 우선)
- _register_instruction: 언어별 어조 설명 문자열 반환
- _build_prompt: system/user 메시지 구조 검증
- ClaudeTranslationAdapter.translate_chunk: 예외 매핑 검증
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from anthropic import RateLimitError as AnthropicRateLimitError
from anthropic._exceptions import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
)

from app.domain.translation.provider import (
    ChunkCue,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderTransientError,
    TranslatedChunk,
    TranslationChunk,
)
from app.infrastructure.providers.claude_adapter import (
    ClaudeTranslationAdapter,
    _build_prompt,
    _infer_register,
    _register_instruction,
)


def _make_chunk(
    cues_text: list[str],
    source_lang: str = "ko",
    target_lang: str = "ja",
) -> TranslationChunk:
    """어조 추론 테스트용 TranslationChunk 생성 헬퍼."""
    return TranslationChunk(
        source_lang=source_lang,  # type: ignore[arg-type]
        target_lang=target_lang,  # type: ignore[arg-type]
        cues=[
            ChunkCue(
                sequence=i + 1,
                start_ms=i * 3000,
                end_ms=i * 3000 + 2900,
                text=t,
            )
            for i, t in enumerate(cues_text)
        ],
    )


class TestInferRegisterJapanese:
    """JA 어조 추론 — 丁寧体 vs 普通体."""

    def test_ja_polite_majority(self) -> None:
        """です・ます형이 다수이면 'polite'를 반환해야 한다."""
        texts = ["行きます", "食べます", "です", "だ。"]
        assert _infer_register("ja", texts) == "polite"

    def test_ja_plain_majority(self) -> None:
        """だ・である형이 다수이면 'plain'을 반환해야 한다."""
        texts = ["行くだ。", "食べるである", "していた", "です"]
        assert _infer_register("ja", texts) == "plain"

    def test_ja_polite_tie_defaults_to_polite(self) -> None:
        """정중·평어 매칭 수가 동수이면 'polite'를 반환해야 한다 (동수 시 정중체 우선)."""
        texts = ["です", "だ。"]
        assert _infer_register("ja", texts) == "polite"

    def test_ja_no_markers_defaults_to_polite(self) -> None:
        """어조 마커가 없으면 'polite'를 반환해야 한다 (0 >= 0 → polite)."""
        texts = ["今日は天気がいい", "映画を見た"]
        assert _infer_register("ja", texts) == "polite"


class TestInferRegisterKorean:
    """KO 어조 추론 — 정중체 vs 평어/한다체."""

    def test_ko_polite_majority(self) -> None:
        """합니다/세요형이 다수이면 'polite'를 반환해야 한다."""
        texts = ["안녕하세요", "잘 지내십니까", "감사합니다"]
        assert _infer_register("ko", texts) == "polite"

    def test_ko_plain_majority(self) -> None:
        """한다/이다형이 다수이면 'plain'을 반환해야 한다."""
        texts = ["학교에 간다", "밥을 먹는다", "나는 학생이다", "세요"]
        assert _infer_register("ko", texts) == "plain"

    def test_ko_mixed_majority_wins(self) -> None:
        """혼재 시 더 많이 매칭되는 어조가 승리해야 한다."""
        # 정중체 3개, 평어 1개 → polite
        texts = ["합니다", "입니다", "세요", "한다"]
        assert _infer_register("ko", texts) == "polite"

    def test_ko_polite_tie_defaults_to_polite(self) -> None:
        """동수 시 'polite'를 반환해야 한다."""
        texts = ["세요", "한다"]
        assert _infer_register("ko", texts) == "polite"


class TestInferRegisterUnknownLang:
    """지원하지 않는 언어에 대한 기본 동작."""

    def test_unknown_lang_defaults_to_polite(self) -> None:
        """알 수 없는 언어는 항상 'polite'를 반환해야 한다 (0 >= 0)."""
        assert _infer_register("zh", ["你好", "再见"]) == "polite"


class TestRegisterInstruction:
    """_register_instruction 반환값 검증."""

    def test_ko_polite_label(self) -> None:
        """KO 정중체 레이블은 '정중체(합니다/세요)'를 포함해야 한다."""
        result = _register_instruction("ko", "polite")
        assert "정중체" in result
        assert "합니다" in result

    def test_ko_plain_label(self) -> None:
        """KO 평어 레이블은 '평어/한다체'를 포함해야 한다."""
        result = _register_instruction("ko", "plain")
        assert "한다" in result or "평어" in result

    def test_ja_polite_label(self) -> None:
        """JA 정중체 레이블은 '丁寧体'와 'です' 를 포함해야 한다."""
        result = _register_instruction("ja", "polite")
        assert "丁寧体" in result
        assert "です" in result

    def test_ja_plain_label(self) -> None:
        """JA 평어 레이블은 '普通体'와 'だ'를 포함해야 한다."""
        result = _register_instruction("ja", "plain")
        assert "普通体" in result
        assert "だ" in result

    def test_unknown_lang_returns_register_as_is(self) -> None:
        """알 수 없는 언어는 register 값을 그대로 반환해야 한다."""
        assert _register_instruction("zh", "polite") == "polite"
        assert _register_instruction("zh", "plain") == "plain"


class TestBuildPrompt:
    """_build_prompt system/user 메시지 구조 검증."""

    def test_system_contains_source_and_target_lang(self) -> None:
        """시스템 메시지에 source_lang과 target_lang이 포함되어야 한다."""
        chunk = _make_chunk(["안녕하세요"], source_lang="ko", target_lang="ja")
        system, _ = _build_prompt(chunk)
        assert "ko" in system
        assert "ja" in system

    def test_system_contains_register_instruction(self) -> None:
        """시스템 메시지에 어조 지시문이 포함되어야 한다."""
        chunk = _make_chunk(["안녕하세요", "감사합니다"], source_lang="ko", target_lang="ja")
        system, _ = _build_prompt(chunk)
        # 정중체 패턴이 포함되어 있으므로 정중체 지시문 포함 기대
        assert "정중체" in system or "丁寧体" in system or "평어" in system or "普通体" in system

    def test_user_contains_cues_json(self) -> None:
        """user 메시지에 번역 대상 cue의 JSON이 포함되어야 한다."""
        chunk = _make_chunk(["테스트 자막"], source_lang="ko", target_lang="ja")
        _, user = _build_prompt(chunk)
        parsed = json.loads(user)
        assert "cues" in parsed
        assert len(parsed["cues"]) == 1
        assert parsed["cues"][0]["sequence"] == 1
        assert parsed["cues"][0]["text"] == "테스트 자막"

    def test_user_contains_context_keys(self) -> None:
        """user 메시지에 context_before / context_after 키가 존재해야 한다."""
        chunk = _make_chunk(["자막 1", "자막 2"], source_lang="ko", target_lang="ja")
        _, user = _build_prompt(chunk)
        parsed = json.loads(user)
        assert "context_before" in parsed
        assert "context_after" in parsed

    def test_user_is_valid_json(self) -> None:
        """user 메시지는 유효한 JSON 문자열이어야 한다."""
        chunk = _make_chunk(["안녕"], source_lang="ko", target_lang="ja")
        _, user = _build_prompt(chunk)
        # json.loads 예외 없이 파싱되어야 함
        parsed = json.loads(user)
        assert isinstance(parsed, dict)


# ── 추가 어조 추론 테스트 (합니다/됩니다 등 FR-014 보완) ─────────────────────────────


class TestInferRegisterKoreanPoliteExtended:
    """KO 정중체 추론 — 합니다/됩니다/갑니다 등 확장 패턴 검증."""

    def test_ko_gamsahamnida_is_polite(self) -> None:
        """'감사합니다.' 는 정중체로 판정해야 한다 (합니다 패턴)."""
        assert _infer_register("ko", ["감사합니다."]) == "polite"

    def test_ko_good_day_seyo_is_polite(self) -> None:
        """'좋은 하루 보내세요.' 는 정중체로 판정해야 한다 (세요 패턴)."""
        assert _infer_register("ko", ["좋은 하루 보내세요."]) == "polite"

    def test_ko_gamnida_is_polite(self) -> None:
        """'공원에 갑니다.' 는 정중체로 판정해야 한다 (합니다 → 갑니다 ⊂ 습니다 패턴)."""
        assert _infer_register("ko", ["공원에 갑니다."]) == "polite"

    def test_ko_doemnida_is_polite(self) -> None:
        """'됩니다' 는 정중체로 판정해야 한다."""
        assert _infer_register("ko", ["됩니다"]) == "polite"

    def test_ko_deurimnida_is_polite(self) -> None:
        """'드립니다' 는 정중체로 판정해야 한다."""
        assert _infer_register("ko", ["말씀드립니다."]) == "polite"


class TestInferRegisterJapaneseExtended:
    """JA 어조 추론 — 丁寧体/普通体 패리티 검증."""

    def test_ja_ikimasu_is_polite(self) -> None:
        """'明日行きます。' 는 정중체(丁寧体)로 판정해야 한다."""
        assert _infer_register("ja", ["明日行きます。"]) == "polite"

    def test_ja_da_is_plain(self) -> None:
        """'だ。' 종결형 문장은 平語体(普通体)로 판정해야 한다."""
        assert _infer_register("ja", ["明日行くだ。"]) == "plain"


# ── ClaudeTranslationAdapter.translate_chunk 예외 매핑 테스트 ───────────────────


def _a_chunk() -> TranslationChunk:
    """번역 어댑터 테스트용 단일 cue TranslationChunk 생성 헬퍼."""
    return TranslationChunk(
        source_lang="ko",  # type: ignore[arg-type]
        target_lang="ja",  # type: ignore[arg-type]
        cues=[ChunkCue(sequence=1, start_ms=0, end_ms=3000, text="안녕하세요")],
    )


def _make_adapter() -> ClaudeTranslationAdapter:
    """테스트용 ClaudeTranslationAdapter 인스턴스 생성 (실제 API 호출 없음)."""
    return ClaudeTranslationAdapter(api_key="test-key", model="claude-opus-4-7")


def _mock_request() -> Mock:
    """anthropic 예외 생성에 필요한 최소 httpx.Request mock."""
    return Mock(spec=httpx.Request)


def _mock_response(status_code: int) -> Mock:
    """anthropic 예외 생성에 필요한 최소 httpx.Response mock."""
    r = Mock(spec=httpx.Response)
    r.status_code = status_code
    r.headers = {}
    r.request = _mock_request()
    return r


def _wrap_as_raw(message_obj: object) -> Mock:
    """``with_raw_response.create()`` 가 돌려주는 raw wrapper 의 최소 mock.

    어댑터는 ``raw.headers`` 를 읽고 ``raw.parse()`` 로 Message 를 추출한다.
    """
    raw = Mock()
    raw.headers = {}
    raw.parse = Mock(return_value=message_obj)
    return raw


class TestClaudeAdapterHeaderLogging:
    """anthropic 응답 헤더(rate limit / request-id) 가 debug 로그로 기록되어야 한다.

    structlog logger.debug 를 직접 spy 해 인자 구조를 검증한다 (caplog 는 structlog
    bind 와 결합이 약해 호출 인자를 안정적으로 캡처하지 못한다).
    """

    @pytest.mark.asyncio
    async def test_response_headers_logged_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """정상 응답 시 anthropic-ratelimit-* 헤더 + request-id 가 debug 호출에 포함되어야 한다."""
        from app.infrastructure.providers import claude_adapter as adapter_mod

        debug_calls: list[tuple[str, dict[str, object]]] = []

        def _spy(event: str, **kwargs: object) -> None:
            debug_calls.append((event, kwargs))

        monkeypatch.setattr(adapter_mod.logger, "debug", _spy)

        adapter = _make_adapter()
        mock_client = AsyncMock()
        mock_content = Mock()
        mock_content.type = "text"
        mock_content.text = json.dumps({"cues": [{"sequence": 1, "text": "こんにちは"}]})
        mock_response_obj = Mock()
        mock_response_obj.content = [mock_content]

        raw = Mock()
        raw.headers = {
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "0",
            "request-id": "req_test_001",
            "x-api-key": "secret-key-should-be-redacted",
        }
        raw.parse = Mock(return_value=mock_response_obj)
        mock_client.messages.with_raw_response.create.return_value = raw
        adapter._client = mock_client

        await adapter.translate_chunk(_a_chunk())

        header_events = [c for c in debug_calls if c[0] == "claude.api.response_headers"]
        assert header_events, "claude.api.response_headers debug 호출이 한 번 이상 있어야 합니다"
        kwargs = header_events[-1][1]
        assert kwargs.get("status") == "ok"
        assert kwargs.get("anthropic-ratelimit-requests-limit") == "50"
        assert kwargs.get("anthropic-ratelimit-requests-remaining") == "0"
        assert kwargs.get("request-id") == "req_test_001"
        # x-api-key 는 rate-limit 헤더 화이트리스트에 없어 아예 노출 안 되거나
        # (현재 구현), 노출되더라도 평문이 아니어야 한다.
        assert kwargs.get("x-api-key") in (None, "***REDACTED***")

    @pytest.mark.asyncio
    async def test_response_headers_logged_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """429 발생 시에도 anthropic 응답 헤더가 debug 호출로 기록되어야 한다."""
        from app.infrastructure.providers import claude_adapter as adapter_mod

        debug_calls: list[tuple[str, dict[str, object]]] = []

        def _spy(event: str, **kwargs: object) -> None:
            debug_calls.append((event, kwargs))

        monkeypatch.setattr(adapter_mod.logger, "debug", _spy)

        adapter = _make_adapter()
        mock_client = AsyncMock()
        response = _mock_response(429)
        response.headers = {
            "anthropic-ratelimit-requests-remaining": "0",
            "retry-after-ms": "5000",
        }
        mock_client.messages.with_raw_response.create.side_effect = AnthropicRateLimitError(
            message="rate limited", response=response, body=None
        )
        adapter._client = mock_client

        with pytest.raises(ProviderRateLimitError):
            await adapter.translate_chunk(_a_chunk())

        header_events = [c for c in debug_calls if c[0] == "claude.api.response_headers"]
        assert header_events, "429 케이스에서도 헤더 로깅이 있어야 합니다"
        kwargs = header_events[-1][1]
        assert kwargs.get("status") == "rate_limited"
        assert kwargs.get("retry-after-ms") == "5000"
        assert kwargs.get("anthropic-ratelimit-requests-remaining") == "0"


class TestClaudeAdapterSdkRetryDisabled:
    """SDK 자체 retry 가 비활성화되어 있어야 한다 (FR-015: retry 권한은 Celery 단일 계층).

    회귀 방지: SDK 가 자체적으로 429/5xx 를 retry 하면 한 번의 _execute 호출이 0.4~0.9s
    간격으로 다발성 호출을 발사해 Anthropic rate limit 회복 윈도우를 잠식한다.
    """

    def test_async_anthropic_constructed_with_max_retries_zero_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api_key 인증 경로에서 max_retries=0 이 SDK 에 전달되어야 한다."""
        recorded: dict[str, object] = {}

        def _spy(**kwargs: object) -> Mock:
            recorded.update(kwargs)
            return Mock()

        monkeypatch.setattr(
            "app.infrastructure.providers.claude_adapter.AsyncAnthropic", _spy
        )
        ClaudeTranslationAdapter(api_key="test-key", model="claude-opus-4-7")
        assert recorded.get("max_retries") == 0

    def test_async_anthropic_constructed_with_max_retries_zero_oauth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """oauth_token 인증 경로에서도 max_retries=0 이 SDK 에 전달되어야 한다."""
        recorded: dict[str, object] = {}

        def _spy(**kwargs: object) -> Mock:
            recorded.update(kwargs)
            return Mock()

        monkeypatch.setattr(
            "app.infrastructure.providers.claude_adapter.AsyncAnthropic", _spy
        )
        ClaudeTranslationAdapter(oauth_token="test-token", model="claude-opus-4-7")  # noqa: S106
        assert recorded.get("max_retries") == 0


class TestClaudeAdapterExceptionMapping:
    """translate_chunk 가 anthropic 예외를 provider 예외로 올바르게 매핑하는지 검증."""

    @pytest.mark.asyncio
    async def test_rate_limit_error_maps_to_provider_rate_limit(self) -> None:
        """anthropic.RateLimitError → ProviderRateLimitError."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        mock_client.messages.with_raw_response.create.side_effect = AnthropicRateLimitError(
            message="rate limited",
            response=_mock_response(429),
            body=None,
        )
        adapter._client = mock_client

        with pytest.raises(ProviderRateLimitError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_rate_limit_extracts_retry_after_ms_header(self) -> None:
        """429 응답의 retry-after-ms 헤더가 retry_after_seconds 에 초 단위로 노출되어야 한다."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        response = _mock_response(429)
        response.headers = {"retry-after-ms": "8500"}
        mock_client.messages.with_raw_response.create.side_effect = AnthropicRateLimitError(
            message="rate limited", response=response, body=None
        )
        adapter._client = mock_client

        with pytest.raises(ProviderRateLimitError) as exc_info:
            await adapter.translate_chunk(_a_chunk())
        assert exc_info.value.retry_after_seconds == pytest.approx(8.5)

    @pytest.mark.asyncio
    async def test_rate_limit_extracts_retry_after_seconds_header(self) -> None:
        """retry-after-ms 가 없으면 retry-after (초) 헤더로 fallback 해야 한다."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        response = _mock_response(429)
        response.headers = {"retry-after": "15"}
        mock_client.messages.with_raw_response.create.side_effect = AnthropicRateLimitError(
            message="rate limited", response=response, body=None
        )
        adapter._client = mock_client

        with pytest.raises(ProviderRateLimitError) as exc_info:
            await adapter.translate_chunk(_a_chunk())
        assert exc_info.value.retry_after_seconds == pytest.approx(15.0)

    @pytest.mark.asyncio
    async def test_rate_limit_no_header_yields_none_hint(self) -> None:
        """retry-after 헤더가 없으면 retry_after_seconds 는 None 이어야 한다 (fallback 트리거)."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        # _mock_response(429) 의 기본 headers={} 사용
        mock_client.messages.with_raw_response.create.side_effect = AnthropicRateLimitError(
            message="rate limited",
            response=_mock_response(429),
            body=None,
        )
        adapter._client = mock_client

        with pytest.raises(ProviderRateLimitError) as exc_info:
            await adapter.translate_chunk(_a_chunk())
        assert exc_info.value.retry_after_seconds is None

    @pytest.mark.asyncio
    async def test_api_connection_error_maps_to_provider_transient(self) -> None:
        """anthropic.APIConnectionError → ProviderTransientError."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        mock_client.messages.with_raw_response.create.side_effect = APIConnectionError(
            message="connection error",
            request=_mock_request(),
        )
        adapter._client = mock_client

        with pytest.raises(ProviderTransientError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_api_status_5xx_maps_to_provider_transient(self) -> None:
        """anthropic.APIStatusError(5xx) → ProviderTransientError."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        mock_client.messages.with_raw_response.create.side_effect = APIStatusError(
            message="server error",
            response=_mock_response(503),
            body=None,
        )
        adapter._client = mock_client

        with pytest.raises(ProviderTransientError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_api_status_4xx_maps_to_provider_permanent(self) -> None:
        """anthropic.APIStatusError(4xx, 인증 외) → ProviderPermanentError."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        mock_client.messages.with_raw_response.create.side_effect = APIStatusError(
            message="bad request",
            response=_mock_response(422),
            body=None,
        )
        adapter._client = mock_client

        with pytest.raises(ProviderPermanentError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_authentication_error_maps_to_provider_permanent(self) -> None:
        """anthropic.AuthenticationError → ProviderPermanentError."""
        adapter = _make_adapter()
        mock_client = AsyncMock()
        mock_client.messages.with_raw_response.create.side_effect = AuthenticationError(
            message="invalid api key",
            response=_mock_response(401),
            body=None,
        )
        adapter._client = mock_client

        with pytest.raises(ProviderPermanentError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_malformed_json_key_error_maps_to_provider_permanent(self) -> None:
        """응답 JSON에서 'sequence'/'text' 키가 누락되면 ProviderPermanentError가 발생해야 한다."""
        adapter = _make_adapter()
        mock_client = AsyncMock()

        # 'text' 키가 없는 cue 항목을 반환하는 Mock 응답
        mock_content = Mock()
        mock_content.type = "text"
        mock_content.text = json.dumps({"cues": [{"sequence": 1}]})  # 'text' 키 누락

        mock_response_obj = Mock()
        mock_response_obj.content = [mock_content]
        mock_client.messages.with_raw_response.create.return_value = _wrap_as_raw(
            mock_response_obj
        )
        adapter._client = mock_client

        with pytest.raises(ProviderPermanentError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_malformed_json_missing_sequence_maps_to_provider_permanent(self) -> None:
        """응답 JSON에서 'sequence' 키가 누락되면 ProviderPermanentError가 발생해야 한다."""
        adapter = _make_adapter()
        mock_client = AsyncMock()

        mock_content = Mock()
        mock_content.type = "text"
        mock_content.text = json.dumps({"cues": [{"text": "こんにちは"}]})  # 'sequence' 키 누락

        mock_response_obj = Mock()
        mock_response_obj.content = [mock_content]
        mock_client.messages.with_raw_response.create.return_value = _wrap_as_raw(
            mock_response_obj
        )
        adapter._client = mock_client

        with pytest.raises(ProviderPermanentError):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_cue_count_mismatch_maps_to_provider_permanent(self) -> None:
        """번역 결과 cue 수가 입력과 다르면 ProviderPermanentError가 발생해야 한다."""
        adapter = _make_adapter()
        mock_client = AsyncMock()

        # 입력 cue 수는 1이지만 결과를 0개 반환
        mock_content = Mock()
        mock_content.type = "text"
        mock_content.text = json.dumps({"cues": []})  # 빈 결과

        mock_response_obj = Mock()
        mock_response_obj.content = [mock_content]
        mock_client.messages.with_raw_response.create.return_value = _wrap_as_raw(
            mock_response_obj
        )
        adapter._client = mock_client

        with pytest.raises(ProviderPermanentError, match="cue 수 불일치"):
            await adapter.translate_chunk(_a_chunk())

    @pytest.mark.asyncio
    async def test_happy_path_returns_translated_chunk(self) -> None:
        """정상적인 Claude 응답이 올바른 TranslatedChunk로 변환되어야 한다."""
        adapter = _make_adapter()
        mock_client = AsyncMock()

        mock_content = Mock()
        mock_content.type = "text"
        mock_content.text = json.dumps(
            {"cues": [{"sequence": 1, "text": "こんにちは"}]}
        )

        mock_response_obj = Mock()
        mock_response_obj.content = [mock_content]
        mock_client.messages.with_raw_response.create.return_value = _wrap_as_raw(
            mock_response_obj
        )
        adapter._client = mock_client

        result = await adapter.translate_chunk(_a_chunk())

        assert isinstance(result, TranslatedChunk)
        assert len(result.cues) == 1
        assert result.cues[0].sequence == 1
        assert result.cues[0].text == "こんにちは"
        assert result.cues[0].start_ms == 0
        assert result.cues[0].end_ms == 3000
