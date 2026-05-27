# ADR 0003 — 응답 Envelope 구조 (Nested 채택)

| 항목 | 내용 |
|---|---|
| **상태** | 채택됨 (Accepted) — 2026-05-28 |
| **결정자** | 프로젝트 팀 |
| **관련 헌법** | 헌법 §API 표준 (v1.0.1 PATCH) — 본 ADR과 짝을 이룬다 |

---

## 컨텍스트

헌법 §API 표준은 모든 응답이 다음 정보를 포함하는 envelope을 사용한다고 명시한다.

> 성공 여부(`success`), 성공 시 페이로드(`data`) 또는 실패 시 에러 상세(`error`),
> 요청 추적 ID(`request_id`).

헌법 본문은 의미 수준의 요구로 작성되어 있어, 실제 구조를 **flat** (예:
`{success, data?, error_code, message, details?, request_id}`) 으로 둘지
**nested** (예: `{success, data?, error: {code, message, details?}, request_id}`)
로 둘지에 대한 결정이 남아 있었다.

[contracts/openapi.yaml](../../specs/001-dual-subtitle-mvp/contracts/openapi.yaml) 의
`ErrorEnvelope` / `ErrorBody` 스키마는 **nested 표현**을 채택하고 있고, FastAPI
예외 핸들러([backend/app/core/exceptions.py](../../backend/app/core/exceptions.py))
및 모든 통합 테스트가 이 nested 구조에 의존한다. 헌법 문구와의 표현 차이가 새로운 기여자에게
혼동을 줄 수 있으므로, 어느 구조를 정식으로 사용하며 어떻게 헌법 문구와 정합시킬지 명문화할 필요가 있다.

---

## 결정

**Nested 구조를 정식으로 채택한다.**

성공 응답:

```json
{
  "success": true,
  "data": { "...": "..." },
  "request_id": "01HXYZ..."
}
```

실패 응답:

```json
{
  "success": false,
  "error": {
    "code": "INVALID_URL",
    "message": "허용되지 않는 URL입니다",
    "details": { "...": "..." }
  },
  "request_id": "01HXYZ..."
}
```

헌법 §API 표준의 "success / error_code / message / request_id" 표현은
**"응답이 success · error 정보 · request_id를 모두 포함해야 한다"**는
의미적 요구로 해석하며, nested 구조는 그 의미를 만족한다고 본다.

이 해석은 헌법 v1.0.1 PATCH 본문에 명시되었다 (헌법 문구의
"flat vs nested 구체 구조는 feature ADR에서 결정한다" 부분, 본 ADR 참조).

---

## 이유

- **OpenAPI 표현이 자연스럽다**: `responses.4xx.content.application/json.schema`
  를 `oneOf: [SuccessEnvelope, ErrorEnvelope]` 로 표현하기 위해 error 필드를 단일 객체로 묶는 편이
  스키마가 깔끔하다. flat 표현은 `error_code` / `message` / `details` 가 nullable / 선택적
  필드로 흩어져 표현이 복잡해진다.
- **TypeScript 타입 자동 생성에 유리**: `openapi-typescript` 산출 결과가
  `{ success: false; error: ErrorBody; ... } | { success: true; data: T; ... }` 형태의
  discriminated union이 되어 클라이언트에서 `if (resp.success)` 단일 분기로 타입 좁히기가 가능하다.
- **확장성**: `error.details` 필드 안에 분류 / 컨텍스트 / 재시도 힌트 등을 자유롭게 확장할 수 있다.
  flat 구조는 추가 필드가 envelope 최상위에 노출되어 키 충돌 위험이 있다.
- **에러와 메타데이터의 분리**: `success` / `request_id` 는 모든 응답의 공통 메타이고,
  `error` / `data` 는 결과 본문이다. nested 구조는 이 두 layer를 명확히 구분한다.

---

## 결과

### 긍정적 결과

- 클라이언트 코드에서 `resp.success` 만 확인하면 TypeScript 컴파일러가 `data` / `error` 접근 가능 여부를 자동으로 좁힌다.
- 에러 분류 / 추가 컨텍스트를 `error.details` 로 확장해도 envelope 최상위 스키마는 그대로 유지된다.
- OpenAPI 스키마 정의가 짧고 명확해진다.

### 부정적 결과 / 트레이드오프

- 헌법 본문의 표현(`error_code` / `message` 가 envelope에 직접 있는 듯한 어조)과 실 구조가
  표면적으로 다르므로, 신규 기여자가 헌법만 보면 혼동할 수 있다 → **본 ADR과
  헌법 §API 표준 단락의 추가 문구로 해결**.
- 에러 응답 접근 시 `body.error.code` 처럼 한 단계 더 들어가야 한다 (vs `body.error_code`).

---

## 대안 검토

| 대안 | 기각 이유 |
|---|---|
| Flat envelope (`{success, data?, error_code, message, details?, request_id}`) | TypeScript discriminated union 표현이 어색하고, `details` 확장 시 envelope 최상위가 지저분해진다 |
| `success` 필드 제거 + HTTP status로만 분기 | 422 / 429 등 상태 코드 외에 비즈니스 분기가 추가되면 success boolean이 다시 필요해진다 |
| 별도 `meta` 객체에 `request_id` 분리 | 단순성 우선(헌법 III) — request_id 하나만을 위해 wrapper 객체를 추가하지 않는다 |

---

## 참조

- [contracts/openapi.yaml — ErrorEnvelope / ErrorBody / SuccessEnvelope 스키마](../../specs/001-dual-subtitle-mvp/contracts/openapi.yaml)
- [backend/app/core/exceptions.py — `_domain_error_handler` 의 nested 직렬화](../../backend/app/core/exceptions.py)
- [backend/app/api/v1/envelope.py — `success_envelope` 헬퍼](../../backend/app/api/v1/envelope.py)
- [헌법 v1.0.1 §API 표준](../../.specify/memory/constitution.md)
- [backend/tests/integration/test_failure_envelope.py — SC-008 envelope coverage 테스트 (T130)](../../backend/tests/integration/test_failure_envelope.py)
