#!/bin/bash
# Start the KAIROS API on http://127.0.0.1:8000 (macOS/Linux/Git Bash).
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=.venv/Scripts/python; fi
exec "$PY" -m uvicorn kairos.api.app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
