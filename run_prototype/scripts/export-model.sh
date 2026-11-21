#!/usr/bin/env bash
# Make the NCNN model once: models/yolo26n_ncnn_model/ (+ models/sample.jpg). Then benchmark it.
#
#   scripts/export-model.sh            export (skipped if it's already there), then benchmark
#   scripts/export-model.sh --force    export again
#   scripts/export-model.sh --keep     keep the temporary export venv (faster next time; ~1 GB)
#
# The robot runs the model with ncnn + numpy only (deskbot/vision/ncnn_detector.py). Exporting needs PyTorch and
# Ultralytics, so they go into a temporary venv (~/.cache/deskbot-export-venv), which is deleted afterwards.
# The robot's own .venv never gets them. Needs internet and ~1.5 GB of free space for a few minutes.
# Linux / Raspberry Pi / macOS. On Windows Smart App Control blocks the PNNX converter: export on the Pi.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

FORCE=0; KEEP=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --keep) KEEP=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

read -r NAME IMGSZ FOUND < <("$PY" -c "
from deskbot.config import VisionConfig
from deskbot.vision.model import find_model
v = VisionConfig(); print(v.model_name, v.imgsz, 1 if find_model(v) else 0)")

if [ "$FOUND" = 1 ] && [ "$FORCE" = 0 ]; then
  echo "NCNN model already in models/${NAME}_ncnn_model (imgsz $IMGSZ). Use --force to export again."
else
  case "$(uname -s)" in
    Linux|Darwin) ;;
    *) echo "Exporting needs Linux or macOS (Windows blocks the PNNX converter). Run this on the Pi."; exit 1 ;;
  esac
  EXPORT_VENV="${DESKBOT_EXPORT_VENV:-$HOME/.cache/deskbot-export-venv}"
  # Raspberry Pi OS mounts /tmp as a small RAM disk; the torch wheel overflows it. Unpack on the SD card.
  if [ -z "${TMPDIR:-}" ]; then export TMPDIR="$HOME/.cache/pip-tmp"; mkdir -p "$TMPDIR"; fi
  cleanup() {
    if [ "$KEEP" = 0 ]; then rm -rf "$EXPORT_VENV"; fi
    rm -rf "$HOME/.cache/pip-tmp"
  }
  trap cleanup EXIT

  BASE_PY="$(command -v python3 || command -v python)"
  if [ ! -x "$EXPORT_VENV/bin/python" ]; then
    echo "==> Temporary export venv: $EXPORT_VENV"
    "$BASE_PY" -m venv "$EXPORT_VENV"
    "$EXPORT_VENV/bin/python" -m pip install --upgrade pip -q
    echo "==> PyTorch (CPU-only) + Ultralytics, for the export only"
    if [ "$(uname -s)" = Linux ]; then
      "$EXPORT_VENV/bin/python" -m pip install --no-cache-dir -q torch torchvision --index-url https://download.pytorch.org/whl/cpu
    fi
    "$EXPORT_VENV/bin/python" -m pip install --no-cache-dir -q "ultralytics>=8.4.0"
  fi

  echo "==> Downloading $NAME and exporting it to NCNN at imgsz $IMGSZ"
  mkdir -p models
  "$EXPORT_VENV/bin/python" - "$ROOT/models" "$NAME" "$IMGSZ" <<'PYEOF'
import shutil, sys
from pathlib import Path

import ultralytics
from ultralytics import YOLO

models, name, imgsz = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
model = YOLO(str(models / f"{name}.pt"))                     # downloads ~5 MB the first time
target = models / f"{name}_ncnn_model"
shutil.rmtree(target, ignore_errors=True)
try:
    out = Path(model.export(format="ncnn", imgsz=imgsz, verbose=False))
except BaseException:
    shutil.rmtree(target, ignore_errors=True)                # don't leave a half-written export behind
    raise
if out.resolve() != target.resolve():
    shutil.move(str(out), str(target))
(models / ".ncnn_export_failed").unlink(missing_ok=True)
shutil.copyfile(Path(ultralytics.__file__).parent / "assets" / "bus.jpg", models / "sample.jpg")
print(f"Model ready: {target}")
PYEOF
  if [ "$KEEP" = 0 ]; then echo "==> Removing the temporary export venv (PyTorch + Ultralytics)"; fi
fi

echo "==> Benchmark (robot venv: ncnn + numpy only)"
exec "$PY" -m deskbot model bench
