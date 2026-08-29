#!/usr/bin/env bash
set -euo pipefail

# dev-up.sh — Redis + API 서버 + Celery 워커 + Next.js 개발 서버를 기동한다.
# PID 파일은 var/run/ 디렉터리에 저장되며, dev-down.sh가 참조해 프로세스를 종료한다.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="${REPO_ROOT}/var/run"
# 헌법 VI — backend/frontend 로그는 저장소 루트 logs/ 하위에 분리 적재한다.
BACKEND_LOG_DIR="${REPO_ROOT}/logs/backend"
FRONTEND_LOG_DIR="${REPO_ROOT}/logs/frontend"
mkdir -p "${PID_DIR}" "${BACKEND_LOG_DIR}" "${FRONTEND_LOG_DIR}" \
  "${REPO_ROOT}/var/db" "${REPO_ROOT}/var/storage"

# 헌법 VI — backend Settings.log_dir 는 기본값 ./logs (cwd 기반). backend cwd 는
# backend/ 이므로 절대경로 LOG_DIR 을 env 로 주입해 저장소 루트 logs/ 에 적재한다.
export LOG_DIR="${REPO_ROOT}/logs"
# Settings.storage_root 도 동일 이유로 절대경로 주입 — 저장소 루트 var/storage/ 에
# 적재하지 않으면 backend/var/storage/ 에 흩어져 운영자가 찾기 어렵다.
export STORAGE_ROOT="${REPO_ROOT}/var/storage"

# 저장소 루트 .env 를 dev 프로세스 환경에 주입한다 (pydantic-settings 의
# env_file=".env" 는 backend cwd 기반이라 루트 .env 를 못 읽기 때문).
# pytest 는 dev-up 과 무관하게 실행되므로 테스트 격리에 영향 없음.
# shellcheck disable=SC1091
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  source "${REPO_ROOT}/.env"
  set +a
fi

BACKEND_VENV="${REPO_ROOT}/backend/.venv"
if [[ ! -d "${BACKEND_VENV}" ]]; then
  echo "ERROR: backend venv 없음 (${BACKEND_VENV}). 'cd backend && python3.12 -m venv .venv && pip install -e \".[dev]\"' 먼저 실행." >&2
  exit 1
fi
if [[ ! -d "${REPO_ROOT}/frontend/node_modules" ]]; then
  echo "ERROR: frontend node_modules 없음. 'cd frontend && npm install' 먼저 실행." >&2
  exit 1
fi

UVICORN="${BACKEND_VENV}/bin/uvicorn"
CELERY="${BACKEND_VENV}/bin/celery"

# 외부 의존 바이너리 사전 체크 (quickstart §1 매핑) — 누락이 런타임 에러로
# 드러나지 않도록 기동 전에 한꺼번에 검증한다.
missing_bins=()
for bin in yt-dlp ffmpeg; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    missing_bins+=("${bin}")
  fi
done
if [[ ${#missing_bins[@]} -gt 0 ]]; then
  echo "ERROR: 필수 바이너리가 설치되어 있지 않습니다: ${missing_bins[*]}" >&2
  echo "  → 'brew install ${missing_bins[*]}' 후 다시 실행하세요." >&2
  exit 1
fi

echo "=== [1/4] Redis 기동 ==="
if ! command -v redis-server >/dev/null 2>&1; then
  echo "ERROR: redis가 설치되어 있지 않습니다." >&2
  echo "  → 'brew install redis' 후 다시 실행하세요." >&2
  exit 1
fi
if ! brew services list 2>/dev/null | grep -q '^redis '; then
  echo "ERROR: redis가 brew formula로 관리되지 않습니다." >&2
  echo "  → 'brew install redis' 로 재설치하거나 수동으로 redis-server를 기동하세요." >&2
  exit 1
fi
brew services start redis
echo "Redis → localhost:6379"

echo ""
echo "=== [2/4] FastAPI 서버 기동 (포트 8000) ==="
(cd "${REPO_ROOT}/backend" && "${UVICORN}" app.main:app --reload --port 8000 \
  >> "${BACKEND_LOG_DIR}/api.stdout.log" 2>&1) &
API_PID=$!
echo "${API_PID}" > "${PID_DIR}/api.pid"
echo "API 서버 PID=${API_PID} → http://localhost:8000"
echo "  stdout/stderr → logs/backend/api.stdout.log"
echo "  structlog 파일 sink → logs/backend/app.log (헌법 VI)"

echo ""
echo "=== [3/4] Celery 워커 기동 ==="
(cd "${REPO_ROOT}/backend" && "${CELERY}" -A app.workers.celery_app worker \
  --loglevel=INFO \
  --concurrency="${JOB_CONCURRENCY:-2}" \
  >> "${BACKEND_LOG_DIR}/worker.stdout.log" 2>&1) &
WORKER_PID=$!
echo "${WORKER_PID}" > "${PID_DIR}/worker.pid"
echo "Celery 워커 PID=${WORKER_PID} concurrency=${JOB_CONCURRENCY:-2}"
echo "  stdout/stderr → logs/backend/worker.stdout.log"

echo ""
echo "=== [4/4] Next.js 개발 서버 기동 (포트 3000) ==="
# Next.js dev 컴파일러 race(특히 middleware self-fetch → /api/internal/access-log
# 컴파일)가 .next 에 부분 손상을 남기면, 다음 cold start 에서 ENOENT 가 반복된다.
# 매 dev-up 마다 캐시를 통째로 비워 손상 누적을 차단한다. 첫 페이지 로드는
# ~1.5초 증가하지만 dev 환경 안정성이 더 중요하다.
if [[ -d "${REPO_ROOT}/frontend/.next" ]]; then
  echo "  .next 캐시 청소 → 손상 누적 차단"
  rm -rf "${REPO_ROOT}/frontend/.next"
fi
(cd "${REPO_ROOT}/frontend" && npm run dev >> "${FRONTEND_LOG_DIR}/dev-server.log" 2>&1) &
WEB_PID=$!
echo "${WEB_PID}" > "${PID_DIR}/web.pid"
echo "Next.js PID=${WEB_PID} → http://localhost:3000"
echo "  dev 서버 출력 → logs/frontend/dev-server.log"
echo "  HTTP access 로그 → logs/frontend/access.log (헌법 VI)"

echo ""
echo "=== 모든 서비스 기동 완료 ==="
echo "  API   : http://localhost:8000/docs"
echo "  Web   : http://localhost:3000"
echo "  중지하려면 ./scripts/dev-down.sh 실행"
