"""T062: Claude 어댑터 순수 헬퍼 단위 테스트 — SDK 호출 없음.

검증 항목:
- _infer_register: JA 정중체/평어, KO 정중체/평어, 혼재(다수결), 동수(정중체 우선)
- _register_instruction: 언어별 어조 설명 문자열 반환
- _build_prompt: system/user 메시지 구조 검증
"""

from __future__ import annotations

import json

from app.domain.translation.provider import ChunkCue, TranslationChunk
from app.infrastructure.providers.claude_adapter import (
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
