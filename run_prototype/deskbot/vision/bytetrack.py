"""
ByteTrack in numpy (20 Nov 2026): the tracker the robot used through Ultralytics, without Ultralytics.

A port of ultralytics/trackers/byte_tracker.py (8.4.213, AGPL-3.0, itself based on ByteTrack by Zhang et al., MIT),
for axis-aligned boxes and without global motion compensation (Ultralytics' ByteTrack has none either). The
logic, constants and order of operations are the same, so the track IDs come out the same (checked frame by frame in
tests/test_ncnn_detector.py against Ultralytics' own tracker).

Per frame:
  1. split detections: high (score >= track_high_thresh) and low (track_low_thresh < score < high)
  2. predict every tracked + lost track with a constant-velocity Kalman filter on (cx, cy, aspect, h)
  3. match tracks to high boxes: cost = 1 - IoU * score (fuse_score), gated at match_thresh
  4. match the still-unmatched *tracked* tracks to the low boxes: cost = 1 - IoU, gated at 0.5;
     tracks still unmatched become lost
  5. match unconfirmed tracks (seen once) to the leftover high boxes (gate 0.7); unmatched ones are removed
  6. leftover high boxes scoring >= new_track_thresh start a track (confirmed when it is seen again,
     or straight away on the first frame)
  7. lost tracks older than track_buffer frames are removed; duplicate tracked/lost pairs (IoU > 0.85) keep the older
Linear assignment: a numpy Hungarian solver (lap_compat.py) with lap's cost_limit padding (lap_compat.lapjv), which picks the same
matches as the `lap` package Ultralytics uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .lap_compat import lapjv

TRACKED, LOST, REMOVED = 1, 2, 3
YAML = Path(__file__).with_name("bytetrack.yaml")


@dataclass
class TrackerArgs:
    track_high_thresh: float = 0.35
    track_low_thresh: float = 0.1
    new_track_thresh: float = 0.45
    track_buffer: int = 45
    match_thresh: float = 0.8
    fuse_score: bool = True


def load_args(path=YAML):
    """TrackerArgs from bytetrack.yaml (flat `key: value` lines; no PyYAML needed)."""
    args = TrackerArgs()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return args
    for key, value in re.findall(r"^(\w+):\s*([^#\s]+)", text, re.M):
        if key in TrackerArgs.__dataclass_fields__:
            cur = getattr(args, key)
            setattr(args, key, value.lower() == "true" if isinstance(cur, bool) else type(cur)(value))
    return args


# ---------------- Kalman filter: state (cx, cy, a, h, vcx, vcy, va, vh), measurement (cx, cy, a, h) ----------------

class KalmanXYAH:
    W_POS, W_VEL = 1.0 / 20, 1.0 / 160

    def __init__(self):
        self.F = np.eye(8)
        self.F[:4, 4:] = np.eye(4)        # dt = 1 frame

    def initiate(self, z):
        z = np.asarray(z, dtype=np.float64)
        h = z[3]
        std = [2 * self.W_POS * h, 2 * self.W_POS * h, 0.01, 2 * self.W_POS * h,
               10 * self.W_VEL * h, 10 * self.W_VEL * h, 1e-5, 10 * self.W_VEL * h]
        return np.r_[z, np.zeros(4)], np.diag(np.square(std))

    def multi_predict(self, mean, cov):
        h = mean[:, 3]
        one = np.ones_like(h)
        sqr = np.square(np.r_[[self.W_POS * h, self.W_POS * h, 0.01 * one, self.W_POS * h,
                               self.W_VEL * h, self.W_VEL * h, 1e-5 * one, self.W_VEL * h]]).T
        q = np.zeros((len(h), 8, 8))
        q[:, range(8), range(8)] = sqr
        mean = mean @ self.F.T
        cov = np.dot(np.dot(self.F, cov).transpose((1, 0, 2)), self.F.T) + q
        return mean, cov

    def update(self, mean, cov, z):
        h = mean[3]
        r = np.diag(np.square([self.W_POS * h, self.W_POS * h, 0.1, self.W_POS * h]))
        s = cov[:4, :4] + r
        gain = np.linalg.solve(s, cov[:, :4].T).T
        mean = mean + (np.asarray(z) - mean[:4]) @ gain.T
        cov = cov - np.linalg.multi_dot((gain, s, gain.T))
        return mean, cov


def _xyah(tlwh):
    r = np.asarray(tlwh, dtype=np.float64).copy()
    r[:2] += r[2:] / 2
    r[2] /= r[3]
    return r


class Track:
    def __init__(self, xyxy, score, cls, idx):
        x1, y1, x2, y2 = xyxy
        self._tlwh = np.array([x1, y1, x2 - x1, y2 - y1], dtype=np.float32)
        self.score, self.cls, self.idx = float(score), int(cls), int(idx)
        self.mean = self.cov = None
        self.state, self.is_activated = 0, False
        self.track_id = self.start_frame = self.frame_id = 0

    @property
    def tlwh(self):
        if self.mean is None:
            return self._tlwh.copy()
        r = self.mean[:4].copy()
        r[2] *= r[3]
        r[:2] -= r[2:] / 2
        return r

    @property
    def xyxy(self):
        r = self.tlwh
        r[2:] += r[:2]
        return r

    def activate(self, kf, frame_id, new_id):
        self.track_id = new_id
        self.mean, self.cov = kf.initiate(_xyah(self._tlwh))
        self.state = TRACKED
        self.is_activated = frame_id == 1
        self.frame_id = self.start_frame = frame_id

    def update(self, kf, det, frame_id):
        """Ultralytics' update() and re_activate() (re-found lost track, same ID) do the same to the state."""
        self.mean, self.cov = kf.update(self.mean, self.cov, _xyah(det.tlwh))
        self.state, self.is_activated, self.frame_id = TRACKED, True, frame_id
        self.score, self.cls, self.idx = det.score, det.cls, det.idx


def iou_matrix(a, b):
    """IoU of every box in a (N,4 xyxy) against every box in b (M,4)."""
    a, b = np.asarray(a, np.float32).reshape(-1, 4), np.asarray(b, np.float32).reshape(-1, 4)
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)), np.float32)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(2)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (area_a[:, None] + area_b[None] - inter + 1e-7)


def _iou_dist(tracks, dets):
    return 1 - iou_matrix([t.xyxy for t in tracks], [d.xyxy for d in dets])


def _assign(cost, thresh):
    """(matches, unmatched rows, unmatched cols) with lap's cost_limit semantics."""
    if cost.size == 0:
        return [], list(range(cost.shape[0])), list(range(cost.shape[1]))
    x, y = lapjv(cost, extend_cost=True, cost_limit=thresh, return_cost=False)
    return [(i, j) for i, j in enumerate(x) if j >= 0], list(np.where(x < 0)[0]), list(np.where(y < 0)[0])


def _joint(a, b):
    ids = {t.track_id for t in a}
    return a + [t for t in b if t.track_id not in ids]


def _sub(a, b):
    ids = {t.track_id for t in b}
    return [t for t in a if t.track_id not in ids]


class ByteTracker:
    def __init__(self, args: TrackerArgs | None = None):
        self.args = args or load_args()
        self.kf = KalmanXYAH()
        self.reset()

    def reset(self):
        self.tracked, self.lost, self.removed = [], [], []
        self.frame_id = 0
        self._next_id = 1

    def _new_id(self):
        self._next_id += 1
        return self._next_id - 1

    def _dists(self, tracks, dets):
        d = _iou_dist(tracks, dets)
        if self.args.fuse_score and d.size:
            d = 1 - (1 - d) * np.array([x.score for x in dets])[None]
        return d

    def update(self, boxes, scores, classes):
        """boxes (N,4 xyxy), scores (N,), classes (N,) for one frame.
        Returns (M,7) float32 rows [x1, y1, x2, y2, track_id, score, cls, idx], idx = index into the input."""
        a = self.args
        self.frame_id += 1
        boxes = np.asarray(boxes, np.float32).reshape(-1, 4)
        scores, classes = np.asarray(scores, np.float32).reshape(-1), np.asarray(classes).reshape(-1)
        wh = boxes[:, 2:] - boxes[:, :2]
        valid = (wh[:, 0] > 0) & (wh[:, 1] > 0)
        high = valid & (scores >= a.track_high_thresh)
        low = valid & (scores > a.track_low_thresh) & (scores < a.track_high_thresh)
        dets = [Track(boxes[i], scores[i], classes[i], i) for i in np.flatnonzero(high)]
        dets_low = [Track(boxes[i], scores[i], classes[i], i) for i in np.flatnonzero(low)]
        activated, refind, lost, removed = [], [], [], []

        unconfirmed = [t for t in self.tracked if not t.is_activated]
        pool = _joint([t for t in self.tracked if t.is_activated], self.lost)
        if pool:                                        # 2. Kalman predict (lost tracks don't grow)
            mean = np.asarray([t.mean for t in pool])
            cov = np.asarray([t.cov for t in pool])
            for i, t in enumerate(pool):
                if t.state != TRACKED:
                    mean[i][7] = 0
            mean, cov = self.kf.multi_predict(mean, cov)
            for t, m, c in zip(pool, mean, cov):
                t.mean, t.cov = m, c

        def apply(track, det):
            if track.state == TRACKED:
                track.update(self.kf, det, self.frame_id)
                activated.append(track)
            else:
                track.update(self.kf, det, self.frame_id)
                refind.append(track)

        matches, u_track, u_det = _assign(self._dists(pool, dets), a.match_thresh)       # 3. high boxes
        for i, j in matches:
            apply(pool[i], dets[j])

        rest = [pool[i] for i in u_track if pool[i].state == TRACKED]                  # 4. low boxes
        if rest and dets_low:
            matches, u_rest, _ = _assign(_iou_dist(rest, dets_low), 0.5)
            for i, j in matches:
                apply(rest[i], dets_low[j])
        else:
            u_rest = list(range(len(rest)))
        for i in u_rest:
            rest[i].state = LOST
            lost.append(rest[i])

        dets = [dets[i] for i in u_det]                                                # 5. unconfirmed
        if unconfirmed:
            matches, u_unconf, u_det = _assign(self._dists(unconfirmed, dets), 0.7)
            for i, j in matches:
                unconfirmed[i].update(self.kf, dets[j], self.frame_id)
                activated.append(unconfirmed[i])
            for i in u_unconf:
                unconfirmed[i].state = REMOVED
                removed.append(unconfirmed[i])
        else:
            u_det = list(range(len(dets)))

        for j in u_det:                                                                # 6. new tracks
            if dets[j].score >= a.new_track_thresh:
                dets[j].activate(self.kf, self.frame_id, self._new_id())
                activated.append(dets[j])

        for t in self.lost:                                                            # 7. expire + merge
            if self.frame_id - t.frame_id > a.track_buffer:
                t.state = REMOVED
                removed.append(t)
        self.tracked = [t for t in self.tracked if t.state == TRACKED]
        self.tracked = _joint(_joint(self.tracked, activated), refind)
        self.lost = _sub(self.lost, self.tracked) + lost
        self.lost = _sub(self.lost, self.removed)
        self.tracked, self.lost = self._dedupe(self.tracked, self.lost)
        self.removed = (self.removed + removed)[-1000:]
        out = [[*t.xyxy.tolist(), t.track_id, t.score, t.cls, t.idx] for t in self.tracked if t.is_activated]
        return np.asarray(out, dtype=np.float32).reshape(-1, 8)

    @staticmethod
    def _dedupe(a, b, thresh=0.15):
        d = _iou_dist(a, b)
        drop_a, drop_b = set(), set()
        for p, q in zip(*np.where(d < thresh)):
            if a[p].frame_id - a[p].start_frame > b[q].frame_id - b[q].start_frame:
                drop_b.add(q)
            else:
                drop_a.add(p)
        return [t for i, t in enumerate(a) if i not in drop_a], [t for i, t in enumerate(b) if i not in drop_b]

    def has_unconfirmed(self):
        return any(not t.is_activated for t in self.tracked)
