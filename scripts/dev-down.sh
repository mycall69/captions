#!/usr/bin/env bash
set -euo pipefail

# dev-down.sh — dev-up.sh가 기동한 모든 서비스를 종료한다.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="${REPO_ROOT}/var/run"

kill_pid_file() {
  local label="$1"
  local pid_file="$2"
  if [[ ! -f "${pid_file}" ]]; then
    echo "[스킵] ${label} (PID 파일 없음: ${pid_file})"
    return 0
  fi
  local pid
  pid=$(cat "${pid_file}")
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "[스킵] ${label} (PID=${pid} 이미 종료됨)"
    rm -f "${pid_file}"
    return 0
  fi
  echo "[종료] ${label} PID=${pid} (SIGTERM)"
  kill "${pid}" 2>/dev/null || true
  # SIGTERM 후 최대 5초 대기, 안 죽으면 SIGKILL
  for _ in $(seq 1 10); do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "${pid}" 2>/dev/null; then
    echo "[강제 종료] ${label} PID=${pid} (SIGKILL)"
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${pid_file}"
}

echo "=== 서비스 종료 시작 ==="

kill_pid_file "Next.js" "${PID_DIR}/web.pid"
kill_pid_file "Celery 워커" "${PID_DIR}/worker.pid"
kill_pid_file "FastAPI 서버" "${PID_DIR}/api.pid"

# 좀비 청소 — PID 파일이 가리키지 못한 잔존 프로세스를 패턴 매칭으로 정리한다.
# dev-up.sh가 도중에 중단되거나 PID 파일이 덮어써져 dev-down이 못 찾는 케이스 대비.
# 본 저장소 경로(${REPO_ROOT})를 패턴에 포함해 외부 동명 프로세스를 잘못 죽이지 않는다.
sweep_zombies() {
  local label="$1"
  local pattern="$2"
  local pids
  pids=$(pgrep -f "${pattern}" || true)
  if [[ -z "${pids}" ]]; then
    return 0
  fi
  echo "[좀비 청소] ${label} — 잔존 PID=${pids//$'\n'/ }"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 1
  pids=$(pgrep -f "${pattern}" || true)
  if [[ -n "${pids}" ]]; then
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
}

echo ""
echo "=== 좀비 프로세스 청소 ==="
sweep_zombies "Next.js dev" "${REPO_ROOT}/frontend/node_modules/.bin/next dev"
sweep_zombies "Next.js server" "next-server.*${REPO_ROOT}"
sweep_zombies "uvicorn (app.main)" "${REPO_ROOT}/backend/\\.venv/bin/uvicorn app.main"
sweep_zombies "celery 워커" "${REPO_ROOT}/backend/\\.venv/bin/celery -A app.workers"

echo ""
echo "=== Redis 서비스 중지 ==="
brew services stop redis

echo ""
echo "=== 모든 서비스 종료 완료 ==="
