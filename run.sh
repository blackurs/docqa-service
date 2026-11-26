#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[docqa] Creating virtual environment..."
  python3 -m venv .venv
fi

echo "[docqa] Installing dependencies..."
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/python -m pip install -q -e .

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[docqa] Created .env from .env.example (mock provider, no API key needed)"
fi

echo "[docqa] Starting API on http://127.0.0.1:8000 (docs: /docs)"
exec .venv/bin/python -m docqa.cli serve "$@"
