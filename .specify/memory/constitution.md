<!--
SYNC IMPACT REPORT
==================
버전: 1.1.0 (2026-05-28, MINOR)
변경 사유: 새 핵심 원칙 VI(Always-On Logging) 추가. FE access 로그·BE 애플리케이션 로그를
`logs/` 디렉토리에 항상 기록하고 기본 INFO 레벨을 강제. 기술 표준 §비기능의 structured
logging 항목과 일관성 유지.
영향 받는 산출물:
  - ✅ `.specify/memory/constitution.md` — 원칙 VI 추가, Sync Impact Report 갱신
  - ✅ `.specify/templates/plan-template.md` — Constitution Check에 "Always-On Logging" 게이트 추가
  - ✅ `CLAUDE.md` — 헌법 v1.1.0 참조 갱신
  - ✅ `.gitignore` — `logs/` 디렉토리 무시 추가
  - ✅ `specs/001-dual-subtitle-mvp/quickstart.md` — `logs/` 디렉토리 안내 추가
  - ⚠ 후속(별도 PR): backend/frontend 런타임 코드가 실제 `logs/` 경로에 파일 sink를 출력하도록
       구성(structlog file handler, Next.js access log middleware). 본 amendment는 정책만 정의.

이전 (v1.0.1, 2026-05-27, PATCH):
변경 사유: API 응답 envelope의 "success / error_code / message / request_id" 표현을
flat/nested 양쪽 해석이 가능하도록 명료화. 의미 변경 없음.

이전 (v1.0.0, 2026-05-27, 최초 비준):
핵심 원칙:
  - I. SDD First
  - II. Architecture First
  - III. AI-Native Development
  - IV. macOS Native Development
  - V. Korean-First Documentation
-->

# Bilingual Subtitle Studio 헌법

## 핵심 원칙

### I. SDD First

모든 개발은 Spec-Driven Development를 따른다. 구현 이전에 PRD, Domain Model,
API Contract, UX Flow, Sequence Diagram, Acceptance Criteria, Test Specification이
승인되어야 한다. **Spec 승인 이전 구현은 금지한다.**

**근거**: 다운로드 / 추출 / 번역 / 렌더링 파이프라인이 얽혀 있어, Spec 없이는
도메인 간 drift가 재작업으로 누적된다.

### II. Architecture First

- Layered Architecture (API → Service → Domain → Infrastructure)
- Domain-oriented 모듈 구조, Separation of Concerns
- Async-first (동기 long-running endpoint 금지), Queue-based 장기 작업
- Strong typing (Python type hints, TypeScript strict)
- Stateless API (상태는 DB / Queue / FS에만 보관)

**근거**: 미디어 도구·LLM·worker queue가 얽힌 시스템에서 느슨한 layering은
곧 주인 없는 코드를 만든다.

### III. AI-Native Development

- giant file / god class 금지
- self-documenting 이름·구조, Python·TypeScript 공통 naming convention
- 비즈니스 로직은 service layer에 격리, controller는 얇게 유지

**근거**: AI는 1급 협업자다. AI가 탐색하기 어려운 코드는 사람에게도 어렵다.

### IV. macOS Native Development

- Apple Silicon arm64, Homebrew, zsh, VSCode
- Python `venv` 기반 runtime 격리, 로컬 파일시스템 저장 우선
- **개발 워크플로우의 Docker 의존 금지**

**근거**: ffmpeg / yt-dlp / Celery 반복 작업에 Docker는 지연과 모호함만 더한다.

### V. Korean-First Documentation

저장소의 모든 마크다운 문서(`*.md`)는 한국어로 작성한다.

- 적용 대상: 헌법, spec, plan, tasks, ADR, README 등 본 저장소의 모든 산출 문서
- 코드 식별자, 명령어, 라이브러리·제품명, 표준 키워드(MUST/SHOULD/NON-NEGOTIABLE 등)는 영문 유지
- 기술 용어는 필요 시 병기 가능 (예: "비동기(async-first)")
- 인용된 영문 원문은 원형을 보존한다

**근거**: 팀의 작업 언어가 한국어이므로 의도 손실이 가장 적고, AI 협업 시 일관된 언어가 검색·맥락 유지에 유리하다.

### VI. Always-On Logging (NON-NEGOTIABLE)

로컬·개발·운영 환경 구분 없이 **항상** 다음 두 종류의 로그를 저장소 루트의 `logs/`
디렉토리에 기록한다.

- **Backend 애플리케이션 로그**: `logs/backend/app.log`
  - 형식: structlog 기반 JSON line (필수 필드: `timestamp`, `level`, `logger`, `event`,
    `request_id`, `job_id`(있을 때), `task_id`(있을 때), `stage`(있을 때))
  - sink: file handler (rotation은 daily 또는 size 기반, 운영 결정)
  - stdout 동시 출력 허용 (개발 가독성). file sink는 비활성화 불가.
- **Frontend 액세스 로그**: `logs/frontend/access.log`
  - 형식: 한 줄 per 요청 (필수 필드: `timestamp`, `method`, `path`, `status`, `duration_ms`,
    `request_id`, `referrer`, `user_agent`)
  - 적용 대상: Next.js 서버가 처리한 모든 HTTP 요청 (`/api/*`, App Router SSR, RSC fetch)
  - sink: file handler. 브라우저 콘솔 로그는 본 항목에 포함되지 않는다.

**기본 로그 레벨은 `INFO`** 로 한다. `LOG_LEVEL` 환경 변수로 단일 변경 가능하되,
프로덕션에서 `DEBUG`로 운영 금지(시크릿 누출 위험). 어떤 환경에서도 `WARNING`보다
조용한 기본값을 채택할 수 없다.

**금지 사항**:

- file sink 자체를 끄는 코드/설정(예: `LOG_TO_FILE=false`)은 도입 금지.
- 시크릿(`api_key`, `oauth_token`, `password`, `authorization` 헤더 값 등)을 로그에
  원문 기록 금지. 적재 전 마스킹 처리는 logging 미들웨어 책임.
- `logs/`는 `.gitignore`에 포함시켜 commit 금지.

**근거**: 비동기 파이프라인 + LLM 호출 + 외부 미디어 도구가 얽혀 있어, 사후 디버깅에는
완전한 시계열 로그가 필수다. 환경별 토글은 "운영에서만 꺼져 있어 재현 불가"의 전형적
실패 모드를 만들기 때문에 NON-NEGOTIABLE로 강제한다.

## 제품 범위 & MVP 경계

**MVP 포함**: 단일 YouTube URL → 다운로드 → 자막 추출(수동 우선, 자동 fallback;
SRT/VTT) → KO↔JA 번역 → dual subtitle 생성 → 브라우저 재생, task progress UI.

**MVP 제외**: 로그인, 결제, 모바일 앱, 라이브 스트리밍, KO↔JA 외 다국어, 협업.
이 항목들은 MVP 아키텍처 결정에 영향을 주어서는 안 된다.

**향후 확장 (시드만 유지)**: Whisper STT, local LLM, vocabulary / sentence mining,
후리가나, 쉐도잉, 브라우저 확장, 데스크톱 앱. 미리 구현하지 말되 확장 지점은 닫지 말 것.

## 기술 표준 & 아키텍처 제약

**Backend**: Python 3.12+, FastAPI, Pydantic, SQLAlchemy, SQLite(MVP) — PostgreSQL
portable schema 유지, SQLite-specific SQL 금지. Celery, yt-dlp, ffmpeg, pysrt, webvtt-py.

**Frontend**: Next.js + TypeScript strict, TailwindCSS, shadcn/ui, desktop-first,
dark mode, 실시간 progress, `any` 금지, OpenAPI 기반 typing 자동화.

**번역 Provider 추상화 (NON-NEGOTIABLE)**: `TranslationProvider` 추상화를 도입하고
service / task는 추상화에만 의존한다. MVP 구현은 Claude Premium Seat. provider별
코드는 단일 adapter 모듈에 한정. chunked / context-preserving / rate-limit / retry / cache 지원.

**Queue-Based Processing (NON-NEGOTIABLE)**: video download, subtitle extraction,
translation, ffmpeg rendering은 Celery task로만 실행하며 inline 처리 금지.
task는 idempotent / retry-safe / cancellable / progress 보고 가능해야 하며,
SQLite lock 경합을 고려해 설계한다.

**보안**: URL validation, path sanitization 필수. ffmpeg / yt-dlp 명령에 untrusted
문자열 interpolation 금지. 시크릿 hardcoding 금지(env 전용). upload size / rate limit 강제.

**비기능**: 비동기·streaming-friendly. 모든 long-running task는 retry / 부분 상태 저장 /
복구 지원. structured logging은 원칙 VI(Always-On Logging)를 따른다. task tracing, metrics 필수.

**API 표준**: REST-first, OpenAPI 자동 생성, `/v1`부터 versioning. 모든 응답은
다음 정보를 포함하는 envelope을 사용한다 — 성공 여부(`success`), 성공 시 페이로드
(`data`) 또는 실패 시 에러 상세(`error`: 최소 `code` + `message`, 선택적 `details`),
요청 추적 ID(`request_id`). flat vs nested 구체 구조는 feature ADR에서 결정한다
(현재 채택: nested `error: { code, message, details? }` — 참조 ADR 0003).

**코딩 표준**: Python — Ruff / Black / mypy / pytest, type hint 필수, async-first,
fat controller 금지, 명시적 DI 선호. TypeScript — strict, `any` 금지, 스키마 typing 자동화.

**테스트**: Backend(unit / integration / async pipeline / Celery worker),
Frontend(component / e2e), Media(subtitle sync / translation / ffmpeg rendering validation).

## 워크플로우 & 품질 게이트

**워크플로우 순서 (강제)**: Constitution → PRD → Domain Model → API Spec → UX Spec
→ Task Breakdown → Implementation → Testing → Refactor. 순서 변경은 거버넌스
예외 절차를 거친다.

**금지 항목 (PR 머지 차단)**:

- giant god file / 동기식 long-running endpoint / hardcoded secret
- untrusted input의 shell interpolation / 자막 파싱 로직 중복
- undocumented public API / spec 없는 구현
- 개발 워크플로우의 Docker 의존 / 번역 provider 직접 결합
- **영문으로 작성된 마크다운 산출물 (원칙 V 위반)**
- **`logs/` 파일 sink를 비활성화하거나 시크릿을 원문 로깅 (원칙 VI 위반)**

**문서화 요구**: 모든 주요 기능은 목적 / 흐름 / 입력 / 출력 / 예외 / 실패 전략을
문서화한다. 헌법 제약·provider·queue / storage topology 변경은 ADR로 기록한다.
모든 산출 문서는 한국어로 작성한다 (원칙 V).

## 거버넌스

본 헌법은 비공식 관행과 구두 합의보다 우선한다. 다른 가이드와 충돌하면 본 문서가 우선한다.

**개정 절차**:

1. `.specify/memory/constitution.md`에 변경 PR 제출
2. 버전 정책에 따라 bump, 상단 Sync Impact Report 갱신
3. 의존 템플릿(plan / spec / tasks / checklist) 동시 검토·갱신
4. 머지 전 승인

**버전 정책 (SemVer)**:

- MAJOR: 기존 spec을 무효화하는 거버넌스·원칙 제거·재정의
- MINOR: 원칙 / 섹션 추가, 가이드 실질 확장
- PATCH: 표현 명확화, 오타, 비의미적 정련

**준수 검토**: 모든 PR은 6개 핵심 원칙, 번역 Provider 추상화, 금지 항목 위반이
없음을 검증한다. 정당화된 위반은 해당 plan.md의 Complexity Tracking에 기록한다.

**런타임 가이드**: AI 에이전트와 기여자는 `CLAUDE.md`(및 동급 에이전트 파일)를
참조한다. 충돌 시 본 헌법이 우선한다.

**최종 원칙**: *Maintainability over cleverness.* 의심스러우면 지루하고 읽기 쉬운 구현을 택한다.

**Version**: 1.1.0 | **Ratified**: 2026-05-27 | **Last Amended**: 2026-05-28
