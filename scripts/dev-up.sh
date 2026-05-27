#!/usr/bin/env bash
set -euo pipefail

# dev-up.sh — Redis + API 서버 + Celery 워커 + Next.js 개발 서버를 기동한다.
# PID 파일은 var/run/ 디렉터리에 저장되며, dev-down.sh가 참조해 프로세스를 종료한다.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="${REPO_ROOT}/var/run"
LOG_DIR="${REPO_ROOT}/var/log"
mkdir -p "${PID_DIR}" "${LOG_DIR}"

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

echo "=== [1/4] Redis 기동 ==="
brew services start redis
echo "Redis → localhost:6379"

echo ""
echo "=== [2/4] FastAPI 서버 기동 (포트 8000) ==="
(cd "${REPO_ROOT}/backend" && "${UVICORN}" app.main:app --reload --port 8000 \
  >> "${LOG_DIR}/api.log" 2>&1) &
API_PID=$!
echo "${API_PID}" > "${PID_DIR}/api.pid"
echo "API 서버 PID=${API_PID} → http://localhost:8000 (logs: var/log/api.log)"

echo ""
echo "=== [3/4] Celery 워커 기동 ==="
(cd "${REPO_ROOT}/backend" && "${CELERY}" -A app.workers.celery_app worker \
  --loglevel=INFO \
  --concurrency="${JOB_CONCURRENCY:-2}" \
  >> "${LOG_DIR}/worker.log" 2>&1) &
WORKER_PID=$!
echo "${WORKER_PID}" > "${PID_DIR}/worker.pid"
echo "Celery 워커 PID=${WORKER_PID} concurrency=${JOB_CONCURRENCY:-2} (logs: var/log/worker.log)"

echo ""
echo "=== [4/4] Next.js 개발 서버 기동 (포트 3000) ==="
(cd "${REPO_ROOT}/frontend" && npm run dev >> "${LOG_DIR}/web.log" 2>&1) &
WEB_PID=$!
echo "${WEB_PID}" > "${PID_DIR}/web.pid"
echo "Next.js PID=${WEB_PID} → http://localhost:3000 (logs: var/log/web.log)"

echo ""
echo "=== 모든 서비스 기동 완료 ==="
echo "  API   : http://localhost:8000/docs"
echo "  Web   : http://localhost:3000"
echo "  중지하려면 ./scripts/dev-down.sh 실행"
