"""
Vision pipeline: newest camera frame -> detector + tracker -> published result.

Threads
    camera  (FrameGrabber)    reads the camera continuously and keeps only the newest frame
    vision  (VisionPipeline)  waits for a frame newer than the last one it processed, runs the
                              detector on it, publishes the result. Never queues: if inference is slower
                              than the camera, the frames in between are skipped.

Consumers (the fusion mapper, the web server) read `latest()` / `results_since()`. They never block
the vision thread. The annotated JPEG for the dashboard is only drawn and encoded when someone
requests it, in the HTTP thread, so the detection loop doesn't pay for it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from ..config import CameraConfig, VisionConfig


@dataclass
class VisionResult:
    seq: int                 # camera frame number
    t_capture: float         # monotonic time the frame was captured
    t_done: float            # monotonic time detection finished
    detections: list         # [Detection]
    infer_ms: float
    image: object = field(repr=False, default=None)

    @property
    def latency_ms(self):
        return (self.t_done - self.t_capture) * 1000


# BGR colours for boxes, fixed order (validated categorical palette, see docs/vision.md)
BOX_COLORS = [(214, 120, 42), (52, 104, 235), (122, 175, 27), (0, 161, 237), (164, 123, 232), (0, 131, 0), (214, 80, 98), (72, 73, 227)]


def annotate(image, detections, color_for, quality=70):
    """Draw boxes + 'label score #track' on a copy of the frame and JPEG-encode it (bytes or None)."""
    import cv2

    img = image.copy()
    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        color = color_for(d.label)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{d.label} {d.score:.2f}" + (f" #{d.track_id}" if d.track_id is not None else "")
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        ty = max(th + 4, y1)
        cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 4, ty), color, -1)
        cv2.putText(img, text, (x1 + 2, ty - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else None


class VisionPipeline:
    def __init__(self, grabber, detector, ccfg: CameraConfig, vcfg: VisionConfig):
        self.grabber = grabber
        self.detector = detector
        self.ccfg = ccfg
        self.vcfg = vcfg
        self._lock = threading.Lock()
        self._results = deque(maxlen=32)
        self._running = False
        self._thread = None
        self.error = None
        self._infer = deque(maxlen=30)
        self._lat = deque(maxlen=30)
        self._done = deque(maxlen=30)
        self._jpeg = (None, -1)          # (bytes, seq) cache
        self._jpeg_lock = threading.Lock()
        self.label_colors = {}
        self.started = time.monotonic()

    # -- lifecycle --

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="vision", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        self.grabber.stop()
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self):
        last = 0
        warmed = False
        while self._running:
            frame = self.grabber.wait_newer(last, timeout=1.0)
            if frame is None:
                continue
            last = frame.seq
            try:
                if not warmed:
                    self.detector.warmup(frame.image)
                    warmed = True
                    continue  # that frame is stale now; take a fresh one
                t0 = time.monotonic()
                dets = self.detector(frame)
                t1 = time.monotonic()
            except Exception as exc:  # vision must never take the robot down
                self.error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5)
                continue
            self.error = None
            res = VisionResult(frame.seq, frame.t, t1, dets, (t1 - t0) * 1000, frame.image)
            with self._lock:
                self._results.append(res)
                self._infer.append(res.infer_ms)
                self._lat.append(res.latency_ms)
                self._done.append(t1)

    # -- consumers --

    def latest(self):
        with self._lock:
            return self._results[-1] if self._results else None

    def results_since(self, seq):
        with self._lock:
            return [r for r in self._results if r.seq > seq]

    def color_for(self, label):
        if label not in self.label_colors:
            self.label_colors[label] = len(self.label_colors) % len(BOX_COLORS)
        return BOX_COLORS[self.label_colors[label]]

    def jpeg(self):
        """Newest frame with boxes drawn, as JPEG bytes (cached per frame)."""
        res = self.latest()
        if res is None:
            frame = self.grabber.latest()
            if frame is None:
                return None
            res = VisionResult(frame.seq, frame.t, frame.t, [], 0.0, frame.image)
        with self._jpeg_lock:
            data, seq = self._jpeg
            if seq == res.seq and data is not None:
                return data
            data = annotate(res.image, res.detections, self.color_for, self.vcfg.jpeg_quality)
            self._jpeg = (data, res.seq)
            return data

    def status(self):
        with self._lock:
            res = self._results[-1] if self._results else None
            infer = sum(self._infer) / len(self._infer) if self._infer else None
            lat = sum(self._lat) / len(self._lat) if self._lat else None
            done = list(self._done)
        fps = (len(done) - 1) / (done[-1] - done[0]) if len(done) > 1 and done[-1] > done[0] else 0.0
        now = time.monotonic()
        return {
            "enabled": True,
            "camera": getattr(self.grabber.source, "name", "?"),
            "camera_model": getattr(self.grabber.source, "model", "?"),
            "detector": getattr(self.detector, "name", "?"),
            "camera_fps": round(self.grabber.fps, 1),
            "detect_fps": round(fps, 1),
            "infer_ms": None if infer is None else round(infer, 1),
            "latency_ms": None if lat is None else round(lat, 1),
            "frame_age_ms": None if res is None else round((now - res.t_capture) * 1000),
            "size": [self.ccfg.width, self.ccfg.height],
            "imgsz": self.vcfg.imgsz,
            "detections": [] if res is None else [d.as_dict() for d in res.detections],
            "error": self.error or self.grabber.error,
        }
