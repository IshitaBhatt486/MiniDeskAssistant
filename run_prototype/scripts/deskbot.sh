#!/usr/bin/env bash
# Interactive menu for everything (start, simulate, test sensors, model, checks).
# Any sub-command also works: scripts/deskbot.sh run --sim
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" -m deskbot "$@"
