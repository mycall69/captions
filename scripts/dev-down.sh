#!/usr/bin/env bash
set -euo pipefail

# dev-down.sh — dev-up.sh가 기동한 모든 서비스를 종료한다.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="${REPO_ROOT}/var/run"

kill_pid_file() {
  local label="$1"
  local pid_file="$2"
  if [[ -f "${pid_file}" ]]; then
    local pid
    pid=$(cat "${pid_file}")
    if kill -0 "${pid}" 2>/dev/null; then
      echo "[종료] ${label} PID=${pid}"
      kill "${pid}"
    else
      echo "[스킵] ${label} (PID=${pid} 이미 종료됨)"
    fi
    rm -f "${pid_file}"
  else
    echo "[스킵] ${label} (PID 파일 없음: ${pid_file})"
  fi
}

echo "=== 서비스 종료 시작 ==="

kill_pid_file "Next.js" "${PID_DIR}/web.pid"
kill_pid_file "Celery 워커" "${PID_DIR}/worker.pid"
kill_pid_file "FastAPI 서버" "${PID_DIR}/api.pid"

echo ""
echo "=== Redis 서비스 중지 ==="
brew services stop redis

echo ""
echo "=== 모든 서비스 종료 완료 ==="
