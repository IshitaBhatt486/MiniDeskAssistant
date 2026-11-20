#!/usr/bin/env bash
# Start the desk buddy: the whole robot + spoken task list with deadlines, reminders and celebrations
# + important phone notifications read aloud. Listens on the network (the phone posts notifications to it).
#   scripts/buddy.sh              on the Pi: http://<pi>:8000   phone webhook: http://<pi>:8000/api/notify
#   scripts/buddy.sh --sim        anywhere: simulated robot, desk, camera and phone
# Docs: docs/buddy.md
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" main.py buddy --lan "$@"
