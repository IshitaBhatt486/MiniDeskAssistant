"""deskbot/vision/ncnn_detector.py + bytetrack.py: YOLO26n on NCNN without PyTorch/Ultralytics (20 Nov 2026).

The pure-numpy parts are tested everywhere. TestMatchesUltralytics runs where Ultralytics and models/yolo26n.pt
exist (the laptop): the network is run through PyTorch with YOLO26's end2end head off (what the NCNN export
contains), and every frame's detections, track IDs and boxes must equal Ultralytics' own predict() / track().
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

import deskbot
from deskbot.config import VisionConfig
from deskbot.vision.bytetrack import ByteTracker, TrackerArgs, iou_matrix, load_args
from deskbot.vision.camera import Frame
from deskbot.vision.detector import make_detector
from deskbot.vision.ncnn_detector import NcnnDetector, decode, letterbox, nms, read_metadata

METADATA = """description: Ultralytics YOLO26n model
stride: 32
task: detect
batch: 1
imgsz:
- 320
- 320
names:
  0: person
  1: bicycle
  2: traffic light
args:
  half: false
"""


def raw_output(boxes, cls, scores, n=2100, nc=80):
    """A fake (84, n) network output with the given boxes (cx, cy, w, h) and class scores."""
    out = np.zeros((4 + nc, n), np.float32)
    out[:4] = np.array([[160, 160, 10, 10]], np.float32).T
    for k, (b, c, s) in enumerate(zip(boxes, cls, scores)):
        out[:4, k] = b
        out[4 + c, k] = s
    return out


class TestPieces(unittest.TestCase):
    def test_metadata_without_pyyaml(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "metadata.yaml").write_text(METADATA, encoding="utf-8")
            meta = read_metadata(d)
        self.assertEqual(meta["imgsz"], 320)
        self.assertEqual(meta["names"], ["person", "bicycle", "traffic light"])

    def test_tracker_yaml(self):
        a = load_args()
        self.assertEqual((a.track_high_thresh, a.track_low_thresh, a.new_track_thresh), (0.35, 0.1, 0.45))
        self.assertEqual((a.track_buffer, a.match_thresh, a.fuse_score), (45, 0.8, True))

    def test_letterbox_centres_and_pads(self):
        img = np.full((240, 320, 3), 200, np.uint8)
        chw, r, (px, py) = letterbox(img, 320)
        self.assertEqual(chw.shape, (3, 320, 320))
        self.assertEqual((r, px, py), (1.0, 0, 40))
        self.assertAlmostEqual(float(chw[0, 0, 0]), 114 / 255, places=5)    # grey padding
        self.assertAlmostEqual(float(chw[0, 160, 160]), 200 / 255, places=5)

    def test_decode_nms_class_aware(self):
        out = raw_output([(100, 100, 40, 40), (102, 101, 40, 40), (101, 100, 40, 40), (250, 250, 20, 20)],
                         [0, 0, 41, 41], [0.9, 0.8, 0.7, 0.05])
        boxes, scores, cls = decode(out, conf=0.1)
        # the two overlapping persons merge; the overlapping cup is a different class so it stays; 0.05 is dropped
        self.assertEqual(sorted(zip(cls.tolist(), np.round(scores.astype(float), 2).tolist())), [(0, 0.9), (41, 0.7)])
        np.testing.assert_allclose(boxes[list(cls).index(0)], [80, 80, 120, 120])
        boxes, scores, cls = decode(out, conf=0.1, classes=[41])
        self.assertEqual(cls.tolist(), [41])

    def test_decode_end2end_output(self):
        out = np.array([[10, 10, 50, 50, 0.9, 0], [0, 0, 5, 5, 0.05, 2]], np.float32)
        boxes, scores, cls = decode(out, conf=0.1)
        self.assertEqual(cls.tolist(), [0])

    def test_nms_matches_brute_force(self):
        rng = np.random.default_rng(1)
        xy = rng.uniform(0, 200, (60, 2))
        boxes = np.concatenate([xy, xy + rng.uniform(10, 60, (60, 2))], 1).astype(np.float32)
        scores = rng.uniform(0, 1, 60).astype(np.float32)
        keep = nms(boxes, scores, 0.5)
        ref, alive = [], list(np.argsort(-scores))
        while alive:
            i = alive.pop(0)
            ref.append(i)
            alive = [j for j in alive if iou_matrix(boxes[i], boxes[j])[0, 0] <= 0.5]
        self.assertEqual(keep.tolist(), ref)


class TestByteTracker(unittest.TestCase):
    def test_id_survives_a_short_gap_and_expires_after_the_buffer(self):
        t = ByteTracker(TrackerArgs(track_buffer=5))
        box = lambda x: [[x, 50, x + 40, 130]]
        for f in range(4):
            out = t.update(box(10 + 3 * f), [0.9], [0])
        self.assertEqual(out[:, 4].tolist(), [1])
        for _ in range(3):                                     # 3 empty frames: lost, not removed
            self.assertEqual(len(t.update(np.zeros((0, 4)), [], [])), 0)
        out = t.update(box(31), [0.9], [0])                    # back where the Kalman filter expects it
        self.assertEqual(out[:, 4].tolist(), [1])
        for _ in range(7):                                     # longer than track_buffer: removed
            t.update(np.zeros((0, 4)), [], [])
        out = t.update(box(31), [0.9], [0])
        self.assertEqual(len(out), 0)                          # a new track is unconfirmed on its first frame
        out = t.update(box(32), [0.9], [0])
        self.assertEqual(out[:, 4].tolist(), [2])

    def test_low_score_box_continues_but_cannot_start_a_track(self):
        t = ByteTracker()
        t.update([[0, 0, 40, 80]], [0.9], [0])
        out = t.update([[1, 0, 41, 80]], [0.2], [0])           # second stage keeps the track alive
        self.assertEqual(out[:, 4].tolist(), [1])
        t2 = ByteTracker()
        self.assertEqual(len(t2.update([[0, 0, 40, 80]], [0.3], [0])), 0)

    def test_detector_runs_with_a_fake_network(self):
        class Fake:
            def __call__(self, chw):
                self.shape = chw.shape
                return raw_output([(160, 160, 60, 100)], [0], [0.9])

        fake = Fake()
        det = NcnnDetector(VisionConfig(), Path("nowhere"), runner=fake)
        img = np.zeros((240, 320, 3), np.uint8)
        first = det(Frame(1, 0.0, img))
        self.assertEqual(fake.shape, (3, 320, 320))
        self.assertEqual([(d.label, d.track_id) for d in first], [("person", 1)])
        np.testing.assert_allclose(first[0].box, [130, 70, 190, 170], atol=0.01)   # padding (40 px) removed
        self.assertEqual(det.predict(img)[0].track_id, None)

    def test_make_detector_picks_by_path(self):
        from deskbot.vision import ncnn_detector

        with tempfile.TemporaryDirectory() as d:
            orig = ncnn_detector.NcnnRunner
            ncnn_detector.NcnnRunner = lambda *a: None
            try:
                self.assertIsInstance(make_detector(VisionConfig(), d), NcnnDetector)
            finally:
                ncnn_detector.NcnnRunner = orig


def _can_compare():
    return importlib.util.find_spec("ultralytics") is not None and (deskbot.MODELS_DIR / "yolo26n.pt").exists()


@unittest.skipUnless(_can_compare(), "needs Ultralytics + models/yolo26n.pt (the laptop)")
class TestMatchesUltralytics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        import ultralytics
        from ultralytics import YOLO

        cls.torch = torch
        cls.assets = Path(ultralytics.__file__).parent / "assets"
        cls.ref = YOLO(str(deskbot.MODELS_DIR / "yolo26n.pt"))
        cls.ref.model.model[-1].end2end = False                 # what the NCNN export contains
        net = cls.ref.model.eval()

        def run(chw):
            with torch.no_grad():
                y = net(torch.from_numpy(chw)[None])
            return (y[0] if isinstance(y, (list, tuple)) else y)[0].numpy()

        cls.det = NcnnDetector(VisionConfig(), deskbot.MODELS_DIR / "yolo26n_ncnn_model", runner=run)

    @property
    def label_index(self):
        return {name: i for i, name in self.ref.names.items()}

    def same(self, want, got, where):
        """Same (key, key, box) rows in any order; numbers within float32 rounding."""
        key = lambda row: (str(row[0]), str(row[1]) if not isinstance(row[1], float) else "", *np.round(row[2], 1))
        want, got = sorted(want, key=key), sorted(got, key=key)
        self.assertEqual(len(want), len(got), where)
        for w, g in zip(want, got):
            if isinstance(w[1], float):
                self.assertEqual(w[0], g[0], where)
                self.assertAlmostEqual(w[1], g[1], places=4, msg=where)
            else:
                self.assertEqual(w[:2], g[:2], where)
            np.testing.assert_allclose(w[2], g[2], atol=0.01, err_msg=where)

    def frames(self):
        import cv2

        for name in ("bus.jpg", "zidane.jpg"):
            big = cv2.imread(str(self.assets / name))
            h, w = big.shape[:2]
            for k in range(30):
                if k in (12, 13, 14, 22):                      # blank frames: tracks go lost, then are re-found
                    yield k, np.zeros((240, 320, 3), np.uint8)
                    continue
                s = 0.75 + 0.01 * k
                cw, ch = int(w * s), min(h, int(w * s * 0.75))
                x0, y0 = int((w - cw) * k / 29), (h - ch) // 2
                yield k, cv2.resize(big[y0:y0 + ch, x0:x0 + cw], (320, 240), interpolation=cv2.INTER_AREA)

    def test_same_detections_ids_and_boxes(self):
        from deskbot.vision.detector import TRACKER_YAML

        vcfg, n, tracked = VisionConfig(), 0, 0
        for k, img in self.frames():
            if k == 0:
                self.det.reset()
                for t in getattr(self.ref.predictor, "trackers", None) or []:
                    t.reset()
            kw = dict(imgsz=320, conf=vcfg.conf, rect=False, verbose=False)   # NCNN models get the square letterbox
            r = self.ref.predict(img, **kw)[0]
            want = [(int(c), float(sc), b) for c, sc, b in zip(r.boxes.cls, r.boxes.conf, r.boxes.xyxy.numpy())]
            got = [(self.label_index[d.label], d.score, np.array(d.box)) for d in self.det.predict(img)]
            self.same(want, got, f"predict, frame {k}")
            rt = self.ref.track(img, persist=True, tracker=str(TRACKER_YAML), **kw)[0]
            ids = rt.boxes.id.int().tolist() if rt.boxes.id is not None else [None] * len(rt.boxes)
            want = [(i, int(c), b) for i, c, b in zip(ids, rt.boxes.cls, rt.boxes.xyxy.numpy())]
            got = [(d.track_id, self.label_index[d.label], np.array(d.box)) for d in self.det(Frame(k, 0.0, img))]
            self.same(want, got, f"track, frame {k}")
            tracked += len(got)
            n += 1
            tracked += len(got)
        self.assertGreater(tracked, 50)
        self.assertEqual(n, 60)


if __name__ == "__main__":
    unittest.main()
