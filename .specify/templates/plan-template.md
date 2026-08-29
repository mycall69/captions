# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Phase 0 전 통과 필수. Phase 1 설계 후 재검토.*

`.specify/memory/constitution.md` v1.1.0에서 도출한 게이트. 각 항목은 예/아니오
질문이며, "아니오"는 아래 Complexity Tracking에 사유와 함께 기록해야 한다.

- **SDD First (I)**: PRD / Domain Model / API Contract / UX Flow / Sequence Diagram / Acceptance Criteria / Test Specification이 존재하거나 Phase 1 산출물로 예정되어 있는가?
- **Architecture First (II)**:
  - Layered architecture(API → Service → Domain → Infrastructure)를 따르는가?
  - 장기 작업은 Celery로 디스패치되는가(동기 blocking endpoint 없음)?
  - API는 stateless인가?
- **AI-Native Development (III)**: 모듈이 작고 단일 목적이며 self-documenting한 이름을 갖는가? giant file 계획 없음?
- **macOS Native Development (IV)**: Docker 없이 macOS(Apple Silicon, Homebrew, `venv`)에서 end-to-end 동작하는가?
- **Korean-First Documentation (V)**: 본 기능의 모든 마크다운 산출물(spec / plan / tasks / ADR 등)이 한국어로 작성되는가?
- **Always-On Logging (VI)**: backend 로그(`logs/backend/app.log`)와 frontend access 로그(`logs/frontend/access.log`)가 모든 환경에서 항상 기록되도록 계획되었는가? 기본 레벨 INFO, file sink 비활성화 옵션 없음, 시크릿 마스킹 적용?
- **번역 Provider 추상화**: 번역 관련 기능이라면 vendor SDK가 아닌 `TranslationProvider` 추상화에 의존하는가?
- **Queue-Based Processing**: download / extraction / translation / ffmpeg는 Celery task로 실행되는가(inline 처리 없음)?
- **보안**: URL validation, path sanitization, shell interpolation 없음, hardcoded secret 없음?
- **API 표준**: 응답에 `success` / `error_code` / `message` / `request_id` 포함, OpenAPI 자동 생성, `/v1`부터 versioning?
- **테스트**: 필요한 테스트 카테고리(unit / integration / async pipeline / Celery worker / media validation as applicable)가 계획됨?
- **코딩 표준**: Python(Ruff / Black / mypy / pytest, type hint, async-first), TypeScript(strict, no `any`, generated API types) 준수?
- **금지 항목**: Forbidden Practices(god file, 동기 long-running endpoint, hardcoded secret, shell interpolation, Docker 의존, provider-coupled translation, 영문 마크다운 산출물) 미포함?

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
