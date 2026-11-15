"""
End-to-end run of EVERY robot feature, showing the live output of each - ONE STANDALONE FILE.
No other project file is imported: copy just this file to the Pi.

    python3 tools/test_e2e.py --motors     # everything, including driving + the map made by spinning (robot MOVES)
    python3 tools/test_e2e.py              # everything except the wheels (map is made standing still)
    python3 tools/test_e2e.py --sim        # fake robot on a fake desk + sample photo: see it all on a laptop
    python3 tools/test_e2e.py --only vision,map   --seconds 15   --camera webcam

Features, in order (Ctrl+C skips to the next one, Ctrl+C twice quickly quits; motors always stop):
    pins      the wiring table
    sensors   live table of all 4 ultrasonic distances (with bars) + both IR edge sensors
    camera    live camera image drawn in the terminal (works over SSH) + fps
    vision    YOLO26n object detection + tracking IDs: boxes drawn on the live image, labels,
              confidence, ms per frame, and where each object is on the desk (cm ahead / left)
    mic       live microphone level meter + history, then the recording is played back
    drive     forward / turn left / turn right / backward with the safety rules (sonar + IR edge),
              live sensor values + pose while moving, and why a move stopped
    map       spins 360 deg in 45 deg steps: 4 sonar beams + IR build an occupancy map, camera
              detections are placed on it as objects; the map is drawn in the terminal

Everything is also saved in e2e_results/<time>/: camera.jpg, detections.jpg, mic.wav, map.png, summary.json.
Pins are copied from robot_config.py so this file runs on its own: update both after rewiring.
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import random
import shutil
import subprocess
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
SPEED = 0.5
LOOP_DT = 0.05                # s, control + display loop
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


class Screen:
    """Redraws in place on a terminal; when output is piped, prints the text once a second and the last image at the end."""

    def __init__(self, title):
        self.title, self.last, self.image, self.lines = title, 0.0, None, []
        print(f"\n\x1b[1m== {title} ==\x1b[0m  (Ctrl+C = next feature)" if not TTY else "", end="" if TTY else "\n", flush=True)
        if TTY:
            sys.stdout.write("\x1b[2J\x1b[?25l")

    def show(self, lines, image=None):
        self.image, self.lines = image, lines
        if TTY:
            head = f"\x1b[1m== {self.title} ==\x1b[0m   Ctrl+C = next feature, twice = quit\x1b[K\n"
            body = (image + "\n") if image else ""
            sys.stdout.write("\x1b[H" + head + body + "\n".join(l + "\x1b[K" for l in lines) + "\n\x1b[J")
            sys.stdout.flush()
        elif time.monotonic() - self.last >= 1.0:
            self.last = time.monotonic()
            print("  " + " | ".join(l.strip() for l in lines[:3] if l.strip()), flush=True)

    def close(self, final_lines=()):
        if TTY:
            sys.stdout.write("\x1b[0m\x1b[?25h\n")
        elif self.image:
            print(self.image)
            print("\n".join(self.lines))
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
    if arg:
        return Path(arg)
    for base in (HERE / "models", Path.cwd() / "models"):
        ncnn = base / "yolo26n_ncnn_model"
        if ncnn.is_dir() and any(ncnn.glob("*.param")):
            return ncnn
        if (base / "yolo26n.pt").exists():
            return base / "yolo26n.pt"
    return None


class Detector:
    """YOLO + a small IoU tracker (keeps an ID on each object from frame to frame)."""

    def __init__(self, path):
        from ultralytics import YOLO
        self.model, self.path = YOLO(str(path), task="detect"), path
        self.tracks, self.next_id = [], 1

    def __call__(self, rgb):
        res = self.model.predict(rgb[:, :, ::-1].copy(), imgsz=YOLO_IMGSZ, conf=YOLO_CONF, verbose=False)[0]
        dets = [(res.names[int(c)], s, b) for c, s, b in zip(res.boxes.cls.tolist(), res.boxes.conf.tolist(), res.boxes.xyxy.tolist())]
        return self._track(dets)

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
        return self.cam

    def detector(self):
        if self.det is None:
            path = find_model(self.args.model)
            if not path or not path.exists():
                raise RuntimeError("no YOLO model in models/ (yolo26n_ncnn_model or yolo26n.pt) - pass --model PATH")
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
    """Safety rules of 13Nov-multisonar.py. Returns the reason to stop, or None."""
    if direction == "forward":
        if ir["front"] != FLOOR_VALUE:
            return "front IR: desk edge"
        if son["front"] < STOP_DISTANCE:
            return f"obstacle {son['front'] * 100:.0f} cm ahead"
    elif direction == "backward":
        if ir["rear"] != FLOOR_VALUE:
            return "rear IR: desk edge"
        if son["rear"] < STOP_DISTANCE:
            return f"obstacle {son['rear'] * 100:.0f} cm behind"
    else:
        for side in ("left", "right"):
            if son[side] < SIDE_STOP_DISTANCE:
                return f"{side} side only {son[side] * 100:.0f} cm away"
    return None


WHEELS = {"forward": (1, 1), "backward": (-1, -1), "left": (-1, 1), "right": (1, -1)}


def drive(ctx, direction, seconds, scr, note=""):
    """One safe move: polls all sensors every LOOP_DT, stops at once on a hazard; updates odometry + map live."""
    m, hw, odo = ctx.get_map(), ctx.hw, ctx.odo
    l, r = (k * SPEED for k in WHEELS[direction])
    son, ir = read_all(hw)
    why = blocked(direction, son, ir)
    if why:
        return f"refused: {why}"
    t0 = last = time.monotonic()
    hw.motors(l, r)
    try:
        while (now := time.monotonic()) - t0 < seconds:
            odo.advance(l, r, now - last)
            last = now
            son, ir = read_all(hw)
            m.integrate(odo, son, ir)
            why = blocked(direction, son, ir)
            if why:
                return f"STOPPED after {now - t0:.2f} s: {why}"
            if time.monotonic() - t0 >= seconds:   # time is up: stop before spending time on drawing
                break
            lines = [f"  {note}{direction:<8} {now - t0:4.1f}/{seconds:.1f} s   pose x {odo.x * 100:+5.1f} cm  y {odo.y * 100:+5.1f} cm  "
                     f"heading {math.degrees(odo.th):5.0f} deg",
                     "  " + "  ".join(f"{n} {fmt_cm(d).strip()}" for n, d in son.items())
                     + "   IR " + " ".join(f"{n} {'floor' if v == FLOOR_VALUE else 'EDGE'}" for n, v in ir.items())]
            scr.show(lines + m.legend()[:1], render(m.image(odo), reserve=8, max_cols=2 * N))
            time.sleep(max(0.0, min(LOOP_DT, seconds - (time.monotonic() - t0))))   # don't overshoot the end
    finally:
        hw.motors(0, 0)
        odo.advance(l, r, time.monotonic() - last)   # the motors ran right up to this moment
    return f"done ({seconds:.1f} s)"


def feat_drive(ctx):
    if not ctx.can_move():
        print("\n== drive ==\n  skipped: wheels only move with --motors (or use --sim)")
        ctx.summary["drive"] = "skipped (no --motors)"
        return
    scr = Screen("drive with safety stops (sonar + IR)")
    results = []
    try:
        for direction, secs in DRIVE_PLAN:
            results.append(f"  {direction:<8} {drive(ctx, direction, secs, scr)}")
            time.sleep(0.3)
    finally:
        ctx.hw.motors(0, 0)
        results.append(f"  odometry: x {ctx.odo.x * 100:+.1f} cm, y {ctx.odo.y * 100:+.1f} cm, heading {math.degrees(ctx.odo.th):.0f} deg")
        scr.close(results)
        ctx.summary["drive"] = [l.strip() for l in results]


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
        turn_time = (2 * math.pi / SPIN_STEPS) / (2 * SPEED * WHEEL_SPEED_AT_FULL / TRACK_WIDTH)
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


FEATURES = ["pins", "sensors", "camera", "vision", "mic", "drive", "map"]


def main():
    ap = argparse.ArgumentParser(description="Run every desk-robot feature and show its output (standalone)")
    ap.add_argument("--motors", action="store_true", help="let the wheels move (drive + spinning map)")
    ap.add_argument("--yes", action="store_true", help="don't ask before moving the wheels")
    ap.add_argument("--sim", action="store_true", help="fake robot + desk + sample camera image (laptop)")
    ap.add_argument("--only", help=f"comma list: {','.join(FEATURES)}")
    ap.add_argument("--skip", help="comma list of features to leave out")
    ap.add_argument("--seconds", type=float, default=8.0, help="how long each live view runs (default 8)")
    ap.add_argument("--camera", default="auto", choices=["auto", "pi", "webcam", "sample", "synthetic"])
    ap.add_argument("--model", help="YOLO model (default models/yolo26n_ncnn_model, then models/yolo26n.pt)")
    ap.add_argument("--mic", help="ALSA capture device, e.g. plughw:1,0")
    ap.add_argument("--out", help="output folder (default e2e_results/<time>)")
    args = ap.parse_args()

    feats = [f.strip() for f in args.only.split(",")] if args.only else list(FEATURES)
    bad = [f for f in feats if f not in FEATURES]
    if bad:
        ap.error(f"unknown feature(s): {', '.join(bad)}")
    if args.skip:
        feats = [f for f in feats if f not in args.skip.split(",")]
    args.out = Path(args.out) if args.out else HERE / "e2e_results" / time.strftime("%Y%m%d-%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)

    hw = SimHardware() if args.sim else RealHardware()
    ctx = Ctx(args, hw)
    print(f"Desk robot - every feature, {'SIMULATED robot' if args.sim else 'real robot'}: {', '.join(feats)}")
    if not args.sim and not args.motors:
        print("Wheels stay still (add --motors to drive and to map by spinning).")
    last_int = 0.0
    try:
        for name in feats:
            try:
                globals()[f"feat_{name}"](ctx)
            except KeyboardInterrupt:
                hw.motors(0, 0) if hw.sim or args.motors else None
                if time.monotonic() - last_int < 1.5:
                    raise
                last_int = time.monotonic()
                print(f"\n  ({name} skipped - Ctrl+C again quickly to quit)")
                ctx.summary.setdefault(name, "skipped by Ctrl+C")
            except Exception as exc:
                print(f"\n\x1b[0m\x1b[?25h== {name} == could not run: {type(exc).__name__}: {exc}")
                ctx.summary[name] = f"error: {type(exc).__name__}: {exc}"
    except KeyboardInterrupt:
        print("\nQuit.")
    finally:
        if TTY:
            sys.stdout.write("\x1b[0m\x1b[?25h")
        try:
            hw.close()
        finally:
            if ctx.cam:
                ctx.cam.close()

    print("\n\x1b[1m== what each feature produced ==\x1b[0m")
    for k, v in ctx.summary.items():
        if isinstance(v, dict):
            v = [str(v["counts"])] + [f"{o['label']} at ({o['x'] * 100:+.0f}, {o['y'] * 100:+.0f}) cm" for o in v["objects"]]
        for i, line in enumerate(v if isinstance(v, list) else [v]):
            print(f"  {k if i == 0 else '':<8} {line}")
    (args.out / "summary.json").write_text(json.dumps(ctx.summary, indent=2), encoding="utf-8")
    print(f"\nFiles (camera.jpg, detections.jpg, mic.wav, map.png, summary.json): {args.out}")


if __name__ == "__main__":
    main()
