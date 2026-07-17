#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p logs

pids=()

stop_all() {
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}

trap stop_all EXIT INT TERM

echo "Starting writing backend: http://127.0.0.1:8000"
./scripts/start-backend.sh > logs/writing-backend.log 2>&1 &
pids+=("$!")

echo "Starting writing frontend: http://127.0.0.1:5173"
./scripts/start-frontend.sh > logs/writing-frontend.log 2>&1 &
pids+=("$!")

echo "Starting publishing backend: http://127.0.0.1:8010"
./scripts/start-publishing-backend.sh > logs/publishing-backend.log 2>&1 &
pids+=("$!")

echo "Starting publishing frontend: http://127.0.0.1:5174"
./scripts/start-publishing-frontend.sh > logs/publishing-frontend.log 2>&1 &
pids+=("$!")

echo
echo "All services are starting."
echo "Open writing workbench: http://127.0.0.1:5173"
echo "Open publishing workbench: http://127.0.0.1:5174"
echo "Logs are in ./logs"
echo "Press Ctrl+C here to stop all services."

wait
