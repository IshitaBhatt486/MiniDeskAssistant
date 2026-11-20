#!/usr/bin/env bash
# Start the pro desk robot: the full robot + a configurable dashboard (add / remove / drag cards, light / dark),
# headpats on 3 touch pads, knock / bump / shake / tip detection from the MPU-6050, Groq as the first AI brain
# (Claude as fallback), a voice studio (pitch, speed, voice, profiles) and Accounts / APIs-in-use cards.
# Listens on the network.
#   scripts/pro.sh              on the Pi: http://<pi>:8000
#   scripts/pro.sh --sim        anywhere: simulated robot, desk, camera, phone, touch pads and IMU events
# Docs: docs/pro.md
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "$PY" main.py pro --lan "$@"
