#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 is required. Set PYTHON_BIN if your executable has another name." >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  "$PYTHON_BIN" -m venv .venv
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Default settings are local-only."
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
HOST_VALUE="$(grep -E '^HOST=' .env | tail -n1 | cut -d= -f2- | tr -d '\r' | xargs || true)"
PORT_VALUE="$(grep -E '^PORT=' .env | tail -n1 | cut -d= -f2- | tr -d '\r' | xargs || true)"
HOST_VALUE="${HOST_VALUE:-127.0.0.1}"
PORT_VALUE="${PORT_VALUE:-8000}"
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST_VALUE" --port "$PORT_VALUE"
