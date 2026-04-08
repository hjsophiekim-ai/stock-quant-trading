#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
else
  PY="${PYTHON:-python3}"
fi

if [[ ! -f ".env" ]]; then
  echo "[WARN] .env not found. Copy env.paper.example -> .env.paper -> .env"
  echo "       See docs/quickstart_real_mock_trading.md"
fi

echo "[backend] python=${PY}"
echo "[backend] uvicorn http://127.0.0.1:8000 | API docs http://127.0.0.1:8000/docs"
exec "${PY}" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
