#!/usr/bin/env bash
# Run the whole app on any computer with the simulated robot, desk and camera.
#   scripts/sim.sh                    simulated camera (no model needed)
#   scripts/sim.sh --camera webcam    real YOLO26n on your webcam, simulated robot
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" -m deskbot run --sim "$@"
