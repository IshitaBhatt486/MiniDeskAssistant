#!/usr/bin/env bash
# Download YOLO26n and export it to NCNN (once). Then benchmark it.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
"$PY" -m deskbot model export
exec "$PY" -m deskbot model bench
