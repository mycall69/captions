# Quickstart: Dual Subtitle MVP

**관련**: [plan.md](./plan.md) · [data-model.md](./data-model.md) · [contracts/openapi.yaml](./contracts/openapi.yaml)

**대상**: macOS Apple Silicon. 헌법 IV — Docker 없이 네이티브 실행.

본 문서는 개발 환경 구축과 첫 end-to-end 실행 절차를 정리한다. 실제 코드는 `/speckit-tasks`
이후의 구현 단계에서 추가되므로, 이 시점에는 **기대 동작과 명령어 시퀀스**가 합의된 기준이다.

## 1. 사전 요구사항

| 도구 | 권장 버전 | 설치 |
|---|---|---|
| Homebrew | 최신 | https://brew.sh |
| Python | 3.12+ | `brew install python@3.12` |
| Node.js | 24.x LTS | `brew install node@24 && brew link --force --overwrite node@24` (혹은 `fnm` / `nvm`로 `.nvmrc` 자동 적용) |
| Redis | 7.x | `brew install redis` |
| ffmpeg | 7.x | `brew install ffmpeg` |
| yt-dlp | 최신 | `brew install yt-dlp` (또는 venv 안에서 `pip install yt-dlp`) |
| Git | 2.40+ | `brew install git` |

zsh 환경 기준. shell 다른 경우 PATH 설정만 동일 적용.

## 2. 저장소 / 환경 변수

```bash
# 저장소 클론 후 루트로 이동
cd /path/to/captions

# 환경 변수 파일 생성 (예시)
cp .env.example .env  # 구현 단계에서 .env.example 추가 예정
```

`.env` 필수 키 (구현 단계 task에 포함):

```
# 공통
APP_ENV=local
LOG_LEVEL=INFO              # 헌법 VI — 기본 INFO 강제, 프로덕션 DEBUG 금지
REQUEST_ID_HEADER=x-request-id

# 데이터 / 스토리지
DATABASE_URL=sqlite+aiosqlite:///./var/db/app.db
LOG_DIR=./logs              # 헌법 VI — backend/app.log + frontend/access.log 적재 루트
STORAGE_ROOT=./var/storage

# 큐
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# 번역 provider (Claude adapter 한정)
# 인증은 둘 중 하나로 설정한다. 둘 다 있으면 CLAUDE_CODE_OAUTH_TOKEN 이 우선한다.
TRANSLATION_PROVIDER=claude
ANTHROPIC_API_KEY=...               # Premium Seat 키 (운영 권장, x-api-key)
CLAUDE_CODE_OAUTH_TOKEN=...         # Claude Code 구독 OAuth 토큰 (개인/실험용, Bearer)
TRANSLATION_MODEL=claude-opus-4-7

# 보안 / rate limit
RATE_LIMIT_PER_MIN=10
ALLOWED_HOSTS=youtube.com,www.youtube.com,m.youtube.com,youtu.be
```

> 시크릿은 절대 commit하지 않는다. `.env`는 `.gitignore`에 포함되어야 한다.

## 3. 백엔드 부트스트랩

```bash
cd backend

# venv 생성 및 활성화 (헌법 IV)
python3.12 -m venv .venv
source .venv/bin/activate

# 의존성 설치 (구현 단계에서 pyproject.toml 정의)
pip install -e ".[dev]"

# DB 초기화
alembic upgrade head

# Redis 기동 (백그라운드 서비스)
brew services start redis

# API 서버 (개발용)
uvicorn app.main:app --reload --port 8000

# 별도 터미널에서 Celery 워커
celery -A app.workers.celery_app worker --loglevel=INFO --concurrency=2
```

## 4. 프론트엔드 부트스트랩

```bash
cd frontend

# 의존성
npm install

# OpenAPI → TS 타입 생성 (API 변경 시 재실행)
npm run codegen          # = openapi-typescript ../specs/.../contracts/openapi.yaml -o lib/api/types.gen.ts

# 개발 서버 (Next.js)
npm run dev              # http://localhost:3000
```

## 5. 통합 스크립트 (옵션)

`scripts/dev-up.sh`이 위 절차를 묶어준다.

```bash
./scripts/dev-up.sh      # redis + api + worker + web (각각 tmux 또는 background)
./scripts/dev-down.sh
```

## 6. 첫 end-to-end 시나리오 (P1 acceptance)

1. `http://localhost:3000` 진입 → URL 입력란 자동 포커스 확인.
2. 자막이 있는 짧은 일본어 YouTube 영상 URL 붙여넣기 → `시작` 클릭.
3. 같은 페이지에서 S2(상세 페이지)로 라우팅되며 단계 인디케이터가 표시되는지 확인.
4. 단계 전이가 5초 이내 화면에 반영되는지 확인 (SC-002).
5. `completed` 상태가 되면 S3 재생 화면이 열리고, dual subtitle이 영상 위에 표시되는지 확인.
6. 자막 토글 / 순서 전환 / SRT·VTT 다운로드가 의도대로 동작하는지 확인 (FR-018·022·023).

## 7. 테스트 실행

```bash
# Backend
cd backend
pytest                                 # 전체
pytest tests/unit -q                   # 단위
pytest tests/integration -q            # API + DB
pytest tests/workers -q                # Celery task
pytest tests/media -q                  # fixture 검증
```

```bash
# Frontend
cd frontend
npm run test                           # Vitest 컴포넌트
npm run test:e2e                       # Playwright (개발 서버 자동 기동)
```

E2E 테스트는 fixture 영상을 사용하므로 외부 네트워크가 불필요하다. 실제 yt-dlp 호출이
필요한 smoke 테스트는 `RUN_REAL_NETWORK=1 pytest tests/media -q -k smoke`로 별도 실행.

## 8. 코딩 표준 검증

```bash
# Backend
cd backend
ruff check .
black --check .
mypy app

# Frontend
cd frontend
npm run lint
npm run type-check
```

CI / pre-commit hook 구성도 헌법 코딩 표준에 따라 동일 명령을 사용한다.

## 9. 자주 만나는 문제

| 증상 | 원인 / 해결 |
|---|---|
| `RedisConnectionError` | `brew services list` 확인. 멈췄으면 `brew services restart redis`. |
| `yt-dlp 실행 파일을 찾을 수 없습니다.` (POST `/v1/jobs` 응답에 노출) | `brew install yt-dlp` 후 `which yt-dlp`로 PATH 확인. dev-up.sh가 사전 체크하므로 보통 기동 단계에서 막힌다. |
| `SUBTITLE_NOT_FOUND` ("이 영상에는 한국어 / 일본어 자막이 없습니다.") | (1) yt-dlp `--list-subs <URL>` 로 자막 트랙 존재 여부 확인 → 트랙은 있는데 다운로드만 막히면 YouTube anti-bot 게이트(`Sign in to confirm you're not a bot`)일 가능성. (2) `.env` 의 `YT_DLP_COOKIES_BROWSER` 를 로컬 브라우저(예: `firefox`)로 설정하고 해당 브라우저에 YouTube 로그인 후 worker 재기동. (3) 그래도 트랙 자체가 없으면 spec FR-008/011 의 정상 실패 — 다른 영상으로 재시도. |
| `yt-dlp` 영상 ID 거절 | 도메인 allowlist 검증 통과 여부 확인 (`backend/app/core/security.py`). 모바일 / 단축 URL은 입력 후 정규화 결과 확인. |
| SQLite `database is locked` | 워커 동시성을 줄이거나(`--concurrency=1`) 트랜잭션 길이 점검. 헌법 — 짧은 트랜잭션 가이드 준수. |
| ffmpeg `command not found` | `brew install ffmpeg` 후 `which ffmpeg`로 PATH 확인. dev-up.sh 사전 체크에도 동일 동작. |
| Anthropic API 인증 실패 | `.env`의 `ANTHROPIC_API_KEY` 또는 `CLAUDE_CODE_OAUTH_TOKEN` 확인. 코드에 하드코딩 시 헌법 위반. |
| SSE 연결이 끊기고 재연결되지 않음 | 브라우저 dev tools → Network → EventStream 확인. `Last-Event-ID`가 정상 전달되는지 확인. |

## 10. 다음 단계

1. `/speckit-tasks` 실행 — plan / data-model / contracts를 입력으로 task 분할.
2. (선택) `/speckit-checklist` — task 단위 품질 체크리스트.
3. `/speckit-implement` 또는 `/speckit-taskstoissues`로 구현 / 이슈화.
