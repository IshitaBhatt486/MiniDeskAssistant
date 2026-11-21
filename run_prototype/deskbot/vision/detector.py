"""
Object detection + tracking.

make_detector picks the detector for a model path:
  NCNN export folder  -> ncnn_detector.NcnnDetector (20 Nov 2026): ncnn + numpy + our own ByteTrack,
                         no PyTorch / Ultralytics. What the robot runs.
  .pt weights         -> YoloDetector below, through Ultralytics (only where Ultralytics is installed,
                         e.g. a Windows laptop where Smart App Control blocks the NCNN DLL).
YoloDetector  the original detector (unchanged): YOLO26n through Ultralytics with ByteTrack (persist=True keeps
              the tracker state between calls, so track IDs stay stable from frame to frame).
              Runs fully on the device: no cloud, no API keys, no per-call cost.
SimDetector   turns SimCamera's ground-truth boxes into detections (with noise and missed
              detections), so mapping can be tested without a camera or a model.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path

from ..config import VisionConfig

TRACKER_YAML = Path(__file__).with_name("bytetrack.yaml")


@dataclass
class Detection:
    label: str
    score: float
    box: tuple            # x1, y1, x2, y2 in pixels
    track_id: int | None  # ByteTrack ID (None if the tracker has not confirmed it yet)

    def as_dict(self):
        return {"label": self.label, "score": round(self.score, 3),
                "box": [round(v, 1) for v in self.box], "track_id": self.track_id}


def make_detector(vcfg: VisionConfig, model_path):
    """NcnnDetector for an NCNN export, YoloDetector (Ultralytics) for .pt weights. Both have the same interface."""
    p = Path(model_path)
    if p.is_dir() or p.suffix == ".param":
        from .ncnn_detector import NcnnDetector

        return NcnnDetector(vcfg, p)
    return YoloDetector(vcfg, p)


class YoloDetector:
    name = "yolo26n-ncnn"

    def __init__(self, vcfg: VisionConfig, model_path):
        # NCNN uses OpenMP; cap the threads BEFORE ncnn is imported so the 20 ms safety loop,
        # the mapper and the web server keep a core on the Pi 4.
        os.environ.setdefault("OMP_NUM_THREADS", str(vcfg.threads))
        try:
            import cv2
            cv2.setNumThreads(1)  # letterbox resize is tiny; don't spin up a second thread pool
        except ImportError:
            pass
        from ultralytics import YOLO

        from .lap_compat import install as install_lap

        self.assignment = install_lap()  # 'lap' normally; 'scipy' if the lap DLL is blocked
        self.vcfg = vcfg
        self.model_path = str(model_path)
        self.model = YOLO(self.model_path, task="detect")
        self.names = None
        self.name = f"{Path(self.model_path).name}"

    def warmup(self, image):
        """First NCNN call allocates memory and builds the tracker; do it before timing anything."""
        from .camera import Frame

        self(Frame(0, 0.0, image))   # creates the predictor + loads the NCNN net
        self._set_threads()
        self(Frame(0, 0.0, image))   # second call runs with the final thread count
        self.reset()                 # don't keep tracks from the warm-up frames

    def _set_threads(self):
        """Ultralytics leaves ncnn's opt.num_threads at its default (all big cores); cap it."""
        backend = getattr(getattr(self.model, "predictor", None), "model", None)
        net = getattr(getattr(backend, "backend", None), "net", None) or getattr(backend, "net", None)
        if net is not None and hasattr(net, "opt"):
            net.opt.num_threads = self.vcfg.threads
            self.threads = self.vcfg.threads

    def __call__(self, frame):
        r = self.model.track(
            frame.image,
            persist=True,
            tracker=str(TRACKER_YAML),
            imgsz=self.vcfg.imgsz,
            conf=self.vcfg.conf,
            classes=self.vcfg.classes,
            verbose=False,
        )[0]
        names = r.names
        b = r.boxes
        if b is None or len(b) == 0:
            return []
        xyxy = b.xyxy.tolist()
        conf = b.conf.tolist()
        cls = b.cls.tolist()
        ids = b.id.tolist() if b.id is not None else [None] * len(xyxy)
        return [Detection(names[int(c)], float(s), tuple(box), None if i is None else int(i))
                for box, s, c, i in zip(xyxy, conf, cls, ids)]

    def predict(self, image, conf=None):
        """Plain detection, no tracker (benchmark / mAP). Returns [Detection] with track_id None."""
        r = self.model.predict(image, imgsz=self.vcfg.imgsz, conf=self.vcfg.conf if conf is None else conf,
                               classes=self.vcfg.classes, verbose=False)[0]
        b = r.boxes
        if b is None or len(b) == 0:
            return []
        return [Detection(r.names[int(c)], float(s), tuple(box), None)
                for box, s, c in zip(b.xyxy.tolist(), b.conf.tolist(), b.cls.tolist())]

    def reset(self):
        """Forget all tracks (e.g. after the map was cleared)."""
        predictor = getattr(self.model, "predictor", None)
        for tr in getattr(predictor, "trackers", None) or []:
            tr.reset()


class SimDetector:
    name = "simulated detector"

    def __init__(self, miss_rate=0.05, pixel_noise=1.5, seed=None):
        self.miss_rate = miss_rate
        self.noise = pixel_noise
        self.rng = random.Random(seed)
        self._ids = {}

    def warmup(self, image):
        pass

    def __call__(self, frame):
        out = []
        for t in frame.truth:
            if self.rng.random() < self.miss_rate:
                continue
            x1, y1, x2, y2 = (v + self.rng.gauss(0, self.noise) for v in t["box"])
            tid = self._ids.setdefault(t["id"], len(self._ids) + 1)
            out.append(Detection(t["label"], self.rng.uniform(0.6, 0.92), (x1, y1, x2, y2), tid))
        return out

    def reset(self):
        self._ids.clear()
