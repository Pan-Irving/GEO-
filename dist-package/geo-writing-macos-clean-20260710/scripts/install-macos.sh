#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

command -v python3 >/dev/null 2>&1 || {
  echo "python3 not found. Please install Python 3.11+ first."
  exit 1
}

command -v npm >/dev/null 2>&1 || {
  echo "npm not found. Please install Node.js 20 LTS+ first."
  exit 1
}

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Please edit .env and fill API keys before starting."
fi

echo "Installing writing backend dependencies..."
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/pip install -r backend/requirements.txt

echo "Installing writing frontend dependencies..."
(cd frontend && npm install)

echo "Installing publishing backend dependencies..."
python3 -m venv publishing/backend/.venv
publishing/backend/.venv/bin/python -m pip install --upgrade pip
publishing/backend/.venv/bin/pip install -r publishing/backend/requirements.txt

echo "Installing publishing frontend dependencies..."
(cd publishing/frontend && npm install)

echo
echo "Install complete."
echo "Next: edit .env, then run ./scripts/start-all-macos.sh"
