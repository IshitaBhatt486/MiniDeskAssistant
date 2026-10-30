#!/usr/bin/env bash
# Start the robot WITH the voice assistant, AI brain, chipmunk speaker, Bluetooth presence and phone remote.
# Listens on the network by default (that's the point of the remote):
#   scripts/assistant.sh                      on the Pi: http://<pi>:8000  ·  remote: http://<pi>:8000/remote
#                                             microphones need https://<pi>:8443 (accept the warning once)
#   scripts/assistant.sh --sim                anywhere: simulated robot, desk, camera and phone
#   scripts/assistant.sh --camera none        no camera
# API keys: copy secrets.env.example to secrets.env and fill it in. Docs: docs/assistant.md
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" -m deskbot assistant --lan "$@"
