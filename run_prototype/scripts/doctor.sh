#!/usr/bin/env bash
# Check installation, camera, model, pins.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" -m deskbot doctor "$@"
