#!/usr/bin/env bash
set -euo pipefail
FRONTEND="$(cd "$(dirname "$0")/../frontend" && pwd)"
cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  npm install
fi
exec npm run dev
