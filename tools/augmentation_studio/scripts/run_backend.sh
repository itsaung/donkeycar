#!/usr/bin/env bash
set -euo pipefail
STUDIO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$STUDIO/../.." && pwd)"
BACKEND="$STUDIO/backend"
VENV="$STUDIO/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "Creating venv at $VENV ..."
  python3.12 -m venv "$VENV" 2>/dev/null || python3 -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  pip install -U pip
  pip install -r "$BACKEND/requirements.txt"
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

export PYTHONPATH="${ROOT}:${BACKEND}${PYTHONPATH:+:$PYTHONPATH}"
cd "$BACKEND"
exec python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
