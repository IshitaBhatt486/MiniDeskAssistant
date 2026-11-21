"""
Turning crashes into explanations (21 Nov 2026). Standard library only, so it still works when the packages it
explains are the ones that are missing.

    use_project_venv()   main.py: restart with run_prototype/.venv's Python when started with another one
                         (`python3 main.py` on the Pi is the system Python, which has none of the packages)
    explain(exc)         (what went wrong, how to fix it) for an exception; names the pip package for a missing module
    report_crash(exc)    prints the explanation, saves the full traceback to outputs/errors/, and for missing
                         packages offers to install them right away
    guarded(fn, ...)     runs one menu action: a crash is explained and you go back to the menu instead of out

Docs: docs/error-recovery.md
"""

from __future__ import annotations

import errno
import importlib
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent           # run_prototype/
VENV = ROOT / ".venv"
ERRORS_DIR = ROOT / "outputs" / "errors"
NO_SWITCH = "DESKBOT_NO_VENV_SWITCH"                    # set to 1 to keep the Python you started with

# import name -> (what to install, where it comes from). "apt": a Raspberry Pi OS package, not pip.
PACKAGES = {
    "numpy": ("numpy", "requirements.txt"), "rich": ("rich", "requirements.txt"),
    "questionary": ("questionary", "requirements.txt"),
    "cv2": ("opencv-python-headless", "requirements-vision.txt"), "ncnn": ("ncnn", "requirements-vision.txt"),
    "bleak": ("bleak", "requirements-assistant.txt"), "pywhispercpp": ("pywhispercpp", "requirements-assistant.txt"),
    "vosk": ("vosk", "requirements-assistant.txt"),
    "simple_pid": ("simple-pid", "requirements-companion.txt"), "ahrs": ("ahrs", "requirements-companion.txt"),
    "matplotlib": ("matplotlib", "requirements-companion.txt"), "PIL": ("pillow", "requirements-companion.txt"),
    "pytweening": ("pytweening", "requirements-companion.txt"), "luma": ("luma.oled", "requirements-companion.txt"),
    "smbus2": ("smbus2", "requirements-companion.txt"),
    "adafruit_mpu6050": ("adafruit-circuitpython-mpu6050", "requirements-companion.txt"),
    "board": ("adafruit-blinka", "requirements-companion.txt"), "busio": ("adafruit-blinka", "requirements-companion.txt"),
    "absl": ("absl-py", "requirements-companion.txt"), "flatbuffers": ("flatbuffers", "requirements-companion.txt"),
    "mediapipe": ("mediapipe", "setup.sh"),
    "gpiozero": ("python3-gpiozero", "apt"), "picamera2": ("python3-picamera2", "apt"), "libcamera": ("python3-picamera2", "apt"),
    "lgpio": ("python3-lgpio", "apt"),
}


# ---------------- which Python ----------------

def venv_python():
    for rel in ("bin/python", "Scripts/python.exe"):
        if (VENV / rel).exists():
            return VENV / rel
    return None


def in_project_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def use_project_venv(argv=None):
    """Re-run this command with .venv's Python if it exists and isn't the one running. Never loops."""
    py = venv_python()
    if os.environ.get(NO_SWITCH) or py is None or in_project_venv():
        return
    argv = list(sys.argv if argv is None else argv)
    argv[0] = os.path.abspath(argv[0])
    os.environ[NO_SWITCH] = "1"
    print(f"(switching to the project's Python, {py.relative_to(ROOT)}, where setup.sh installed the packages)",
          file=sys.stderr)
    if os.name == "posix":
        os.execv(str(py), [str(py), *argv])                 # replaces this process: Ctrl+C, exit code etc. unchanged
    sys.exit(subprocess.call([str(py), *argv]))


def _python_cmd():
    """How to name the Python that is running, for fix instructions."""
    if in_project_venv():
        return ".venv/bin/python" if os.name == "posix" else r".venv\Scripts\python"
    return Path(sys.executable).name


# ---------------- explaining ----------------

def missing_module(exc):
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        return exc.name.split(".")[0]
    return None


def explain(exc):
    """(what went wrong, how to fix it) in plain words."""
    mod = missing_module(exc)
    if mod:
        pip, source = PACKAGES.get(mod, (mod, None))
        what = f"the Python package '{pip}' is not installed (import of '{exc.name}' failed)"
        if source == "apt":
            return what + "; it comes from Raspberry Pi OS, not pip", f"sudo apt install {pip}  (or bash scripts/setup.sh)"
        if source == "setup.sh":
            return what + " (optional: gestures)", f"{_python_cmd()} -m pip install --no-deps {pip}  (or bash scripts/setup.sh)"
        if venv_python() and not in_project_venv():
            return (what + f" for {sys.executable}. The packages are in .venv",
                    ".venv/bin/python main.py  (main.py switches to it unless DESKBOT_NO_VENV_SWITCH is set)")
        if venv_python() is None and sys.platform.startswith("linux"):
            return what + "; there is no .venv yet", "bash scripts/setup.sh  (creates .venv and installs everything)"
        req = f" -r {source}" if source else f" {pip}"
        return what, f"{_python_cmd()} -m pip install{req}"
    if isinstance(exc, ImportError):
        return (f"a package is installed but broken: {exc}",
                f"{_python_cmd()} -m pip install --force-reinstall <that package>  (or bash scripts/setup.sh)")
    if isinstance(exc, PermissionError):
        return (f"permission denied: {exc.filename or exc}",
                "your user needs the gpio/i2c/video/audio groups (bash scripts/setup.sh adds them; log out and in "
                "again), or another program is holding it: sudo systemctl stop deskbot")
    if isinstance(exc, OSError):
        code = exc.errno
        if code == errno.EBUSY or "busy" in str(exc).lower():
            return f"a device is busy: {exc}", "another program uses it; the service? sudo systemctl stop deskbot"
        if code in (errno.EADDRINUSE,):
            return f"the network port is in use: {exc}", "the robot is probably already running: sudo systemctl stop deskbot"
        if code in (errno.EREMOTEIO if hasattr(errno, "EREMOTEIO") else 121, errno.ENODEV, errno.ENXIO, errno.EIO):
            return (f"a sensor/screen did not answer on its bus: {exc}",
                    "check its wiring and power; I2C devices: i2cdetect -y 1; I2C enabled? sudo raspi-config")
        if isinstance(exc, FileNotFoundError):
            return f"file or device not found: {exc.filename or exc}", "bash scripts/setup.sh, or check the path"
        if code == errno.ENOSPC:
            return "the SD card is full", "df -h; delete old outputs/ folders or the pip cache (pip cache purge)"
    msg = str(exc).strip() or "(no message)"
    if "GPIO" in msg and ("busy" in msg.lower() or "in use" in msg.lower()):
        return f"the GPIO pins are in use: {msg}", "stop the service first: sudo systemctl stop deskbot"
    return f"{type(exc).__name__}: {msg[:300]}", "the full traceback is saved (see below); python main.py health checks everything"


def save_traceback(exc):
    try:
        ERRORS_DIR.mkdir(parents=True, exist_ok=True)
        path = ERRORS_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        path.write_text(f"python: {sys.executable} {sys.version.split()[0]}\nargv: {sys.argv}\n\n{text}", encoding="utf-8")
        return path
    except OSError:
        return None


# ---------------- recovering ----------------

def missing_requirements():
    """Unsatisfied lines of every requirements*.txt, via scripts/missing_packages.py."""
    files = sorted(str(p) for p in ROOT.glob("requirements*.txt"))
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "missing_packages.py"), *files],
                       capture_output=True, text=True, timeout=60)
    return [line for line in p.stdout.splitlines() if line.strip()]


def can_install_here():
    """pip into the running Python makes sense: the project's .venv (or any venv when there is no .venv)."""
    if venv_python() and not in_project_venv():
        return False                               # wrong Python: installing here would not help the real one
    if sys.prefix == sys.base_prefix and sys.platform.startswith("linux"):
        return False                               # system Python on the Pi: pip refuses (externally managed)
    return True


def install_hint(missing):
    """One line: every missing requirement and the one command that installs them all."""
    if venv_python() and not in_project_venv():
        cmd = ".venv/bin/python main.py  (you are not using the project's Python)"
    elif venv_python() is None and sys.platform.startswith("linux"):
        cmd = "bash scripts/setup.sh"
    else:
        cmd = f"{_python_cmd()} -m pip install " + " ".join(f'"{m}"' for m in missing)
    return (f"{len(missing)} package(s) missing: {', '.join(missing)}. Install them all: {cmd}  "
            "(or from the laptop: bash tools/deploy.sh <user>@<pi>)")


def offer_install(exc):
    """For a missing pip package: offer to install every missing requirement now. True if it worked."""
    mod = missing_module(exc)
    source = PACKAGES.get(mod, (mod, None))[1] if mod else None
    if not mod or source in ("apt", "setup.sh"):
        return False
    try:
        missing = missing_requirements()
    except (OSError, subprocess.SubprocessError):
        missing = []
    return offer_install_list(missing or [PACKAGES.get(mod, (mod, None))[0]])


def offer_install_list(missing):
    if not missing or not (sys.stdin.isatty() and sys.stdout.isatty()) or not can_install_here():
        return False
    try:
        answer = input(f"\nInstall the {len(missing)} missing package(s) now ({', '.join(missing)})? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if answer not in ("", "y", "yes"):
        return False
    env = dict(os.environ)
    if sys.platform.startswith("linux") and "TMPDIR" not in env:   # /tmp on the Pi is a small RAM disk
        env["TMPDIR"] = str(Path.home() / ".cache" / "pip-tmp")
        Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    code = subprocess.call([sys.executable, "-m", "pip", "install", *missing], env=env)
    importlib.invalidate_caches()                  # so the next import finds the new packages without a restart
    if code == 0:
        print("Installed. Try it again.")
        return True
    print(f"pip failed (exit code {code}). Try: bash scripts/setup.sh")
    return False


def report_crash(exc, where=""):
    """Explain an exception in plain words, save its traceback, offer the fix. Returns True if it was fixed."""
    what, fix = explain(exc)
    path = save_traceback(exc)
    print(f"\n✗ {where + ' stopped: ' if where else ''}{what}", file=sys.stderr)
    print(f"  How to fix: {fix}", file=sys.stderr)
    if path:
        print(f"  Full details: {path}", file=sys.stderr)
    if os.environ.get("DESKBOT_DEBUG"):
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    return offer_install(exc)


def guarded(fn, *args, where="", after_crash=None, **kwargs):
    """Run one action; a crash is explained instead of ending the program. Returns fn's result, or None.
    after_crash (e.g. "press Enter") runs after the explanation, so it stays on screen."""
    try:
        return fn(*args, **kwargs)
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        report_crash(exc, where)
        if after_crash:
            after_crash()
    return None
