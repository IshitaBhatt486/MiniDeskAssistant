#!/usr/bin/env bash
# Interactive sensor tests (motors never move).
#   scripts/sensors.sh                         menu
#   scripts/sensors.sh front | all | camera | detect
#   scripts/sensors.sh detect --camera webcam
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" -m deskbot sensors "$@"
