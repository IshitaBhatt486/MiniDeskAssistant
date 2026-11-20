#!/usr/bin/env bash
# Start the full desk robot: every feature (wake word, routines, smart home, reader, local AI, games, hydration,
# briefings, owner recognition, guard mode, Telegram), each switchable on the dashboard. Listens on the network.
#   scripts/full.sh              on the Pi: http://<pi>:8000
#   scripts/full.sh --sim        anywhere: simulated robot, desk, camera and phone
# Every feature and command: python main.py help. Docs: docs/full.md, docs/local-only.md
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" main.py full --lan "$@"
