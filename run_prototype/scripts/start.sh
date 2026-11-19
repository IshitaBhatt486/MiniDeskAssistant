#!/usr/bin/env bash
# Start the whole app: robot + 4 sonars + IR + Pi camera + YOLO26n/ByteTrack + fusion maps + dashboard.
#   scripts/start.sh                 http://localhost:8000 on the Pi
#   scripts/start.sh --lan           also from other devices on the network
#   scripts/start.sh --camera none   no camera (maps from sonar + IR only)
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" -m deskbot run "$@"
