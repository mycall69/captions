---
description: "Dual Subtitle MVP — 사용자 스토리별 dependency-ordered 작업 목록"
---

# Tasks: Dual Subtitle MVP

**Input**: 설계 문서 from `specs/001-dual-subtitle-mvp/` — [spec.md](./spec.md), [plan.md](./plan.md), [data-model.md](./data-model.md), [contracts/openapi.yaml](./contracts/openapi.yaml), [contracts/events.md](./contracts/events.md), [research.md](./research.md)

**Prerequisites**: plan.md ✅, spec.md ✅, data-model.md ✅, contracts/ ✅, research.md ✅, quickstart.md ✅

**Tests**: 본 작업에서는 **테스트 task를 포함**한다. 사유: 헌법 I(Test Specification 필수) + Testing Principles(unit / integration / async pipeline / Celery worker / 미디어 validation 모두 mandatory). plan.md §Testing Strategy 매트릭스에 매핑된다.

**Organization**: 사용자 스토리(US1·US2·US3)별로 phase를 묶어 독립 구현·검증·증분 출시 가능하도록 구성한다.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 다른 파일이며 미완료 task에 의존하지 않으므로 병렬 실행 가능
- **[Story]**: 어느 사용자 스토리에 속하는지 (US1 / US2 / US3). Setup·Foundational·Polish는 라벨 없음.
- 모든 task는 **정확한 파일 경로** 포함

## Path Conventions

plan.md §Project Structure 기준.

- 백엔드: `backend/...`
- 프론트엔드: `frontend/...`
- 런타임 저장소: `var/...`
- 스크립트: `scripts/...`
- ADR: `docs/adr/...`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 저장소 부트스트랩 — backend / frontend 골격, 도구 체인, 보조 스크립트.

- [x] 001 Initialize backend skeleton at `backend/` with `pyproject.toml` (deps: fastapi, pydantic v2, sqlalchemy 2, aiosqlite, alembic, celery, redis, structlog, pydantic-settings, anthropic, yt-dlp, pysrt, webvtt-py, httpx, sse-starlette, slowapi)
- [x] 002 Initialize frontend skeleton at `frontend/` with `package.json` (Next.js 15 App Router, TypeScript strict, Tailwind, shadcn/ui, TanStack Query, Zustand, openapi-typescript, Vitest, Playwright, MSW)
- [x] 003 [P] Configure backend tooling — `backend/pyproject.toml` Ruff·Black·mypy·pytest 설정 + `backend/.pre-commit-config.yaml`
- [x] 004 [P] Configure frontend tooling — `frontend/tsconfig.json` strict, `frontend/.eslintrc.*`, `frontend/.prettierrc`
- [x] 005 [P] Add `.env.example` at repo root with keys defined in `specs/001-dual-subtitle-mvp/quickstart.md` §2
- [x] 006 [P] Add `scripts/dev-up.sh` and `scripts/dev-down.sh` orchestrating redis + api + worker + web
- [x] 007 [P] Update `.gitignore` to exclude `.venv/`, `node_modules/`, `var/`, `.env`, `frontend/.next/`
- [x] 008 [P] ADR `docs/adr/0001-translation-provider-abstraction.md` documenting Protocol-based abstraction decision (헌법 — Translation Provider Abstraction NON-NEGOTIABLE)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 user story가 의존하는 공통 인프라. Phase 2 완료 전에는 어떤 user story도 시작할 수 없다.

**⚠️ CRITICAL**: 본 phase 완료 후에야 US1·US2·US3 작업이 (이론상) 병렬 가능.

### Backend — 핵심 모듈

- [x] 009 Implement FastAPI app factory in `backend/app/main.py` (lifespan, CORS, middleware ordering, `/v1` router mount)
- [x] 010 [P] Implement structlog config + request_id middleware in `backend/app/core/logging.py` and `backend/app/api/v1/middleware/request_id.py`
- [x] 011 [P] Implement settings loader in `backend/app/core/config.py` using pydantic-settings (env keys from quickstart.md §2) — **`JOB_CONCURRENCY: int = 2` 필드 포함 (spec Clarifications Q5)** + Celery worker 기동 명령에 `--concurrency=$JOB_CONCURRENCY` 적용 가이드 명시. 환경변수가 1 미만이면 1로 클램프.
- [x] 012 [P] Implement URL validation + path sanitization in `backend/app/core/security.py` (host allowlist, 11-char video ID extraction, playlist URL rejection per research §9)
- [x] 013 [P] Implement domain exceptions and API error mapper in `backend/app/core/exceptions.py` (error codes from contracts/openapi.yaml `ErrorBody`)
- [x] 014 [P] Implement response envelope wrapper in `backend/app/api/v1/envelope.py` (`success / data / error / request_id`)
- [x] 015 [P] Implement ID generators (ULID-based job_id, request_id) in `backend/app/core/ids.py`

### Backend — 데이터 계층 (data-model.md 전체)

- [x] 016 Implement async SQLAlchemy engine + session factory with WAL pragma in `backend/app/infrastructure/db/session.py`
- [x] 017 Implement ORM mappings for all 7 tables (video_job, subtitle_track, subtitle_cue, translation_task, render_task, video_asset, job_event) in `backend/app/infrastructure/db/orm.py`
- [x] 018 Configure Alembic in `backend/alembic.ini` + `backend/app/infrastructure/db/migrations/env.py`
- [x] 019 Generate initial migration `backend/app/infrastructure/db/migrations/versions/0001_initial_schema.py` covering all 7 tables + indexes from data-model.md
- [x] 020 [P] Implement filesystem storage abstraction in `backend/app/infrastructure/storage/filesystem.py` (`var/storage/<job_id>/...` path composition, sanitized)

### Backend — 도메인 골격 + Queue 인프라

- [x] 021 [P] Implement JobStatus enum and state transition machine in `backend/app/domain/jobs/states.py` (transitions per data-model.md §상태 머신)
- [x] 022 [P] Define VideoJob + VideoMetadata Pydantic domain models in `backend/app/domain/jobs/models.py`
- [x] 023 [P] Define `JobRepository` Protocol in `backend/app/domain/jobs/repository.py`
- [x] 024 [P] Define `TranslationProvider` Protocol + DTOs (`TranslatedChunk`, `Lang`) in `backend/app/domain/translation/provider.py` (research §6)
- [x] 025 [P] Implement Redis event bus (publish + subscribe primitives) in `backend/app/domain/events/bus.py`
- [x] 026 Configure Celery app, task routing, retry defaults in `backend/app/workers/celery_app.py` (broker/result backend from settings)

### Frontend — 공통 셸

- [x] 027 [P] Configure Tailwind + globals in `frontend/tailwind.config.ts` and `frontend/app/globals.css` (dark mode 기본, color tokens placeholder)
- [x] 028 [P] Initialize shadcn/ui primitives in `frontend/components/ui/` (button, input, badge, card, dialog, tabs, sonner toast)
- [x] 029 [P] Implement OpenAPI → TS codegen script in `frontend/scripts/codegen.ts` and generate `frontend/lib/api/types.gen.ts` from `specs/001-dual-subtitle-mvp/contracts/openapi.yaml`
- [x] 030 [P] Implement fetch client wrapper that unwraps envelope and maps `ErrorBody` to typed errors in `frontend/lib/api/client.ts`
- [x] 031 Implement `AppLayout` (dark mode, font, container) and `AppHeader` (per wireframes C1) in `frontend/app/layout.tsx` and `frontend/components/header/AppHeader.tsx`

### Test 인프라

- [x] 032 [P] Implement `FakeTranslationProvider` returning deterministic translations + context inspection in `backend/tests/fixtures/fake_provider.py`
- [x] 033 [P] Add subtitle fixture set (short SRT/VTT in ja + ko) at `backend/tests/fixtures/subtitles/` plus a minimal mp4 sample at `backend/tests/fixtures/media/`
- [x] 034 [P] Configure pytest + pytest-asyncio + pytest-celery in `backend/pyproject.toml` and `backend/tests/conftest.py` (DB fixture with in-memory SQLite, Redis fakeredis fallback)
- [x] 035 [P] Configure Playwright + MSW skeleton in `frontend/playwright.config.ts` and `frontend/tests/e2e/setup.ts`

**Checkpoint**: Phase 2 완료 — user story 구현 시작 가능.

---

## Phase 3: User Story 1 — 단일 영상으로 dual subtitle 시청 완료 (Priority: P1) 🎯 MVP

**Goal**: 사용자가 YouTube URL을 입력하고 자동 처리 후 브라우저에서 dual subtitle과 함께 영상을 재생할 수 있다.

**Independent Test**: 자막이 있는 5~15분 길이의 영상 URL을 입력 → 처리 완료 → S3 재생 화면에서 dual subtitle이 표시되고 토글·순서 전환·SRT/VTT 다운로드가 동작.

**관련 FR**: FR-001~FR-023, FR-027, FR-028, FR-031~FR-034, FR-036, FR-037 / **관련 SC**: SC-001, SC-003, SC-004, SC-005, SC-007, SC-008

### Tests for User Story 1 ⚠️ (구현 전에 작성하고 실패 상태 확인)

- [x] 036 [P] [US1] Contract test `POST /v1/jobs` (성공·중복 URL 재사용·INVALID_URL·rate limit) in `backend/tests/integration/test_jobs_post.py`
- [x] 037 [P] [US1] Contract test `GET /v1/jobs/{id}` (envelope·404·상태 필드) in `backend/tests/integration/test_jobs_get.py`
- [x] 038 [P] [US1] Contract test `GET /v1/jobs/{id}/subtitles` (페이지네이션·언어 분리·완료 전 409) in `backend/tests/integration/test_subtitles_get.py`
- [x] 039 [P] [US1] Contract test `GET /v1/jobs/{id}/download?format=srt|vtt&order=...` (Content-Disposition·완료 전 409) in `backend/tests/integration/test_download.py`
- [x] 040 [P] [US1] Contract test `GET /v1/jobs/{id}/video` HTTP Range (206 partial, 200 full) in `backend/tests/integration/test_video_range.py`
- [x] 041 [P] [US1] Worker test: download task (mock yt-dlp, subprocess arg list, idempotent, retry) in `backend/tests/workers/test_download_task.py`
- [x] 042 [P] [US1] Worker test: extract_subtitles (manual 우선, auto fallback, ko/ja 미발견 실패) in `backend/tests/workers/test_extract_subtitles_task.py`
- [x] 043 [P] [US1] Worker test: translate task (FakeProvider, chunk 분할, context 전달, rate limit retry 횟수) in `backend/tests/workers/test_translate_task.py`
- [x] 044 [P] [US1] Worker test: render task (dual SRT/VTT 생성, video_asset 등록) in `backend/tests/workers/test_render_task.py`
- [x] 045 [P] [US1] End-to-end chain test (download→extract→translate→render) with FakeProvider in `backend/tests/workers/test_pipeline_chain.py`
- [x] 046 [P] [US1] Unit test: subtitle normalizer (SRT/VTT 파싱, overlapping cue 정리, 빈 cue 제거) in `backend/tests/unit/test_subtitle_normalize.py`
- [x] 047 [P] [US1] Unit test: chunking policy (60s window + cue 경계 보존 + context 3 cue) in `backend/tests/unit/test_chunking.py`
- [x] 048 [P] [US1] Unit test: dual subtitle generator (두 줄 cue, order 옵션, VTT/SRT 형식) in `backend/tests/unit/test_dual_generator.py`
- [x] 049 [P] [US1] Unit test: URL validator (host allowlist, video ID 추출, playlist 거절) in `backend/tests/unit/test_url_validator.py`
- [x] 050 [P] [US1] Unit test: state machine (적법/위법 전이) in `backend/tests/unit/test_job_states.py`
- [x] 051 [P] [US1] Media validation: dual subtitle 시간 정렬 ±200ms (SC-004) in `backend/tests/media/test_dual_alignment.py`
- [x] 052 [P] [US1] Frontend component test: `UrlInputCard` (검증·에러 표시·시작 버튼 활성화) in `frontend/tests/component/UrlInputCard.test.tsx`
- [x] 053 [P] [US1] Frontend component test: `DualSubtitleOverlay` (두 줄 렌더, 순서 전환) in `frontend/tests/component/DualSubtitleOverlay.test.tsx`
- [x] 054 [P] [US1] Playwright e2e: US1 P1 acceptance flow (URL 입력 → 처리 완료 → dual subtitle 재생) in `frontend/tests/e2e/us1-dual-playback.spec.ts`

### Implementation for User Story 1

#### Domain — Subtitles

- [x] 055 [P] [US1] Define `SubtitleCue`, `SubtitleTrack`, `Lang` Pydantic domain models in `backend/app/domain/subtitles/models.py`
- [x] 056 [P] [US1] Implement SRT/VTT subtitle normalizer (pysrt + webvtt-py → cues) in `backend/app/domain/subtitles/normalize.py`
- [x] 057 [P] [US1] Implement dual subtitle generator (two-line per cue, order option, SRT/VTT serializers) in `backend/app/domain/subtitles/dual.py`
- [x] 058 [US1] Implement subtitles service (track CRUD, cue paging, dual subtitle 합성) in `backend/app/domain/subtitles/service.py`

#### Domain — Translation

- [x] 059 [P] [US1] Implement chunking policy (60s window + cue 경계 보존 + 3 cue context padding) in `backend/app/domain/translation/chunking.py`
- [x] 060 [P] [US1] Implement translation cache (Redis-backed, sha256 key, TTL 7d) in `backend/app/domain/translation/cache.py`
- [x] 061 [US1] Implement translation service (chunk dispatch, cache lookup, retry with exponential backoff, provider injection) in `backend/app/domain/translation/service.py`
- [x] 062 [US1] Implement Claude translation adapter (anthropic SDK 결합 유일 지점, prompt 템플릿 ko↔ja, temperature 0) in `backend/app/infrastructure/providers/claude_adapter.py` — **어조(register) 추론 + 보존 prompt 분기 포함 (spec Clarifications Q1 / FR-014)**: chunk 입력의 cue 본문에서 KO 합니다/한다체 또는 JA です·ます / だ·である체를 추론(다수결, 혼재 시 다수 어조), 추론 결과를 시스템 prompt에 명시해 동일 어조로 출력 강제. 어조 분기 로직은 본 adapter 모듈에만 둔다 (도메인 누출 금지 — 헌법 Translation Provider Abstraction NON-NEGOTIABLE).

#### Domain — Media

- [x] 063 [P] [US1] Implement yt-dlp video download wrapper (subprocess arg list, format `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b`, output path 고정) in `backend/app/domain/media/download.py`
- [x] 064 [P] [US1] Implement yt-dlp subtitle download wrapper (manual 우선 + auto fallback, `--sub-langs ko,ja`) in `backend/app/infrastructure/youtube/subtitles.py`
- [x] 065 [P] [US1] Implement yt-dlp metadata extractor (`--dump-json --no-playlist`, 영상 ID·길이·제목·채널 매핑) in `backend/app/infrastructure/youtube/metadata.py` — **영상 길이 검증 포함 (spec Clarifications Q2 / FR-003)**: `duration_sec > 3600`이면 `VideoTooLongError` 발생(에러 코드 `INVALID_INPUT`, 메시지 "영상 길이가 60분을 초과합니다 (실제: {duration}초)"). 단위 테스트 1건 추가: 3601초 영상 → 거절.
- [x] 066 [P] [US1] Implement ffmpeg remux wrapper (subprocess arg list, `-c copy` only — MVP soft subtitle 방침) in `backend/app/domain/media/render.py`

#### Persistence

- [x] 067 [US1] Implement SQLAlchemy-backed `JobRepository` in `backend/app/infrastructure/db/repositories/job_repository.py` (CRUD + youtube_video_id lookup)
- [x] 068 [US1] Implement subtitle / cue / track repositories in `backend/app/infrastructure/db/repositories/subtitle_repository.py`
- [x] 069 [US1] Implement `VideoAssetRepository` in `backend/app/infrastructure/db/repositories/asset_repository.py`

#### Jobs Service

- [x] 070 [US1] Implement jobs service (`create_or_reuse`, `get`, `transition_to`, `mark_failed`) in `backend/app/domain/jobs/service.py` — 동일 URL 재사용 분기 포함 (research §10) + **메타데이터 조회 직후 60분 초과 검증 분기 (spec Clarifications Q2 / FR-003)**: `VideoTooLongError`를 도메인 `IllegalInputError`로 변환해 API 계층에 `INVALID_INPUT`으로 노출. 작업은 생성되지 않는다(DB에 미기록).

#### Workers / Pipeline

- [x] 071 [US1] Implement `download_video_task` Celery task in `backend/app/workers/tasks/download.py` (state → downloading, persist mp4 asset)
- [x] 072 [US1] Implement `extract_subtitles_task` Celery task in `backend/app/workers/tasks/extract_subtitles.py` (state → subtitle_processing, source track 저장; ko/ja 미발견 시 SUBTITLE_NOT_FOUND → failed)
- [x] 073 [US1] Implement `translate_task` Celery task in `backend/app/workers/tasks/translate.py` (state → translating, chunk loop, completed_chunks 갱신)
- [x] 074 [US1] Implement `render_dual_subtitle_task` Celery task in `backend/app/workers/tasks/render.py` (state → rendering → completed, dual_srt / dual_vtt 자산 생성)
- [x] 075 [US1] Implement pipeline orchestration `build_job_chain(job_id)` in `backend/app/workers/pipeline.py` (Celery `chain` + `link_error` propagation)

#### API — REST 엔드포인트

- [x] 076 [US1] Define API request/response schemas in `backend/app/api/v1/schemas/jobs.py` and `backend/app/api/v1/schemas/subtitles.py` (contracts/openapi.yaml 매핑)
- [x] 077 [US1] Implement `POST /v1/jobs` route in `backend/app/api/v1/routes/jobs.py` (URL validation → create_or_reuse → dispatch chain → 201/200 응답)
- [x] 078 [US1] Implement `GET /v1/jobs/{id}` route in `backend/app/api/v1/routes/jobs.py`
- [x] 079 [US1] Implement `GET /v1/jobs/{id}/subtitles` route in `backend/app/api/v1/routes/subtitles.py` (offset/limit, source+translated 동시 반환)
- [x] 080 [US1] Implement `GET /v1/jobs/{id}/download` route in `backend/app/api/v1/routes/media.py` (format/order, Content-Disposition)
- [x] 081 [US1] Implement `GET /v1/jobs/{id}/video` Range-aware route in `backend/app/api/v1/routes/media.py` (206 Partial Content)
- [x] 082 [US1] Mount `/v1` API router and wire dependency-injected services in `backend/app/main.py` (T009 확장)

#### Frontend — S1 진입 / S3 재생

- [x] 083 [P] [US1] Implement `UrlInputCard` (입력·검증·시작) in `frontend/components/url-input/UrlInputCard.tsx`
- [x] 084 [P] [US1] Implement `playerPreferenceStore` (Zustand persisted) — subtitle 표시 toggle, 순서, 형식 in `frontend/lib/stores/playerStore.ts`
- [x] 085 [P] [US1] Implement `VideoPlayer` component (HTML5 video, `/v1/jobs/:id/video` 스트리밍, Range·시킹) in `frontend/components/player/VideoPlayer.tsx`
- [x] 086 [P] [US1] Implement `DualSubtitleOverlay` component (두 줄 cue 렌더, 시간 동기 currentTime hook) in `frontend/components/player/DualSubtitleOverlay.tsx`. **FR-021a 매핑**: 자동 자막 출처일 때 `AutoSubtitleBadge` 컴포넌트(또는 MetadataHeader 슬롯)에 "🤖 자동 자막 기반" 배지를 노출. 컴포넌트 테스트는 T053을 확장.
- [x] 087 [P] [US1] Implement `SubtitleControls` component (자막 토글, 순서 전환, 단축키 S/R) in `frontend/components/player/SubtitleControls.tsx`
- [x] 088 [P] [US1] Implement `SubtitleCueList` component (시간 클릭 → seek) in `frontend/components/player/SubtitleCueList.tsx`
- [x] 089 [P] [US1] Implement `DownloadActions` (SRT/VTT 다운로드 링크, order param) in `frontend/components/player/DownloadActions.tsx`
- [x] 090 [US1] Compose `S1` page (URL 입력 → POST /v1/jobs → /jobs/[id] 라우팅) in `frontend/app/page.tsx`
- [x] 091 [US1] Compose `S3` (state=completed 분기) in `frontend/app/jobs/[id]/page.tsx` — VideoPlayer + DualSubtitleOverlay + SubtitleControls + SubtitleCueList + DownloadActions

**Checkpoint**: US1 단독으로 동작 — MVP 출시 가능.

---

## Phase 4: User Story 2 — 장기 작업 진행 상황 실시간 확인 (Priority: P2)

**Goal**: 사용자가 처리 도중 단계 / 진행률을 실시간으로 보고 실패 시 사유를 즉시 확인.

**Independent Test**: 영상 처리 도중 S2 페이지를 열어 단계 인디케이터가 페이지 새로고침 없이 5초 이내 갱신되는지 확인. 실패 시 단계명 + 사유가 노출되는지 확인.

**관련 FR**: FR-024~FR-026, FR-028, FR-035, FR-036, FR-037 / **관련 SC**: SC-002, SC-008

### Tests for User Story 2 ⚠️

- [ ] T092 [P] [US2] Contract test `GET /v1/jobs/{id}/events` SSE stream (5종 이벤트, Last-Event-ID replay, keepalive) in `backend/tests/integration/test_events_sse.py`
- [ ] T093 [P] [US2] Worker test: 상태 전이 시 JobEvent 영구화 + Redis publish 원자성 in `backend/tests/workers/test_event_publishing.py`
- [ ] T094 [P] [US2] Contract test `DELETE /v1/jobs/{id}` cancel (진행 중 → failed, 종결 작업 409) in `backend/tests/integration/test_jobs_cancel.py`
- [ ] T095 [P] [US2] Frontend component test: `StageProgressBar` (6노드 상태별 렌더), `StatusBadge` (7 variant) in `frontend/tests/component/StageProgressBar.test.tsx`, `StatusBadge.test.tsx`
- [ ] T096 [P] [US2] Playwright e2e: US2 progress visibility — SSE mock 서버로 단계 전이를 받았을 때 UI 갱신 in `frontend/tests/e2e/us2-progress.spec.ts`

### Implementation for User Story 2

- [ ] T097 [P] [US2] Implement `JobEventRepository` + persistence helpers in `backend/app/infrastructure/db/repositories/event_repository.py`
- [ ] T098 [P] [US2] Implement event payload builders for `job.state_changed / job.progress / job.completed / job.failed / job.info` per contracts/events.md in `backend/app/domain/events/payloads.py`
- [ ] T099 [US2] Implement `JobEventPublisher` (transactional: DB INSERT + Redis publish) in `backend/app/domain/events/publisher.py`
- [ ] T100 [US2] Inject `JobEventPublisher` into worker tasks T071–T074 — 단계 시작/완료/진행률 이벤트 publish (T071·T072·T073·T074 수정)
- [ ] T101 [US2] Implement `GET /v1/jobs/{id}/events` SSE endpoint using sse-starlette in `backend/app/api/v1/routes/events.py` (Redis pub/sub 구독, keepalive 30s) — **모듈 레벨에 `KEEPALIVE_INTERVAL_SEC` 상수를 반드시 노출(test seam: T092 의 keepalive 테스트가 monkeypatch 로 짧게 덮어쓰므로, Settings 안에 숨기지 말고 라우터 모듈에서 직접 import 가능해야 함)**
- [ ] T102 [US2] Implement Last-Event-ID replay (50건 한도) reading `job_event` table in `backend/app/api/v1/routes/events.py` (T101 확장)
- [ ] T103 [US2] Implement `DELETE /v1/jobs/{id}` cancel route in `backend/app/api/v1/routes/jobs.py` (T077 확장 — Celery task revoke + state → failed/USER_CANCELLED) + **부분 산출물 완전 삭제 책임 (spec Clarifications Q3 / FR-028)**: 취소 확정 후 `app/infrastructure/storage/filesystem.py`의 `purge_job_directory(job_id)`를 호출해 `var/storage/<job_id>/` 전체를 삭제. DB의 `video_job` 행은 감사 목적 보존(상태/사유만 갱신). `purge_job_directory` 헬퍼가 T020 storage 모듈에 없다면 본 task에서 함께 추가. 통합 테스트 1건: 진행 중 취소 → 디렉터리 부재 확인.
- [ ] T104 [P] [US2] Implement `StatusBadge` component (7 status variant + 자동 자막 배지) in `frontend/components/job-list/StatusBadge.tsx`
- [ ] T105 [P] [US2] Implement `StageProgressBar` component (6노드 + 현재 노드 회전 인디케이터) in `frontend/components/stage-progress/StageProgressBar.tsx`
- [ ] T106 [P] [US2] Implement `StageLog` component (단계별 타임라인) in `frontend/components/stage-progress/StageLog.tsx`
- [ ] T107 [P] [US2] Implement `FailurePanel` component (사유·재시도 CTA) in `frontend/components/stage-progress/FailurePanel.tsx`
- [ ] T108 [P] [US2] Implement `MetadataPanel` component in `frontend/components/job-detail/MetadataPanel.tsx`
- [ ] T109 [P] [US2] Implement SSE hook `useJobEvents(jobId)` with EventSource, Last-Event-ID, fallback 5s polling in `frontend/lib/sse.ts`
- [ ] T110 [US2] Wire SSE updates into TanStack Query cache (partial `setQueryData` per event) in `frontend/lib/api/hooks.ts`
- [ ] T111 [US2] Compose `S2` (state ∈ {pending..rendering, failed}) in `frontend/app/jobs/[id]/page.tsx` — MetadataPanel + StageProgressBar + StageLog + FailurePanel (conditional) (T091과 동일 page에서 분기)

**Checkpoint**: US1 + US2 동작 — 진행 상황이 실시간으로 보이는 완성도 향상 MVP.

---

## Phase 5: User Story 3 — 최근 작업 목록에서 재방문 (Priority: P3)

**Goal**: 사용자가 메인 페이지에서 최근 작업 목록을 보고 완료 항목을 선택해 즉시 재생.

**Independent Test**: 1건 완료 처리 → S1 진입 → 목록에 항목 노출 확인 → 클릭 시 S3 즉시 진입.

**관련 FR**: FR-029, FR-030, FR-004 / **관련 SC**: SC-005, SC-006

### Tests for User Story 3 ⚠️

- [x] T112 [P] [US3] Contract test `GET /v1/jobs` (페이지네이션·status 필터·next_cursor) in `backend/tests/integration/test_jobs_list.py`
- [x] T113 [P] [US3] Frontend component test: `JobListItem` (completed/in-progress/failed variant) in `frontend/tests/component/JobListItem.test.tsx`
- [x] T114 [P] [US3] Playwright e2e: US3 recent jobs revisit — 완료 항목 클릭 → S3 진입 in `frontend/tests/e2e/us3-recent.spec.ts`

### Implementation for User Story 3

- [x] T115 [US3] Implement `GET /v1/jobs` cursor-based list endpoint in `backend/app/api/v1/routes/jobs.py` (T077·T078 확장 — `ix_video_job_status_created_at` 인덱스 사용)
- [x] T116 [P] [US3] Implement `JobListItem` component (썸네일·메타·상태별 우측 액션) in `frontend/components/job-list/JobListItem.tsx`
- [x] T117 [P] [US3] Implement `EmptyState` component (빈 상태 C3) in `frontend/components/job-list/EmptyState.tsx`
- [x] T118 [P] [US3] Implement `useRecentJobs` hook (TanStack Query, 10초 stale, 진행 중 항목만 SSE-driven 부분 갱신) in `frontend/lib/api/hooks.ts`
- [x] T119 [US3] Integrate recent jobs list into `S1` (T090 확장) — 5건 + "전체 보기" + EmptyState 분기

**Checkpoint**: 세 가지 user story 모두 독립적으로 동작.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 모든 user story에 걸친 마무리 작업.

- [ ] T120 [P] Implement IP-based rate limiting middleware (slowapi, 기본 10 req/min) in `backend/app/api/v1/middleware/rate_limit.py`
- [ ] T121 [P] Implement OpenAPI export script — FastAPI 런타임 스펙을 `specs/001-dual-subtitle-mvp/contracts/openapi.yaml`과 diff 검증 in `backend/scripts/export_openapi.py`
- [ ] T122 [P] Implement Toast / InlineError components in `frontend/components/feedback/Toast.tsx` and `frontend/components/feedback/InlineError.tsx`
- [ ] T123 [P] Implement Skip-by-default real-network smoke test in `backend/tests/media/test_smoke_real.py` (env `RUN_REAL_NETWORK=1` 시만 실행)
- [ ] T124 [P] Implement performance sanity tests in `backend/tests/integration/test_performance.py` — 다음 SC를 자동화 검증: **(SC-007)** 신규 작업 제출 `POST /v1/jobs` 응답 ≤ 1초, **(SC-002)** SSE 단계 전이 push 평균 latency ≤ 5초, **(SC-005)** 동일 URL 재요청 시 기존 완료 작업 재사용 응답이 ≤ 5초. fixture: pre-seeded completed job + identical URL re-POST → reused=true + latency assertion.
- [ ] T125 [P] Add structured logging assertions in `backend/tests/integration/test_logging.py` (필수 필드 `request_id / job_id / task_id / stage` 확인)
- [ ] T126 [P] Write `README.md` at repo root (한국어, 헌법 V) — 프로젝트 소개·실행 방법·문서 링크 트리
- [ ] T127 [P] Author ADR `docs/adr/0002-soft-subtitle-render.md` documenting MVP soft-subtitle decision (research §7)
- [ ] T128 Run `quickstart.md` §6 end-to-end validation locally and record any deviations as follow-ups
- [ ] T129 Review final tasks completeness with `/speckit-analyze` (선택, 권장)
- [ ] T130 [P] **(SC-008)** Implement failure envelope coverage test in `backend/tests/integration/test_failure_envelope.py` — 6개 실패 시나리오(`INVALID_URL`, `INVALID_INPUT`(video too long), `SUBTITLE_NOT_FOUND`, `DOWNLOAD_FAILED`, `TRANSLATION_FAILED`, `USER_CANCELLED`) 각각에 대해 응답 envelope이 `error.code` + `error.message`(한국어, 빈 문자열 아님) + `request_id`를 모두 포함하는지 검증. failed 작업 행의 `error_stage` / `error_message` 필드도 동일 검증.
- [ ] T131 [P] Author ADR `docs/adr/0003-response-envelope-shape.md` — 헌법 §API Principles의 "success / error_code / message / request_id"라는 flat 표현과 실 계약(`{ success, data?, error: { code, message, details? }, request_id }`의 nested 구조)이 의미적으로 동등함을 명문화. 결정: nested 표현을 정식 채택 (이유: OpenAPI schema·TypeScript 타입 생성·에러 분류용 details 확장 용이). 헌법 표현은 "응답이 success·error 정보·request_id를 모두 포함해야 한다"는 의미로 해석한다고 ADR에 기록. 헌법 v1.0.1 PATCH와 짝을 이룬다.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 진입 의존 없음 — 즉시 시작
- **Phase 2 (Foundational)**: Phase 1 완료 후 시작. **모든 user story를 막는다.**
- **Phase 3 (US1)**: Phase 2 완료 후 시작 — MVP의 본체
- **Phase 4 (US2)**: Phase 2 완료 후 시작 가능하지만, 워커 task에 이벤트 publisher를 주입하는 T100이 T071–T074(US1) 결과를 수정하므로 실무상 **US1 워커 완성 후 진행 권장**
- **Phase 5 (US3)**: Phase 2 완료 후 US1과 병렬 가능 — list API와 list UI는 US1·US2와 파일 충돌 없음 (T115는 jobs.py 확장, US1 T077과 같은 파일이므로 시간 분리 필요)
- **Phase 6 (Polish)**: US1·US2·US3 중 의도한 슬라이스까지 완료된 후

### User Story-Level Dependencies

- **US1 (P1)**: Phase 2 의존. 다른 스토리에 비종속.
- **US2 (P2)**: Phase 2 의존 + US1의 워커 task가 존재해야 publisher 주입 가능 (Soft dependency: US1의 T071–T074).
- **US3 (P3)**: Phase 2 의존. US1·US2와 독립이나 `routes/jobs.py` 동시 편집을 피하기 위해 시간 분리 권장.

### Story 내부 순서 (US1 기준)

1. 테스트(T036–T054)는 구현 전 작성·실패 확인 (헌법 — TDD 권장)
2. 도메인 모델 (T055, T059, T060)
3. 도메인 서비스 (T058, T061, T062)
4. Repository (T067–T069)
5. Job service (T070)
6. Workers (T071–T075)
7. API 스키마 / 라우트 (T076–T082)
8. Frontend 컴포넌트 (T083–T089)
9. Frontend page composition (T090, T091)

### 병렬 가능 Task 집합 (대표)

```text
Phase 1 setup: { T003, T004, T005, T006, T007, T008 } 동시 진행 가능

Phase 2 foundational [P] 그룹:
  { T010, T011, T012, T013, T014, T015 }            # core/* 별 파일
  { T020 }                                            # storage
  { T021, T022, T023, T024, T025 }                   # domain Protocols
  { T027, T028, T029, T030 }                         # frontend foundation
  { T032, T033, T034, T035 }                         # test infra

US1 tests [P]: T036~T054 모두 병렬 (서로 다른 파일)
US1 domain models [P]: T055, T056, T057, T059, T060, T063, T064, T065, T066
US1 frontend components [P]: T083, T084, T085, T086, T087, T088, T089
US2 frontend components [P]: T104, T105, T106, T107, T108, T109
US3 frontend [P]: T116, T117, T118
Polish [P]: T120, T121, T122, T123, T124, T125, T126, T127
```

---

## Implementation Strategy

### MVP First (US1 단독)

1. Phase 1 → Phase 2 → Phase 3 (US1)
2. Phase 3 완료 후 **STOP & VALIDATE**: `quickstart.md` §6 시나리오로 P1 acceptance 검증
3. 출시 / 데모 가능

### Incremental Delivery

1. MVP (US1)만으로 1차 데모
2. US2 추가 → 진행 상황 가시화 → 사용성 향상 → 2차 데모
3. US3 추가 → 작업 이력 → 재방문 가치 추가
4. Phase 6(폴리시) — 라이트 보안·로깅·성능 검증으로 정식 0.1 출시

### Parallel Team Strategy

- 2명 이상이라면 Phase 2 완료 후 다음과 같이 분담:
  - 개발자 A: US1 백엔드 (워커·서비스·API)
  - 개발자 B: US1 프론트엔드 + US3 프론트엔드
  - 개발자 C: US2(이벤트·SSE·진행 UI). US1 워커가 안정화된 후 합류.

---

## Notes

- **테스트 작성 순서**: 헌법 — 테스트는 구현 전에 작성하고 실패 상태를 1회 확인한 뒤 구현으로 전환한다.
- **모든 산출 문서는 한국어**: 헌법 원칙 V. PR 본문·ADR·README·주석 외 코드 식별자는 영문 유지.
- **shell 호출 금지 원칙**: 외부 바이너리(yt-dlp / ffmpeg) 호출은 항상 인자 배열, `shell=True` 절대 금지 (FR-033).
- **Provider 결합 금지**: `app/domain/translation/*`는 `TranslationProvider` Protocol에만 의존. Anthropic SDK import는 `app/infrastructure/providers/claude_adapter.py`에만 등장해야 한다 (헌법 — Translation Provider Abstraction NON-NEGOTIABLE).
- **상태 머신 위배 시도는 거절**: 서비스 계층에서 `IllegalStateTransitionError`로 막고 해당 unit test 1건 이상 포함 (T050).
- **commit 단위**: 큰 묶음보다 task 1~2개 단위 commit이 헌법 III(작은 단위)에 부합.
- **stop & validate 체크포인트**: 각 Phase 종료 시 acceptance scenario를 직접 확인.
