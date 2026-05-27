# ADR 0001 — 번역 Provider 추상화 (Translation Provider Abstraction)

| 항목 | 내용 |
|---|---|
| **상태** | 승인됨 (2026-05-27) |
| **결정자** | 프로젝트 팀 |
| **관련 헌법** | 헌법 §Translation Provider Abstraction NON-NEGOTIABLE |

---

## 컨텍스트

이 프로젝트는 YouTube 자막을 KO↔JA로 번역하기 위해 외부 LLM API를 호출한다.
현재 사용하는 provider는 Anthropic Claude이지만, 다음과 같은 이유로 직접 결합을 피해야 한다.

1. **벤더 독립성**: Anthropic SDK가 업데이트되거나 provider를 교체할 경우, 의존하는 코드 범위가 최소화되어야 재작업 비용이 줄어든다.
2. **테스트 용이성**: 실제 API 호출 없이 `FakeTranslationProvider`로 대체해 단위·통합 테스트를 수행할 수 있어야 한다.
3. **단일 책임**: 어조(register) 보존, chunk prompt 구성, 모델 파라미터 설정은 adapter 내부에 한정되어야 한다. 도메인 서비스가 특정 provider의 SDK 개념을 알아서는 안 된다.
4. **헌법 준수**: 헌법의 "Translation Provider Abstraction NON-NEGOTIABLE" 게이트는 이 결정을 구현 레벨에서 강제한다.

---

## 결정

`app/domain/translation/provider.py`에 `TranslationProvider` Protocol을 정의한다.
모든 도메인 서비스·Celery task는 이 Protocol에만 의존하고, `anthropic` SDK를 직접 import하지 않는다.

Anthropic Claude 구현은 **단일 파일** `app/infrastructure/providers/claude_adapter.py`에만 존재하며,
해당 파일 외부에서 `import anthropic`은 금지된다.

### Protocol 인터페이스 (요약)

```python
from typing import Protocol
from app.domain.translation.models import TranslationChunk, TranslatedChunk

class TranslationProvider(Protocol):
    async def translate_chunk(
        self,
        source_lang: str,
        target_lang: str,
        cues: list[TranslationChunk],
        context_before: list[TranslationChunk],
        context_after: list[TranslationChunk],
    ) -> TranslatedChunk:
        ...
```

### 구현 구조

```
app/
  domain/
    translation/
      provider.py          ← TranslationProvider Protocol 정의
      service.py           ← Protocol 타입에만 의존
  infrastructure/
    providers/
      claude_adapter.py    ← anthropic SDK 직접 결합 유일 지점
      fake_adapter.py      ← 테스트 전용 FakeTranslationProvider
```

### 의존 방향

```
domain/translation/service.py
  └─ 의존 → TranslationProvider (Protocol)
                ↑ 구현
  app/infrastructure/providers/claude_adapter.py
  app/infrastructure/providers/fake_adapter.py
```

---

## 결과

### 긍정적 결과

- Claude 이외의 provider(예: OpenAI, local Ollama) 추가 시 `claude_adapter.py`와 동일한 구조의 파일만 추가하면 된다.
- `FakeTranslationProvider`로 번역 파이프라인 전체를 네트워크 없이 테스트할 수 있다.
- 어조 보존(register preservation) 로직, prompt 구성, temperature 설정이 한 파일에 모여 리뷰·수정이 용이하다.
- mypy strict 모드에서 Protocol 구현 누락을 컴파일 타임에 감지한다.

### 부정적 결과 / 트레이드오프

- Provider 교체 시 DI(Dependency Injection) 설정(`celery_app.py` 또는 FastAPI lifespan)을 함께 수정해야 한다.
- Protocol은 런타임 `isinstance` 검사를 지원하지 않으므로, DI 컨테이너 없이 수동 주입을 사용한다 (단순성 우선 — 헌법 III).

---

## 대안 검토

| 대안 | 기각 이유 |
|---|---|
| 도메인 서비스에서 `anthropic` SDK 직접 호출 | 테스트 불가, 벤더 결합, 헌법 위반 |
| ABC(Abstract Base Class) 사용 | Protocol이 더 가볍고, 명시적 상속 없이 structural subtyping 적용 가능 |
| 독립 provider 패키지(`captions-translation`) 분리 | 단일 호스트 MVP에서 패키지 분리는 import 그래프 복잡도를 높인다 (헌법 III 위반) |

---

## 참고

- 헌법 §Translation Provider Abstraction NON-NEGOTIABLE
- 헌법 §II Architecture First — Layered Architecture
- [plan.md](../../specs/001-dual-subtitle-mvp/plan.md) §Translation Pipeline
- [research.md](../../specs/001-dual-subtitle-mvp/research.md)
