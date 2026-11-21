"""End-to-end in simulation: robot + simulated camera + fusion mapper + web server. Plus real YOLO if available."""

import gzip
import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import deskbot
from deskbot.config import AppConfig
from deskbot.mapping.fusion import FusionMapper
from deskbot.robot import make_robot
from deskbot.vision.camera import FrameGrabber, SimCamera
from deskbot.vision.detector import SimDetector
from deskbot.vision.pipeline import VisionPipeline

START = (0.6, 0.28)  # SimHardware start pose = map origin


def wait_for(cond, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class SimStack:
    def __init__(self):
        self.cfg = AppConfig()
        self.robot, self.hw = make_robot(sim=True)
        self.vision = VisionPipeline(FrameGrabber(SimCamera(self.cfg.camera, self.hw)).start(),
                                     SimDetector(seed=3), self.cfg.camera, self.cfg.vision).start()
        self.mapper = FusionMapper(self.robot, self.cfg, self.vision)
        self.mapper.start()

    def close(self):
        self.vision.stop()
        self.mapper.stop()
        self.robot.close()

    def obj(self, label):
        return next((o for o in self.mapper.snapshot()["objects"] if o["label"] == label), None)


class TestFusionSim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = SimStack()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_1_objects_land_at_their_true_positions(self):
        self.assertTrue(wait_for(lambda: self.s.obj("cup") and self.s.obj("bottle")), "cup/bottle never mapped")
        time.sleep(1.0)
        for label, (tx, ty) in {"cup": (0.93, 0.42), "bottle": (1.02, 0.13)}.items():
            o = self.s.obj(label)
            err = ((o["x"] - (tx - START[0])) ** 2 + (o["y"] - (ty - START[1])) ** 2) ** 0.5
            self.assertLess(err, 0.05, f"{label} mapped {err * 100:.1f} cm from the truth")
            self.assertGreater(o["p"], 0.9)

    def test_2_layers_are_consistent(self):
        snap = self.s.mapper.snapshot()
        n = snap["size"]
        import base64
        heat = base64.b64decode(snap["heat"])
        self.assertEqual(len(heat), n * n)
        cup = self.s.obj("cup")
        res = snap["resolution"]
        c, r = int(cup["x"] / res) + n // 2, int(cup["y"] / res) + n // 2
        self.assertGreater(heat[r * n + c], 200)                  # confident object at the cup
        self.assertIn("cup", snap["labels"])

    def test_3_moved_object_is_forgotten(self):
        with self.s.hw._lock:
            mug = next(o for o in self.s.hw.OBSTACLES if o["label"] == "Mug")
            mug["x"], mug["y"] = 0.15, 0.15                       # far behind the robot, out of view
        self.assertTrue(wait_for(lambda: self.s.obj("cup") is None, 4.0), "old cup position never cleared")
        self.assertIsNotNone(self.s.obj("bottle"))                # untouched objects stay

    def test_4_pose_history_interpolates(self):
        m = self.s.mapper
        with m._lock:
            m.poses.clear()
            m.poses.extend([(0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 0.0, 0.2)])
            for got, want in zip(m.pose_at(0.5), (0.5, 0.0, 0.1)):
                self.assertAlmostEqual(got, want, places=9)
            # heading interpolates the short way round across 0 / 2*pi
            m.poses.clear()
            m.poses.extend([(0.0, 0.0, 0.0, 6.2), (1.0, 0.0, 0.0, 0.1)])
            th = m.pose_at(0.5)[2] % (2 * 3.141592653589793)
            self.assertTrue(th > 6.2 or th < 0.1, th)
            m.poses.clear()


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from deskbot.web.server import FusionHandler
        cls.s = SimStack()
        FusionHandler.robot = cls.s.robot
        FusionHandler.mapper = cls.s.mapper
        FusionHandler.vision = cls.s.vision
        FusionHandler.app_cfg = cls.s.cfg
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FusionHandler)
        cls.httpd.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        from deskbot.web.server import FusionHandler
        FusionHandler.stopping = True
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.s.close()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()

    def post(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())

    def test_index_has_new_cards_and_old_ones(self):
        _, _, body = self.get("/")
        html = body.decode()
        for needle in ("geo-canvas", "sem-canvas", "heat-canvas", "cam-img", "fusion.js", "sonar-card", "app.js"):
            self.assertIn(needle, html)

    def test_fusion_gzip(self):
        _, headers, body = self.get("/api/fusion", {"Accept-Encoding": "gzip"})
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        data = json.loads(gzip.decompress(body))
        for key in ("geo", "heat", "sem_label", "objects", "stats", "pose"):
            self.assertIn(key, data)

    def test_vision_and_camera(self):
        wait_for(lambda: self.s.vision.latest() is not None)
        _, _, body = self.get("/api/vision")
        self.assertTrue(json.loads(body)["enabled"])
        status, headers, jpg = self.get("/camera.jpg")
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(jpg[:2], b"\xff\xd8")

    def test_reset_and_shuffle(self):
        epoch = json.loads(gzip.decompress(self.get("/api/fusion", {"Accept-Encoding": "gzip"})[2]))["epoch"]
        self.assertEqual(self.post("/api/fusion/reset")[0], 200)
        self.assertEqual(self.s.mapper.epoch, epoch + 1)
        self.assertEqual(self.post("/api/sim/shuffle")[0], 200)

    def test_legacy_api_still_works(self):
        _, _, body = self.get("/api/state")
        self.assertEqual(json.loads(body)["mode"], "simulation")
        self.assertIn("sonars", json.loads(body))


def _yolo_available():
    """An NCNN export that loads here (the Pi), or the .pt weights + Ultralytics (the laptop)."""
    import importlib.util

    from deskbot.config import VisionConfig
    from deskbot.vision.model import find_model
    if find_model(VisionConfig()):
        try:
            import ncnn  # noqa: F401  (Windows Smart App Control may block the DLL)
            return True
        except Exception:
            pass
    return importlib.util.find_spec("ultralytics") is not None and (deskbot.MODELS_DIR / "yolo26n.pt").exists()


@unittest.skipUnless(_yolo_available(), "no usable YOLO26n model here (run scripts/export-model.sh on the Pi)")
class TestYolo(unittest.TestCase):
    def test_detects_and_tracks_on_sample_photo(self):
        from deskbot.config import VisionConfig
        from deskbot.vision.camera import Frame
        from deskbot.vision.detector import make_detector
        from deskbot.vision.model import find_model, sample_image

        cfg = AppConfig()
        path = find_model(VisionConfig()) or deskbot.MODELS_DIR / "yolo26n.pt"
        det = make_detector(cfg.vision, path)   # NcnnDetector on the Pi, Ultralytics YoloDetector for the .pt
        img = sample_image(cfg.camera)
        det.warmup(img)
        dets = []
        for k in range(1, 4):
            dets = det(Frame(k, 0.0, img))
        labels = {d.label for d in dets}
        self.assertTrue({"bus", "person"} & labels, f"got {labels}")
        self.assertTrue(all(d.track_id is not None for d in dets))  # ByteTrack assigned IDs


if __name__ == "__main__":
    unittest.main()
