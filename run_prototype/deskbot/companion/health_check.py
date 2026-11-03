"""
The full health check: `python main.py health`, also offered when `python main.py` opens.

Tests software, every sensor, IMU, screen, camera + detector, gestures, voice, microphone, Bluetooth, network and
the unit tests, then prints one verdict and saves report.md + report.json to outputs/health/<time>/.

Each check is PASS, WARN (works, but look at it), FAIL (broken) or SKIP (does not apply here). One failing part
never stops the others. Motors only move with --motors or after you agree; every move uses the normal safety rules.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import MODELS_DIR, ROOT, ui
from .config import OUTPUTS_DIR, load_config
from .imu import G, calibration_file, load_calibration
from .shared import fresh_imu

PI_ONLY = {"smbus2", "adafruit_mpu6050", "luma.oled.device", "gpiozero", "mediapipe.tasks.python.vision"}
LIBRARIES = [("NumPy", "numpy"), ("OpenCV", "cv2"), ("Pillow", "PIL"), ("Matplotlib", "matplotlib"), ("SciPy", "scipy"),
             ("simple-pid", "simple_pid"), ("ahrs", "ahrs"), ("pytweening", "pytweening"), ("luma.core", "luma.core"),
             ("luma.oled", "luma.oled.device"), ("smbus2", "smbus2"), ("Adafruit MPU-6050", "adafruit_mpu6050"),
             ("gpiozero", "gpiozero"), ("MediaPipe", "mediapipe.tasks.python.vision")]
MARK = {"pass": "[green]PASS[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]", "skip": "[dim]SKIP[/dim]"}


def is_pi():
    try:
        return "raspberry pi" in Path("/proc/device-tree/model").read_text(errors="ignore").lower()
    except OSError:
        return False


@dataclass
class Check:
    section: str
    name: str
    status: str
    detail: str
    fix: str = ""


class Report:
    def __init__(self, live=True):
        self.checks = []
        self.live = live
        self.section = ""

    def add(self, name, status, detail="", fix=""):
        self.checks.append(Check(self.section, name, status, str(detail), fix))
        if self.live:
            ui.out(f"  {MARK[status]}  {name}: {detail}")

    def start(self, section):
        self.section = section
        if self.live:
            ui.out(f"\n[bold]{section}[/bold]")

    def count(self, status):
        return sum(c.status == status for c in self.checks)

    @property
    def healthy(self):
        return self.count("fail") == 0

    @property
    def score(self):
        ran = self.count("pass") + self.count("warn") + self.count("fail")
        return round(100 * (self.count("pass") + 0.5 * self.count("warn")) / ran) if ran else 0

    @property
    def verdict(self):
        return "NEEDS ATTENTION" if self.count("fail") else "WORKING, WITH WARNINGS" if self.count("warn") else "HEALTHY"

    def save(self, folder=None):
        folder = folder or OUTPUTS_DIR / "health" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "report.json").write_text(json.dumps({"verdict": self.verdict, "score": self.score,
                                                        "checks": [asdict(c) for c in self.checks]}, indent=2), encoding="utf-8")
        lines = [f"# Robot health: {self.verdict} ({self.score}%)", "", f"Run: {datetime.now():%Y-%m-%d %H:%M}", "",
                 "| Area | Check | Result | Details | How to fix |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {c.section} | {c.name} | {c.status.upper()} | {c.detail} | {c.fix} |".replace("\n", " ") for c in self.checks]
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return folder


# ---------------- software and system ----------------

def check_software(r, sim, cfg):
    r.start("Software")
    r.add("Python", "pass" if sys.version_info >= (3, 9) else "fail", platform.python_version(), "Python 3.9 or newer is needed")
    for label, module in LIBRARIES:
        try:
            importlib.import_module(module)
            r.add(label, "pass", "loaded")
        except Exception as exc:
            text = f"{type(exc).__name__}: {str(exc)[:80]}"
            if module in PI_ONLY and not is_pi():
                r.add(label, "skip", f"only needed on the Pi ({text})")
            else:
                r.add(label, "fail", text, "bash scripts/setup.sh")
    try:
        import robot_config
        robot_config.validate()
        r.add("Pin table", "pass", f"{len(robot_config.all_pins())} pins, no conflicts")
    except Exception as exc:
        r.add("Pin table", "fail", exc, "fix robot_config.py")
    has_ncnn = (MODELS_DIR / f"{cfg.vision.model_name}_ncnn_model").is_dir()
    has_pt = (MODELS_DIR / f"{cfg.vision.model_name}.pt").exists()
    r.add("Vision model", "pass" if has_ncnn else "warn" if has_pt else "fail",
          "NCNN export found" if has_ncnn else "PyTorch weights only (slower)" if has_pt else "missing", "python main.py model export")
    r.add("Gesture model", "pass" if (MODELS_DIR / "gesture_recognizer.task").exists() else "warn",
          "found" if (MODELS_DIR / "gesture_recognizer.task").exists() else "will download on first use")
    cal = load_calibration(sim)
    r.add("Calibration", "pass" if cal.get("drive") else "warn", f"from {cal['date'][:10]}" if cal.get("date") else "never run",
          f"python main.py calibrate{' --sim' if sim else ''}")
    r.add("Calibration file", "pass" if calibration_file(sim).exists() or not cal else "warn", calibration_file(sim).name)


def check_system(r):
    r.start("System")
    free = shutil.disk_usage(ROOT).free / 1e9
    r.add("Disk space", "pass" if free > 2 else "warn" if free > 0.5 else "fail", f"{free:.1f} GB free", "delete old folders in outputs/")
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        probe = OUTPUTS_DIR / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        r.add("Outputs folder", "pass", "writable")
    except OSError as exc:
        r.add("Outputs folder", "fail", exc, "check folder permissions")
    r.add("CPU cores", "pass" if (os.cpu_count() or 1) >= 4 else "warn", os.cpu_count())
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        m = re.search(r"MemAvailable:\s+(\d+)", meminfo.read_text())
        mb = int(m.group(1)) / 1024 if m else 0
        r.add("Free memory", "pass" if mb > 500 else "warn", f"{mb:.0f} MB", "close other programs")
    temp = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp.exists():
        c = int(temp.read_text()) / 1000
        r.add("CPU temperature", "pass" if c < 70 else "warn" if c < 80 else "fail", f"{c:.0f} °C", "add a heatsink or fan")
    if shutil.which("vcgencmd"):
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5).stdout
        bits = int(out.split("=")[-1].strip() or "0", 16)
        r.add("Power", "fail" if bits & 0x5 else "warn" if bits & 0x50000 else "pass",
              "under-voltage or throttling now" if bits & 0x5 else "under-voltage earlier since boot" if bits & 0x50000 else "stable",
              "use a stronger 5 V supply and a short cable")


# ---------------- hardware through the running processes ----------------

def _wait(fn, timeout, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(step)
    return None


def check_processes(r, rig):
    r.start("Robot processes")
    time.sleep(2.2)                  # loop rates are published once a second
    wanted = {"motor": 10, "sensors": 25, "body": 20}
    for role, minimum in wanted.items():
        p = rig.shared.procs[role].read()
        alive = rig.procs[role].is_alive()
        hz = p["loop_hz"]
        if not alive:
            r.add(role, "fail", "process stopped", "see the messages above")
        elif hz != hz:
            r.add(role, "warn", "running, no loop rate yet")
        else:
            r.add(role, "pass" if hz >= minimum else "warn", f"{hz:.0f} loops/s")


def check_sensors(r, rig, sim=False):
    r.start("Distance and edge sensors")
    robot = rig.robot
    if not _wait(lambda: robot.latest_reading().get("t"), 5):
        r.add("Sensor data", "fail", "nothing arrived", "check the sensor wiring and power")
        return False
    samples, floors = {}, {"front_floor": [], "back_floor": []}
    ages = []
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        reading = robot.latest_reading()
        ages.append(time.monotonic() - reading["t"])
        for k, v in (reading.get("distances") or {}).items():
            samples.setdefault(k, []).append(v)
        for k in floors:
            floors[k].append(bool(reading[k]))
        time.sleep(0.02)
    r.add("Data age", "pass" if np.median(ages) < 0.1 else "fail", f"{np.median(ages) * 1000:.0f} ms")
    silent = 0
    for name in ("front", "left", "right", "rear"):
        a = np.array(samples.get(name, []), float)
        near = a[a < 1.95]
        fix = f"check the {name} sonar wiring and its ECHO voltage divider"
        if not a.size:
            r.add(f"{name} sonar", "fail", "no readings", fix)
        elif np.median(a) < 0.03:
            r.add(f"{name} sonar", "fail", "reads almost zero", fix)
        elif not near.size:
            silent += 1
            r.add(f"{name} sonar", "pass" if sim else "warn", "no echo (nothing within 2 m" + ")" if sim else "no echo (nothing within 2 m, or not connected)",
                  f"put your hand in front of it; {fix}")
        elif near.std() > 0.03:
            r.add(f"{name} sonar", "warn", f"{np.median(near) * 100:.0f} cm, noisy (±{near.std() * 100:.1f} cm)", fix)
        else:
            r.add(f"{name} sonar", "pass", f"{np.median(near) * 100:.0f} cm, steady")
    for key, label in (("front_floor", "front edge sensor"), ("back_floor", "rear edge sensor")):
        pct = 100 * np.mean(floors[key])
        r.add(label, "pass" if pct == 100 else "warn" if pct > 0 else "fail", f"saw the desk {pct:.0f} % of the time",
              "put the robot on the desk; check the sensor height and wiring")
    return True


def check_imu(r, rig, sim):
    r.start("MPU-6050")
    if not _wait(lambda: fresh_imu(rig.shared, time.monotonic()), 3):
        r.add("Data", "warn" if not is_pi() and not sim else "fail", "no readings",
              "check VCC, GND, SDA, SCL; run i2cdetect -y 1 and look for 68")
        return
    rows, last, end = [], -1, time.monotonic() + 2.0
    while time.monotonic() < end:
        if rig.shared.imu.version != last:
            last = rig.shared.imu.version
            v = fresh_imu(rig.shared, time.monotonic())
            if v:
                rows.append([v["rax"], v["ray"], v["raz"], v["rgx"], v["rgy"], v["rgz"], v["tilt"]])
        time.sleep(0.004)
    a = np.array(rows)
    rate = len(a) / 2.0
    r.add("Sample rate", "pass" if rate >= 40 else "warn", f"{rate:.0f} per second")
    gravity = float(np.linalg.norm(a[:, :3].mean(axis=0)))
    r.add("Accelerometer", "pass" if abs(gravity - G) < 1.0 else "fail", f"gravity reads {gravity:.2f} m/s²", "check the mounting; run calibration")
    noise = float(a[:, 3:6].std(axis=0).max())
    r.add("Gyroscope", "pass" if noise < 0.05 else "warn", f"noise {noise:.3f} rad/s", "keep the robot still during this test")
    tilt = float(np.degrees(a[:, 6].mean()))
    r.add("Level", "pass" if tilt < 8 else "warn", f"tilted {tilt:.1f}°", "put the robot on a flat desk, or run calibration")


def check_face(r, rig, sim, cfg):
    r.start("OLED eyes")
    if sim:
        r.add("Screen", "skip", "simulation has no screen")
    else:
        try:
            from smbus2 import SMBus
            with SMBus(cfg.companion.oled.port) as bus:
                bus.read_byte(cfg.companion.oled.address)
            r.add("Screen", "pass", f"answers at {cfg.companion.oled.address:#x}")
        except Exception as exc:
            r.add("Screen", "fail", exc, "check the OLED wiring; run i2cdetect -y 1 and look for 3c")
    first = _wait(rig.shared.face_frame.read, 5)
    if first is None:
        r.add("Animation", "fail", "no frames drawn", "run python main.py face")
        return
    time.sleep(1.0)
    second = rig.shared.face_frame.read()
    r.add("Animation", "pass" if second[0] > first[0] else "fail", f"{second[0] - first[0]} frames in the last second")


def check_camera(r, rig, camera, timeout=90):
    from ..runtime.procs import decode_result

    r.start("Camera and object detection")
    if camera == "none":
        r.add("Camera", "skip", "started without a camera")
        return
    status = _wait(lambda: rig.shared.procs["camera"].read()["ready"] in (1, -1) and rig.shared.procs["camera"].read()["ready"], timeout, 0.2)
    if status != 1:
        r.add("Camera", "fail", "did not start" if status is None else "failed to start",
              "check the ribbon cable: rpicam-hello --list-cameras")
        return
    first = _wait(rig.shared.frames.read, 15)
    if first is None:
        r.add("Frames", "fail", "none arrived", "check the camera")
        return
    t0 = time.monotonic()
    time.sleep(2.0)
    last = rig.shared.frames.read()
    fps = (last[0] - first[0]) / (time.monotonic() - t0)
    r.add("Frames", "pass" if fps >= 5 else "warn", f"{fps:.0f} per second")
    gray = last[2].mean(axis=2)
    level = float(gray.mean())
    r.add("Exposure", "pass" if 30 <= level <= 225 else "warn", f"brightness {level:.0f} of 255", "check the lighting and the lens cover")
    if not _wait(lambda: len(rig.shared.detections.rows()) > 0, 30, 0.2):
        r.add("Detector", "fail", "no results", "python main.py model info")
        return
    h = decode_result(rig.shared.detections.rows()[-1])
    labels = sorted({d.label for d in h["detections"]})
    r.add("Detector", "pass", f"{h['infer_ms']:.0f} ms per image, sees: {', '.join(labels) or 'nothing right now'}")


def check_motors(r, rig, sim, cfg):
    from .calibration import Calibration, MotionBlocked

    r.start("Motors")
    reading = rig.robot.latest_reading()
    if not (reading.get("front_floor") and reading.get("back_floor")):
        r.add("Motors", "skip", "both edge sensors must see the desk first")
        return
    cal = Calibration(rig.robot, rig.shared, cfg, sim, folder=Path("unused"), log=lambda m: None)
    for direction, label in (("left", "turn left"), ("right", "turn right"), ("forward", "forward"), ("backward", "backward")):
        try:
            angle = cal._timed(direction, 0.3)
            if direction in ("left", "right") and angle is not None:
                moved = abs(np.degrees(angle))
                correct = (angle > 0) == (direction == "left")
                r.add(label, "pass" if moved > 5 and correct else "warn" if moved > 5 else "fail",
                      f"gyro saw {np.degrees(angle):+.0f}°", "check motor wiring, battery and wheels; swap motor wires if reversed")
            else:
                r.add(label, "pass", "move completed")
        except MotionBlocked as exc:
            r.add(label, "warn", f"stopped by a safety rule: {exc}", "give the robot more room")
    rig.robot.stop(source="auto")


# ---------------- other devices ----------------

def check_gestures(r, sim, cfg):
    r.start("Hand gestures")
    if sim:
        r.add("Recogniser", "skip", "simulation uses simulated gestures")
        return
    from .gestures import MediaPipeRecognizer
    try:
        rec = MediaPipeRecognizer(cfg.companion.gesture, log=lambda m: None)
        name, _ = rec(np.zeros((240, 320, 3), np.uint8), time.monotonic())
        rec.close()
        r.add("Recogniser", "pass", f"model loaded, blank image gave {name}")
    except Exception as exc:
        r.add("Recogniser", "fail", str(exc)[:120], "pip install --no-deps mediapipe")


def check_audio(r, sound):
    from ..assistant.settings import Settings
    from ..assistant.stt import capture_devices, record_robot_mic
    from ..assistant.voice import Player, Speaker, find_tts, read_wav

    r.start("Voice and microphone")
    tts, errors = find_tts()
    if tts is None:
        r.add("Speech engine", "fail", "; ".join(errors)[:120], "sudo apt install espeak-ng")
    else:
        try:
            x, rate = read_wav(tts.synth("Health check."))
            r.add("Speech engine", "pass" if len(x) > rate * 0.1 else "fail", f"{tts.name}, {len(x) / rate:.1f} s of audio")
        except Exception as exc:
            r.add("Speech engine", "fail", str(exc)[:120], "sudo apt install espeak-ng")
    player = Player()
    r.add("Speaker output", "pass" if player.name else "fail", player.name or "no audio player", "sudo apt install alsa-utils")
    if sound and tts is not None and player.name:
        speaker = Speaker(Settings())
        try:
            player.play(speaker.synth("Speaker test."))
            r.add("Speaker sound", "pass", "test phrase played (listen for it)")
        except Exception as exc:
            r.add("Speaker sound", "fail", str(exc)[:120], "check DESKBOT_AUDIO_DEVICE")
        speaker.close()
    if not shutil.which("arecord"):
        r.add("Microphone", "skip", "arecord is not available here")
        return
    if not capture_devices():
        r.add("Microphone", "warn", "no recording device found", "plug in the USB sound card; check arecord -l")
        return
    try:
        x, _ = read_wav(record_robot_mic(1.0))
        level = float(np.sqrt(np.mean(x ** 2)))
        r.add("Microphone", "pass" if level > 0.0005 else "warn", f"level {level:.4f}", "check the capsule wiring (red = tip, black = sleeve)")
    except Exception as exc:
        r.add("Microphone", "fail", str(exc)[:120], "python main.py test-mic")


def check_network(r):
    from ..assistant.settings import has_secret, load_secrets

    r.start("Bluetooth and network")
    try:
        importlib.import_module("bleak")
        if shutil.which("bluetoothctl"):
            out = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True, timeout=5).stdout
            r.add("Bluetooth", "pass" if "Powered: yes" in out else "warn", "powered on" if "Powered: yes" in out else "adapter off or missing", "sudo rfkill unblock bluetooth")
        else:
            r.add("Bluetooth", "skip", "no BlueZ on this computer")
    except Exception as exc:
        r.add("Bluetooth", "warn" if is_pi() else "skip", str(exc)[:100], "pip install -r requirements-assistant.txt")
    load_secrets()
    r.add("AI key", "pass" if has_secret("ANTHROPIC_API_KEY") else "warn", "set" if has_secret("ANTHROPIC_API_KEY") else "not set (offline brain)", "add ANTHROPIC_API_KEY to secrets.env")
    speech = has_secret("GROQ_API_KEY") or has_secret("OPENAI_API_KEY")
    r.add("Speech-to-text key", "pass" if speech else "warn", "set" if speech else "not set", "add GROQ_API_KEY to secrets.env")
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=3).close()
        r.add("Internet", "pass", "reachable")
    except OSError as exc:
        r.add("Internet", "warn", f"not reachable ({exc})", "check Wi-Fi. The robot still works offline")


def check_unit_tests(r):
    r.start("Unit tests")
    if not (ROOT.parent / "tests").is_dir():
        r.add("Test suite", "pass", "skipped: the unit tests are kept outside run_prototype")
        return
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=ROOT.parent,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        r.add("Test suite", "fail", "took longer than 10 minutes")
        return
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", p.stderr)
    summary = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "no output"
    r.add("Test suite", "pass" if p.returncode == 0 else "fail", f"{ran.group(1)} tests in {float(ran.group(2)):.0f} s: {summary}" if ran else summary,
          "python main.py test -v")


def _guarded(r, fn, *args):
    """One broken check must not stop the rest of the report."""
    try:
        return fn(r, *args)
    except Exception as exc:
        r.add("Check crashed", "fail", f"{fn.__name__}: {type(exc).__name__}: {str(exc)[:120]}")
        return None


def run_health(sim=False, camera=None, motors=False, unit_tests=True, sound=False, live=True):
    from .app import Rig

    camera = camera or ("sim" if sim else "pi")
    cfg = load_config()
    r = Report(live)
    ui.header("Robot health check", "simulated robot" if sim else "this robot")
    _guarded(r, check_software, sim, cfg)
    _guarded(r, check_system)
    rig = None
    r.start("Starting the robot")
    try:
        rig = Rig(sim=sim, camera=camera)
    except Exception as exc:
        r.add("Start", "fail", str(exc)[:160], "is the robot already running? sudo systemctl stop deskbot")
    if rig is not None:
        try:
            cfg = rig.cfg
            _guarded(r, check_processes, rig)
            sensors_ok = _guarded(r, check_sensors, rig, sim)
            _guarded(r, check_imu, rig, sim)
            _guarded(r, check_face, rig, sim, cfg)
            _guarded(r, check_camera, rig, camera)
            if motors and sensors_ok:
                _guarded(r, check_motors, rig, sim, cfg)
            elif not motors:
                r.start("Motors")
                r.add("Motors", "skip", "not tested (use --motors, or agree when asked)")
        finally:
            rig.close()
    _guarded(r, check_gestures, sim, cfg)
    _guarded(r, check_audio, sound)
    _guarded(r, check_network)
    if unit_tests:
        _guarded(r, check_unit_tests)
    folder = r.save()
    problems = [(c.section, c.name, c.status.upper(), c.detail, c.fix) for c in r.checks if c.status in ("fail", "warn")]
    if problems:
        ui.table("Needs a look", ["Area", "Check", "Result", "Details", "How to fix"], problems)
    say = ui.ok if r.verdict == "HEALTHY" else ui.warn if r.healthy else ui.fail
    say(f"Health: {r.verdict}, score {r.score}%  ({r.count('pass')} passed, {r.count('warn')} warnings, "
        f"{r.count('fail')} failed, {r.count('skip')} skipped)")
    ui.out(f"Report: {folder / 'report.md'}")
    return r
