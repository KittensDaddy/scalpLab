#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
scalp recorder-daemon &
RECORDER_PID=$!
trap 'kill "$RECORDER_PID" 2>/dev/null || true; wait "$RECORDER_PID" 2>/dev/null || true' EXIT INT TERM
scalp serve --host 0.0.0.0 --port 1120
