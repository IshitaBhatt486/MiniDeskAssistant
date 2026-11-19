#!/usr/bin/env bash
# Run the assistant automatically on boot (systemd), on the Raspberry Pi.
#
#   scripts/install-service.sh install     create + enable + start  deskbot.service
#   scripts/install-service.sh uninstall   stop + disable + remove it
#   scripts/install-service.sh status | logs | restart | stop | start
#
# The service runs `python main.py start --lan` (everything) as YOU (not root), restarts it 5 s after a crash,
# and grants the real-time priority the motor/sensor processes ask for (LimitRTPRIO, see runtime.md).
# While the service runs, the GPIO is busy: stop it before running scripts/start.sh or sensor tests by hand.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=/etc/systemd/system/deskbot.service
USER_NAME="$(id -un)"
PY="$ROOT/.venv/bin/python"
ACTION="${1:-install}"

case "$ACTION" in
  install)
    [ -x "$PY" ] || { echo "No .venv yet - run scripts/setup.sh first."; exit 1; }
    [ "$USER_NAME" != root ] || { echo "Run this as your normal user (it uses sudo itself), not with sudo."; exit 1; }
    # gpio: motors/sensors, audio: speaker + mic, bluetooth: BLE scanning, video: camera
    for g in gpio audio bluetooth video; do
      getent group "$g" >/dev/null && sudo usermod -aG "$g" "$USER_NAME"
    done
    sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Desk assistant robot (deskbot assistant)
After=network-online.target bluetooth.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $ROOT/main.py start --lan
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=40
LimitRTPRIO=60
LimitNICE=-10

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now deskbot
    echo "Installed. It now starts on every boot."
    echo "  logs:   scripts/install-service.sh logs      stop: scripts/install-service.sh stop"
    ;;
  uninstall)
    sudo systemctl disable --now deskbot 2>/dev/null || true
    sudo rm -f "$UNIT"
    sudo systemctl daemon-reload
    echo "Removed."
    ;;
  status) systemctl status deskbot --no-pager ;;
  logs) journalctl -u deskbot -f -n 100 ;;
  restart|stop|start) sudo systemctl "$ACTION" deskbot ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
