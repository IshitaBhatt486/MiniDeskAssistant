"""
YOLO26n on NCNN directly, with ByteTrack in numpy (20 Nov 2026). No PyTorch, no Ultralytics.

Needs only ncnn, numpy and OpenCV (resize); track matching is numpy too. It does what Ultralytics did around the same
NCNN network, step by step (details and measurements: docs/ncnn-detector.md):

  1. letterbox   resize the BGR frame to fit imgsz x imgsz keeping its shape (cv2.INTER_LINEAR), pad the rest
                 with grey 114, image centred; BGR -> RGB, HWC -> CHW, 0..1 floats
  2. network     ncnn.Net from models/<name>_ncnn_model/model.ncnn.param + .bin, input "in0", output "out0":
                 (84, N) = cx, cy, w, h (input pixels) + 80 class scores per anchor (N = 2100 at 320).
                 The NCNN export has no NMS-free head (Ultralytics turns YOLO26's end2end branch off for NCNN),
                 so step 3 is needed.
  3. NMS         best class per anchor, keep score > conf, optional class filter, class-aware NMS at IoU 0.5
                 (Ultralytics' predict default), at most 300 boxes
  4. unletterbox remove the padding, divide by the scale, clip to the image
  5. ByteTrack   bytetrack.py with deskbot/vision/bytetrack.yaml; output boxes are the tracks' Kalman boxes,
                 like Ultralytics' model.track(persist=True)

The network runner is swappable (`runner=`), which is how the tests compare this file with Ultralytics on a laptop
where Windows blocks the NCNN DLL.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np

from ..config import VisionConfig
from .bytetrack import ByteTracker
from .coco import NAMES
from .detector import Detection

PAD_VALUE = 114
NMS_IOU = 0.5        # Ultralytics PREDICT_IOU
MAX_DET = 300
MAX_NMS = 30000
MAX_WH = 7680        # class offset for class-aware NMS


def read_metadata(folder):
    """imgsz and class names from the export's metadata.yaml (flat YAML, parsed without PyYAML)."""
    meta = {"imgsz": None, "names": None}
    try:
        text = (Path(folder) / "metadata.yaml").read_text(encoding="utf-8")
    except OSError:
        return meta
    m = re.search(r"^imgsz:\s*\n\s*-\s*(\d+)|^imgsz:\s*\[?\s*(\d+)", text, re.M)
    if m:
        meta["imgsz"] = int(m.group(1) or m.group(2))
    block = re.search(r"^names:\s*\n((?:[ \t]+\d+:.*\n?)+)", text, re.M)
    if block:
        names = dict(re.findall(r"^\s+(\d+):\s*['\"]?(.*?)['\"]?\s*$", block.group(1), re.M))
        meta["names"] = [names[str(i)] for i in range(len(names))] if names else None
    return meta


def letterbox(image, size):
    """(CHW float32 RGB 0..1 of size x size, scale, (pad_x, pad_y)). Same arithmetic as Ultralytics' LetterBox."""
    import cv2

    h, w = image.shape[:2]
    r = min(size / h, size / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    dw, dh = (size - nw) / 2, (size - nh) / 2
    if (w, h) != (nw, nh):
        image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    image = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(PAD_VALUE,) * 3)
    chw = np.ascontiguousarray(image[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32) / 255.0
    return chw, r, (left, top)


def nms(boxes, scores, iou):
    """Indices kept by greedy NMS, highest score first (same result as torchvision.ops.nms)."""
    order = scores.argsort()[::-1]
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = w * h
        order = rest[inter / (areas[i] + areas[rest] - inter) <= iou]
    return np.asarray(keep, dtype=int)


def decode(out, conf, classes=None, iou=NMS_IOU, max_det=MAX_DET):
    """Raw output (84, N) or (1, 84, N) -> (boxes xyxy (K,4), scores (K,), classes (K,)) in input pixels.
    Also accepts an NMS-free (end2end) output (K, 6) = x1, y1, x2, y2, score, class."""
    out = np.asarray(out, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    if out.ndim == 2 and out.shape[1] == 6 and out.shape[0] != 6:       # end2end: already final boxes
        keep = out[:, 4] > conf
        if classes is not None:
            keep &= np.isin(out[:, 5].astype(int), classes)
        out = out[keep][:max_det]
        return out[:, :4], out[:, 4], out[:, 5].astype(int)
    pred = out.T                                                        # (N, 4 + nc)
    cls_scores = pred[:, 4:]
    best = cls_scores.argmax(1)
    score = cls_scores[np.arange(len(best)), best]
    keep = score > conf
    if classes is not None:
        keep &= np.isin(best, classes)
    xywh, score, best = pred[keep, :4], score[keep], best[keep]
    if not len(score):
        return np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, int)
    if len(score) > MAX_NMS:
        top = score.argsort()[::-1][:MAX_NMS]
        xywh, score, best = xywh[top], score[top], best[top]
    boxes = np.concatenate([xywh[:, :2] - xywh[:, 2:] / 2, xywh[:, :2] + xywh[:, 2:] / 2], 1)
    keep = nms(boxes + best[:, None] * MAX_WH, score, iou)[:max_det]
    return boxes[keep], score[keep], best[keep]


class NcnnRunner:
    """Runs the exported network. One extractor per call (NCNN extractors are single-use)."""

    def __init__(self, folder, threads):
        import ncnn

        folder = Path(folder)
        param = folder if folder.is_file() else next(folder.glob("*.param"))
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = threads
        self.net.load_param(str(param))
        self.net.load_model(str(param.with_suffix(".bin")))
        self.input = self.net.input_names()[0]
        self.output = sorted(self.net.output_names())[0]
        self._mat = ncnn.Mat

    def __call__(self, chw):
        with self.net.create_extractor() as ex:
            ex.input(self.input, self._mat(chw))
            return np.array(ex.extract(self.output)[1])


class NcnnDetector:
    """Same interface as detector.YoloDetector: __call__(frame) -> [Detection], predict(image), warmup, reset."""

    def __init__(self, vcfg: VisionConfig, model_path, runner=None):
        # NCNN uses OpenMP; cap the threads BEFORE ncnn is imported so the 20 ms safety loop, the mapper and the web
        # server keep a core on the Pi 4.
        os.environ.setdefault("OMP_NUM_THREADS", str(vcfg.threads))
        try:
            import cv2
            cv2.setNumThreads(1)  # letterbox resize is tiny; don't spin up a second thread pool
        except ImportError:
            pass
        self.vcfg = vcfg
        self.model_path = str(model_path)
        meta = read_metadata(model_path) if Path(model_path).is_dir() else {"imgsz": None, "names": None}
        self.imgsz = meta["imgsz"] or vcfg.imgsz
        self.names = meta["names"] or list(NAMES)
        self.runner = runner or NcnnRunner(model_path, vcfg.threads)
        self.threads = vcfg.threads
        self.tracker = ByteTracker()
        self.name = f"{Path(self.model_path).name} (ncnn)"

    def _detect(self, image, conf):
        chw, r, (px, py) = letterbox(image, self.imgsz)
        boxes, scores, cls = decode(self.runner(chw), conf, self.vcfg.classes)
        if len(boxes):
            boxes = (boxes - np.array([px, py, px, py], np.float32)) / r
            h, w = image.shape[:2]
            boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
            boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
        return boxes, scores, cls

    def _label(self, c):
        c = int(c)
        return self.names[c] if 0 <= c < len(self.names) else str(c)

    def __call__(self, frame):
        boxes, scores, cls = self._detect(frame.image, self.vcfg.conf)
        tracks = self.tracker.update(boxes, scores, cls)
        if not len(tracks):
            if self.tracker.has_unconfirmed():          # Ultralytics hides new tracks until they're confirmed
                return []
            return [Detection(self._label(c), float(s), tuple(map(float, b)), None) for b, s, c in zip(boxes, scores, cls)]
        h, w = frame.image.shape[:2]                    # Kalman boxes can run past the edge: clip like Ultralytics
        tracks[:, [0, 2]] = tracks[:, [0, 2]].clip(0, w)
        tracks[:, [1, 3]] = tracks[:, [1, 3]].clip(0, h)
        return [Detection(self._label(t[6]), float(t[5]), tuple(map(float, t[:4])), int(t[4])) for t in tracks]

    def predict(self, image, conf=None):
        """Plain detection, no tracker (benchmark / mAP). Returns [Detection] with track_id None."""
        boxes, scores, cls = self._detect(image, self.vcfg.conf if conf is None else conf)
        return [Detection(self._label(c), float(s), tuple(map(float, b)), None) for b, s, c in zip(boxes, scores, cls)]

    def warmup(self, image):
        """The first NCNN call allocates memory; do it before timing anything."""
        self._detect(image, self.vcfg.conf)
        self._detect(image, self.vcfg.conf)
        self.reset()

    def reset(self):
        """Forget all tracks (e.g. after the map was cleared)."""
        self.tracker.reset()
