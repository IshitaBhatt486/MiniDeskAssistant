"""
deskbot - the desk assistant robot application (15 Nov 2026).

    python -m deskbot            interactive menu
    python -m deskbot --help     all sub-commands

Layout:
    deskbot/config.py      every tunable for camera, vision and mapping (pins stay in robot_config.py)
    deskbot/robot.py       builds the robot (real GPIO or simulation) from the proven dashboard/ classes
    deskbot/vision/        camera capture, YOLO26n (NCNN) + ByteTrack, camera geometry
    deskbot/mapping/       decaying geometric grid, semantic object map, sensor fusion + confidence heatmap
    deskbot/web/           dashboard server (extends dashboard/server.py) + extra cards
    deskbot/checks/        interactive sensor tests, system check, model benchmark
    deskbot/cli.py         the interactive CLI

The older entry points (3Nov-latest.py, 13Nov-multisonar.py, dashboard/server*.py, test_*.py) are
unchanged and still work. This package re-uses their robot/safety code instead of copying it.
Docs: docs/deskbot.md, vision.md, fusion.md
"""

import sys
from pathlib import Path

__version__ = "1.0.0"

ROOT = Path(__file__).resolve().parent.parent      # run_prototype/ (robot_config.py lives here)
LEGACY_DASHBOARD = ROOT / "dashboard"              # robot.py, multisonar.py, mapping.py, server.py
MODELS_DIR = ROOT / "models"                       # YOLO weights + NCNN export (git-ignored)

# The dashboard modules import each other as top-level modules ("from robot import ...")
# and import robot_config from the repo root, so both directories go on sys.path once, here.
for _p in (str(ROOT / "hardware_tests"), str(ROOT), str(LEGACY_DASHBOARD)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
