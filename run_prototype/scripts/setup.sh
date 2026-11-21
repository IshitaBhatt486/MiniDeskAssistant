#!/usr/bin/env bash
# One-time install. Safe to re-run.
#
#   scripts/setup.sh              everything (system packages on the Pi, venv, Python packages, NCNN model)
#   scripts/setup.sh --no-vision  skip NCNN/OpenCV/the model (mapping from sonar + IR only)
#   scripts/setup.sh --no-model   install packages but don't export the model yet
#   scripts/setup.sh --no-assistant  skip the voice assistant (espeak-ng, Bluetooth, bleak, whisper.cpp, vosk)
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
  # 20 Nov 2026: the right touch pad is on GPIO 14 (UART TX), so the serial console and UART are switched off
  step "Serial console off (GPIO 14 is the right touch pad)"
  sudo raspi-config nonint do_serial_cons 1 || echo "Could not turn the serial console off: sudo raspi-config > Interface > Serial"
  sudo raspi-config nonint do_serial_hw 1 || true
  sudo usermod -aG gpio "$(id -un)" || true
  if [ "$ASSISTANT" = 1 ]; then
    step "Assistant system packages: espeak-ng (voice), alsa-utils (speaker/mic), bluez (Bluetooth), openssl (HTTPS)"
    sudo apt-get install -y espeak-ng alsa-utils bluez openssl
    step "Full robot extras: tesseract-ocr (reading pages without AI)"
    sudo apt-get install -y tesseract-ocr || true
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
# Raspberry Pi OS mounts /tmp as a small RAM disk; big wheels (opencv) overflow it with
# "[Errno 28] No space left on device". Unpack them on the SD card instead.
if [ -z "${TMPDIR:-}" ] && [ "$(uname -s)" = Linux ]; then
  export TMPDIR="$HOME/.cache/pip-tmp"; mkdir -p "$TMPDIR"
fi
"$PY" -m pip install --upgrade pip -q
"$PY" -m pip install -r requirements.txt
# 20 Nov 2026 (runs with or without --no-vision): the robot runs YOLO26n on NCNN directly (deskbot/vision/ncnn_detector.py), so PyTorch, Ultralytics
# and lap are no longer installed here. Remove them (and their CUDA / GUI-OpenCV leftovers) from an older install.
# On the laptop (top-level .venv) nothing is removed: the tools and benchmarks there still use Ultralytics.
# Everything the old install had that the new one doesn't (measured with an aarch64 install of both, 20 Nov 2026).
# Nothing in the new install or in deskbot needs any of these. setuptools stays (pip uses it).
REMOVED_PKGS='torch|torchvision|ultralytics|ultralytics[-_]thop|ultralytics[-_]platform|lap|polars|polars[-_]runtime[-_]32'
REMOVED_PKGS="$REMOVED_PKGS|opencv[-_]python|sympy|mpmath|networkx|psutil|jinja2|markupsafe|httpx|httpcore|nvidia[-_].*|triton"
# 20 Nov 2026, second round: scipy -> numpy, faster-whisper -> whisper.cpp (pywhispercpp), anthropic SDK -> plain HTTPS.
# Again only packages that the new install doesn't contain at all (aarch64 install of both, compared).
REMOVED_PKGS="$REMOVED_PKGS|scipy|anthropic|faster[-_]whisper|ctranslate2|onnxruntime|av|tokenizers|huggingface[-_]hub|hf[-_]xet"
REMOVED_PKGS="$REMOVED_PKGS|pydantic|pydantic[-_]core|annotated[-_]types|typing[-_]inspection|jiter|docstring[-_]parser|anyio|sniffio"
REMOVED_PKGS="$REMOVED_PKGS|h11|httpx2|httpcore2|truststore|filelock|fsspec|pyyaml|click|protobuf|opentelemetry[-_]api"
if [ "$(uname -s)" = Linux ] && [ -d .venv ]; then
  OLD_PKGS="$("$PY" -m pip list --local --format=freeze 2>/dev/null | cut -d= -f1 \
    | grep -iE "^($REMOVED_PKGS)\$" || true)"
  if [ -n "$OLD_PKGS" ]; then
    step "Removing packages the robot no longer needs: $(echo $OLD_PKGS)"
    "$PY" -m pip uninstall -y $OLD_PKGS || echo "Could not remove all of them (not fatal)"
    # pip keeps the downloaded wheels (torch alone ~200 MB compressed) in ~/.cache/pip; they're never needed again
    "$PY" -m pip cache purge >/dev/null 2>&1 || true
  fi
fi
if [ "$VISION" = 1 ]; then
  step "Vision packages: NCNN, OpenCV (headless)"
  "$PY" -m pip install -r requirements-vision.txt
  # opencv-python and opencv-python-headless share the cv2/ folder: removing one breaks the other, so reinstall
  if echo "${OLD_PKGS:-}" | grep -qix opencv-python; then
    "$PY" -m pip install --force-reinstall --no-deps "opencv-python-headless>=4.8"
  fi
fi

if [ "$ASSISTANT" = 1 ]; then
  step "Assistant packages: bleak (Bluetooth LE), whisper.cpp (speech to text), vosk (wake word)"
  "$PY" -m pip install -r requirements-assistant.txt
  [ -f secrets.env ] || echo "note: no secrets.env yet - copy secrets.env.example to secrets.env and add your API keys"
fi

step "Companion packages: IMU, PID control, OLED eyes, figures, hand gestures"
"$PY" -m pip install -r requirements-companion.txt
"$PY" -m pip install --no-deps mediapipe || echo "MediaPipe did not install: the robot works, gesture control stays off"

if [ "$MODEL" = 1 ]; then
  step "YOLO26n NCNN model (exported once in a temporary venv that is deleted afterwards)"
  bash scripts/export-model.sh || echo "Model export failed: object detection stays off until it works. Retry: scripts/export-model.sh"
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
