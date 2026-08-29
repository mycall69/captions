# Captions — Dual Subtitle MVP

YouTube 영상에서 자막을 추출해 한국어 ↔ 일본어로 번역하고, 원문과 번역문을 한 화면에
함께 보여주는 듀얼 자막 서비스의 MVP 저장소다. 본 저장소의 모든 작업은
[헌법](.specify/memory/constitution.md) v1.0.1을 따르며, 모든 마크다운 산출물은
한국어로 작성한다 (헌법 V).

## 주요 기능

- **US1 — 듀얼 자막 생성**: YouTube URL을 입력하면 원본·번역 자막을 정렬해 한 화면에 표시한다.
- **US2 — 진행 상황 실시간 추적**: 다운로드 → 자막 추출 → 번역 → 렌더링 단계 전이를 SSE로 5초 이내 반영한다.
- **US3 — 최근 작업 목록**: 진행 중 / 완료 / 실패 작업을 카드로 확인하고 상세 페이지로 빠르게 복귀한다.

## 기술 스택

- **Runtime**: Python 3.12 · Node.js 24 LTS (저장소 루트 `.nvmrc` 참고)
- **Backend**: FastAPI · Pydantic v2 · SQLAlchemy 2 (aiosqlite) · Celery · Redis · structlog
- **번역 Provider**: Anthropic Claude API (`TranslationProvider` Protocol을 통해 추상화 — ADR 0001)
- **미디어 처리**: yt-dlp · pysrt · webvtt-py · ffmpeg (`-c copy` remux 전용 — ADR 0002)
- **Frontend**: Next.js 15 (App Router) · TypeScript strict · Tailwind · shadcn/ui · TanStack Query · Zustand
- **테스트**: pytest · Vitest · Playwright · MSW

## 빠른 시작

상세 절차는 [개발 환경 가이드](specs/001-dual-subtitle-mvp/quickstart.md)를 참고한다. 요약하면 다음과 같다.

```bash
# 1. 의존성 설치
cd backend && uv sync
cd ../frontend && npm install

# 2. .env 준비 (.env.example 복사 후 ANTHROPIC_API_KEY 등 채우기)
cp .env.example .env

# 3. 개발 서버 일괄 기동 (redis + api + worker + web)
./scripts/dev-up.sh

# 4. 브라우저에서 http://localhost:3000 진입
```

## 디렉터리 구조

```text
captions/
├── backend/                 FastAPI · Celery 워커 · 도메인 / 인프라 계층
│   ├── app/
│   │   ├── api/v1/          REST 라우트 · 미들웨어 · 의존성
│   │   ├── core/            공통 유틸 (config, ids, security, exceptions)
│   │   ├── domain/          순수 도메인 모델 / 서비스 / Protocol
│   │   ├── infrastructure/  DB · 외부 provider 어댑터
│   │   └── workers/         Celery task 체인
│   └── tests/               unit · integration · workers · media
├── frontend/                Next.js 15 App Router 클라이언트
│   ├── app/                 페이지 · 레이아웃 · 라우팅
│   ├── components/          UI · 기능별 컴포넌트
│   └── lib/                 API 클라이언트 · 상태 store · 훅
├── docs/adr/                Architecture Decision Records (MADR 형식)
├── scripts/                 dev-up / dev-down 등 보조 스크립트
├── specs/                   기능별 명세 / 계획 / 작업 (Spec Kit)
└── var/                     런타임 저장소 (DB · 미디어 · 로그)
```

## 문서 트리

- 명세 (PRD): [specs/001-dual-subtitle-mvp/spec.md](specs/001-dual-subtitle-mvp/spec.md)
- 구현 계획: [specs/001-dual-subtitle-mvp/plan.md](specs/001-dual-subtitle-mvp/plan.md)
- API 컨트랙트: [specs/001-dual-subtitle-mvp/contracts/openapi.yaml](specs/001-dual-subtitle-mvp/contracts/openapi.yaml)
- 실시간 이벤트 (SSE): [specs/001-dual-subtitle-mvp/contracts/events.md](specs/001-dual-subtitle-mvp/contracts/events.md)
- 데이터 모델: [specs/001-dual-subtitle-mvp/data-model.md](specs/001-dual-subtitle-mvp/data-model.md)
- 와이어프레임: [specs/001-dual-subtitle-mvp/wireframes.md](specs/001-dual-subtitle-mvp/wireframes.md)
- 리서치 노트: [specs/001-dual-subtitle-mvp/research.md](specs/001-dual-subtitle-mvp/research.md)
- 개발 환경: [specs/001-dual-subtitle-mvp/quickstart.md](specs/001-dual-subtitle-mvp/quickstart.md)
- 헌법: [.specify/memory/constitution.md](.specify/memory/constitution.md)
- ADR 목록: [docs/adr/](docs/adr/)

## 개발 명령어

| 영역 | 명령어 | 설명 |
|---|---|---|
| Backend | `cd backend && uv run pytest` | 전체 테스트 (unit · integration · workers · media) |
| Backend | `cd backend && uv run pytest tests/integration -q` | 통합 테스트만 |
| Backend | `cd backend && uv run ruff check .` | Lint |
| Backend | `cd backend && uv run mypy app/` | 타입 검사 |
| Frontend | `cd frontend && npm run test` | Vitest 컴포넌트 테스트 |
| Frontend | `cd frontend && npm run test:e2e` | Playwright E2E |
| Frontend | `cd frontend && npm run lint` | ESLint |
| Frontend | `cd frontend && npm run type-check` | TypeScript strict 체크 |
| 전체 | `./scripts/dev-up.sh` | redis · api · worker · web 일괄 기동 |
| 전체 | `./scripts/dev-down.sh` | 일괄 종료 |

실제 yt-dlp 네트워크 호출이 필요한 smoke 테스트는 `RUN_REAL_NETWORK=1 uv run pytest tests/media -k smoke`로 별도 실행한다.

## 라이선스 / 기여 가이드

- 라이선스: TBD (출시 전 결정)
- 기여 가이드: 본 저장소는 [Spec Kit](https://github.com/github/spec-kit) 워크플로우를 따른다.
  새 기능은 `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → 구현 → `/speckit-analyze` 순서를 거치며,
  모든 PR은 헌법 게이트(테스트·문서·번역 provider 추상화·한국어 마크다운)를 통과해야 한다.
- **`.specify/feature.json` 재생성 안내**: Spec Kit v1.0.1부터 현재 작업 중인 feature 디렉터리는
  git 브랜치 이름이 아니라 `.specify/feature.json`(머신 로컬 상태, git 추적 제외)으로만 결정된다.
  브랜치를 전환하거나 새로 clone한 직후 `check-prerequisites.sh` 등 Spec Kit 스크립트가
  `"ERROR: Feature directory not found"`를 내면, 아래처럼 현재 feature를 가리키도록 파일을 다시
  만들어주면 된다 (`/speckit-plan` 등 Spec Kit 명령을 한 번 실행해도 자동으로 재생성된다).

  ```bash
  echo '{"feature_directory":"specs/001-dual-subtitle-mvp"}' > .specify/feature.json
  ```
