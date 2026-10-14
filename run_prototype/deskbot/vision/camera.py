"""
Camera sources + a latest-frame grabber.

Sources (all return BGR uint8 frames of CameraConfig.width x height):
    PiCamera      Raspberry Pi camera via picamera2 (libcamera). The ISP scales to 320x240 in
                  hardware and delivers RGB888, which is B,G,R byte order = OpenCV's native order,
                  so no CPU resize or colour conversion is needed.
    OpenCVCamera  USB webcam index or a video file (laptop testing).
    SimCamera     renders the simulated desk from SimHardware and attaches ground-truth boxes,
                  so the whole vision -> mapping path runs without a camera or a model.

FrameGrabber runs the source in its own thread and keeps ONLY the newest frame. The detector always
takes the newest frame and older frames are dropped, never queued. So the latency is one inference plus
at most one frame period, however slow the detector is.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from ..config import CameraConfig
from .geometry import CameraModel


@dataclass
class Frame:
    seq: int
    t: float                      # time.monotonic() when the frame was captured
    image: np.ndarray             # BGR, H x W x 3
    truth: list = field(default_factory=list)  # SimCamera only: ground-truth boxes


class PiCamera:
    name = "pi"

    def __init__(self, cfg: CameraConfig):
        from picamera2 import Picamera2  # system package: sudo apt install python3-picamera2

        if not Picamera2.global_camera_info():
            raise RuntimeError("No Raspberry Pi camera detected (check the ribbon cable; rpicam-hello --list-cameras)")
        self.cfg = cfg
        self.cam = Picamera2()
        kwargs = {}
        if cfg.rotate_180:
            from libcamera import Transform
            kwargs["transform"] = Transform(hflip=True, vflip=True)
        config = self.cam.create_video_configuration(
            main={"size": (cfg.width, cfg.height), "format": "RGB888"},
            buffer_count=cfg.buffer_count,
            queue=False,                         # never hand out a frame captured before the request
            controls={"FrameRate": cfg.fps},
            **kwargs,
        )
        self.cam.configure(config)
        self.cam.start()
        self.model = self.cam.camera_properties.get("Model", "?")
        time.sleep(0.5)  # auto exposure / white balance settle

    def read(self):
        img = self.cam.capture_array("main")
        t = time.monotonic()
        if img.shape[2] == 4:
            img = img[:, :, :3]
        return t, img, []

    def close(self):
        try:
            self.cam.stop()
        finally:
            self.cam.close()


class OpenCVCamera:
    name = "opencv"

    def __init__(self, cfg: CameraConfig, source=0):
        import cv2

        self.cfg = cfg
        self.cv2 = cv2
        if isinstance(source, int) and sys.platform == "win32":
            # DirectShow: Media Foundation (OpenCV's Windows default) hangs on open when torch is loaded
            self.cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera/video {source!r}")
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # don't let the driver queue stale frames
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        self.is_file = isinstance(source, str)
        self.model = str(source)
        self._period = 1.0 / cfg.fps if self.is_file else 0.0
        self._last = 0.0

    def read(self):
        if self._period:  # play files in real time instead of as fast as possible
            wait = self._last + self._period - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        ok, img = self.cap.read()
        if not ok and self.is_file:
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, 0)  # loop the video
            ok, img = self.cap.read()
        if not ok:
            raise RuntimeError("Camera read failed")
        t = time.monotonic()
        if img.shape[1] != self.cfg.width or img.shape[0] != self.cfg.height:
            img = self.cv2.resize(img, (self.cfg.width, self.cfg.height), interpolation=self.cv2.INTER_AREA)
        return t, img, []

    def close(self):
        self.cap.release()


# ---------------- simulation ----------------

SKY = np.array([205, 200, 196], np.uint8)      # BGR
DESK = np.array([170, 190, 210], np.uint8)
FLOOR = np.array([60, 60, 60], np.uint8)


class SimCamera:
    """Renders the simulated desk (SimHardware) and reports ground-truth boxes for SimDetector."""

    name = "sim"

    def __init__(self, cfg: CameraConfig, hw):
        self.cfg = cfg
        self.hw = hw
        self.cam = CameraModel(cfg)
        self.model = "simulated"
        self._period = 1.0 / cfg.fps
        self._next = time.monotonic()

    def _pose(self):
        with self.hw._lock:
            self.hw._step()
            return self.hw.x, self.hw.y, self.hw.theta

    def _to_robot(self, pose, wx, wy):
        x, y, th = pose
        dx, dy = wx - x, wy - y
        c, s = math.cos(th), math.sin(th)
        return dx * c + dy * s, -dx * s + dy * c

    def _outline(self, ob):
        """Footprint points of an obstacle in world coordinates."""
        if ob["kind"] == "circle":
            return [(ob["x"] + ob["r"] * math.cos(a), ob["y"] + ob["r"] * math.sin(a))
                    for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
        pts = []
        for fx in np.linspace(0, 1, 5):
            for fy in (0, 1):
                pts += [(ob["x"] + fx * ob["w"], ob["y"] + fy * ob["h"]), (ob["x"] + fy * ob["w"], ob["y"] + fx * ob["h"])]
        return pts

    def _boxes(self, pose):
        W, H = self.cfg.width, self.cfg.height
        boxes = []
        for ob in self.hw.OBSTACLES:
            pts = [self._to_robot(pose, *p) for p in self._outline(ob)]
            dist = min(math.hypot(px - self.cfg.x, py - self.cfg.y) for px, py in pts)
            uvs = []
            for px, py in pts:
                for z in (0.0, ob.get("height", 0.05)):
                    uv = self.cam.project(px, py, z)
                    if uv:
                        uvs.append(uv)
            if len(uvs) < len(pts):          # partly behind the camera
                continue
            us, vs = [p[0] for p in uvs], [p[1] for p in uvs]
            x1, x2, y1, y2 = min(us), max(us), min(vs), max(vs)
            if x2 < 0 or x1 > W or y2 < 0 or y1 > H:
                continue
            cx1, cx2, cy1, cy2 = max(0, x1), min(W - 1, x2), max(0, y1), min(H - 1, y2)
            visible = (cx2 - cx1) * (cy2 - cy1) / max(1e-6, (x2 - x1) * (y2 - y1))
            if visible < 0.35 or cx2 - cx1 < 4 or cy2 - cy1 < 4:
                continue
            boxes.append({"label": ob.get("coco", ob["label"].lower()), "box": (cx1, cy1, cx2, cy2),
                          "dist": dist, "color": ob.get("color", (90, 90, 160)), "id": ob["label"]})
        # occlusion: drop objects whose columns are mostly covered by nearer objects
        boxes.sort(key=lambda b: b["dist"])
        covered = np.zeros(W, bool)
        out = []
        for b in boxes:
            x1, _, x2, _ = (int(v) for v in b["box"])
            cols = covered[x1:x2 + 1]
            if cols.size and cols.mean() > 0.7:
                continue
            covered[x1:x2 + 1] = True
            out.append(b)
        return out

    def _render(self, boxes):
        W, H = self.cfg.width, self.cfg.height
        img = np.empty((H, W, 3), np.uint8)
        horizon = int(np.clip(self.cam.cy - self.cam.fy * math.tan(math.radians(self.cfg.pitch_deg)), 0, H))
        img[:horizon] = SKY
        img[horizon:] = DESK
        for b in sorted(boxes, key=lambda b: -b["dist"]):  # far first, near objects paint over
            x1, y1, x2, y2 = (int(v) for v in b["box"])
            img[y1:y2, x1:x2] = b["color"]
        return img

    def read(self):
        wait = self._next - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next = max(self._next + self._period, time.monotonic())
        pose = self._pose()
        t = time.monotonic()
        boxes = self._boxes(pose)
        return t, self._render(boxes), boxes

    def close(self):
        pass


def open_camera(kind, cfg: CameraConfig, sim_hw=None):
    """kind: 'pi' | 'webcam' | 'sim' | a webcam index ('0') | a video file path."""
    if kind == "pi":
        return PiCamera(cfg)
    if kind == "sim":
        if sim_hw is None:
            raise RuntimeError("The simulated camera needs the simulated robot (--sim)")
        return SimCamera(cfg, sim_hw)
    if kind == "webcam":
        return OpenCVCamera(cfg, 0)
    if str(kind).isdigit():
        return OpenCVCamera(cfg, int(kind))
    return OpenCVCamera(cfg, str(kind))


# ---------------- latest-frame grabber ----------------

class FrameGrabber:
    """Reads the source continuously in its own thread; keeps only the newest frame."""

    def __init__(self, source):
        self.source = source
        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._seq = 0
        self._running = False
        self.error = None
        self.fps = 0.0
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        times = []
        while self._running:
            try:
                t, img, truth = self.source.read()
            except Exception as exc:
                self.error = str(exc)
                time.sleep(0.5)
                continue
            self.error = None
            times.append(t)
            if len(times) > 30:
                times.pop(0)
            if len(times) > 1:
                self.fps = (len(times) - 1) / max(1e-6, times[-1] - times[0])
            with self._cond:
                self._seq += 1
                self._frame = Frame(self._seq, t, img, truth)
                self._cond.notify_all()

    def latest(self):
        with self._cond:
            return self._frame

    def wait_newer(self, seq, timeout=1.0):
        """Block until a frame newer than `seq` exists; return the newest one (or None on timeout)."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > seq or not self._running, timeout)
            f = self._frame
            return f if f is not None and f.seq > seq else None

    def stop(self):
        self._running = False
        with self._cond:
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
        self.source.close()
