#!/usr/bin/env bash
# Start the desk hub: the buddy robot + "remember this idea", focus mode, Google Calendar reminders, Spotify,
# connected accounts and a Claude cost meter. Listens on the network.
#   scripts/hub.sh              on the Pi: http://<pi>:8000
#   scripts/hub.sh --sim        anywhere: simulated robot, desk, camera and phone
# Accounts need ADMIN_PIN + client IDs in secrets.env. Docs: docs/hub.md
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" main.py hub --lan "$@"
