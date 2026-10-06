"""
System check: is everything the app needs installed and working? Each failed item says how to fix it.

    python -m deskbot doctor
"""

from __future__ import annotations

import importlib
import platform
import shutil
import sys
from pathlib import Path

from .. import MODELS_DIR, ROOT, ui
from ..config import VisionConfig


def _pi_model():
    p = Path("/proc/device-tree/model")
    return p.read_text(errors="ignore").strip("\x00\n ") if p.exists() else None


def _import(name):
    try:
        mod = importlib.import_module(name)
        return True, getattr(mod, "__version__", "ok")
    except Exception as exc:  # ImportError, or a blocked DLL (OSError)
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"


def run():
    ui.header("System check", f"deskbot in {ROOT}")
    rows = []
    ok_all = True

    def add(item, good, detail, fix=""):
        nonlocal ok_all
        mark = "[green]✓[/green]" if good is True else "[yellow]![/yellow]" if good is None else "[red]✗[/red]"
        if good is False:
            ok_all = False
        rows.append((mark, item, detail, "" if good is True else fix))

    v = sys.version_info
    add("Python", v >= (3, 9), f"{platform.python_version()} ({sys.executable})", "Python 3.9+ needed")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    add("Virtual env", True if in_venv else None, ".venv active" if in_venv else "system Python",
        "run through scripts/*.sh (they use .venv) or: source .venv/bin/activate")
    pi = _pi_model()
    add("Board", True if pi else None, pi or f"{platform.system()} {platform.machine()} (not a Pi: use --sim)",
        "fine for simulation; the robot itself needs the Pi")
    if pi and platform.machine() not in ("aarch64", "arm64"):
        add("64-bit OS", False, platform.machine(), "Ultralytics/PyTorch need 64-bit Raspberry Pi OS (Bookworm)")

    for mod, fix in [
        ("numpy", "pip install numpy"),
        ("cv2", "pip install opencv-python-headless (or sudo apt install python3-opencv)"),
        ("ultralytics", "pip install -r requirements-vision.txt"),
        ("ncnn", "pip install ncnn"),
        ("rich", "pip install rich"),
        ("questionary", "pip install questionary"),
    ]:
        good, detail = _import(mod)
        add(mod, good, detail, fix)

    good, detail = _import("lap")
    if good:
        add("lap (ByteTrack matching)", True, detail)
    else:
        sp, _ = _import("scipy")
        add("lap (ByteTrack matching)", None if sp else False,
            f"{detail} -> using the scipy fallback" if sp else detail,
            "pip install lap (or scipy for the fallback). 'blocked' = Windows Smart App Control")

    good, detail = _import("gpiozero")
    add("gpiozero", good if pi else (True if good else None), detail, "sudo apt install python3-gpiozero")

    good, detail = _import("picamera2")
    if good:
        try:
            from picamera2 import Picamera2
            cams = Picamera2.global_camera_info()
            add("Pi camera", bool(cams), ", ".join(c.get("Model", "?") for c in cams) or "none detected",
                "reseat the ribbon cable; rpicam-hello --list-cameras")
        except Exception as exc:
            add("Pi camera", False, str(exc)[:80], "rpicam-hello --list-cameras")
    else:
        add("picamera2", False if pi else None, detail,
            "sudo apt install python3-picamera2; the venv must be created with --system-site-packages")

    try:
        import robot_config
        robot_config.validate()
        add("robot_config.py", True, f"{len(robot_config.all_pins())} pins, no conflicts")
    except Exception as exc:
        add("robot_config.py", False, str(exc), "fix the pin table in robot_config.py")

    vcfg = VisionConfig()
    from ..vision.model import find_model
    m = find_model(vcfg)
    pt = MODELS_DIR / f"{vcfg.model_name}.pt"
    if m:
        add("YOLO26n NCNN model", True, f"{m.relative_to(ROOT)} (imgsz {vcfg.imgsz})")
    else:
        add("YOLO26n NCNN model", None if pt.exists() else False,
            f"not exported{' (PyTorch .pt present: slower fallback)' if pt.exists() else ''}",
            "python -m deskbot model export   (or scripts/export-model.sh)")

    # multi-process runtime: 4 cores, real-time permission for the motor + sensor processes
    import os
    ncpu = os.cpu_count() or 1
    add("CPU cores", True if ncpu >= 4 else None, f"{ncpu}",
        "the runtime pins motor/sensors/camera/nav to cores 0-3; with fewer cores they share")
    if hasattr(os, "sched_setscheduler"):
        try:
            import resource
            rt = resource.getrlimit(resource.RLIMIT_RTPRIO)[0]
        except Exception:
            rt = 0
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        add("Real-time priority", True if (rt >= 50 or is_root) else None,
            "allowed" + (" (root)" if is_root else f" (rtprio {rt})") if (rt >= 50 or is_root) else f"not allowed (rtprio {rt})",
            "scripts/enable-realtime.sh, then log out and in. Without it motor/sensors run at normal priority")

    free = shutil.disk_usage(ROOT).free / 1e9
    add("Disk space", free > 1.0, f"{free:.1f} GB free", "free some space (the model export needs ~1 GB temporarily)")

    temp = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp.exists():
        c = int(temp.read_text()) / 1000
        add("CPU temperature", c < 75, f"{c:.0f} °C", "add a heatsink/fan: the Pi 4 throttles at 80 °C and inference slows down")

    ui.table("", ["", "Check", "Result", "How to fix"], rows)
    if ok_all:
        ui.ok("Everything needed is in place.")
    else:
        ui.warn("Some checks failed - see 'How to fix'. Simulation (--sim) works without the Pi parts.")
    return ok_all
