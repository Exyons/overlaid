#!/usr/bin/env bash
# Development: FastAPI on 8787, Vite on 5173 proxying /api to it.
# Production:  build the frontend, then FastAPI serves dist/ from one port.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8787}"

case "${1:-dev}" in
  dev)
    uv run uvicorn api.main:app --reload --port "$PORT" &
    trap 'kill 0' EXIT
    npm --prefix web run dev
    ;;
  build)
    npm --prefix web ci
    npm --prefix web run build
    ;;
  serve)
    [ -d web/dist ] || { echo "Run './run.sh build' first."; exit 1; }
    exec uv run uvicorn api.main:app --port "$PORT"
    ;;
  *)
    echo "usage: ./run.sh [dev|build|serve]" >&2
    exit 1
    ;;
esac
