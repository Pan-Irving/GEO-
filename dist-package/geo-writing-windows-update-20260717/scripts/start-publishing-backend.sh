#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/publishing/backend"

valid_venv() {
  [ -x "$1/bin/python" ] && "$1/bin/python" -c "import sys" >/dev/null 2>&1
}

VENV_DIR=""
if valid_venv "$ROOT_DIR/publishing/backend/.venv"; then
  VENV_DIR="$ROOT_DIR/publishing/backend/.venv"
elif valid_venv "$ROOT_DIR/.venv"; then
  VENV_DIR="$ROOT_DIR/.venv"
fi

if [ -z "$VENV_DIR" ]; then
  echo "No Python virtual environment found. Run: python -m venv .venv && source .venv/bin/activate && pip install -r publishing/backend/requirements.txt"
  exit 1
fi

source "$VENV_DIR/bin/activate"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
