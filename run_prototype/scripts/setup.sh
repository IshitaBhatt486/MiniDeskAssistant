#!/usr/bin/env bash
# One-time install. Safe to re-run.
#
#   scripts/setup.sh              everything (system packages on the Pi, venv, Python packages, NCNN model)
#   scripts/setup.sh --no-vision  skip Ultralytics/NCNN (mapping from sonar + IR only)
#   scripts/setup.sh --no-model   install packages but don't export the model yet
#   scripts/setup.sh --no-assistant  skip the voice assistant (espeak-ng, Bluetooth, anthropic, bleak)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VISION=1
MODEL=1
ASSISTANT=1
for arg in "$@"; do
  case "$arg" in
    --no-vision) VISION=0; MODEL=0 ;;
    --no-model) MODEL=0 ;;
    --no-assistant) ASSISTANT=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

if grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
  step "Raspberry Pi detected: $(tr -d '\0' < /proc/device-tree/model)"
  if [ "$(uname -m)" != "aarch64" ]; then
    echo "WARNING: 32-bit OS ($(uname -m)). Ultralytics needs 64-bit Raspberry Pi OS (Bookworm)."
  fi
  step "System packages (camera stack + GPIO) - asks for your password"
  # picamera2/libcamera only exist as system packages, which is why the venv below uses --system-site-packages
  sudo apt-get update -qq
  sudo apt-get install -y python3-picamera2 python3-gpiozero python3-venv python3-pip libopenblas0
  step "I2C bus for the MPU-6050 and OLED (400 kHz, so screen updates don't delay the IMU)"
  sudo apt-get install -y i2c-tools
  sudo raspi-config nonint do_i2c 0 || echo "Could not enable I2C automatically: use sudo raspi-config"
  BOOT_CONFIG=/boot/firmware/config.txt; [ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
  grep -q '^dtparam=i2c_arm_baudrate=' "$BOOT_CONFIG" || echo 'dtparam=i2c_arm_baudrate=400000' | sudo tee -a "$BOOT_CONFIG" >/dev/null
  sudo usermod -aG i2c "$(id -un)" || true
  if [ "$ASSISTANT" = 1 ]; then
    step "Assistant system packages: espeak-ng (voice), alsa-utils (speaker/mic), bluez (Bluetooth), openssl (HTTPS)"
    sudo apt-get install -y espeak-ng alsa-utils bluez openssl
    sudo usermod -aG bluetooth,audio "$(id -un)" || true   # BLE scanning + sound without root (takes effect at next login)
  fi
fi

PYTHON="$(command -v python3 || command -v python)"
if [ ! -d .venv ]; then
  step "Creating .venv (with system site packages, so picamera2 + gpiozero are visible)"
  "$PYTHON" -m venv --system-site-packages .venv
fi
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=.venv/Scripts/python.exe; fi

step "Python packages"
"$PY" -m pip install --upgrade pip -q
"$PY" -m pip install -r requirements.txt
if [ "$VISION" = 1 ]; then
  step "Vision packages: Ultralytics (YOLO26), NCNN, lap (ByteTrack) - large download on first install"
  "$PY" -m pip install -r requirements-vision.txt
fi

if [ "$ASSISTANT" = 1 ]; then
  step "Assistant packages: anthropic (AI brain), bleak (Bluetooth LE)"
  "$PY" -m pip install -r requirements-assistant.txt
  [ -f secrets.env ] || echo "note: no secrets.env yet - copy secrets.env.example to secrets.env and add your API keys"
fi

step "Companion packages: IMU, PID control, OLED eyes, figures, hand gestures"
"$PY" -m pip install -r requirements-companion.txt
"$PY" -m pip install --no-deps mediapipe || echo "MediaPipe did not install: the robot works, gesture control stays off"

if [ "$MODEL" = 1 ]; then
  step "Downloading YOLO26n and exporting it to NCNN (imgsz 320)"
  "$PY" -m deskbot model export || echo "Model export failed - the app will fall back to PyTorch weights. Retry: scripts/export-model.sh"
fi

step "System check"
"$PY" -m deskbot doctor || true

cat <<'EOF'

Done. Next (reboot once if I2C was just enabled):
  python main.py              menu of everything
  python main.py calibrate    calibrate the robot, sensors and IMU
  python main.py start --lan  start the whole robot
  scripts/assistant.sh       start the robot + voice assistant + phone remote (http://<pi>:8000/remote)
  scripts/install-service.sh  ...start it automatically on boot
  scripts/hotspot.sh on       make the Pi its own Wi-Fi hotspot
  scripts/start.sh            start the robot (dashboard on http://localhost:8000)
  scripts/start.sh --lan      ...reachable from your phone/laptop on the same Wi-Fi
  scripts/sim.sh              simulation on any computer
  scripts/sensors.sh          test sensors + camera + detection
  scripts/deskbot.sh          interactive menu for all of the above
EOF
