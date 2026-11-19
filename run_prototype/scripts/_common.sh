#!/usr/bin/env bash
# Shared by every script in scripts/: go to run_prototype/ and pick the Python to use.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"            # Raspberry Pi / Linux / macOS
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"    # Windows (Git Bash)
elif [ -x "$ROOT/../.venv/bin/python" ]; then
  PY="$ROOT/../.venv/bin/python"         # environment at the top of the full repository
elif [ -x "$ROOT/../.venv/Scripts/python.exe" ]; then
  PY="$ROOT/../.venv/Scripts/python.exe"
else
  PY="$(command -v python3 || command -v python)"
  echo "note: .venv not found - using $PY. Run scripts/setup.sh once to install everything." >&2
fi

export PYTHONUNBUFFERED=1

is_pi() { grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; }
