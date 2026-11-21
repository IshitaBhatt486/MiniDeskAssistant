# Errors explained, not dumped (21 Nov 2026)

`run_prototype/deskbot/recovery.py`. Before this, one missing package (`ahrs`, then `pytweening`) ended `python3
main.py` with a traceback, even inside the health check, whose job is to report missing packages.

## What happens now

| Situation | Before | Now |
| --- | --- | --- |
| `python3 main.py` on the Pi (the system Python) | every package "missing" | `main.py` restarts itself with `.venv/bin/python`, where `setup.sh` installed the packages: `(switching to the project's Python, .venv/bin/python …)` |
| A package is missing in the health check | crash | a **FAIL** line per package (what's missing + the exact command), "Start: FAIL" with the reason, robot parts **SKIP**, every other check still runs; at the end one line lists **all** missing packages with one install command, and asks *Install the N missing package(s) now? [Y/n]* |
| A menu action crashes | the program ends | a plain-words explanation + how to fix + where the full traceback is saved, *Press Enter*, back to the menu; a missing package is offered for install, and the action works on the next try without restarting |
| A command crashes (`python main.py imu`) | traceback | the same explanation, exit code 1 |
| Ctrl+C | traceback | `Stopped.`, exit code 130 |

Example:

```
✗ 'face' stopped: the Python package 'pytweening' is not installed (import of 'pytweening' failed)
  How to fix: .venv/bin/python -m pip install -r requirements-companion.txt
  Full details: ~/deskbot/outputs/errors/2026-11-21_17-04-36.txt

Install the 3 missing package(s) now (simple-pid>=2.0, ahrs>=0.4, pytweening>=1.2)? [Y/n]
```

## How it works

- **`use_project_venv()`** is called first by `main.py`. If `run_prototype/.venv` exists and `sys.prefix` isn't
  that folder, it re-runs the same command with `.venv`'s Python. On Linux that's `os.execv`, which replaces the
  process, so Ctrl+C, the exit code and systemd all behave as before. On Windows it's `subprocess.call` +
  `sys.exit`. It sets `DESKBOT_NO_VENV_SWITCH=1` before switching, so it can never loop. Set that variable yourself
  to keep the Python you started with. A `.venv` made with `--system-site-packages` (as `setup.sh` does) still has
  `sys.prefix` = `.venv`, so it's detected correctly.
- **`explain(exc)`** returns *(what went wrong, how to fix it)*:
  - `ModuleNotFoundError`: the import name is mapped to the pip package and its requirements file (`PACKAGES`:
    `simple_pid` → `simple-pid`, `cv2` → `opencv-python-headless`, `PIL` → `pillow`, `adafruit_mpu6050` →
    `adafruit-circuitpython-mpu6050`, …). apt-only modules (`gpiozero`, `picamera2`, `lgpio`) get `sudo apt install`.
    MediaPipe gets `pip install --no-deps` (as in `setup.sh`). Wrong Python → "use .venv". No `.venv` on the Pi →
    `bash scripts/setup.sh`.
  - Other `ImportError`: installed but broken → `--force-reinstall`.
  - `PermissionError`: user groups (gpio/i2c/video/audio, log out and in again) or the service holding the device.
  - `EBUSY` / "GPIO busy": `sudo systemctl stop deskbot`. `EADDRINUSE`: the robot is already running.
  - `EREMOTEIO` (121) / `ENODEV` / `ENXIO` / `EIO`: an I2C device didn't answer → wiring, `i2cdetect -y 1`, raspi-config.
  - `ENOSPC`: SD card full. Anything else: type + message, and a pointer to the saved traceback.
- **`report_crash(exc)`** prints the explanation to stderr and saves the full traceback (with the Python path and
  argv) to `outputs/errors/<time>.txt`. If `DESKBOT_DEBUG` is set, it also prints the traceback. Then it calls
  `offer_install`.
- **`offer_install` / `offer_install_list`** ask only when all of these are true: stdin **and** stdout are terminals
  (Windows reports `NUL` as a terminal, so stdin alone isn't enough), the running Python is the project's venv (or any
  venv when there's no `.venv`), and the package comes from pip. The system Python on Raspberry Pi OS refuses pip
  installs (PEP 668, "externally managed"), so there it shows the command instead. The list of missing packages comes
  from `scripts/missing_packages.py` (the same check `tools/deploy.sh` uses, see [deploy.md](deploy.md)). pip runs
  with `TMPDIR=~/.cache/pip-tmp` because `/tmp` on the Pi is a small RAM disk. Afterwards
  `importlib.invalidate_caches()` runs. Python doesn't cache *failed* imports in `sys.modules`, so the next attempt
  finds the new packages without a restart.
- **`guarded(fn, …, after_crash=ui.pause)`** wraps each menu action (`companion/cli.py`: the action code moved
  unchanged into `_menu_action(c)`) and the opening "run the health check?" question.
- **Health check** (`companion/health_check.py`):
  - `from .app import Rig` moved inside the "Start" `try`, so the whole robot import chain (app → body → eyes →
    pytweening) can fail without crashing.
  - Library FAILs and crashed checks use `explain()`. A crashed check also saves its traceback.
  - New "Python in use" WARN when you aren't in `.venv`.
  - `_missing_summary()` at the end lists every missing package with one install command.

## Testing it

On a machine without the companion packages (this laptop, 21 Nov 2026), `python main.py health --sim --no-motors
--no-unit-tests` finishes: 4 library FAILs plus "Start: FAIL (pytweening)", the summary line, and exit code 1 instead
of a traceback. `python main.py imu --sim` prints the explanation and exits with 1. The venv switch was tested with a
temporary `run_prototype/.venv`, and the opt-out with `DESKBOT_NO_VENV_SWITCH=1`.
