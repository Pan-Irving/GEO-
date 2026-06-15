#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/publishing/frontend"

if [ ! -d "node_modules" ]; then
  echo "publishing/frontend/node_modules not found. Run: cd publishing/frontend && npm install"
  exit 1
fi

npm run dev -- --host 127.0.0.1 --port 5174
