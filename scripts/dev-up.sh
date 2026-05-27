#!/usr/bin/env bash
set -euo pipefail

# dev-up.sh — Redis + API 서버 + Celery 워커 + Next.js 개발 서버를 기동한다.
# PID 파일은 var/run/ 디렉터리에 저장되며, dev-down.sh가 참조해 프로세스를 종료한다.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="${REPO_ROOT}/var/run"
mkdir -p "${PID_DIR}"

echo "=== [1/4] Redis 기동 ==="
brew services start redis
echo "Redis → localhost:6379"

echo ""
echo "=== [2/4] FastAPI 서버 기동 (포트 8000) ==="
(
  cd "${REPO_ROOT}/backend"
  source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000 &
  echo $! > "${PID_DIR}/api.pid"
  echo "API 서버 PID=$(cat "${PID_DIR}/api.pid") → http://localhost:8000"
)

echo ""
echo "=== [3/4] Celery 워커 기동 ==="
(
  cd "${REPO_ROOT}/backend"
  source .venv/bin/activate
  celery -A app.workers.celery_app worker \
    --loglevel=INFO \
    --concurrency="${JOB_CONCURRENCY:-2}" &
  echo $! > "${PID_DIR}/worker.pid"
  echo "Celery 워커 PID=$(cat "${PID_DIR}/worker.pid") concurrency=${JOB_CONCURRENCY:-2}"
)

echo ""
echo "=== [4/4] Next.js 개발 서버 기동 (포트 3000) ==="
(
  cd "${REPO_ROOT}/frontend"
  npm run dev &
  echo $! > "${PID_DIR}/web.pid"
  echo "Next.js PID=$(cat "${PID_DIR}/web.pid") → http://localhost:3000"
)

echo ""
echo "=== 모든 서비스 기동 완료 ==="
echo "  API   : http://localhost:8000/docs"
echo "  Web   : http://localhost:3000"
echo "  중지하려면 ./scripts/dev-down.sh 실행"
