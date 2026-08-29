# Implementation Plan: Dual Subtitle MVP

**Branch**: `001-dual-subtitle-mvp` | **Date**: 2026-05-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-dual-subtitle-mvp/spec.md`

**관련 문서**: [헌법](../../.specify/memory/constitution.md) · [와이어프레임](./wireframes.md) · [research](./research.md) · [data-model](./data-model.md) · [contracts](./contracts/) · [quickstart](./quickstart.md)

## Summary

YouTube URL 1건을 입력받아 `다운로드 → 자막 추출 → KO↔JA 번역 → dual subtitle 생성 → 브라우저 재생`을 수행하는 단일 호스트 웹 애플리케이션. FastAPI(REST + SSE) + Celery(워커) + SQLite(메타데이터) + 로컬 파일시스템(미디어) + Next.js(SPA-ish App Router). 모든 장기 작업은 Celery로 분리되며, FastAPI는 stateless·async-first 라우터에 한정. 번역은 `TranslationProvider` Protocol을 통해 호출되어 Claude/Anthropic SDK는 단일 adapter 모듈에만 결합된다.

## Technical Context

**Language/Version**:
- Backend: Python 3.12+
- Frontend: TypeScript 5.x (Next.js 15 App Router, React 19)

**Primary Dependencies**:
- Backend: FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic, Celery 5.x, Redis(브로커/백엔드), yt-dlp, ffmpeg(외부 바이너리), pysrt, webvtt-py, structlog, httpx, anthropic SDK(adapter 한정)
- Frontend: Next.js 15, TailwindCSS, shadcn/ui, TanStack Query, Zustand(가벼운 클라이언트 상태), Vitest, Playwright

**Storage**:
- 메타데이터: SQLite (WAL 모드, async SQLAlchemy)
- 미디어/자막 산출물: 로컬 파일시스템 `./var/storage/<job_id>/`
- 작업 브로커/캐시: Redis (Homebrew 네이티브)

**Testing**:
- Backend: pytest, pytest-asyncio, httpx AsyncClient, pytest-celery (eager + 실제 worker 듀얼 모드), 미디어 파이프라인용 fixture 영상/자막 세트
- Frontend: Vitest(컴포넌트), Playwright(e2e), MSW(API mock)

**Target Platform**: macOS Apple Silicon (arm64), Homebrew, zsh, Python `venv`. 헌법 IV — Docker 의존 금지.

**Project Type**: Web application (backend + frontend + worker)

**Performance Goals** (사양 SC-001~SC-008 매핑):
- POST `/v1/jobs` 응답 ≤ 1초 (SC-007)
- 상태 전이 → 클라이언트 반영 ≤ 5초 (SC-002) — SSE로 즉시 push
- 15분 영상 end-to-end ≤ 10분 (SC-001)
- dual subtitle 시간축 오차 ±200ms (SC-004)

**Constraints**:
- **영상 길이 하드 상한 120분 (7200s)** — 메타데이터 단계에서 초과 영상은 즉시 거절 (`INVALID_INPUT`). spec §Clarifications 2026-05-28 (60분 → 120분 확장 결정), FR-003 매핑.
- SQLite 동시성: WAL + 쓰기 직렬화 어댑터. 워커는 별도 connection-per-task.
- 시크릿: env 전용. `pydantic-settings`로 로드.
- 외부 바이너리: yt-dlp / ffmpeg는 `subprocess` + 인자 배열만 사용(`shell=True` 금지). 헌법 보안 FR-033.
- 번역 provider: `TranslationProvider` Protocol 의존, Claude SDK 직접 의존 금지(adapter 제외).
- 한국어 문서화: 모든 신규 `*.md`는 한국어 (헌법 V / FR-038).
- **번역 어조 보존**: 원문이 정중체이면 정중체로, 친근체이면 친근체로 번역. cue 내부 어조가 혼재하면 다수 어조를 따른다. spec §Clarifications Q1 / FR-014 매핑. Claude adapter prompt에 적용.

**Scale/Scope**: 단일 호스트, 단일 익명 사용자 컨텍스트. **동시 처리 작업 기본 상한 2건** — 환경변수 `JOB_CONCURRENCY`로 조정 가능. 초과 작업은 `pending` 상태로 대기열에 보류. Celery worker `--concurrency=$JOB_CONCURRENCY`로 기동. 일일 처리 영상 ≤ 50건 가정. UI 화면 3개(S1/S2/S3). spec §Clarifications Q5 / FR-027 매핑.

## Constitution Check

*GATE: Phase 0 전 통과 필수. Phase 1 설계 후 재검토.*

| 게이트 | 판정 | 근거 |
|---|---|---|
| **SDD First (I)** — PRD / Domain Model / API Contract / UX Flow / Sequence Diagram / Acceptance Criteria / Test Specification | ✅ | spec.md(PRD + acceptance), wireframes.md(UX), 본 plan(아키텍처) + Phase 1 산출물(data-model, contracts/openapi.yaml, contracts/events.md, quickstart, sequences in research). Test Specification은 plan §Testing Strategy. |
| **Architecture First (II)** — Layered / Celery / Stateless | ✅ | `app/api → service → domain → infrastructure`. 장기 작업 모두 Celery. API 라우터는 stateless. |
| **AI-Native (III)** — 작은 단위, self-documenting | ✅ | 모듈 ≤ 200 LoC 가이드. 도메인별 디렉터리. giant file 없음. |
| **macOS Native (IV)** — Apple Silicon / brew / venv / no Docker | ✅ | Redis는 brew. ffmpeg / yt-dlp는 brew. Docker 미사용. |
| **Korean-First Documentation (V)** | ✅ | 본 plan 및 모든 신규 산출물 한국어. |
| **번역 Provider 추상화** | ✅ | `TranslationProvider` Protocol + `ClaudeTranslationAdapter`. 도메인/태스크는 Protocol에만 의존. |
| **Queue-Based Processing** | ✅ | download / extract / translate / render 모두 Celery task. |
| **보안** | ✅ | URL validation(`urllib.parse` + 도메인 화이트리스트), 경로 sanitize, subprocess 인자 배열, env 시크릿. |
| **API 표준** | ✅ | `success / error_code / message / request_id` envelope, `/v1`, FastAPI OpenAPI 자동 생성. |
| **테스트** | ✅ | unit / integration / async pipeline / Celery worker / 미디어 validation 모두 계획. |
| **코딩 표준** | ✅ | Python Ruff·Black·mypy·pytest, TS strict + `any` 금지, OpenAPI→TS 타입 생성. |
| **금지 항목** | ✅ | god file·동기 long-running·hardcoded secret·shell interpolation·Docker·provider coupling·영문 md 모두 미포함. |

**Phase 1 재검토**: 데이터 모델·API 컨트랙트·이벤트 스키마를 생성한 후에도 모든 게이트가 동일하게 통과. Complexity Tracking 항목 없음.

## Project Structure

### Documentation (this feature)

```text
specs/001-dual-subtitle-mvp/
├── spec.md
├── plan.md                 ← 본 파일
├── wireframes.md
├── research.md             ← Phase 0
├── data-model.md           ← Phase 1
├── quickstart.md           ← Phase 1
├── contracts/              ← Phase 1
│   ├── openapi.yaml
│   └── events.md           ← SSE 이벤트 스키마
├── checklists/
│   └── requirements.md
└── tasks.md                ← /speckit-tasks (본 명령 대상 아님)
```

### Source Code (repository root)

```text
captions/
├── backend/
│   ├── pyproject.toml              # Ruff / Black / mypy / pytest 설정 포함
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py                 # FastAPI 앱 팩토리
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── routes/
│   │   │       │   ├── jobs.py
│   │   │       │   ├── subtitles.py
│   │   │       │   ├── media.py
│   │   │       │   └── events.py   # SSE
│   │   │       ├── schemas/        # Pydantic request/response DTO
│   │   │       └── envelope.py     # success/error_code/message/request_id wrapper
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings
│   │   │   ├── logging.py          # structlog 설정
│   │   │   ├── security.py         # URL validation, path sanitize
│   │   │   ├── exceptions.py       # 도메인 예외 → API envelope mapper
│   │   │   └── ids.py              # request_id / job_id 생성
│   │   ├── domain/
│   │   │   ├── jobs/
│   │   │   │   ├── models.py       # Pydantic 도메인 모델
│   │   │   │   ├── states.py       # 상태 전이 enum + 머신
│   │   │   │   ├── service.py
│   │   │   │   └── repository.py   # Protocol
│   │   │   ├── subtitles/
│   │   │   │   ├── models.py
│   │   │   │   ├── normalize.py    # SRT/VTT → 내부 cue 모델
│   │   │   │   ├── dual.py         # 두 트랙 → SRT/VTT 합본 생성
│   │   │   │   └── service.py
│   │   │   ├── translation/
│   │   │   │   ├── provider.py     # TranslationProvider Protocol
│   │   │   │   ├── chunking.py     # cue → chunk 정책
│   │   │   │   ├── cache.py        # 콘텐츠 해시 기반 캐시
│   │   │   │   └── service.py
│   │   │   ├── media/
│   │   │   │   ├── download.py     # yt-dlp wrapper (subprocess arg list)
│   │   │   │   └── render.py       # ffmpeg wrapper (MVP는 soft subtitle만)
│   │   │   └── events/
│   │   │       └── bus.py          # job 이벤트 publish (Redis pub/sub)
│   │   ├── infrastructure/
│   │   │   ├── db/
│   │   │   │   ├── session.py      # async SQLAlchemy engine, WAL
│   │   │   │   ├── orm.py          # ORM 매핑
│   │   │   │   └── migrations/     # Alembic
│   │   │   ├── storage/
│   │   │   │   └── filesystem.py   # var/storage/<job_id>/ 경로 추상화
│   │   │   ├── youtube/
│   │   │   │   └── metadata.py     # yt-dlp --dump-json wrapper
│   │   │   └── providers/
│   │   │       └── claude_adapter.py  # anthropic SDK 직접 결합 유일 지점
│   │   └── workers/
│   │       ├── celery_app.py       # Celery 인스턴스 + 라우팅 + 워커 옵션
│   │       ├── pipeline.py         # job 단계 dispatch (chord/chain)
│   │       └── tasks/
│   │           ├── download.py
│   │           ├── extract_subtitles.py
│   │           ├── translate.py
│   │           └── render.py
│   └── tests/
│       ├── unit/                   # 모델/서비스 순수 함수 테스트
│       ├── integration/            # API + DB 통합
│       ├── workers/                # Celery task (eager + worker 양 모드)
│       └── media/                  # fixture 영상/자막 검증
│
├── frontend/
│   ├── package.json
│   ├── tsconfig.json               # strict, noImplicitAny
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx              # 헤더 / 다크 모드
│   │   ├── page.tsx                # S1 메인
│   │   ├── jobs/[id]/page.tsx      # S2 / S3 (상태에 따라 분기)
│   │   └── globals.css
│   ├── components/
│   │   ├── ui/                     # shadcn primitives
│   │   ├── header/AppHeader.tsx
│   │   ├── url-input/UrlInputCard.tsx
│   │   ├── job-list/JobListItem.tsx
│   │   ├── job-list/StatusBadge.tsx
│   │   ├── stage-progress/StageProgressBar.tsx
│   │   ├── stage-progress/StageLog.tsx
│   │   ├── player/VideoPlayer.tsx
│   │   ├── player/DualSubtitleOverlay.tsx
│   │   ├── player/SubtitleControls.tsx
│   │   ├── player/SubtitleCueList.tsx
│   │   └── feedback/Toast.tsx
│   ├── lib/
│   │   ├── api/                    # openapi-typescript 생성 클라이언트
│   │   ├── api/client.ts           # fetch wrapper (envelope 처리)
│   │   ├── sse.ts                  # SSE 구독 hook
│   │   ├── stores/jobStore.ts      # Zustand
│   │   └── format/time.ts
│   └── tests/
│       ├── component/
│       └── e2e/                    # Playwright (3개 화면 user story 시나리오)
│
├── var/
│   └── storage/                    # job별 미디어/자막 파일 (런타임 생성)
│
├── scripts/
│   ├── dev-up.sh                   # brew services start redis + worker + api + web
│   ├── dev-down.sh
│   └── seed-fixtures.sh
│
└── docs/
    └── adr/
        └── 0001-translation-provider-abstraction.md
```

**Structure Decision**: 단일 리포의 **3-디렉터리 구조** — `backend/`(API + 도메인 + 워커), `frontend/`(Next.js App Router), 런타임 산출물용 `var/`. backend는 Layered Architecture를 디렉터리로 강제(`api → domain → infrastructure`, `workers/`는 도메인 호출). 워커를 backend 패키지 내부에 두는 이유: 도메인/모델/세션 공유, 별도 패키지화 시 import 그래프 복잡도가 헌법 III(단순성)를 해친다. 같은 코드베이스 안에서 **실행 단위만 분리**(`uvicorn`, `celery -A app.workers.celery_app worker`).

## Sequence (Job 처리 흐름)

```
사용자 → S1 [URL 입력]
        ↓ POST /v1/jobs                (≤1s 응답)
FastAPI ──VideoJob 생성(pending)──→ SQLite
       ──Celery 디스패치(chain)─────→ Redis 브로커
        ↓ (즉시) 201 + job_id, status
사용자 → S2 [상세 페이지]
       ──GET /v1/jobs/{id}/events──→ FastAPI SSE
                                    ↑ Redis pub/sub로 워커 상태 push
Worker1 download (downloading)         → 파일시스템 + DB 상태 갱신 + 이벤트
Worker2 extract_subtitles (subtitle_processing) → 자막 정규화 + DB + 이벤트
Worker3 translate (translating)         → chunk 단위 호출, 청크별 진행률 이벤트
Worker4 render (rendering)              → dual SRT/VTT 생성, 자산 등록, 이벤트
DB 상태 = completed                     → 이벤트 push
사용자 → S3 [재생]
       ──GET /v1/jobs/{id}/video─────→ FastAPI (Range 지원)
       ──GET /v1/jobs/{id}/subtitles─→ cue 목록 + 두 언어
       ──GET /v1/jobs/{id}/download──→ dual SRT/VTT 다운로드
실패 경로: 어느 task에서 예외 → 상태 = failed, error_stage / error_message 저장,
           이벤트 push, 후속 task 자동 취소.
```

자세한 단계별 트리거·재시도·예외 처리는 [research.md](./research.md) §파이프라인 결정과 [contracts/events.md](./contracts/events.md) 참고.

## Translation Pipeline (요약)

- **청크 정책**: 시간축 기준 60초 윈도우, 단 한 cue 경계는 자르지 않는다. 인접 청크 각각에서 직전·직후 3 cue를 **context-only**로 함께 전달(번역 결과에 포함하지 않음). 자세 내용: [research.md](./research.md) §청크.
- **provider 호출**: `TranslationProvider.translate_chunk(source_lang, target_lang, cues, context_before, context_after) -> TranslatedChunk`.
- **재시도**: provider rate limit(`RateLimitError`)·일시 네트워크 오류 → exponential backoff `1s, 2s, 4s, 8s` (4회). 최종 실패 시 작업 `failed`.
- **캐시**: chunk 내용 해시(`sha256(source_lang+target_lang+normalized_cue_text)`) → 결과. Redis에 저장(TTL 7일, MVP는 메모리 제약 시 비활성 가능).
- **결정성**: provider temperature 0, max_tokens는 chunk 길이 + buffer.
- **어조 보존 (Register Preservation)**: Claude adapter는 chunk 입력 직전에 cue 본문의 어조(KO 합니다/한다체, JA です·ます / だ·である체)를 추론한 뒤, 추론 결과를 prompt 지시문에 포함해 동일 어조로 출력하도록 강제한다. cue 내부 어조가 혼재하면 다수 어조를 따른다. spec §Clarifications Q1 / FR-014 매핑. 어조 추론 로직은 `app/infrastructure/providers/claude_adapter.py`에 한정(도메인 코드에 어조 분기 로직 누출 금지 — 헌법 Translation Provider Abstraction NON-NEGOTIABLE).

## Media Pipeline (요약)

- **다운로드**: `yt-dlp -f "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b" --no-playlist --restrict-filenames` 형태로 호출. 출력 경로는 `var/storage/<job_id>/video.mp4` 고정. 인자 배열, never shell.
- **자막 추출**: 동일 yt-dlp `--write-sub --sub-langs ko,ja --sub-format vtt --skip-download` 또는 별도 호출. `--write-auto-sub`는 manual 부재 시에만 한 번 더 시도.
- **정규화**: pysrt/webvtt-py로 cue 파싱 → 내부 `SubtitleCue(start_ms, end_ms, text)` 리스트. 빈 cue / overlapping cue 정리.
- **렌더링(MVP)**: ffmpeg로 **video remux만 수행** (필요 시 fastseek). dual subtitle은 별도 SRT/VTT 파일로 저장하고, **브라우저에서 두 언어를 클라이언트 측 overlay로 합성**(VideoPlayer + DualSubtitleOverlay). 따라서 MVP의 ffmpeg 호출은 "필요한 경우의 컨테이너 변환"에만 한정 — 영상 자체에 자막을 burn-in하지 않는다(soft subtitle 방식). 자세한 결정: [research.md](./research.md) §렌더링.
- **임시 파일**: `var/storage/<job_id>/tmp/` 하위에 격리, task 완료 후 즉시 정리.

## API & Events 요약

- **REST 라우트** (전부 `/v1` prefix)
  - `POST /jobs` — 작업 생성 (URL 검증, 동일 URL 완료작업 재사용)
  - `GET /jobs` — 페이지네이션 목록
  - `GET /jobs/{id}` — 상세
  - `DELETE /jobs/{id}` — 취소
  - `GET /jobs/{id}/subtitles` — cue 목록(원문/번역 동시 제공)
  - `GET /jobs/{id}/download` — dual SRT/VTT 다운로드(query `format`, `order`)
  - `GET /jobs/{id}/video` — mp4 스트리밍 (HTTP Range)
  - `GET /jobs/{id}/events` — **SSE** 스트림
- **응답 envelope**: 모든 응답에 `{ success, data?, error?, request_id }`. 에러는 도메인 예외 → `ApiError` → 표준 HTTP code + envelope.
- **SSE 이벤트**: `job.state_changed`, `job.progress`, `job.completed`, `job.failed`. 스키마는 [contracts/events.md](./contracts/events.md).

OpenAPI 스펙: [contracts/openapi.yaml](./contracts/openapi.yaml).

## Frontend Architecture 요약

- **라우팅(App Router)**: `/` (S1), `/jobs/[id]` (S2/S3 통합 — 상태에 따라 컴포넌트 트리 분기).
- **데이터 페칭**: TanStack Query + 생성된 OpenAPI 클라이언트. 작업 상세 화면은 SSE로 mutate를 부분적으로 무효화(React Query `setQueryData`).
- **클라이언트 상태**: 자막 표시·순서 토글은 Zustand `playerPreferenceStore`(localStorage persisted).
- **컴포넌트 트리**:
  ```
  AppLayout
   └─ AppHeader
   └─ page (/)
      ├─ UrlInputCard
      └─ JobListItem*
   └─ page (/jobs/[id])
      ├─ when state ∈ {pending..rendering, failed}: JobDetail
      │   ├─ MetadataPanel
      │   ├─ StageProgressBar
      │   ├─ StageLog
      │   └─ (실패) FailurePanel
      └─ when state = completed: JobPlayback
          ├─ MetadataHeader
          ├─ VideoPlayer
          │   └─ DualSubtitleOverlay
          ├─ SubtitleControls
          ├─ SubtitleCueList
          └─ DownloadActions
  ```
- **타입 안전성**: `openapi-typescript`로 백엔드 OpenAPI → `types/api.ts` 자동 생성. `any` 금지.

## Testing Strategy

| 범주 | 도구 | 범위 |
|---|---|---|
| Backend unit | pytest | 도메인 모델·서비스 순수 함수(상태 머신, 청크 정책, dual cue 병합, URL 검증) |
| Backend integration | pytest + httpx | API 라우트 + DB. envelope/에러 코드/페이지네이션. SSE는 별도 통합 테스트(short-lived stream). |
| Workers | pytest-celery | 각 task의 eager 모드 + 실제 worker로 chain 1회 end-to-end. retry 정책 검증. |
| Media validation | pytest | fixture 자막(SRT/VTT) 정규화 결과 스냅샷. dual subtitle 시간 정렬 ≤200ms (SC-004) 검증. |
| Translation | pytest | `FakeTranslationProvider` 어댑터로 contract 테스트. context 전달·청크 분할·재시도 로직 검증. |
| Frontend component | Vitest | UrlInputCard 검증/에러, StatusBadge 6+1 variant, StageProgressBar 단계 표시, DualSubtitleOverlay 두 줄 렌더. |
| Frontend e2e | Playwright | US1·US2·US3의 acceptance scenario를 시나리오로 1:1 재현. SSE는 mock SSE 서버로 stub. |

## 비기능 요구 매핑

| 요구 | 구현 포인트 |
|---|---|
| 비동기·streaming-friendly | FastAPI async + uvicorn. video 응답은 Range. Celery로 장기 작업 분리. |
| retry / 부분 상태 / 복구 | task별 `autoretry_for + retry_backoff`. cue 단위 진행률 DB 영구화. 재시작 시 마지막 청크부터. |
| structured logging | structlog. 모든 log에 `request_id` / `job_id` / `task_id` / `stage` 필드. |
| 보안 | URL allowlist(`youtube.com`/`youtu.be`), path는 `Path` 추상화로만 합성. subprocess 인자 배열. env 시크릿. rate limit은 FastAPI의 `slowapi`로 IP 기준 10 req/min. |

## Complexity Tracking

(헌법 위반 없음. 표 비어 둠.)

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
