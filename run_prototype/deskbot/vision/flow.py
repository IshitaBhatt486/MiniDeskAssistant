"""
Move boxes between detections with sparse Lucas-Kanade optical flow ("detect every N frames").

On a detection frame, up to `n` corner points (Shi-Tomasi) are picked inside each box. On the frames
in between, those points are tracked with pyramidal Lucas-Kanade; each box moves by the MEDIAN point
displacement and scales by the MEDIAN change in point spread (robust to a few points sliding onto the
background). That costs ~1-2 ms at 320x240 on a Pi 4 core, against tens to hundreds of ms for a YOLO
inference. Track IDs and labels are kept; the score decays slightly per propagated frame. A box whose
points can't be followed (blur, a textureless surface) is HELD where it was until the next detection
(at most detect_every - 1 frames away), rather than disappearing and reappearing.

Same idea as MedianFlow and as "detect + track in between" pipelines on embedded boards
(see docs/runtime.md for the references).
"""

from __future__ import annotations

import numpy as np

from .detector import Detection

LK_PARAMS = None


def _lk_params(cv2):
    global LK_PARAMS
    if LK_PARAMS is None:
        LK_PARAMS = dict(winSize=(15, 15), maxLevel=2,
                         criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))
    return LK_PARAMS


class FlowTracker:
    def __init__(self, n_points=12, decay=0.97, min_points=3):
        import cv2

        self.cv2 = cv2
        self.n = n_points
        self.decay = decay
        self.min_points = min_points
        self.prev = None
        self.tracks = []      # [(Detection, points (k, 1, 2) float32)]

    @staticmethod
    def gray(cv2, image):
        return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def _points(self, gray, box):
        cv2 = self.cv2
        h, w = gray.shape
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        roi = gray[y1:y2, x1:x2]
        pts = cv2.goodFeaturesToTrack(roi, maxCorners=self.n, qualityLevel=0.01, minDistance=3)
        if pts is None or len(pts) < self.min_points:
            # textureless box: use a regular 3x3 grid inside it instead
            gx, gy = np.meshgrid(np.linspace(0.25, 0.75, 3) * (x2 - x1), np.linspace(0.25, 0.75, 3) * (y2 - y1))
            pts = np.stack([gx.ravel(), gy.ravel()], 1).reshape(-1, 1, 2)
        pts = pts.astype(np.float32)
        pts[:, 0, 0] += x1
        pts[:, 0, 1] += y1
        return pts

    def reset(self, image, detections):
        """A fresh detection: re-seed the points from its boxes."""
        gray = self.gray(self.cv2, image)
        self.prev = gray
        self.tracks = []
        for d in detections:
            pts = self._points(gray, d.box)
            if pts is not None:
                self.tracks.append((d, pts))

    def update(self, image):
        """Propagate every box to this frame. Returns the moved detections."""
        if self.prev is None or not self.tracks:
            return []
        cv2 = self.cv2
        gray = self.gray(cv2, image)
        allp = np.concatenate([p for _, p in self.tracks])
        new, status, _ = cv2.calcOpticalFlowPyrLK(self.prev, gray, allp, None, **_lk_params(cv2))
        status = status.ravel().astype(bool)
        out, kept, i = [], [], 0
        h, w = gray.shape
        for det, pts in self.tracks:
            k = len(pts)
            ok = status[i:i + k]
            p0, p1 = pts[ok, 0], new[i:i + k][ok, 0]
            i += k
            if len(p1) < self.min_points:      # lost the points: hold the box until the next detection
                held = Detection(det.label, det.score * self.decay, det.box, det.track_id)
                out.append(held)
                kept.append((held, pts))
                continue
            d = np.median(p1 - p0, axis=0)
            s0 = np.linalg.norm(p0 - p0.mean(0), axis=1)
            s1 = np.linalg.norm(p1 - p1.mean(0), axis=1)
            good = s0 > 1.0
            scale = float(np.clip(np.median(s1[good] / s0[good]), 0.8, 1.25)) if good.sum() >= 2 else 1.0
            x1, y1, x2, y2 = det.box
            cx, cy = (x1 + x2) / 2 + d[0], (y1 + y2) / 2 + d[1]
            hw, hh = (x2 - x1) / 2 * scale, (y2 - y1) / 2 * scale
            box = (max(0.0, cx - hw), max(0.0, cy - hh), min(w - 1.0, cx + hw), min(h - 1.0, cy + hh))
            if box[2] - box[0] < 2 or box[3] - box[1] < 2:
                continue
            moved = Detection(det.label, det.score * self.decay, box, det.track_id)
            out.append(moved)
            kept.append((moved, p1.reshape(-1, 1, 2).astype(np.float32)))
        self.tracks = kept
        self.prev = gray
        return out
