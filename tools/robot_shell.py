"""
Interactive robot shell: type exactly what the robot should do.

    python3 tools/robot_shell.py                  # real robot, wheels locked until you type `motors on`
    python3 tools/robot_shell.py --motors         # real robot, wheels allowed (asks once)
    python3 tools/robot_shell.py --sim            # fake robot on a fake desk (laptop)
    python3 tools/robot_shell.py --sim "forward 20; left 90; look; find cup"     # run commands, then exit

Examples at the prompt:
    forward 30cm        back 2s         left 90         right 45deg      spin
    find cup            goto bottle     home            map              showmap
    status   sonar front   ir   sensors 5   camera   snap   detect 10   look   listen 5
    set speed 0.4       set stop 25     repeat 4 forward 10; left 90
    help                help goto       quit

Several commands can go on one line, separated by ';'. Ctrl+C stops the current command (and the motors)
and returns to the prompt; Ctrl+D or `quit` exits.

STANDALONE: no other project file is needed - copy just this file to the Pi. Pins, geometry and calibration
are copied in below (same values as robot_config.py / test_e2e.py): update them after rewiring.
Details: docs/robot-shell.md
"""

from __future__ import annotations

import argparse
import builtins
import importlib
import cmd
import socket
import threading
import zlib
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import difflib
import re
import array
import math
import os
import random
import shutil
import subprocess
import struct
import sys
import time
import wave
from pathlib import Path

# ---------------- PINS (BCM) - copy of robot_config.py ----------------

LEFT_MOTOR = {"forward": 22, "backward": 23, "enable": 13}
RIGHT_MOTOR = {"forward": 27, "backward": 17, "enable": 12}
SONARS = {"front": (24, 25), "left": (4, 18), "right": (21, 9), "rear": (10, 11)}   # (TRIG, ECHO)
IR_FRONT, IR_BACK = 19, 26
PHYSICAL_PIN = {4: 7, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33, 17: 11, 18: 12, 19: 35, 21: 40,
                22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13}

# ---------------- ROBOT GEOMETRY (same values as dashboard/ and deskbot/) ----------------

SONAR_MOUNTS = {"front": (0.06, 0.0, 0.0), "left": (0.0, 0.065, 90.0),     # x fwd, y left (m), facing (deg)
                "right": (0.0, -0.065, -90.0), "rear": (-0.06, 0.0, 180.0)}
IR_OFFSET = 0.07              # m ahead / behind the centre
WHEEL_SPEED_AT_FULL = 0.25    # m/s at 100 % PWM (uncalibrated dead reckoning)
TRACK_WIDTH = 0.12            # m
CAM_HFOV, CAM_VFOV = 62.2, 48.8   # deg, Camera Module v2
CAM_X, CAM_HEIGHT, CAM_PITCH = 0.05, 0.09, 12.0   # m ahead, m above desk, deg tilted down

# ---------------- BEHAVIOUR (same rules as 13Nov-multisonar.py) ----------------

MAX_DISTANCE = 2.0
STOP_DISTANCE = 0.20          # front when forward, rear when backward
SIDE_STOP_DISTANCE = 0.08     # left/right while turning
FLOOR_VALUE = 0               # IR LOW = floor
SPEED = 0.5                   # PWM for forward/back
TURN_SPEED = 0.7              # PWM for turning on the spot (needs more torque than driving straight)
LOOP_DT = 0.02                # s, safety loop (sensors checked 50 times a second)
DRAW_DT = 0.15                # s, screen redraw / map update while moving (drawing is slow on a Pi)
SONAR_CONFIRM_S = 0.10        # a sonar hazard must last this long before the robot stops (filters false echoes)
IR_CONFIRM = 2                # an IR edge must be seen on this many readings in a row
BUSY = threading.RLock()      # held while a command (terminal or dashboard) uses the hardware
STOP_REQ = threading.Event()  # set by the dashboard Stop button / Space key: the running move stops at once
TELE = {"sonars": {}, "ir": {}, "pose": (0.0, 0.0, 0.0), "moving": None, "busy": None, "t": 0.0}
LATEST = {"frame": None, "dets": [], "t": 0.0, "det_t": 0.0}   # newest camera frame + detections (any command)
LOG = deque(maxlen=400)       # (seq, text) of everything printed, for the dashboard log
LOG_SEQ = [0]


class StopRequested(Exception):
    """Raised inside a move when the dashboard Stop button was pressed."""


def in_main_thread():
    return threading.current_thread() is threading.main_thread()


_print = builtins.print
_LOGBUF = threading.local()
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\001\002]")


def _log_text(text):
    buf = getattr(_LOGBUF, "s", "") + text
    *lines, _LOGBUF.s = buf.split("\n")
    for line in lines:
        line = re.sub(r"^robot \(.*?\) > ", "", _ANSI.sub("", line)).rstrip()
        if line.strip() and "▀" not in line:
            LOG_SEQ[0] += 1
            LOG.append((LOG_SEQ[0], line))


def print(*args, sep=" ", end="\n", file=None, flush=False):  # noqa: A001 - also copies output to the dashboard log
    if file is not None:
        return _print(*args, sep=sep, end=end, file=file, flush=flush)
    if threading.current_thread().name != "dashboard-cmd":     # dashboard commands don't scribble over the prompt
        _print(*args, sep=sep, end=end, flush=flush)
    _log_text(sep.join(str(a) for a in args) + end)


CAL = {}                      # calibration: {"forward": {"pwm": .5, "rate": cm/s}, "left": {"pwm": .7, "rate": deg/s}, ...}
MODEL_PATH = None             # remembered YOLO model path
DRIVE_PLAN = [("forward", 1.0), ("left", 0.6), ("right", 0.6), ("backward", 1.0)]
SPIN_STEPS = 8                # map: 8 x 45 deg

# ---------------- MAP ----------------

RES, N = 0.05, 80             # 5 cm cells, 4 m x 4 m, start pose in the centre
L_OCC, L_FREE, L_FLOOR, L_LIM = 0.85, -0.40, -0.60, 4.0
SONAR_USEFUL = 1.2            # m, trust hits up to here
SONAR_CONE = math.radians(7.5)
OBJ_MERGE = 0.15              # m, same label closer than this = same object

# ---------------- OTHER ----------------

CAPTURE = (640, 480)
YOLO_IMGSZ, YOLO_CONF = 320, 0.25
MIC_RATE = 16000
COLOURS = [(255, 90, 90), (80, 200, 255), (255, 210, 0), (120, 255, 120), (255, 120, 255), (255, 160, 60)]
HERE = Path(__file__).resolve().parents[1] / "run_prototype"     # models, settings and results live there
TTY = sys.stdout.isatty()
if os.name == "nt":
    os.system("")             # turns on ANSI colours in the Windows console
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # block characters on any console / pipe
except Exception:
    pass


def swatch(c, text="■"):
    return f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m{text}\x1b[0m"


def bar(frac, width=24):
    n = int(max(0.0, min(1.0, frac)) * width)
    return "█" * n + "░" * (width - n)


# ---------------- TERMINAL OUTPUT ----------------

def render(rgb, reserve=8, max_cols=None):
    """RGB image -> text using '▀' half blocks (2 pixels per character, 24-bit colour)."""
    import numpy as np
    h, w = rgb.shape[:2]
    term = shutil.get_terminal_size((100, 32))
    cols = min(term.columns - 1, max_cols or 10 ** 6)
    rows_avail = max(4, term.lines - reserve)
    rows = max(1, int(cols * h / w / 2))
    if rows > rows_avail:
        rows = rows_avail
        cols = max(1, int(rows * 2 * w / h))
    xs = np.linspace(0, w - 1, cols).astype(int)
    ys = np.linspace(0, h - 1, rows * 2).astype(int)
    small = rgb[ys][:, xs].tolist()
    out = []
    for r in range(rows):
        top, bot = small[2 * r], small[2 * r + 1]
        out.append("".join(f"\x1b[38;2;{t[0]};{t[1]};{t[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m▀" for t, b in zip(top, bot)) + "\x1b[0m")
    return "\n".join(out)


# ---------------- inline (non full-screen) live display ----------------

class Screen:
    """Live view drawn in place under the prompt (cursor moves up and redraws); piped output prints once a second."""

    def __init__(self, title):
        self.title, self.n, self.image, self.lines, self.last = title, 0, None, [], 0.0
        self.tty = TTY and in_main_thread()     # dashboard commands print plain status lines instead
        print(f"\x1b[1m{title}\x1b[0m" + ("   (Ctrl+C = stop)" if self.tty else ""), flush=True)
        if self.tty:
            sys.stdout.write("\x1b[?25l")

    def show(self, lines, image=None):
        self.image, self.lines = image, lines
        if not self.tty:
            if time.monotonic() - self.last >= 1.0:
                self.last = time.monotonic()
                print("  " + " | ".join(l.strip() for l in lines[:3] if l.strip()), flush=True)
            return
        text = ((image + "\n") if image else "") + "\n".join(l + "\x1b[K" for l in lines)
        sys.stdout.write((f"\x1b[{self.n}F" if self.n else "") + "\x1b[J" + text + "\n")
        sys.stdout.flush()
        self.n = text.count("\n") + 1

    def close(self, final_lines=()):
        if self.tty:
            sys.stdout.write("\x1b[0m\x1b[?25h")
        elif self.image and in_main_thread():
            print(self.image)
        for l in final_lines:
            print(l)
        sys.stdout.flush()

# ---------------- HARDWARE: REAL ----------------

class RealHardware:
    sim = False

    def __init__(self):
        self._sonars = self._ir = self._motors = None

    def sonars(self):
        """{name: metres} for all four (MAX_DISTANCE = no echo)."""
        if self._sonars is None:
            from gpiozero import DistanceSensor
            self._sonars = {n: DistanceSensor(echo=e, trigger=t, max_distance=MAX_DISTANCE, queue_len=1)
                            for n, (t, e) in SONARS.items()}
            time.sleep(0.2)
        return {n: s.distance for n, s in self._sonars.items()}

    def ir(self):
        """{'front': 0/1, 'rear': 0/1}, 0 = floor."""
        if self._ir is None:
            from gpiozero import DigitalInputDevice
            self._ir = {"front": DigitalInputDevice(IR_FRONT), "rear": DigitalInputDevice(IR_BACK)}
        return {n: d.value for n, d in self._ir.items()}

    def motors(self, left, right):
        if self._motors is None:
            from gpiozero import Motor
            self._motors = (Motor(**LEFT_MOTOR), Motor(**RIGHT_MOTOR))
        for m, v in zip(self._motors, (left, right)):
            m.forward(min(v, 1)) if v > 0 else m.backward(min(-v, 1)) if v < 0 else m.stop()

    def objects_in_view(self):
        return None   # real robot: objects come from the camera + YOLO

    def close(self):
        if self._motors:
            for m in self._motors:
                m.stop()
                m.close()
        for group in (self._sonars, self._ir):
            for d in (group or {}).values():
                d.close()


# ---------------- HARDWARE: SIMULATED DESK ----------------

class SimHardware:
    """1.2 x 0.8 m desk against a wall (back y=0.8 and left x=0), open edges at the front and right."""
    sim = True
    DESK = (0.0, 0.0, 1.2, 0.8)
    OBJECTS = [("cup", 0.93, 0.47, 0.04), ("bottle", 1.0, 0.17, 0.035), ("book", 0.30, 0.62, 0.07)]

    def __init__(self):
        self.x, self.y, self.th = 0.6, 0.35, 0.0
        self.speed, self.t = (0.0, 0.0), time.monotonic()

    def _step(self):
        now = time.monotonic()
        dt, self.t = now - self.t, now
        vl, vr = (s * WHEEL_SPEED_AT_FULL for s in self.speed)
        v, w = (vl + vr) / 2, (vr - vl) / TRACK_WIDTH
        self.th += w * dt
        self.x += v * math.cos(self.th) * dt
        self.y += v * math.sin(self.th) * dt

    def _world(self, dx, dy):
        c, s = math.cos(self.th), math.sin(self.th)
        return self.x + dx * c - dy * s, self.y + dx * s + dy * c

    def _ray(self, ox, oy, ang):
        for i in range(1, int(MAX_DISTANCE / 0.005)):
            d = i * 0.005
            px, py = ox + d * math.cos(ang), oy + d * math.sin(ang)
            if py >= 0.8 or px <= 0.0 or any(math.hypot(px - x, py - y) < r for _, x, y, r in self.OBJECTS):
                return d + random.gauss(0, 0.003)
        return MAX_DISTANCE

    def sonars(self):
        self._step()
        return {n: self._ray(*self._world(mx, my), self.th + math.radians(a)) for n, (mx, my, a) in SONAR_MOUNTS.items()}

    def ir(self):
        self._step()
        x0, y0, x1, y1 = self.DESK
        out = {}
        for n, off in (("front", IR_OFFSET), ("rear", -IR_OFFSET)):
            px, py = self._world(off, 0)
            out[n] = FLOOR_VALUE if x0 <= px <= x1 and y0 <= py <= y1 else 1
        return out

    def motors(self, left, right):
        self._step()
        self.speed = (left, right)

    def objects_in_view(self):
        """[(label, score, x_fwd, y_left)] robot-frame, what an ideal detector would see."""
        self._step()
        out = []
        c, s = math.cos(self.th), math.sin(self.th)
        for label, x, y, _ in self.OBJECTS:
            dx, dy = x - self.x, y - self.y
            fx, fy = dx * c + dy * s, -dx * s + dy * c
            if 0.08 < math.hypot(fx, fy) < 1.0 and abs(math.atan2(fy, fx)) < math.radians(CAM_HFOV / 2):
                out.append((label, 0.9, fx, fy))
        return out

    def close(self):
        self.speed = (0.0, 0.0)


# ---------------- CAMERA ----------------

class Camera:
    def __init__(self, mode, sim):
        import numpy as np
        self.np, self.close_fn, self.desc = np, (lambda: None), ""
        tries = {"auto": ["sample", "synthetic"] if sim else ["pi", "webcam"],
                 "pi": ["pi"], "webcam": ["webcam"], "sample": ["sample"], "synthetic": ["synthetic"]}[mode]
        errors = []
        for kind in tries:
            try:
                getattr(self, f"_open_{kind}")()
                return
            except Exception as exc:
                errors.append(f"{kind}: {exc}")
        raise RuntimeError("no camera - " + "; ".join(errors))

    def _open_pi(self):
        from picamera2 import Picamera2
        info = Picamera2.global_camera_info()
        if not info:
            raise RuntimeError("no Pi camera detected (rpicam-hello --list-cameras, reseat the ribbon)")
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"size": CAPTURE, "format": "RGB888"}))
        cam.start()
        time.sleep(1.0)
        self.grab = lambda: cam.capture_array("main")[:, :, 2::-1].copy()   # BGR -> RGB
        self.close_fn = lambda: (cam.stop(), cam.close())
        self.desc = f"Pi camera {info[0].get('Model', '?')}"

    def _open_webcam(self):
        import cv2
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        if not cap.isOpened():
            raise RuntimeError("webcam 0 not found")
        for _ in range(3):
            cap.read()

        def grab():
            ok, f = cap.read()
            if not ok:
                raise RuntimeError("webcam read failed")
            return f[:, :, ::-1].copy()
        self.grab, self.close_fn, self.desc = grab, cap.release, "webcam 0"

    def _open_sample(self):
        import cv2
        import ultralytics
        img = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
        if img is None:
            raise RuntimeError("ultralytics sample photo missing")
        img = cv2.resize(img, CAPTURE)[:, :, ::-1].copy()
        np = self.np

        def grab():  # slow pan + noise so it looks like a live feed
            shift = int(20 * math.sin(time.monotonic()))
            noisy = np.roll(img, shift, axis=1).astype(np.int16) + np.random.randint(-4, 5, img.shape)
            return noisy.clip(0, 255).astype(np.uint8)
        self.grab, self.desc = grab, "sample photo (simulated camera)"

    def _open_synthetic(self):
        np = self.np
        y, x = np.mgrid[0:CAPTURE[1], 0:CAPTURE[0]]

        def grab():
            t = int(time.monotonic() * 40)
            return np.stack([(x + t) % 256, y % 256, (x + y) % 256], -1).astype(np.uint8)
        self.grab, self.desc = grab, "synthetic test pattern"

    def close(self):
        self.close_fn()


def save_image(rgb, path):
    """JPEG/PNG via OpenCV if present, else a PPM next to it. Returns the path written."""
    try:
        import cv2
        cv2.imwrite(str(path), rgb[:, :, ::-1])
        return path
    except ImportError:
        path = path.with_suffix(".ppm")
        path.write_bytes(f"P6 {rgb.shape[1]} {rgb.shape[0]} 255\n".encode() + rgb.tobytes())
        return path


# ---------------- VISION ----------------

def find_model(arg):
    """--model, else the remembered path, else models/ next to this file, the current folder, home or the repo."""
    if arg:
        return Path(arg)
    cands = [Path(MODEL_PATH)] if MODEL_PATH else []
    for base in (HERE / "models", Path.cwd() / "models", HERE, Path.cwd(), Path.home() / "models",
                 Path.home() / "desk-assistant-robot" / "models",
                 Path.home() / "robotics-and-computer-vision-projects" / "desk-assistant-robot" / "models"):
        cands += [base / "yolo26n_ncnn_model", base / "yolo26n.pt"]
    for c in cands:
        if (c.is_dir() and any(c.glob("*.param"))) or c.is_file():
            return c
    return None


def download_model():
    """Fetch yolo26n.pt (~5 MB, free, from the Ultralytics GitHub release) into models/ next to this file."""
    from ultralytics import YOLO
    d = HERE / "models"
    d.mkdir(parents=True, exist_ok=True)
    old = os.getcwd()
    os.chdir(d)                       # ultralytics downloads into the current folder
    try:
        model = YOLO("yolo26n.pt")
    finally:
        os.chdir(old)
    target = d / "yolo26n.pt"
    got = Path(getattr(model, "ckpt_path", "") or target)
    if not target.exists() and got.exists():
        shutil.copy(got, target)
    if not target.exists():
        raise RuntimeError("could not download the YOLO model - is the Pi online? Or copy the models/ folder next to this file")
    return target


class Detector:
    """YOLO + a small IoU tracker (keeps an ID on each object from frame to frame)."""

    def __init__(self, path):
        from ultralytics import YOLO
        self.model, self.path = YOLO(str(path), task="detect"), path
        self.tracks, self.next_id = [], 1

    def __call__(self, rgb):
        res = self.model.predict(rgb[:, :, ::-1].copy(), imgsz=YOLO_IMGSZ, conf=YOLO_CONF, verbose=False)[0]
        dets = [(res.names[int(c)], s, b) for c, s, b in zip(res.boxes.cls.tolist(), res.boxes.conf.tolist(), res.boxes.xyxy.tolist())]
        out = self._track(dets)
        LATEST.update(dets=out, det_t=time.time())
        return out

    def _track(self, dets):
        out, used = [], set()
        for label, score, box in sorted(dets, key=lambda d: -d[1]):
            best, best_iou = None, 0.3
            for t in self.tracks:
                if t["label"] == label and id(t) not in used and _iou(t["box"], box) > best_iou:
                    best, best_iou = t, _iou(t["box"], box)
            if best is None:
                best = {"id": self.next_id, "label": label, "miss": 0}
                self.next_id += 1
                self.tracks.append(best)
            best.update(box=box, miss=0)
            used.add(id(best))
            out.append({"id": best["id"], "label": label, "score": score, "box": box})
        for t in self.tracks:
            if id(t) not in used:
                t["miss"] += 1
        self.tracks = [t for t in self.tracks if t["miss"] < 10]
        return out


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def ground_point(u, v, w, h):
    """Pixel -> robot-frame (x forward, y left) point on the desk, or None above the horizon (pinhole model)."""
    fx, fy = (w / 2) / math.tan(math.radians(CAM_HFOV) / 2), (h / 2) / math.tan(math.radians(CAM_VFOV) / 2)
    a, b = (u - w / 2) / fx, (v - h / 2) / fy
    sp, cp = math.sin(math.radians(CAM_PITCH)), math.cos(math.radians(CAM_PITCH))
    dx, dy, dz = cp - b * sp, -a, -sp - b * cp
    if dz >= -1e-3:
        return None
    t = CAM_HEIGHT / -dz
    return CAM_X + dx * t, dy * t


def draw_boxes(rgb, dets):
    img = rgb.copy()
    h, w = img.shape[:2]
    t = max(2, w // 90)
    for d in dets:
        c = COLOURS[d["id"] % len(COLOURS)]
        x1, y1, x2, y2 = (int(v) for v in d["box"])
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        img[y1:y1 + t, x1:x2] = c
        img[max(y1, y2 - t):y2, x1:x2] = c
        img[y1:y2, x1:x1 + t] = c
        img[y1:y2, max(x1, x2 - t):x2] = c
    return img


# ---------------- MAP ----------------

class Odometry:
    def __init__(self):
        self.x = self.y = self.th = 0.0

    def advance(self, left, right, dt):
        vl, vr = left * WHEEL_SPEED_AT_FULL, right * WHEEL_SPEED_AT_FULL
        v, w = (vl + vr) / 2, (vr - vl) / TRACK_WIDTH
        for _ in range(int(dt / 0.01) + 1):
            h = dt / (int(dt / 0.01) + 1)
            self.th = (self.th + w * h) % (2 * math.pi)
            self.x += v * math.cos(self.th) * h
            self.y += v * math.sin(self.th) * h

    def advance_vw(self, v, w, dt):
        """Integrate a known forward speed v (m/s) and turn rate w (rad/s) for dt seconds."""
        n = int(dt / 0.01) + 1
        for _ in range(n):
            self.th = (self.th + w * dt / n) % (2 * math.pi)
            self.x += v * math.cos(self.th) * dt / n
            self.y += v * math.sin(self.th) * dt / n

    def to_map(self, dx, dy):
        c, s = math.cos(self.th), math.sin(self.th)
        return self.x + dx * c - dy * s, self.y + dx * s + dy * c


class Map:
    """Log-odds occupancy grid (sonar beams + IR floor/edge) plus an object layer from the camera."""

    def __init__(self):
        import numpy as np
        self.np = np
        self.L = np.zeros((N, N), np.float32)
        self.edge = np.zeros((N, N), bool)
        self.objects, self.trail = [], []

    def cell(self, x, y):
        c, r = int(math.floor(x / RES)) + N // 2, int(math.floor(y / RES)) + N // 2
        return (r, c) if 0 <= r < N and 0 <= c < N else None

    def beam(self, ox, oy, ang, d):
        hit = d < min(SONAR_USEFUL, MAX_DISTANCE - 0.01)
        rng = d if hit else SONAR_USEFUL
        free, occ = set(), set()
        for a in (ang - SONAR_CONE, ang, ang + SONAR_CONE):
            for i in range(int(max(0.0, rng - RES) / (RES / 2))):
                cl = self.cell(ox + i * RES / 2 * math.cos(a), oy + i * RES / 2 * math.sin(a))
                if cl:
                    free.add(cl)
            if hit:
                cl = self.cell(ox + rng * math.cos(a), oy + rng * math.sin(a))
                if cl:
                    occ.add(cl)
        for cl in free - occ:
            self.L[cl] = max(-L_LIM, self.L[cl] + L_FREE)
        for cl in occ:
            self.L[cl] = min(L_LIM, self.L[cl] + L_OCC)

    def integrate(self, odo, sonars, ir):
        for n, d in sonars.items():
            mx, my, a = SONAR_MOUNTS[n]
            self.beam(*odo.to_map(mx, my), odo.th + math.radians(a), d)
        for n, off in (("front", IR_OFFSET), ("rear", -IR_OFFSET)):
            cl = self.cell(*odo.to_map(off, 0))
            if cl:
                if ir[n] == FLOOR_VALUE:
                    self.L[cl] = max(-L_LIM, self.L[cl] + L_FLOOR)
                else:
                    self.edge[cl] = True
        if not self.trail or math.hypot(self.trail[-1][0] - odo.x, self.trail[-1][1] - odo.y) > 0.01:
            self.trail.append((odo.x, odo.y))

    def add_object(self, label, score, x, y):
        for o in self.objects:
            if o["label"] == label and math.hypot(o["x"] - x, o["y"] - y) < OBJ_MERGE:
                k = o["n"] = o["n"] + 1
                o["x"] += (x - o["x"]) / k
                o["y"] += (y - o["y"]) / k
                o["score"] = max(o["score"], score)
                return
        self.objects.append({"label": label, "score": score, "x": x, "y": y, "n": 1})

    def counts(self):
        return {"occupied": int((self.L > 0.85).sum()), "free": int((self.L < -0.85).sum()),
                "edge": int(self.edge.sum()), "objects": len(self.objects)}

    def image(self, odo, crop=True):
        """RGB, +x right, +y up. Unknown dark, free light, occupied red, edge yellow, trail blue, robot green."""
        np = self.np
        p = 1 / (1 + np.exp(-self.L))
        img = np.empty((N, N, 3), np.uint8)
        img[:] = (40, 42, 54)
        known = np.abs(self.L) > 0.3
        shade = (235 - p * 200).astype(np.uint8)
        img[known] = np.stack([shade, shade, shade], -1)[known]
        img[self.L > 0.85] = (220, 50, 50)
        img[self.edge] = (255, 200, 0)
        for x, y in self.trail:
            cl = self.cell(x, y)
            if cl:
                img[cl] = (90, 140, 255)
        for i, o in enumerate(self.objects):
            cl = self.cell(o["x"], o["y"])
            if cl:
                img[max(0, cl[0] - 1):cl[0] + 1, max(0, cl[1] - 1):cl[1] + 1] = COLOURS[(i + 2) % len(COLOURS)]
        rc = self.cell(odo.x, odo.y)
        if rc:
            img[rc] = (0, 220, 0)
            hc = self.cell(*odo.to_map(0.08, 0))
            if hc:
                img[hc] = (180, 255, 180)
        img = img[::-1]   # row 0 = top = +y
        if crop:
            rows = np.where((img != (40, 42, 54)).any(axis=(1, 2)))[0]
            cols = np.where((img != (40, 42, 54)).any(axis=(0, 2)))[0]
            if len(rows):
                r0, r1 = max(0, rows[0] - 3), min(N, rows[-1] + 4)
                c0, c1 = max(0, cols[0] - 3), min(N, cols[-1] + 4)
                img = img[r0:r1, c0:c1]
        return img

    def legend(self):
        lines = [f"{swatch((220, 50, 50))} obstacle  {swatch((235, 235, 235))} free  {swatch((40, 42, 54))} unknown  "
                 f"{swatch((255, 200, 0))} desk edge  {swatch((90, 140, 255))} path  {swatch((0, 220, 0))} robot  "
                 f"(1 cell = {RES * 100:.0f} cm)"]
        for i, o in enumerate(self.objects):
            lines.append(f"  {swatch(COLOURS[(i + 2) % len(COLOURS)])} {o['label']:<10} {o['x'] * 100:+6.0f} cm x  "
                         f"{o['y'] * 100:+6.0f} cm y   seen {o['n']}x  conf {o['score']:.2f}")
        return lines


# ---------------- SHARED STATE ----------------

class Ctx:
    def __init__(self, args, hw):
        self.args, self.hw, self.out = args, hw, args.out
        self.odo, self.map = Odometry(), None
        self.cam = self.det = None
        self.summary = {}

    def camera(self):
        if self.cam is None:
            self.cam = Camera(self.args.camera, self.hw.sim)
            raw = self.cam.grab

            def grab():                       # every frame any command takes also feeds the dashboard
                f = raw()
                LATEST.update(frame=f, t=time.time())
                return f
            self.cam.grab = grab
        return self.cam

    def detector(self):
        if self.det is None:
            global MODEL_PATH
            path = find_model(self.args.model)
            if not path or not path.exists():
                print("No YOLO model found - downloading yolo26n.pt (about 5 MB, only this once)...", flush=True)
                path = download_model()
                print(f"Saved {path}", flush=True)
            if str(path) != MODEL_PATH and not self.args.model:
                MODEL_PATH = str(path)
                save_settings()       # remembered for next time
            print(f"Loading {path.name} with ultralytics (30 s+ the first time)...", flush=True)
            self.det = Detector(path)
        return self.det

    def get_map(self):
        if self.map is None:
            self.map = Map()
        return self.map

    def can_move(self):
        if self.hw.sim:
            return True
        if not self.args.motors:
            return False
        if not getattr(self, "_confirmed", False):
            if not in_main_thread() and not self.args.yes:
                print("  The wheels must be unlocked in the terminal first (type: motors on).")
                return False
            if not self.args.yes:
                a = input("The WHEELS WILL MOVE. Robot on the desk, >20 cm from edges? [y/N] ").strip().lower()
                if not a.startswith("y"):
                    self.args.motors = False
                    return False
            self._confirmed = True
        return True


def read_all(hw):
    return hw.sonars(), hw.ir()


def fmt_cm(d):
    return "  no echo" if d >= MAX_DISTANCE - 0.005 else f"{d * 100:6.1f} cm"


# ---------------- FEATURES ----------------

def feat_pins(ctx):
    print("\n\x1b[1m== pins ==\x1b[0m")
    rows = [(f"left motor {k}", p) for k, p in LEFT_MOTOR.items()] + [(f"right motor {k}", p) for k, p in RIGHT_MOTOR.items()]
    for n, (t, e) in SONARS.items():
        rows += [(f"{n} sonar trigger", t), (f"{n} sonar echo (via divider)", e)]
    rows += [("front IR", IR_FRONT), ("rear IR", IR_BACK)]
    print(f"  {'Signal':<30}{'GPIO':>5}{'Pin':>5}")
    for label, p in rows:
        print(f"  {label:<30}{p:>5}{PHYSICAL_PIN[p]:>5}")
    dup = len(rows) - len({p for _, p in rows})
    print(f"  {len(rows)} signals, {'no conflicts' if not dup else f'{dup} DUPLICATE pins!'}")
    ctx.summary["pins"] = f"{len(rows)} signals, {dup} duplicates"


def feat_sensors(ctx):
    scr = Screen("sensors: 4 ultrasonic + 2 IR")
    stats = {n: [] for n in SONARS}
    ir_seen = {"front": set(), "rear": set()}
    m = ctx.get_map()
    end = time.monotonic() + ctx.args.seconds
    try:
        while time.monotonic() < end:
            son, ir = read_all(ctx.hw)
            m.integrate(ctx.odo, son, ir)
            lines = []
            for n, d in son.items():
                stats[n].append(d)
                lines.append(f"  {n:<6} {fmt_cm(d)}  {bar(1 - d / MAX_DISTANCE)}")
            for n, v in ir.items():
                ir_seen[n].add(v)
                lines.append(f"  {n} IR  {'floor' if v == FLOOR_VALUE else swatch((255, 200, 0), 'EDGE / no floor')}  (raw {v})")
            lines.append(f"  {end - time.monotonic():4.1f} s left")
            scr.show(lines)
            time.sleep(0.1)
    finally:
        out = []
        for n, v in stats.items():
            echo = [d for d in v if d < MAX_DISTANCE - 0.005]
            out.append(f"  {n:<6} " + (f"min {min(echo) * 100:.0f} / max {max(echo) * 100:.0f} cm, {len(echo)}/{len(v)} echoes" if echo else f"no echo in {len(v)} readings"))
        out += [f"  {n} IR   saw " + ", ".join("floor" if x == FLOOR_VALUE else "edge" for x in sorted(s)) for n, s in ir_seen.items()]
        scr.close(out)
        ctx.summary["sensors"] = [l.strip() for l in out]


def feat_camera(ctx):
    cam = ctx.camera()
    scr = Screen(f"camera: {cam.desc}")
    frames, t0, f = 0, time.monotonic(), None
    try:
        while time.monotonic() - t0 < ctx.args.seconds:
            f = cam.grab()
            frames += 1
            fps = frames / (time.monotonic() - t0)
            scr.show([f"  {f.shape[1]}x{f.shape[0]}  {fps:4.1f} fps   brightness {f.mean():.0f}/255"], render(f, reserve=4))
    finally:
        path = save_image(f, ctx.out / "camera.jpg") if f is not None else None
        line = f"  {frames} frames, {frames / max(time.monotonic() - t0, 1e-6):.1f} fps, saved {path}"
        scr.close([line])
        ctx.summary["camera"] = f"{cam.desc}: {line.strip()}"


def feat_vision(ctx):
    cam, det = ctx.camera(), ctx.detector()
    scr = Screen(f"vision: {det.path.name} + tracking on {cam.desc}")
    seen, times, last, f = {}, [], [], None
    print("  warming up the model...", flush=True)
    det.model.predict(cam.grab()[:, :, ::-1].copy(), imgsz=YOLO_IMGSZ, verbose=False)   # first call is slow, not counted
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < max(ctx.args.seconds, 5):
            f = cam.grab()
            t = time.perf_counter()
            dets = det(f)
            times.append((time.perf_counter() - t) * 1000)
            last = dets
            lines = [f"  {len(dets)} objects   {times[-1]:5.0f} ms/frame ({1000 / times[-1]:4.1f} fps)   imgsz {YOLO_IMGSZ}"]
            for d in dets[:8]:
                seen.setdefault(d["id"], d["label"])
                x1, y1, x2, y2 = d["box"]
                gp = ground_point((x1 + x2) / 2, y2, f.shape[1], f.shape[0])
                where = f"{gp[0] * 100:4.0f} cm ahead, {gp[1] * 100:+4.0f} cm left" if gp and gp[0] < 3 else "above the desk plane"
                lines.append(f"  {swatch(COLOURS[d['id'] % len(COLOURS)])} #{d['id']:<3} {d['label']:<12} {d['score']:.2f}   {where}")
            scr.show(lines, render(draw_boxes(f, dets), reserve=len(lines) + 3))
    finally:
        path = None
        if f is not None:
            img = draw_boxes(f, last)
            try:
                import cv2
                bgr = img[:, :, ::-1].copy()
                for d in last:
                    c = COLOURS[d["id"] % len(COLOURS)][::-1]
                    cv2.putText(bgr, f"#{d['id']} {d['label']} {d['score']:.2f}", (int(d["box"][0]), max(14, int(d["box"][1]) - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2)
                path = ctx.out / "detections.jpg"
                cv2.imwrite(str(path), bgr)
            except ImportError:
                path = save_image(img, ctx.out / "detections.jpg")
        ms = sorted(times)[len(times) // 2] if times else 0
        labels = sorted(set(seen.values()))
        out = [f"  {len(times)} frames, median {ms:.0f} ms ({1000 / ms if ms else 0:.1f} fps)",
               f"  {len(seen)} tracked objects: {', '.join(labels) or 'none'}", f"  saved {path}"]
        scr.close(out)
        ctx.summary["vision"] = [l.strip() for l in out]


def feat_mic(ctx):
    chunk = MIC_RATE // 20
    proc = None
    if ctx.hw.sim:
        def read():
            time.sleep(chunk / MIC_RATE)
            loud = (time.monotonic() % 2) < 0.25           # a "clap" every 2 s
            amp = 9000 if loud else 60
            return array.array("h", (max(-32768, min(32767, int(random.gauss(0, amp)))) for _ in range(chunk)))
        device = "simulated mic"
    else:
        if not shutil.which("arecord"):
            raise RuntimeError("arecord not found (Linux only): sudo apt install -y alsa-utils")
        import re
        listing = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
        m = re.search(r"card (\d+):.*?device (\d+):", listing)
        device = ctx.args.mic or (f"plughw:{m.group(1)},{m.group(2)}" if m else None)
        if not device:
            raise RuntimeError("no capture device in `arecord -l` - plug in the USB sound card")
        proc = subprocess.Popen(["arecord", "-D", device, "-f", "S16_LE", "-c", "1", "-r", str(MIC_RATE), "-t", "raw", "-q"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def read():
            data = proc.stdout.read(chunk * 2)
            if not data:
                raise RuntimeError(proc.stderr.read().decode(errors="replace").strip() or "arecord stopped")
            return array.array("h", data)

    scr = Screen(f"microphone: {device} - talk, clap, tap")
    allsamp, hist, levels = array.array("h"), [], []
    spark = " ▁▂▃▄▅▆▇█"
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < ctx.args.seconds:
            s = read()
            allsamp.extend(s)
            rms = math.sqrt(sum(v * v for v in s) / len(s)) or 1e-9
            db = 20 * math.log10(rms / 32768)
            levels.append(db)
            hist = (hist + [spark[int(max(0, min(1, (db + 60) / 60)) * 8)]])[-70:]
            clip = "  CLIPPING" if max(map(abs, s)) >= 32700 else ""
            scr.show([f"  {db:6.1f} dBFS  {bar((db + 60) / 60, 40)}{clip}", f"  {''.join(hist)}",
                      f"  {ctx.args.seconds - (time.monotonic() - t0):4.1f} s left"])
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        path = ctx.out / "mic.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(MIC_RATE)
            w.writeframes(allsamp.tobytes())
        out = [f"  {len(allsamp) / MIC_RATE:.1f} s recorded, quietest {min(levels, default=0):.0f} dBFS, loudest {max(levels, default=0):.0f} dBFS, saved {path}"]
        if levels and max(levels) - min(levels) < 6:
            out.append("  level hardly changed - mic not connected/powered, or input muted (alsamixer, F4)")
        scr.close(out)
        ctx.summary["mic"] = [l.strip() for l in out]
    if not ctx.hw.sim and shutil.which("aplay"):
        print("  playing it back...", flush=True)
        subprocess.run(["aplay", "-q", str(path)])


def blocked(direction, son, ir):
    """Safety rules of 13Nov-multisonar.py. Returns (kind, reason) with kind 'ir' or 'sonar', or None."""
    if direction == "forward":
        if ir["front"] != FLOOR_VALUE:
            return "ir", "front IR: desk edge"
        if son["front"] < STOP_DISTANCE:
            return "sonar", f"obstacle {son['front'] * 100:.0f} cm ahead"
    elif direction == "backward":
        if ir["rear"] != FLOOR_VALUE:
            return "ir", "rear IR: desk edge"
        if son["rear"] < STOP_DISTANCE:
            return "sonar", f"obstacle {son['rear'] * 100:.0f} cm behind"
    else:
        for side in ("left", "right"):
            if son[side] < SIDE_STOP_DISTANCE:
                return "sonar", f"{side} side only {son[side] * 100:.0f} cm away"
    return None


def rate(direction):
    """How fast the robot really moves now: cm/s (forward/backward) or deg/s (left/right).
    The calibrated value scaled to the current PWM if calibrated, otherwise the uncalibrated wheel model."""
    pwm = SPEED if direction in ("forward", "backward") else TURN_SPEED
    c = CAL.get(direction)
    if c and c.get("rate") and c.get("pwm"):
        return c["rate"] * pwm / c["pwm"]
    if direction in ("forward", "backward"):
        return pwm * WHEEL_SPEED_AT_FULL * 100
    return math.degrees(2 * pwm * WHEEL_SPEED_AT_FULL / TRACK_WIDTH)


def lag(direction):
    """Seconds lost at the start of a move (motors spinning up minus coasting after stop), from calibration."""
    c = CAL.get(direction)
    return float(c.get("lag", 0.0)) if isinstance(c, dict) else 0.0


def move_time(direction, amount):
    """Motor-on time for `amount` cm (forward/backward) or degrees (left/right): amount / rate + start-up lag."""
    if amount <= 0:
        return 0.0
    return max(0.0, amount / rate(direction) + lag(direction))


def velocity(direction):
    """(v m/s, w rad/s) for odometry."""
    r = rate(direction)
    return {"forward": (r / 100, 0.0), "backward": (-r / 100, 0.0),
            "left": (0.0, math.radians(r)), "right": (0.0, -math.radians(r))}[direction]


WHEELS = {"forward": (1, 1), "backward": (-1, -1), "left": (-1, 1), "right": (1, -1)}


def drive(ctx, direction, seconds, scr, note=""):
    """One safe move: polls all sensors every LOOP_DT, stops at once on a hazard; updates odometry + map live."""
    m, hw, odo = ctx.get_map(), ctx.hw, ctx.odo
    pwm = SPEED if direction in ("forward", "backward") else TURN_SPEED
    l, r = (k * pwm for k in WHEELS[direction])
    v, w = velocity(direction)
    lag_s = lag(direction)

    def eff(t):            # seconds of real motion after t seconds of motor-on time (nothing during spin-up)
        return max(0.0, t - max(lag_s, 0.0))
    ctx.last_drive_s = 0.0
    # refuse only if the hazard shows on all of 3 readings (one false echo must not block a move)
    hits, why = 0, None
    for _ in range(3):
        b = blocked(*((direction,) + read_all(hw)))
        if b:
            hits, why = hits + 1, b
        time.sleep(0.03)
    if hits == 3:
        return f"refused: {why[1]}"
    if STOP_REQ.is_set():
        raise StopRequested()
    t0 = last = time.monotonic()
    last_draw = 0.0
    ir_hits, sonar_since = 0, None
    hw.motors(l, r)
    TELE["moving"] = direction
    try:
        while (now := time.monotonic()) - t0 < seconds:
            if STOP_REQ.is_set():
                raise StopRequested()
            odo.advance_vw(v, w, eff(now - t0) - eff(last - t0))
            last = now
            son, ir = read_all(hw)
            TELE.update(sonars=son, ir=ir, pose=(odo.x, odo.y, odo.th), t=time.time())
            why = blocked(direction, son, ir)
            # debounce: an IR edge on IR_CONFIRM readings in a row, a sonar hazard lasting SONAR_CONFIRM_S
            ir_hits = ir_hits + 1 if why and why[0] == "ir" else 0
            if why and why[0] == "sonar":
                sonar_since = sonar_since or now
            else:
                sonar_since = None
            if ir_hits >= IR_CONFIRM or (sonar_since and now - sonar_since >= SONAR_CONFIRM_S):
                return f"STOPPED after {now - t0:.2f} s: {why[1]}"
            if time.monotonic() - t0 >= seconds:   # time is up: stop before spending time on drawing
                break
            if now - last_draw < DRAW_DT:
                time.sleep(max(0.0, min(LOOP_DT, seconds - (time.monotonic() - t0))))
                continue
            last_draw = now
            m.integrate(odo, son, ir)
            lines = [f"  {note}{direction:<8} {now - t0:4.1f}/{seconds:.1f} s   pose x {odo.x * 100:+5.1f} cm  y {odo.y * 100:+5.1f} cm  "
                     f"heading {math.degrees(odo.th):5.0f} deg",
                     "  " + "  ".join(f"{n} {fmt_cm(d).strip()}" for n, d in son.items())
                     + "   IR " + " ".join(f"{n} {'floor' if v == FLOOR_VALUE else 'EDGE'}" for n, v in ir.items())]
            scr.show(lines + m.legend()[:1], render(m.image(odo), reserve=8, max_cols=2 * N))
            time.sleep(max(0.0, min(LOOP_DT, seconds - (time.monotonic() - t0))))   # don't overshoot the end
    finally:
        hw.motors(0, 0)
        end = time.monotonic()
        # the motors ran right up to this moment; a negative lag means the robot coasts on after the stop
        odo.advance_vw(v, w, max(0.0, (end - t0) - lag_s) - eff(last - t0))
        ctx.last_drive_s = end - t0
        TELE.update(moving=None, pose=(odo.x, odo.y, odo.th))
    return f"done ({seconds:.1f} s)"


def detect_objects(ctx):
    """Objects in front now, robot frame: [(label, score, x, y)]."""
    sim = ctx.hw.objects_in_view()
    if sim is not None:
        return sim
    try:
        cam, det = ctx.camera(), ctx.detector()
    except Exception:
        return []
    f = cam.grab()
    out = []
    for d in det(f):
        x1, y1, x2, y2 = d["box"]
        gp = ground_point((x1 + x2) / 2, y2, f.shape[1], f.shape[0])
        if gp and 0.05 < gp[0] < 1.5:
            out.append((d["label"], d["score"], gp[0], gp[1]))
    return out


def feat_map(ctx):
    m = ctx.get_map()
    moving = ctx.can_move()
    scr = Screen("map: occupancy grid (4 sonars + IR) + objects from the camera")
    notes = []
    try:
        steps = SPIN_STEPS if moving else 1
        turn_time = move_time("left", 360 / SPIN_STEPS)
        for k in range(steps):
            if moving and k:
                res = drive(ctx, "left", turn_time, scr, note=f"step {k + 1}/{steps}  ")
                if not res.startswith("done"):
                    notes.append(f"  turn {k}: {res}")
            for _ in range(int(0.5 / LOOP_DT)):       # dwell: several sonar sweeps per heading
                son, ir = read_all(ctx.hw)
                m.integrate(ctx.odo, son, ir)
                time.sleep(LOOP_DT)
            for label, score, x, y in detect_objects(ctx):
                m.add_object(label, score, *ctx.odo.to_map(x, y))
            scr.show([f"  step {k + 1}/{steps}  heading {math.degrees(ctx.odo.th):4.0f} deg   {m.counts()}"] + m.legend(),
                     render(m.image(ctx.odo), reserve=8 + len(m.objects), max_cols=2 * N))
        if not moving:
            notes.append("  robot did not move (no --motors): map from the current spot only")
        scr.show([f"  {m.counts()}"] + m.legend(), render(m.image(ctx.odo), reserve=8 + len(m.objects), max_cols=2 * N))
        time.sleep(min(ctx.args.seconds, 4) if TTY else 0)
    finally:
        ctx.hw.motors(0, 0)
        img = m.image(ctx.odo)
        path = save_image(img.repeat(8, 0).repeat(8, 1), ctx.out / "map.png")
        out = notes + [f"  {m.counts()}", f"  saved {path}"]
        if not TTY:
            scr.image = render(img, reserve=8, max_cols=2 * N)
            scr.lines = m.legend()
        scr.close(out)
        ctx.summary["map"] = {"counts": m.counts(), "objects": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in o.items()} for o in m.objects]}




# ---------------- SHELL ----------------

try:
    import readline   # line editing, up-arrow history and Tab completion (Linux/Pi; not in Windows Python)
    READLINE = True
except ImportError:
    readline = None
    READLINE = False
HISTORY = str(Path.home() / ".robot_shell_history")
SETTINGS_FILE = None      # set in main(): robot_shell_settings.json next to this file (…_sim.json for --sim)
CAL_LINE_S = (0.4, 1.0)   # s driven during line calibration: a short and a long run -> speed + start-up lag
CAL_TURN_S = (0.5, 1.2)   # s turned during turn calibration


def save_settings():
    """Remember speeds, safety distances, calibration and the model path as the defaults for next time."""
    if not SETTINGS_FILE:
        return
    data = {"speed": SPEED, "turn_speed": TURN_SPEED, "stop_cm": round(STOP_DISTANCE * 100, 1),
            "side_cm": round(SIDE_STOP_DISTANCE * 100, 1), "steps": SPIN_STEPS, "calibration": CAL, "model": MODEL_PATH}
    try:
        Path(SETTINGS_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        print(warn(f"  (could not save settings: {exc})"))


def load_settings():
    global SPEED, TURN_SPEED, STOP_DISTANCE, SIDE_STOP_DISTANCE, SPIN_STEPS, CAL, MODEL_PATH
    try:
        d = json.loads(Path(SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    SPEED = float(d.get("speed", SPEED))
    TURN_SPEED = float(d.get("turn_speed", TURN_SPEED))
    STOP_DISTANCE = float(d.get("stop_cm", STOP_DISTANCE * 100)) / 100
    SIDE_STOP_DISTANCE = float(d.get("side_cm", SIDE_STOP_DISTANCE * 100)) / 100
    SPIN_STEPS = int(d.get("steps", SPIN_STEPS))
    CAL = d.get("calibration") or {}
    MODEL_PATH = d.get("model")
    return True


def cal_text():
    if not CAL:
        return warn("not calibrated") + dim(" (type: calibrate)")
    parts = [f"{k} {v['rate']:.0f} {'cm/s' if k in ('forward', 'backward') else 'deg/s'} @ {v['pwm']:g}"
             + (f" (+{v['lag']:.2f}s start)" if v.get("lag") else "")
             for k, v in CAL.items() if isinstance(v, dict)]
    return good("calibrated") + dim(f" {CAL.get('date', '')}: " + ", ".join(parts))

COMMON_LABELS = ["person", "cup", "bottle", "book", "cell phone", "laptop", "mouse", "keyboard", "remote",
                 "scissors", "chair", "clock", "vase", "teddy bear", "any"]
SETTINGS = {  # name: (module attribute, unit shown, scale from typed value to stored value, min, max)
    "speed": ("SPEED", "", 1.0, 0.1, 1.0),
    "turn": ("TURN_SPEED", "", 1.0, 0.1, 1.0),
    "stop": ("STOP_DISTANCE", "cm", 0.01, 0.05, 1.0),
    "side": ("SIDE_STOP_DISTANCE", "cm", 0.01, 0.02, 0.5),
    "steps": ("SPIN_STEPS", "", 1, 1, 36),
}
HELP = """
\x1b[1mYou can type plain English:\x1b[0m  "go forward 30 cm", "turn left 90 degrees", "find the cup", "go to the bottle",
"what do you see", "where am i", "take a picture", "go home", "forward 20 then left 90".
Press \x1b[1mEnter\x1b[0m on an empty line for a numbered menu.   Short forms: f b l r s q ?

\x1b[1mMoving\x1b[0m  (needs `motors on`, --motors or --sim; every move has the sonar + IR safety stops)
  forward [20cm | 0.3m | 2s]     back [...]          a plain number is cm (default 20 cm)
  left [90 | 45deg | 1s]         right [...]         a plain number is degrees (default 90)
  spin [360]                     home                drive back to where the robot started
\x1b[1mTasks\x1b[0m
  find <object>      turn in steps until the camera sees it, then face it   (e.g. find cup, find any)
  goto <object>      find it, then drive up to it (the front sonar stops it at the stop distance)
  map [steps]        spin on the spot and build the obstacle map (default 8 x 45 deg)
\x1b[1mSensing\x1b[0m
  status             every sensor once + pose + settings
  sonar [name]       one reading (front/left/right/rear, default all)      ir    one IR reading
  sensors [s]        live sensor table          camera [s]   live camera image
  snap [file]        one picture, shown + saved  detect [s]   live YOLO boxes + tracking IDs
  look               what the camera sees now, with distance and bearing (adds it to the map)
  listen [s]         mic level meter, then plays the clip back            play [file]
\x1b[1mMap\x1b[0m
  showmap   objects   pose   resetmap
\x1b[1mSettings and scripting\x1b[0m
  set [speed 0.4 | turn 0.7 | stop 25 | side 8 | steps 8]   faster   slower   (saved as defaults)
  calibrate [drive | turn | show | reset]   model [download | export]   motors on | off   pins
  dashboard [local] [port]   web page (open it from your laptop) with live sensors, camera, map, drive pad, command box
  wait <s>      repeat <n> <command>      run <file>      cmd1; cmd2   (or: cmd1 then cmd2)
  help <command>      examples      menu      quit
"""

EXAMPLES = [
    ("go forward 30 cm", "drive 30 cm forward (stops early for obstacles / desk edges)"),
    ("turn left 90 degrees", "turn on the spot"),
    ("back 2 seconds", "drive backward for 2 s"),
    ("what do you see", "list the objects in view with distance and direction"),
    ("find the cup", "turn around until the camera sees a cup, then face it"),
    ("go to the bottle", "find it and drive up to it"),
    ("scan", "spin once and build the obstacle map"),
    ("show the map", "draw the map with the objects on it"),
    ("go home", "drive back to where the robot started"),
    ("forward 20 then left 90 then forward 20", "several steps in one line"),
    ("repeat 4 right 90", "do a command several times"),
    ("slower", "lower the speed (faster = raise it)"),
]

MENU = [  # (text, command); commands without an argument ask for one
    ("What do the sensors read?", "status"), ("What does the camera see?", "look"),
    ("Drive forward 20 cm", "forward 20cm"), ("Drive back 20 cm", "back 20cm"),
    ("Turn left 90 deg", "left 90"), ("Turn right 90 deg", "right 90"),
    ("Find an object...", "find"), ("Go to an object...", "goto"),
    ("Scan and build the map", "map"), ("Show the map", "showmap"),
    ("Go back home", "home"), ("Live camera", "camera"), ("Live object detection", "detect"),
    ("Listen with the microphone", "listen"), ("Settings", "set"), ("Turn the wheels on/off", "motors"),
    ("Calibrate distances and turns", "calibrate"), ("Open the web dashboard", "dashboard"),
]

# ---------------- plain-English input ----------------

ALIASES = {"f": "forward", "fw": "forward", "fwd": "forward", "forwards": "forward", "ahead": "forward",
           "b": "back", "bk": "back", "backward": "back", "backwards": "back", "reverse": "back",
           "l": "left", "r": "right", "s": "stop", "halt": "stop", "freeze": "stop",
           "q": "quit", "bye": "quit", "?": "help", "h": "help", "cam": "camera", "video": "camera",
           "pic": "snap", "photo": "snap", "picture": "snap", "see": "look", "mic": "listen", "record": "listen",
           "scan": "map", "explore": "map", "where": "pose", "sensor": "sensors", "settings": "set", "search": "find",
           "go-to": "goto", "approach": "goto"}
PHRASES = {
    "what do you see": "look", "what can you see": "look", "what is in front of you": "look", "look around you": "look",
    "where am i": "pose", "where are you": "pose", "how far": "sonar", "distances": "sonar",
    "take a picture": "snap", "take a photo": "snap", "turn around": "left 180", "come back": "home", "return": "home",
    "what can you do": "examples", "help me": "help", "commands": "help", "show map": "showmap",
    "speed up": "faster", "slow down": "slower", "clear map": "resetmap", "reset map": "resetmap",
}
VERB_RULES = [  # (regex at the start, replacement)
    (r"^(go|come|return|head|drive)\s+(back\s+)?home\b", "home"),
    (r"^(go|move|drive|head)\s+(forwards?|ahead|straight)\b", "forward"),
    (r"^(go|move|drive)\s+(backwards?|back)\b", "back"),
    (r"^(turn|rotate|go|spin)\s+left\b", "left"),
    (r"^(turn|rotate|go|spin)\s+right\b", "right"),
    (r"^(go|drive|move|head|come)\s+(over\s+)?(to|towards?)\b", "goto"),
    (r"^(look|search)\s+for\b|^(where\s+is|where's|locate|find\s+me)\b", "find"),
    (r"^(take|snap)\s+(a\s+)?(picture|photo|pic)\b", "snap"),
    (r"^(show|draw)\s+(me\s+)?(the\s+)?map\b", "showmap"),
    (r"^(look\s+around|map\s+the\s+(area|room|desk)|scan\s+the\s+(area|room|desk))\b", "map"),
    (r"^(spin|rotate)(\s+around)?\b", "spin"),
    (r"^listen\s+to\b", "listen"),
]
NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "ten": "10", "fifteen": "15", "twenty": "20", "thirty": "30",
                "forty": "40", "fifty": "50", "sixty": "60", "ninety": "90", "hundred": "100", "half": "0.5"}
UNITS = {"cm": "cm", "cms": "cm", "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "centimetres": "cm",
         "mm": "mm", "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
         "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
         "deg": "", "degree": "", "degrees": "", "°": ""}
LEAD_FILLER = {"please", "can", "could", "would", "you", "robot", "now", "just", "ok", "okay", "hey"}
ARG_FILLER = {"the", "a", "an", "by", "for", "please", "to", "around", "me"}
RAW_ARGS = {"run", "snap", "play"}   # keep these arguments exactly as typed (file names)


def normalize(text):
    """'please go forward thirty centimeters' -> 'forward 30cm'. Plain commands pass through unchanged."""
    raw = text.strip()
    if not raw or raw.split()[0].lower() in RAW_ARGS:
        return raw
    t = re.sub(r"[?!,.](?!\d)", " ", raw.lower().replace("°", " ")).strip()
    if t in PHRASES:
        return PHRASES[t]
    words = [NUMBER_WORDS.get(w, w) for w in t.split()]
    merged = []
    for w in words:   # "30 cm" -> "30cm", "90 degrees" -> "90", "half a meter" -> "0.5m"
        if merged and re.fullmatch(r"-?\d+(\.\d+)?", merged[-1]) and w in ("a", "an"):
            continue
        if merged and re.fullmatch(r"-?\d+(\.\d+)?", merged[-1]) and w in UNITS:
            merged[-1] += UNITS[w]
        else:
            merged.append(w)
    while merged and merged[0] in LEAD_FILLER:
        merged.pop(0)
    t = " ".join(merged)
    if t in PHRASES:
        return PHRASES[t]
    for pattern, repl in VERB_RULES:
        if re.match(pattern, t):
            t = re.sub(pattern, repl, t, count=1)
            break
    words = t.split()
    if not words:
        return ""
    words[0] = ALIASES.get(words[0], words[0])
    if words[0] in SETTINGS and len(words) > 1:   # "speed 0.4" -> "set speed 0.4"
        words.insert(0, "set")
    return " ".join([words[0]] + [w for w in words[1:] if w not in ARG_FILLER])


def split_steps(line):
    """'a; b then c and then d' -> ['a', 'b', 'c', 'd']."""
    return [p.strip() for p in re.split(r";|\band then\b|\bthen\b|\band\b", line) if p.strip()]


def colour(code, text):
    return f"\x1b[{code}m{text}\x1b[0m"


def good(t):
    return colour("32", t)


def warn(t):
    return colour("33", t)


def bad(t):
    return colour("31", t)


def dim(t):
    return colour("2", t)


def friendly(exc):
    """An exception -> one plain sentence with what to do about it."""
    text = str(exc)
    if isinstance(exc, ModuleNotFoundError):
        return {
            "gpiozero": "The motors and sensors need gpiozero, which only exists on the Raspberry Pi. "
                        "On a laptop, start with --sim.",
            "ultralytics": "Object detection needs YOLO: pip install ultralytics (Pi: pip install -r requirements-vision.txt).",
            "numpy": "This needs numpy: pip install numpy",
            "cv2": "This needs OpenCV: pip install opencv-python-headless",
            "picamera2": "The Pi camera needs picamera2: sudo apt install -y python3-picamera2",
        }.get(exc.name, f"Missing Python package '{exc.name}': pip install {exc.name}")
    if "busy" in text.lower() or "already in use" in text.lower():
        return "A GPIO pin is busy - is another robot script (or the dashboard) running? Stop it first."
    if isinstance(exc, FileNotFoundError):
        return f"File not found: {exc.filename or text}"
    if isinstance(exc, (ValueError, RuntimeError)):
        return text[:1].upper() + text[1:]
    return f"{type(exc).__name__}: {text}"




# ---------------- argument parsing ----------------

def parse_line(tok, direction="forward"):
    """'30cm' '0.3m' '300mm' '2s' '30' (cm) -> (seconds, text)."""
    if tok is None:
        tok = "20cm"
    t = tok.lower().strip()
    try:
        if t.endswith("cm"):
            m = float(t[:-2]) / 100
        elif t.endswith("mm"):
            m = float(t[:-2]) / 1000
        elif t.endswith("m"):
            m = float(t[:-1])
        elif t.endswith("s"):
            s = float(t[:-1])
            return s, f"{s:g} s (~{max(0.0, s - lag(direction)) * rate(direction):.0f} cm)"
        else:
            m = float(t) / 100
    except ValueError:
        raise ValueError(f"can't read '{tok}': use e.g. 30cm, 0.3m, 2s or 30") from None
    return move_time(direction, abs(m) * 100), f"{abs(m) * 100:g} cm"


def parse_turn(tok, direction="left", default=90.0):
    """'90' '45deg' '1.5s' -> (seconds, text)."""
    t = (tok or f"{default}").lower().strip()
    try:
        if t.endswith("s") and not t.endswith("deg"):
            s = float(t[:-1])
            return s, f"{s:g} s (~{max(0.0, s - lag(direction)) * rate(direction):.0f} deg)"
        deg = float(t[:-3] if t.endswith("deg") else t)
    except ValueError:
        raise ValueError(f"can't read '{tok}': use e.g. 90, 45deg or 1s") from None
    return move_time(direction, abs(deg)), f"{abs(deg):g} deg"


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


# ---------------- the shell ----------------

class RobotShell(cmd.Cmd):
    intro = ""
    doc_header = "Commands (help <command> for details)"

    def __init__(self, args):
        super().__init__()
        self.args = args
        ns = argparse.Namespace(seconds=8.0, camera=args.camera, model=args.model, mic=args.mic,
                                out=args.out, motors=args.motors, yes=args.yes)
        self.hw = SimHardware() if args.sim else RealHardware()
        self.ctx = Ctx(ns, self.hw)
        self.snaps = 0
        self._update_prompt()

    # -- plumbing --

    def _update_prompt(self):
        mode = "sim" if self.hw.sim else ("wheels on" if self.ctx.args.motors else "wheels locked")
        if TTY:
            c = "36" if self.hw.sim or self.ctx.args.motors else "33"
            # \001 \002 tell readline the colour codes take no space (keeps line editing correct)
            self.prompt = f"\001\x1b[1;{c}m\002robot\001\x1b[0;2m\002 ({mode})\001\x1b[0m\002 > " if READLINE else \
                f"\x1b[1;{c}mrobot\x1b[0;2m ({mode})\x1b[0m > "
        else:
            self.prompt = f"robot ({mode}) > "

    def emptyline(self):
        self.do_menu("")

    def _command_names(self):
        return sorted(n[3:] for n in self.get_names() if n.startswith("do_") and n != "do_EOF")

    def default(self, line):
        word = line.split()[0]
        names = self._command_names()
        close = difflib.get_close_matches(word, names + list(ALIASES), n=3, cutoff=0.6)
        close = list(dict.fromkeys(ALIASES.get(c, c) for c in close))
        hint = f"  Did you mean {' or '.join(good(c) for c in close)}?" if close else ""
        print(bad(f"  I don't know '{word}'.") + hint + dim("  (Enter = menu, help = all commands, examples = ideas)"))

    def onecmd(self, line):
        """Runs `a; b then c` one after the other; Ctrl+C or an error stops the rest of the line."""
        if not line.strip():
            return self.emptyline()
        if line == "EOF":                                # end of input (Ctrl+D / end of a piped script)
            return self.do_EOF("")
        if normalize(line) == "stop":                   # works even while the dashboard is driving
            return self.do_stop("")
        if not BUSY.acquire(timeout=3):
            print(warn(f"  Busy: the dashboard is running '{TELE['busy'] or 'something'}'.") + dim("  Wait, or type stop."))
            return False
        try:
            if in_main_thread():
                STOP_REQ.clear()
                TELE["busy"] = line
            return self._run_line(line)
        finally:
            if in_main_thread():
                TELE["busy"] = None
            BUSY.release()

    def _run_line(self, line):
        for part in split_steps(line):
            if part.isdigit():                      # a number = an item from the menu
                k = int(part)
                if not 1 <= k <= len(MENU):
                    print(bad(f"  There is no menu item {k}.") + dim("  Press Enter to see the menu."))
                    return False
                part = MENU[k - 1][1]
                print(dim(f"  -> {part}"))
            cmdline = normalize(part)
            if cmdline != part and part.split()[0].lower() not in self._command_names():
                print(dim(f"  -> {cmdline}"))      # show how plain English was understood
            try:
                if super().onecmd(cmdline):
                    return True
            except KeyboardInterrupt:
                self._halt()
                print("\n\x1b[0m\x1b[?25h" + warn("  Stopped (Ctrl+C). Motors are off."))
                return False
            except StopRequested:
                self._halt()
                print("\x1b[0m\x1b[?25h" + warn("  Stopped (Stop button). Motors are off."))
                return False
            except Exception as exc:
                self._halt()
                print("\x1b[0m\x1b[?25h" + bad("  ✗ " + friendly(exc)))
                return False
            finally:
                self._update_prompt()
        return False

    def _ask(self, question):
        """Ask for a missing argument (only when a person is at the keyboard)."""
        if not (sys.stdin.isatty() and in_main_thread()):
            raise ValueError(question.rstrip(" ?:") + " - it is missing")
        try:
            return input(f"  {question} ").strip()
        except EOFError:
            return ""

    def _halt(self):
        try:
            if self.hw.sim or self.ctx.args.motors:
                self.hw.motors(0, 0)
        except Exception:
            pass

    def _with_seconds(self, arg, fn):
        old = self.ctx.args.seconds
        if arg.strip():
            self.ctx.args.seconds = float(arg.strip().rstrip("s"))   # "5" or "5s"
        try:
            fn(self.ctx)
        finally:
            self.ctx.args.seconds = old

    def _need_motors(self):
        if self.ctx.can_move():
            return True
        print(warn("  The wheels are locked, so the robot won't move.") +
              f" Type {good('motors on')} to unlock them" + dim(" (or start with --motors; --sim on a laptop)."))
        return False

    def _move(self, direction, seconds, what):
        if seconds < 0.02:
            return "done (nothing to do)"
        pwm = f"speed {SPEED:g}" if direction in ("forward", "backward") else f"turn speed {TURN_SPEED:g}"
        cal = "calibrated" if isinstance(CAL.get(direction), dict) else warn("NOT calibrated")
        scr = Screen(f"→ {direction} {what}" + dim(f"   ({seconds:.2f} s at {pwm}, ") + cal + dim(")"))
        res = drive(self.ctx, direction, seconds, scr)
        if res.startswith("done"):
            msg = good("  ✓ done")
        else:
            msg = warn(f"  ⚠ {res}") + dim("  (safety stop - the robot is fine. Nothing there? `sensors` shows "
                                            "which sensor is reading wrong)")
        scr.close([msg, dim(f"  {self._pose_text()}")])
        return res

    def _turn_by(self, rad, what=None):
        """Turn in place by rad (positive = left). Returns the drive result."""
        d = "left" if rad > 0 else "right"
        return self._move(d, move_time(d, abs(math.degrees(rad))), what or f"{abs(math.degrees(rad)):.0f} deg")

    def _pose_text(self):
        o = self.ctx.odo
        return f"pose: x {o.x * 100:+.1f} cm, y {o.y * 100:+.1f} cm, heading {math.degrees(o.th) % 360:.0f} deg (from the start pose)"

    def _look(self, quiet=False):
        """Objects in view now: [(label, score, x_fwd, y_left)]; also added to the map."""
        if not self.hw.sim:
            self.ctx.camera()
            self.ctx.detector()     # raise here (not silently) if the camera/model is missing
        objs = detect_objects(self.ctx)
        m = self.ctx.get_map()
        for label, score, x, y in objs:
            m.add_object(label, score, *self.ctx.odo.to_map(x, y))
        if not quiet:
            if not objs:
                print("  nothing recognised in view")
            for label, score, x, y in sorted(objs, key=lambda o: math.hypot(o[2], o[3])):
                print(f"  {label:<12} {score:.2f}   {math.hypot(x, y) * 100:5.0f} cm away, "
                      f"{math.degrees(math.atan2(y, x)):+4.0f} deg ({'left' if y > 0 else 'right'})   "
                      f"[{x * 100:.0f} cm ahead, {y * 100:+.0f} cm left]")
        return objs

    # -- moving --

    def do_forward(self, arg):
        """forward [20cm | 0.3m | 2s | 30]  - drive forward (plain number = cm). Stops for an obstacle < stop distance or a desk edge."""
        if self._need_motors():
            s, what = parse_line(arg or None)
            self._move("forward", s, what)

    def do_back(self, arg):
        """back [20cm | 2s]  - drive backward. Stops for an obstacle behind or the rear desk edge."""
        if self._need_motors():
            s, what = parse_line(arg or None, "backward")
            self._move("backward", s, what)

    do_backward = do_back

    def do_left(self, arg):
        """left [90 | 45deg | 1s]  - turn left on the spot (plain number = degrees). Stops if a side sonar is < side distance."""
        if self._need_motors():
            s, what = parse_turn(arg or None)
            self._move("left", s, what)

    def do_right(self, arg):
        """right [90 | 45deg | 1s]  - turn right on the spot."""
        if self._need_motors():
            s, what = parse_turn(arg or None, "right")
            self._move("right", s, what)

    def do_spin(self, arg):
        """spin [360]  - turn left by this many degrees (default a full turn)."""
        if self._need_motors():
            s, what = parse_turn(arg or None, "left", default=360)
            self._move("left", s, what)

    # -- calibration --

    def _number(self, question, default=None):
        """Ask for a number; Enter = default. Piped input (no person) takes the default."""
        while True:
            if not (sys.stdin.isatty() and in_main_thread()):
                if default is None:
                    raise ValueError(question.rstrip(" ?:") + " - no answer (run this at the keyboard)")
                print(f"  {question} {default:g}")
                return float(default)
            try:
                ans = input(f"  {question} ").strip().lower().replace("cm", "").replace("deg", "").strip()
            except EOFError:
                ans = ""
                if default is None:
                    raise ValueError("no answer given") from None
            if not ans and default is not None:
                return float(default)
            try:
                return float(ans)
            except ValueError:
                print(warn("  Please type a number") + (dim(f" (Enter = {default:g})") if default is not None else ""))

    def _ready(self, text):
        if not (sys.stdin.isatty() and in_main_thread()):
            return True
        try:
            return not input(f"  {text} [Enter = go, s = skip] ").strip().lower().startswith("s")
        except EOFError:
            return True

    def _sonar_median(self, name, n=7):
        vals = []
        for _ in range(n):
            vals.append(self.hw.sonars()[name])
            time.sleep(0.07)
        return sorted(vals)[n // 2]

    @staticmethod
    def _fit(samples):
        """[(seconds, amount)] -> (rate per s, lag s). Two lengths separate the true speed from the start-up delay:
        amount = rate * (t - lag). One sample: rate = amount / t, lag 0."""
        pts = [(t, d) for t, d in samples if t > 0 and d > 0]
        if not pts:
            return None, 0.0
        if len({round(t, 2) for t, _ in pts}) >= 2:
            n = len(pts)
            mt, md = sum(t for t, _ in pts) / n, sum(d for _, d in pts) / n
            var = sum((t - mt) ** 2 for t, _ in pts)
            a = sum((t - mt) * (d - md) for t, d in pts) / var if var else 0
            if a > 0:
                lag_s = max(-0.3, min(0.6, mt - md / a))
                return a, lag_s
        t, d = max(pts)
        return d / t, 0.0

    def _cal_drive(self, direction, secs):
        """Drive `direction` for secs; returns (motor-on seconds, cm moved) or None if skipped."""
        sonar = "front" if direction == "forward" else "rear"
        before = self._sonar_median(sonar)
        use_sonar = 0.25 < before < 1.6
        if not use_sonar and not self.hw.sim:
            print(dim(f"  Mark where a wheel touches the desk; you'll measure how far it goes {direction}."))
        sim0 = (self.hw.x, self.hw.y) if self.hw.sim else None
        self._move(direction, secs, f"{secs:g} s (calibration)")
        elapsed = self.ctx.last_drive_s
        time.sleep(0.4)
        guess = None
        if self.hw.sim:
            guess = round(math.hypot(self.hw.x - sim0[0], self.hw.y - sim0[1]) * 100, 1)
        elif use_sonar:
            guess = round((before - self._sonar_median(sonar)) * 100, 1)
        q = (f"Moved {guess:g} cm by the {'simulator' if self.hw.sim else sonar + ' sonar'}. Enter = accept, or type what you measured (cm):"
             if guess and guess > 0 else f"How many cm did it move {direction}?")
        return elapsed, self._number(q, guess if guess and guess > 0 else None)

    def _cal_lines(self):
        print(colour("1", "\n  Calibrating driving") +
              f" at speed {SPEED:g}: 4 short drives - forward, back, forward, back ({CAL_LINE_S[0]:g} s then {CAL_LINE_S[1]:g} s),"
              " so it ends near where it started. Give it ~50 cm of clear desk in front AND behind.")
        print(dim("  Distances are measured with the front/rear sonar when something is 25-160 cm away; you can always type what you measured."))
        if not self._ready("Ready?"):
            return
        samples = {"forward": [], "backward": []}
        for secs in CAL_LINE_S:
            for direction in ("forward", "backward"):
                res = self._cal_drive(direction, secs)
                if res:
                    samples[direction].append(res)
        for direction, pts in samples.items():
            r, lg = self._fit(pts)
            if not r:
                print(warn(f"  {direction}: it didn't move, so nothing was saved. Check the battery and wiring, or try a higher speed."))
                continue
            CAL[direction] = {"pwm": SPEED, "rate": round(r, 2), "lag": round(lg, 3)}
            print(good(f"  ✓ {direction}: {r:.1f} cm/s at speed {SPEED:g}, start-up lag {lg:+.2f} s"))
        CAL["date"] = time.strftime("%Y-%m-%d")
        save_settings()                     # saved now, even if the turn part is skipped or stopped

    def _run_turn(self, direction, secs):
        th0 = self.hw.th if self.hw.sim else None
        self._move(direction, secs, f"{secs:g} s (calibration)")
        elapsed = self.ctx.last_drive_s
        guess = round(abs(math.degrees(self.hw.th - th0))) if self.hw.sim else None
        deg = self._number(f"How many degrees did it turn {direction}? (90 = quarter turn, 180 = half, 360 = full circle, "
                           "0 = it didn't really move):", guess)
        return elapsed, deg

    def _cal_turns(self):
        global TURN_SPEED
        print(colour("1", "\n  Calibrating turns") +
              f": 4 turns on the spot - left, right, left, right ({CAL_TURN_S[0]:g} s then {CAL_TURN_S[1]:g} s)."
              " Tip: put a pen or tape along the robot's front edge so you can see the angle.")
        if not self._ready("Ready?"):
            return
        while True:
            samples = {"left": [], "right": []}
            stalled = False
            for secs in CAL_TURN_S:
                for direction in ("left", "right"):
                    t, deg = self._run_turn(direction, secs)
                    if secs == CAL_TURN_S[0] and deg < 15:
                        stalled = True
                        break
                    samples[direction].append((t, deg))
                if stalled:
                    break
            if not stalled:
                break
            if TURN_SPEED >= 1.0:
                print(warn("  Still not turning at full power - check the battery, the wheels and that nothing rubs."))
                return
            TURN_SPEED = min(1.0, round(TURN_SPEED + 0.15, 2))
            print(warn(f"  Barely moved - trying again with more power (turn speed {TURN_SPEED:g})."))
        for direction, pts in samples.items():
            r, lg = self._fit(pts)
            if r:
                CAL[direction] = {"pwm": TURN_SPEED, "rate": round(r, 1), "lag": round(lg, 3)}
                print(good(f"  ✓ turn {direction}: {r:.0f} deg/s at turn speed {TURN_SPEED:g}, start-up lag {lg:+.2f} s"))
        CAL["date"] = time.strftime("%Y-%m-%d")
        save_settings()

    def _cal_sensors(self):
        """Motors off: are all four sonars steady, and do both edge sensors see the desk?"""
        print(colour("1", "\n  Checking the sensors") + dim(" (keep the robot still)"))
        readings = {}
        floor = {"front": 0, "rear": 0}
        rounds = 20
        for _ in range(rounds):
            son, ir = read_all(self.hw)
            for name, d in son.items():
                readings.setdefault(name, []).append(d)
            for name in floor:
                floor[name] += ir[name] == 0
            time.sleep(0.05)
        for name, vals in readings.items():
            vals = sorted(vals)
            near = [v for v in vals if v < MAX_DISTANCE - 0.01]
            spread = (near[-1] - near[0]) * 100 if near else 0
            text = f"  {name:<6} sonar {fmt_cm(vals[len(vals) // 2])}, varies by {spread:.1f} cm"
            print(warn(text + " - noisy, check the wiring") if spread > 5 else good(text))
        for name, seen in floor.items():
            text = f"  {name:<6} edge sensor saw the desk {seen * 100 // rounds} % of the time"
            print(good(text) if seen == rounds else warn(text))

    def do_calibrate(self, arg):
        """calibrate [all | drive | turn | show | reset]  - measure how fast THIS robot really drives and turns (speed and
        start-up lag), so `forward 20cm` and `left 90` come out right. Saved after each part as the default for next time."""
        global SPEED, CAL
        part = (arg.strip().lower() or "all")
        part = {"forward": "drive", "back": "drive", "backward": "drive", "line": "drive", "turns": "turn"}.get(part, part)
        if part == "show":
            print(f"  {cal_text()}")
            print(dim(f"  settings file: {SETTINGS_FILE} ({'found' if SETTINGS_FILE and Path(SETTINGS_FILE).exists() else 'not saved yet'})"))
            return
        if part == "reset":
            CAL = {}
            save_settings()
            print("  calibration cleared (using the uncalibrated wheel model)")
            return
        if part not in ("all", "drive", "turn"):
            raise ValueError("use: calibrate [all | drive | turn | show | reset]")
        if part == "all":
            self._cal_sensors()
        if not self._need_motors():
            return
        print(colour("1", "  Calibration") + " - the robot makes a few short moves; you check how far it went. "
              + dim("Ctrl+C stops it at any time; finished parts stay saved."))
        if part == "all":
            SPEED = max(0.1, min(1.0, self._number(f"Driving speed 0.1-1 (lower = gentler, more accurate). Enter = {SPEED:g}:", SPEED)))
        if part in ("all", "drive"):
            self._cal_lines()
        if part in ("all", "turn"):
            self._cal_turns()
        save_settings()
        print(f"\n  {cal_text()}")
        print(dim(f"  Saved to {SETTINGS_FILE} - used automatically next time. Now `forward 20cm` = "
                  f"{move_time('forward', 20):.2f} s, `left 90` = {move_time('left', 90):.2f} s, `left 45` = {move_time('left', 45):.2f} s."))

    def do_model(self, arg):
        """model [download | export | <path>]  - show the YOLO model; download it; export it to NCNN (2-3x faster on the Pi); or use another file."""
        global MODEL_PATH
        a = arg.strip()
        if not a:
            m = find_model(self.ctx.args.model)
            print(f"  YOLO model: {m}" if m else warn("  No YOLO model yet.") + " `look`/`detect` will download it, or type: model download")
        elif a == "download":
            print("  downloading yolo26n.pt (~5 MB)...")
            MODEL_PATH = str(download_model())
            self.ctx.det = None
            save_settings()
            print(good(f"  ✓ {MODEL_PATH}"))
        elif a == "export":
            from ultralytics import YOLO
            src = find_model(self.ctx.args.model)
            if not src or src.suffix != ".pt":
                src = download_model()
            print(f"  exporting {src.name} to NCNN at imgsz {YOLO_IMGSZ} (takes a minute or two)...")
            out = Path(YOLO(str(src)).export(format="ncnn", imgsz=YOLO_IMGSZ, verbose=False))
            target = src.parent / "yolo26n_ncnn_model"
            if out.resolve() != target.resolve():
                shutil.rmtree(target, ignore_errors=True)
                shutil.move(str(out), str(target))
            MODEL_PATH, self.ctx.det = str(target), None
            save_settings()
            print(good(f"  ✓ {target} (used from now on)"))
        else:
            if not Path(a).exists():
                raise FileNotFoundError(a)
            MODEL_PATH, self.ctx.det = a, None
            save_settings()
            print(good(f"  ✓ using {a}"))

    def do_stop(self, arg):
        """stop  - stop the motors and whatever command is running (also the dashboard's)."""
        STOP_REQ.set()
        self._halt()
        print("  motors stopped")

    def do_home(self, arg):
        """home  - drive back to the start pose (dead reckoning): turn to face it, drive, turn to the start heading."""
        if not self._need_motors():
            return
        o = self.ctx.odo
        dist = math.hypot(o.x, o.y)
        if dist > 0.02:
            self._turn_by(wrap(math.atan2(-o.y, -o.x) - o.th), "to face home")
            res = self._move("forward", move_time("forward", dist * 100), f"{dist * 100:.0f} cm home")
            if not res.startswith("done"):
                print("  could not reach home:", res)
                return
        self._turn_by(wrap(-o.th), "to the start heading")
        print(f"  home. {self._pose_text()}")

    # -- tasks --

    def _find(self, label):
        label = label.strip().lower()
        if not label:
            label = self._ask("Which object? (e.g. cup, bottle, person, or any):").lower()
            if not label:
                print(dim("  ok, never mind"))
                return None
        match = lambda name: label == "any" or label in name.lower()  # noqa: E731
        can_move = self.ctx.can_move()
        steps = SPIN_STEPS if can_move else 1
        for k in range(steps):
            hits = [o for o in self._look(quiet=True) if match(o[0])]
            if hits:
                name, score, x, y = min(hits, key=lambda o: math.hypot(o[2], o[3]))
                bearing = math.atan2(y, x)
                print(f"  found {name} ({score:.2f}): {math.hypot(x, y) * 100:.0f} cm away, {math.degrees(bearing):+.0f} deg")
                if can_move and abs(bearing) > math.radians(3):
                    self._turn_by(bearing, f"{abs(math.degrees(bearing)):.0f} deg to face the {name}")
                return name, math.hypot(x, y)
            if can_move and k < steps - 1:
                print(f"  no {label} in view, turning {360 / steps:.0f} deg ({k + 1}/{steps})")
                self._turn_by(2 * math.pi / steps)
        print(f"  {label} not found" + ("" if can_move else " in view (motors off, so the robot could not look around)"))
        return None

    def do_find(self, arg):
        """find <object>  - look around in steps until the camera sees it, then turn to face it. `find any` = first object seen."""
        self._find(arg)

    def do_goto(self, arg):
        """goto <object>  - find it, face it, then drive up to it. The front sonar stops the robot at the stop distance."""
        if not self._need_motors():
            return
        found = self._find(arg)
        if found:
            name, dist = found
            res = self._move("forward", move_time("forward", max(0.0, dist - 0.10) * 100), f"to the {name}")
            if res.startswith("done") or "obstacle" in res:   # the object itself stopping us = arrived
                print(f"  at the {name}: front sonar {fmt_cm(self.hw.sonars()['front']).strip()}")
            else:
                print(f"  could not reach the {name}")

    def do_map(self, arg):
        """map [steps]  - spin on the spot in steps, sweeping all 4 sonars and the camera into the map (motors off: from here only)."""
        global SPIN_STEPS
        old = SPIN_STEPS
        if arg.strip():
            SPIN_STEPS = max(1, int(arg))
        try:
            self._with_seconds("0", feat_map)
        finally:
            SPIN_STEPS = old

    # -- sensing --

    def do_status(self, arg):
        """status  - all sensors once, pose, motors, settings, map size."""
        son, ir = read_all(self.hw)
        for n, d in son.items():
            print(f"  sonar {n:<6} {fmt_cm(d)}")
        for n, v in ir.items():
            print(f"  IR {n:<9} {'floor' if v == FLOOR_VALUE else 'EDGE / no floor'}")
        print(f"  {self._pose_text()}")
        print(f"  motors {'sim' if self.hw.sim else 'ON' if self.ctx.args.motors else 'off'}; " + self._settings_text())
        if self.ctx.map:
            print(f"  map: {self.ctx.map.counts()}")

    def do_sonar(self, arg):
        """sonar [front|left|right|rear]  - one distance reading (default: all four)."""
        son = self.hw.sonars()
        names = [arg.strip()] if arg.strip() else list(son)
        for n in names:
            if n not in son:
                raise ValueError(f"no sonar '{n}' (front, left, right, rear)")
            print(f"  {n:<6} {fmt_cm(son[n])}")

    def complete_sonar(self, text, *_):
        return [n for n in SONARS if n.startswith(text)]

    def do_ir(self, arg):
        """ir  - one reading of both IR edge sensors."""
        for n, v in self.hw.ir().items():
            print(f"  {n:<6} {'floor' if v == FLOOR_VALUE else 'EDGE / no floor'}  (raw {v})")

    def do_sensors(self, arg):
        """sensors [seconds]  - live table of all sonars + IR (default 8 s). Readings also go into the map."""
        self._with_seconds(arg, feat_sensors)

    def do_camera(self, arg):
        """camera [seconds]  - live camera image in the terminal + fps; saves camera.jpg."""
        self._with_seconds(arg, feat_camera)

    def do_snap(self, arg):
        """snap [file]  - take one picture, show it, save it (default: the results folder)."""
        f = self.ctx.camera().grab()
        print(render(f, reserve=4))
        self.snaps += 1
        path = Path(arg.strip()) if arg.strip() else self.ctx.out / f"snap-{self.snaps}.jpg"
        print(f"  saved {save_image(f, path)}")

    def do_detect(self, arg):
        """detect [seconds]  - live YOLO object detection with tracking IDs, boxes drawn on the image; saves detections.jpg."""
        self._with_seconds(arg, feat_vision)

    def do_look(self, arg):
        """look  - list what the camera sees right now: label, confidence, distance, bearing. Adds the objects to the map."""
        self._look()

    def do_listen(self, arg):
        """listen [seconds]  - microphone level meter (default 8 s), saves mic.wav and plays it back."""
        self._with_seconds(arg, feat_mic)

    def do_play(self, arg):
        """play [file]  - play a .wav (default: the last recording)."""
        path = arg.strip() or str(self.ctx.out / "mic.wav")
        if not shutil.which("aplay"):
            raise RuntimeError("aplay not found (Linux only): sudo apt install -y alsa-utils")
        subprocess.run(["aplay", "-q", path])

    # -- map --

    def do_showmap(self, arg):
        """showmap  - draw the map built so far (sonar + IR + objects) with its legend."""
        m = self.ctx.get_map()
        print(render(m.image(self.ctx.odo), reserve=6 + len(m.objects), max_cols=2 * N))
        print("\n".join(m.legend()))
        print(f"  {m.counts()}")

    def do_objects(self, arg):
        """objects  - objects on the map, with distance and bearing from where the robot is now."""
        m, o = self.ctx.get_map(), self.ctx.odo
        if not m.objects:
            print("  none yet - use look, find, map or detect")
        for ob in m.objects:
            dx, dy = ob["x"] - o.x, ob["y"] - o.y
            b = math.degrees(wrap(math.atan2(dy, dx) - o.th))
            print(f"  {ob['label']:<12} at ({ob['x'] * 100:+.0f}, {ob['y'] * 100:+.0f}) cm   "
                  f"{math.hypot(dx, dy) * 100:.0f} cm away, {b:+.0f} deg   seen {ob['n']}x")

    def do_pose(self, arg):
        """pose  - where the robot thinks it is (dead reckoning from motor timing, no encoders)."""
        print(f"  {self._pose_text()}")

    def do_resetmap(self, arg):
        """resetmap  - forget the map and objects; the current spot becomes the new start pose."""
        self.ctx.map, self.ctx.odo = None, Odometry()
        print("  map cleared, pose reset to (0, 0, 0)")

    # -- settings / scripting --

    def _settings_text(self):
        parts = []
        for k, (attr, unit, scale, *_r) in SETTINGS.items():
            v = globals()[attr] / scale
            parts.append(f"{k} {v:g}{unit}")
        return ", ".join(parts)

    def do_set(self, arg):
        """set [name value]  - change a setting: speed 0.1-1, stop <cm> (front/rear), side <cm> (turns), steps <n> (map/find). No args = show."""
        parts = arg.split()
        if not parts:
            print(f"  {self._settings_text()}")
            print(dim("  change with e.g.  set speed 0.4  ·  set stop 25  ·  set side 8  ·  set steps 8  ·  faster  ·  slower"))
            return
        if len(parts) != 2 or parts[0] not in SETTINGS:
            raise ValueError(f"use: set <{'|'.join(SETTINGS)}> <value>")
        attr, unit, scale, lo, hi = SETTINGS[parts[0]]
        v = float(parts[1].rstrip("cm")) * scale
        if not lo <= v <= hi:
            raise ValueError(f"{parts[0]} must be {lo / scale:g}-{hi / scale:g}{unit}")
        globals()[attr] = int(v) if attr == "SPIN_STEPS" else v
        save_settings()
        print(f"  {self._settings_text()}" + dim("   (saved as the default)"))

    def complete_set(self, text, *_):
        return [k for k in SETTINGS if k.startswith(text)]

    def complete_find(self, text, *_):
        names = set(COMMON_LABELS) | {o["label"] for o in (self.ctx.map.objects if self.ctx.map else [])}
        return sorted(n for n in names if n.startswith(text))

    complete_goto = complete_find

    def do_motors(self, arg):
        """motors on|off  - allow or lock the wheels (asks for confirmation once when turning on)."""
        a = arg.strip().lower() or ("off" if self.ctx.args.motors else "on")   # bare `motors` toggles
        if self.hw.sim:
            print("  simulation: motors are always allowed")
        elif a == "on":
            self.ctx.args.motors = True
            self.ctx._confirmed = False
            print("  motors ON" if self.ctx.can_move() else "  motors stay off")
        elif a == "off":
            self._halt()
            self.ctx.args.motors = False
            print("  motors off")
        else:
            print(f"  motors are {'ON' if self.ctx.args.motors else 'off'}  (motors on | motors off)")

    def do_pins(self, arg):
        """pins  - the wiring table."""
        feat_pins(self.ctx)

    def do_wait(self, arg):
        """wait <seconds>  - pause (useful in command lines and scripts)."""
        time.sleep(float(arg or 1))

    def do_repeat(self, arg):
        """repeat <n> <command>  - run a command n times, e.g. `repeat 4 forward 20; left 90` repeats only `forward 20`.
        To repeat a whole sequence, put it in a file and use `run`."""
        n, _, rest = arg.partition(" ")
        if not rest.strip():
            raise ValueError("use: repeat <n> <command>")
        for i in range(int(n)):
            print(f"  -- {i + 1}/{n}: {rest.strip()}")
            if super().onecmd(normalize(rest.strip())):
                return True

    def do_run(self, arg):
        """run <file>  - run commands from a text file, one per line ('#' starts a comment)."""
        for raw in Path(arg.strip()).read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                print(f"{self.prompt}{line}")
                if self.onecmd(line):
                    return True

    def do_help(self, arg):
        """help [command]  - list commands, or explain one."""
        if arg:
            name = ALIASES.get(arg.strip().lower(), arg.strip().lower())
            fn = getattr(self, f"do_{name}", None)
            print(f"  {fn.__doc__.strip()}" if fn and fn.__doc__ else f"  no command '{arg}'")
        else:
            print(HELP)

    def do_menu(self, arg):
        """menu  - numbered list of common actions (also shown when you press Enter on an empty line)."""
        print(colour("1", "  What should the robot do?") + dim("  type a number, or any command"))
        half = (len(MENU) + 1) // 2
        for i in range(half):
            left = f"  {i + 1:>2}. {MENU[i][0]}"
            right = f"{i + 1 + half:>2}. {MENU[i + half][0]}" if i + half < len(MENU) else ""
            print(f"{left:<40}{right}")

    def do_examples(self, arg):
        """examples  - things you can say to the robot."""
        for text, what in EXAMPLES:
            print(f"  {good(text):<52} {dim(what)}")

    def do_faster(self, arg):
        """faster  - raise the speed by 0.1 (max 1.0)."""
        self.do_set(f"speed {min(1.0, round(SPEED + 0.1, 2))}")

    def do_slower(self, arg):
        """slower  - lower the speed by 0.1 (min 0.1)."""
        self.do_set(f"speed {max(0.1, round(SPEED - 0.1, 2))}")

    def do_quit(self, arg):
        """quit  - stop the motors and exit."""
        return True

    do_exit = do_quit

    def do_EOF(self, arg):
        print()
        return True

    def do_dashboard(self, arg):
        """dashboard [local] [port] | dashboard stop  - web dashboard: live sensors, camera with boxes, map, drive buttons,
        command box and log. Open it from your laptop/phone on the same Wi-Fi; `local` = only this computer."""
        words = arg.lower().split()
        if "stop" in words:
            dashboard_stop()
            print("  dashboard stopped")
            return
        if DASH["server"]:
            print_urls()
            return
        port = next((int(w) for w in words if w.isdigit()), 8080)
        dashboard_start(self, port, lan="local" not in words)

    def do_opencamera(self, arg):
        """opencamera  - open the camera now (the dashboard does this when its camera card is shown)."""
        try:
            print(f"  camera: {self.ctx.camera().desc}")
            DASH["cam_error"] = ""
        except Exception as exc:
            DASH["cam_error"] = friendly(exc)      # shown on the page; not retried until `opencamera` is typed
            raise

    def do_loadmodel(self, arg):
        """loadmodel  - load the YOLO model now (the dashboard's Boxes switch does this)."""
        self.ctx.detector()
        print(good("  ✓ YOLO model loaded"))

    def close(self):
        dashboard_stop()
        self._halt()
        try:
            self.hw.close()
        finally:
            if self.ctx.cam:
                self.ctx.cam.close()


# ---------------- WEB DASHBOARD ----------------

DASH = {"server": None, "shell": None, "port": 8080, "lan": False, "cam_seen": 0.0, "boxes": False, "cam_error": "",
        "camera_on": True, "error": "", "running": False}
DASH_BLOCKED = {"quit", "exit", "eof", "calibrate", "dashboard", "run"}   # need the terminal (questions / files)


def png_bytes(rgb):
    """Minimal PNG encoder (zlib + struct) so the dashboard needs no image library."""
    import numpy as np
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def encode_image(rgb):
    """(bytes, content type): JPEG with OpenCV if available, else PNG."""
    try:
        import cv2
        ok, buf = cv2.imencode(".jpg", rgb[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            return buf.tobytes(), "image/jpeg"
    except ImportError:
        pass
    return png_bytes(rgb), "image/png"


def lan_ip():
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.connect(("10.255.255.255", 1))   # picks the outgoing interface; no packet is sent
        ip = sk.getsockname()[0]
        sk.close()
        return ip
    except OSError:
        return None


def print_urls():
    port = DASH["port"]
    ip = lan_ip()
    if DASH["lan"]:
        if ip:
            print(good(f"  Dashboard: open  http://{ip}:{port}  on your laptop or phone (same Wi-Fi)"))
        print(dim(f"  On this computer: http://localhost:{port}") +
              warn("   No login: anyone on this Wi-Fi can drive the robot") + dim(" (`dashboard local` = only this computer)."))
        if ip and os.environ.get("SSH_CONNECTION"):
            print(dim(f"  Can't connect? Check the laptop is on the same network as {ip}, or use an SSH tunnel: "
                      f"ssh -L {port}:localhost:{port} <user>@{ip}  then open http://localhost:{port}"))
    else:
        print(good(f"  Dashboard: http://localhost:{port}") + dim("  (this computer only)"))
        if ip:
            print(dim(f"  From your laptop: SSH tunnel  ssh -L {port}:localhost:{port} <user>@{ip}  then open http://localhost:{port}"))


def run_dashboard_cmd(line):
    """Run a typed/button command for the dashboard in a worker thread. Returns (ok, message)."""
    sh = DASH["shell"]
    word = normalize(line).split()[0] if normalize(line) else ""
    if word in DASH_BLOCKED:
        return False, f"'{word}' needs the terminal"
    if word == "stop":
        sh.do_stop("")
        return True, "stopped"
    if TELE["busy"]:
        return False, f"busy with '{TELE['busy']}' - press Stop first"

    def work():
        if not BUSY.acquire(timeout=3):
            print(warn("  busy"))
            return
        try:
            STOP_REQ.clear()
            TELE["busy"] = line
            print(colour("36", f"[dashboard] {line}"))
            sh.onecmd(line)
        finally:
            TELE["busy"] = None
            BUSY.release()
            sh._update_prompt()
    threading.Thread(target=work, name="dashboard-cmd", daemon=True).start()
    return True, "started"


def sampler():
    """While nothing else uses the hardware: refresh sensor readings (and the camera if the page shows it)."""
    sh = DASH["shell"]
    while DASH["running"]:
        time.sleep(0.25)
        if TELE["busy"] or not BUSY.acquire(blocking=False):
            continue
        try:
            son, ir = read_all(sh.hw)
            o = sh.ctx.odo
            TELE.update(sonars=son, ir=ir, pose=(o.x, o.y, o.th), t=time.time())
            if DASH["camera_on"] and sh.ctx.cam and time.monotonic() - DASH["cam_seen"] < 3:
                f = sh.ctx.cam.grab()          # opening the camera is a visible command (opencamera), not done here
                if DASH["boxes"] and sh.ctx.det:
                    sh.ctx.det(f)
            DASH["error"] = ""
        except Exception as exc:
            DASH["error"] = friendly(exc)
            time.sleep(1.0)
        finally:
            BUSY.release()


def state_json(since):
    sh = DASH["shell"]
    o = sh.ctx.odo
    m = sh.ctx.map
    objs = []
    for ob in (m.objects if m else []):
        dx, dy = ob["x"] - o.x, ob["y"] - o.y
        objs.append({"label": ob["label"], "x": round(ob["x"] * 100), "y": round(ob["y"] * 100), "n": ob["n"],
                     "dist": round(math.hypot(dx, dy) * 100), "bearing": round(math.degrees(wrap(math.atan2(dy, dx) - o.th)))})
    fresh = time.time() - LATEST["det_t"] < 2
    x, y, th = TELE["pose"] if TELE["moving"] else (o.x, o.y, o.th)
    return {
        "mode": "simulation" if sh.hw.sim else "real robot",
        "wheels": bool(sh.hw.sim or (sh.ctx.args.motors and (getattr(sh.ctx, "_confirmed", False) or sh.ctx.args.yes))),
        "busy": TELE["busy"], "moving": TELE["moving"],
        "sonars": {k: (None if v >= MAX_DISTANCE - 0.005 else round(v * 100, 1)) for k, v in TELE["sonars"].items()},
        "ir": {k: ("floor" if v == FLOOR_VALUE else "edge") for k, v in TELE["ir"].items()},
        "age": round(time.time() - TELE["t"], 1) if TELE["t"] else None,
        "pose": {"x": round(x * 100, 1), "y": round(y * 100, 1), "heading": round(math.degrees(th) % 360)},
        "settings": {"speed": SPEED, "turn": TURN_SPEED, "stop": round(STOP_DISTANCE * 100), "side": round(SIDE_STOP_DISTANCE * 100)},
        "calibration": _ANSI.sub("", cal_text()), "stop_distance": STOP_DISTANCE * 100,
        "objects": objs, "map": m.counts() if m else None,
        "detections": [{"id": d["id"], "label": d["label"], "score": round(d["score"], 2)} for d in LATEST["dets"]] if fresh else [],
        "camera": LATEST["frame"] is not None, "boxes": DASH["boxes"], "camera_on": DASH["camera_on"],
        "camera_error": DASH["cam_error"],
        "model": bool(sh.ctx.det), "error": DASH["error"],
        "log": [[n, t] for n, t in list(LOG) if n > since],
    }


class DashHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        try:
            if path == "/":
                return self._send(200, DASH_HTML, "text/html; charset=utf-8")
            if path == "/api/state":
                since = int(dict(q.split("=") for q in query.split("&") if "=" in q).get("since", 0))
                return self._send(200, state_json(since))
            if path == "/camera":
                DASH["cam_seen"] = time.monotonic()
                sh = DASH["shell"]
                if sh.ctx.cam is None and not TELE["busy"] and not DASH["cam_error"] and DASH["camera_on"]:
                    run_dashboard_cmd("opencamera")
                f = LATEST["frame"]
                if f is None:
                    return self._send(204, b"")
                if DASH["boxes"] and time.time() - LATEST["det_t"] < 2:
                    f = draw_boxes(f, LATEST["dets"])
                body, ctype = encode_image(f[::2, ::2] if f.shape[1] > 400 else f)
                return self._send(200, body, ctype)
            if path == "/map":
                sh = DASH["shell"]
                img = sh.ctx.get_map().image(sh.ctx.odo)
                return self._send(200, png_bytes(img.repeat(6, 0).repeat(6, 1)), "image/png")
            return self._send(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._send(500, {"error": friendly(exc)})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/cmd":
                ok, msg = run_dashboard_cmd(str(data.get("cmd", "")).strip())
                return self._send(200 if ok else 409, {"ok": ok, "message": msg})
            if self.path == "/api/stop":
                DASH["shell"].do_stop("")
                return self._send(200, {"ok": True})
            if self.path == "/api/toggle":
                for k in ("boxes", "camera_on"):
                    if k in data:
                        DASH[k] = bool(data[k])
                if DASH["boxes"] and not DASH["shell"].ctx.det:
                    run_dashboard_cmd("loadmodel")
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(500, {"error": friendly(exc)})


def dashboard_start(sh, port=8080, lan=True):
    if DASH["server"]:
        return print_urls()
    # Load the image libraries here, in the main thread. Importing a C extension (numpy) for the first time in a
    # server thread while the main thread waits at the prompt deadlocks on Windows and freezes the whole page.
    importlib.import_module("numpy")
    try:
        importlib.import_module("cv2")
    except ImportError:
        pass
    try:
        srv = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), DashHandler)
    except OSError as exc:
        print(bad(f"  ✗ Could not start the dashboard on port {port}: {exc}.") + dim(f"  Try: dashboard {port + 1}"))
        return
    srv.daemon_threads = True
    DASH.update(server=srv, shell=sh, port=port, lan=lan, running=True)
    threading.Thread(target=srv.serve_forever, name="dashboard-http", daemon=True).start()
    threading.Thread(target=sampler, name="dashboard-sampler", daemon=True).start()
    print_urls()


def dashboard_stop():
    srv = DASH["server"]
    if srv:
        DASH.update(server=None, running=False)
        srv.shutdown()
        srv.server_close()


DASH_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Desk Robot</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2129;--mut:#6b7280;--line:#e3e6ea;--acc:#2563eb;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--ink:#e6e8eb;--mut:#9aa1ab;--line:#2a2f37;--acc:#60a5fa;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--chip:#232831}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:2}
h1{font-size:17px;margin:0}.chip{background:var(--chip);border-radius:99px;padding:3px 10px;font-size:12px;color:var(--mut)}
.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad)}
#stopbig{margin-left:auto;background:var(--bad);color:#fff;border:0;border-radius:8px;padding:9px 18px;font-weight:700;font-size:15px;cursor:pointer}
main{display:grid;gap:14px;padding:14px 16px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));max-width:1400px;margin:auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;min-width:0}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:0 0 10px;display:flex;justify-content:space-between;align-items:center}
.pad{display:grid;grid-template-columns:repeat(3,64px);grid-template-rows:repeat(3,52px);gap:6px;justify-content:center;margin:6px 0 12px}
button{font:inherit;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:8px;padding:7px 10px;cursor:pointer}
button:hover{border-color:var(--acc)}.pad button{font-size:20px}.pad .stop{background:var(--bad);color:#fff;border:0;font-size:13px;font-weight:700}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}
input[type=text]{flex:1;min-width:0;font:inherit;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
.bar{height:10px;background:var(--chip);border-radius:6px;overflow:hidden;flex:1}.bar i{display:block;height:100%;background:var(--acc)}
.sonar{display:grid;grid-template-columns:52px 1fr 70px;gap:8px;align-items:center;margin:6px 0}.mono{font-family:ui-monospace,Consolas,monospace}
.near i{background:var(--bad)}.ir{display:flex;gap:8px;margin-top:10px}.pill{flex:1;text-align:center;padding:6px;border-radius:8px;background:var(--chip)}
.pill.edge{background:var(--warn);color:#111}img.view{width:100%;border-radius:8px;background:var(--chip);display:block;image-rendering:pixelated;min-height:120px}
#log{height:240px;overflow:auto;background:var(--bg);border-radius:8px;padding:8px;font:12px/1.4 ui-monospace,Consolas,monospace;white-space:pre-wrap}
table{width:100%;border-collapse:collapse}td{padding:3px 4px;border-bottom:1px solid var(--line)}.mut{color:var(--mut)}
label{display:flex;gap:8px;align-items:center}input[type=range]{flex:1}.err{color:var(--bad);font-size:13px;margin-top:6px}
.legend span{display:inline-flex;align-items:center;gap:4px;margin-right:10px;font-size:12px;color:var(--mut)}.legend b{width:10px;height:10px;border-radius:2px;display:inline-block}
</style></head><body>
<header><h1>Desk Robot</h1><span class="chip" id="mode">…</span><span class="chip" id="wheels">…</span>
<span class="chip" id="busy">idle</span><span class="chip mono" id="pose">pose</span><button id="stopbig" title="Space">STOP</button></header>
<main>
<section class="card"><h2>Drive <span class="mut" style="text-transform:none">arrows / WASD · Space = stop</span></h2>
 <div class="pad"><span></span><button data-m="forward">▲</button><span></span>
 <button data-m="left">◀</button><button class="stop" data-stop>STOP</button><button data-m="right">▶</button>
 <span></span><button data-m="back">▼</button><span></span></div>
 <div class="row"><span class="mut">Step</span><select id="step"><option value="5,15">small (5 cm / 15°)</option><option value="10,30" selected>medium (10 cm / 30°)</option><option value="20,90">big (20 cm / 90°)</option></select></div>
 <div class="row"><button data-c="look">What do you see?</button><button data-ask="find">Find…</button><button data-ask="goto">Go to…</button>
 <button data-c="map">Scan map</button><button data-c="home">Go home</button><button data-c="spin">Spin</button><button data-c="resetmap">Reset map</button></div>
 <div class="row"><input type="text" id="cmd" placeholder='Tell it what to do, e.g. "forward 30 cm then left 90"'><button id="send">Send</button></div>
 <div class="err" id="cmderr"></div></section>
<section class="card"><h2>Sensors <span class="mut mono" id="age"></span></h2><div id="sonars"></div>
 <div class="ir"><div class="pill" id="ir-front">front IR</div><div class="pill" id="ir-rear">rear IR</div></div><div class="err" id="err"></div></section>
<section class="card"><h2>Camera <span><label style="display:inline-flex"><input type="checkbox" id="boxes"> boxes (YOLO)</label></span></h2>
 <img class="view" id="cam" alt="camera"><div id="dets" class="mut" style="margin-top:6px"></div></section>
<section class="card"><h2>Map <span class="mut mono" id="mapc"></span></h2><img class="view" id="map" alt="map">
 <div class="legend" style="margin-top:6px"><span><b style="background:#dc3232"></b>obstacle</span><span><b style="background:#ebebeb;border:1px solid #999"></b>free</span><span><b style="background:#ffc800"></b>edge</span><span><b style="background:#5a8cff"></b>path</span><span><b style="background:#00dc00"></b>robot</span></div>
 <table id="objs" style="margin-top:8px"></table></section>
<section class="card"><h2>Settings <span class="mut" style="text-transform:none">saved as defaults</span></h2>
 <label>Speed <input type="range" id="s-speed" min="0.1" max="1" step="0.05"><span class="mono" id="v-speed"></span></label>
 <label>Turn speed <input type="range" id="s-turn" min="0.1" max="1" step="0.05"><span class="mono" id="v-turn"></span></label>
 <label>Stop distance <input type="range" id="s-stop" min="5" max="60" step="1"><span class="mono" id="v-stop"></span></label>
 <p class="mut" id="cal" style="margin:10px 0 0"></p></section>
<section class="card" style="grid-column:1/-1"><h2>Log</h2><div id="log"></div></section>
</main>
<script>
const $=id=>document.getElementById(id);let since=0,st={},editing=false;
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});return r.json().catch(()=>({}))}
async function cmd(c){$('cmderr').textContent='';const r=await post('/api/cmd',{cmd:c});if(!r.ok)$('cmderr').textContent=r.message||'error'}
function stop(){post('/api/stop')}
function step(){return $('step').value.split(',')}
function move(m){const[cm,deg]=step();cmd(m==='left'||m==='right'?`${m} ${deg}`:`${m} ${cm}cm`)}
document.querySelectorAll('[data-m]').forEach(b=>b.onclick=()=>move(b.dataset.m));
document.querySelectorAll('[data-stop]').forEach(b=>b.onclick=stop);$('stopbig').onclick=stop;
document.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>cmd(b.dataset.c));
document.querySelectorAll('[data-ask]').forEach(b=>b.onclick=()=>{const o=prompt('Which object? (cup, bottle, person, any…)');if(o)cmd(`${b.dataset.ask} ${o}`)});
$('send').onclick=()=>{const v=$('cmd').value.trim();if(v){cmd(v);$('cmd').value=''}};
$('cmd').addEventListener('keydown',e=>{if(e.key==='Enter')$('send').click()});
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target.type==='text')return;
 const k={ArrowUp:'forward',w:'forward',ArrowDown:'back',s:'back',ArrowLeft:'left',a:'left',ArrowRight:'right',d:'right'}[e.key];
 if(e.key===' '){e.preventDefault();stop()}else if(k){e.preventDefault();move(k)}});
$('boxes').onchange=e=>post('/api/toggle',{boxes:e.target.checked});
for(const k of['speed','turn','stop']){const el=$('s-'+k);el.oninput=()=>{editing=true;$('v-'+k).textContent=el.value};
 el.onchange=()=>{editing=false;cmd(`set ${k} ${el.value}`)}}
function chip(el,text,cls){el.textContent=text;el.className='chip '+(cls||'')}
function render(s){st=s;chip($('mode'),s.mode);chip($('wheels'),s.wheels?'wheels on':'wheels locked (type motors on in the terminal)',s.wheels?'ok':'warn');
 chip($('busy'),s.busy?(s.moving?`moving ${s.moving}: `:'')+s.busy:'idle',s.busy?'warn':'ok');
 $('pose').textContent=`x ${s.pose.x} cm  y ${s.pose.y} cm  ${s.pose.heading}°`;$('age').textContent=s.age!=null?`${s.age}s ago`:'';
 $('sonars').innerHTML=['front','left','right','rear'].map(n=>{const v=s.sonars[n];const pct=v==null?0:Math.max(0,100-v/2);
  const near=v!=null&&v<(n==='left'||n==='right'?s.settings.side:s.settings.stop);
  return `<div class="sonar ${near?'near':''}"><span>${n}</span><div class="bar"><i style="width:${pct}%"></i></div><span class="mono">${v==null?(n in s.sonars?'no echo':'—'):v+' cm'}</span></div>`}).join('');
 for(const n of['front','rear']){const e=$('ir-'+n),v=s.ir[n];e.textContent=`${n} IR: ${v||'—'}`;e.className='pill '+(v==='edge'?'edge':'')}
 $('err').textContent=s.error||'';$('boxes').checked=s.boxes;
 if(s.camera_error)$('dets').textContent='Camera: '+s.camera_error;else $('dets').textContent=s.detections.length?s.detections.map(d=>`#${d.id} ${d.label} ${d.score}`).join(' · '):(s.boxes?(s.model?'no objects':'loading YOLO…'):'');
 $('mapc').textContent=s.map?`${s.map.occupied} obstacle · ${s.map.free} free cells`:'';
 $('objs').innerHTML=s.objects.map(o=>`<tr><td>${o.label}</td><td class="mono">${o.dist} cm</td><td class="mono">${o.bearing>0?'+':''}${o.bearing}°</td><td class="mut">seen ${o.n}×</td></tr>`).join('');
 if(!editing)for(const k of['speed','turn','stop']){$('s-'+k).value=s.settings[k];$('v-'+k).textContent=s.settings[k]+(k==='stop'?' cm':'')}
 $('cal').textContent=s.calibration;
 if(s.log.length){const L=$('log'),atEnd=L.scrollTop+L.clientHeight>=L.scrollHeight-20;
  for(const[n,t]of s.log){L.append(t+String.fromCharCode(10));since=n}if(atEnd)L.scrollTop=L.scrollHeight}}
async function poll(){try{render(await (await fetch('/api/state?since='+since)).json())}catch(e){chip($('busy'),'disconnected','bad')}setTimeout(poll,300)}
function camLoop(){const i=$('cam');i.onload=i.onerror=()=>setTimeout(camLoop,200);i.src='/camera?t='+Date.now()}
function mapLoop(){const i=$('map');i.onload=i.onerror=()=>setTimeout(mapLoop,st.busy?500:1500);i.src='/map?t='+Date.now()}
poll();camLoop();mapLoop();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Interactive desk-robot shell")
    ap.add_argument("commands", nargs="*", help="run these commands (';' separated) and exit, e.g. \"forward 20; look\"")
    ap.add_argument("--sim", action="store_true", help="fake robot on a fake desk")
    ap.add_argument("--motors", action="store_true", help="allow the wheels from the start (asks once)")
    ap.add_argument("--yes", action="store_true", help="don't ask before the wheels move")
    ap.add_argument("--camera", default="auto", choices=["auto", "pi", "webcam", "sample", "synthetic"])
    ap.add_argument("--model", help="YOLO model path (default models/yolo26n_ncnn_model, then models/yolo26n.pt)")
    ap.add_argument("--mic", help="ALSA capture device, e.g. plughw:1,0")
    ap.add_argument("--out", help="where pictures/recordings go (default e2e_results/shell-<time>)")
    ap.add_argument("--dashboard", action="store_true", help="start the web dashboard too (open it from your laptop/phone)")
    ap.add_argument("--lan", action="store_true", help="same as --dashboard (kept for old commands)")
    ap.add_argument("--local", action="store_true", help="with --dashboard: only this computer can open it")
    ap.add_argument("--port", type=int, default=8080, help="dashboard port (default 8080)")
    args = ap.parse_args()
    args.out = Path(args.out) if args.out else HERE / "e2e_results" / time.strftime("shell-%Y%m%d-%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)

    global SETTINGS_FILE
    SETTINGS_FILE = str(HERE / ("robot_shell_settings_sim.json" if args.sim else "robot_shell_settings.json"))
    load_settings()
    sh = RobotShell(args)
    try:
        if args.commands:
            sh.onecmd(" ".join(args.commands))
            return
        welcome(args)
        if args.dashboard or args.lan or args.local:
            dashboard_start(sh, args.port, lan=not args.local)
        if not CAL and not args.sim and sys.stdin.isatty():
            a = input("  This robot isn't calibrated yet, so distances and angles will be off. "
                      "Calibrate now? It takes about a minute and the robot moves. [Y/n] ").strip().lower()
            if not a.startswith("n"):
                if not sh.ctx.args.motors:
                    sh.ctx.args.motors, sh.ctx._confirmed = True, False
                sh.onecmd("calibrate")
        if READLINE:
            try:
                readline.read_history_file(HISTORY)
            except OSError:
                pass
        while True:
            try:
                sh.cmdloop()
                break
            except KeyboardInterrupt:
                STOP_REQ.set()                  # also stops a move the dashboard started
                sh._halt()
                print("\n" + dim("  (type quit to leave)"))
    finally:
        if READLINE and not args.commands:
            try:
                readline.write_history_file(HISTORY)
            except OSError:
                pass
        sh.close()
        print(dim("Motors stopped. Bye."))


def welcome(args):
    model = find_model(args.model)
    where = "SIMULATED robot on a fake desk" if args.sim else "real robot"
    wheels = good("unlocked") if args.sim or args.motors else warn("locked") + dim(" (type: motors on)")
    print(colour("1", "\n  Desk robot") + dim(f"  ·  {where}  ·  ") + "wheels " + wheels)
    print(dim(f"  object detection: {model if model else 'no model yet - downloaded automatically the first time you use look/detect'}"))
    print("  " + cal_text() + dim(f"   ·   speed {SPEED:g}, turn speed {TURN_SPEED:g}, stop {STOP_DISTANCE * 100:.0f} cm"))
    print(dim(f"  settings: {SETTINGS_FILE}" + ("" if Path(SETTINGS_FILE).exists() else " (not saved yet)")))
    print(f"\n  Just tell it what to do, e.g.  {good('go forward 30 cm')}  ·  {good('turn left 90')}  ·  "
          f"{good('what do you see')}  ·  {good('find the cup')}  ·  {good('go home')}")
    print(f"  Press {colour('1', 'Enter')} for a menu  ·  {colour('1', 'help')} for every command  ·  "
          f"{colour('1', 'examples')} for ideas  ·  {colour('1', 'Ctrl+C')} stops the robot  ·  {colour('1', 'quit')} to leave\n")


if __name__ == "__main__":
    main()
