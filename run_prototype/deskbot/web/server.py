"""
The whole app: robot + fusion mapping + vision + dashboard, in one process.

Extends dashboard/server.py (same JSON API, same security rules, same drive/safety cards) with:

    GET  /                    dashboard page = dashboard/static/index.html + the cards in web/static/cards.html
    GET  /api/fusion          geometric + semantic + heatmap layers (gzip, ~1-3 kB)
    POST /api/fusion/reset    clear all maps, re-anchor the pose
    GET  /api/vision          camera/detector status, fps, latency, current detections
    GET  /camera.mjpg         live annotated camera (MJPEG). Frames are only encoded while someone watches
    GET  /camera.jpg          one annotated frame
    POST /api/sim/shuffle     (simulation) move the mug somewhere else, to watch stale data fade

Design: docs/deskbot.md
"""

from __future__ import annotations

import gzip
import json
import time
from argparse import Namespace
from pathlib import Path
from urllib.parse import urlsplit

from server import STATIC_DIR as LEGACY_STATIC, Handler, serve  # dashboard/server.py

from ..config import AppConfig

WEB_DIR = Path(__file__).resolve().parent / "static"

NEW_STATIC = {
    "/static/fusion.js": ("fusion.js", "text/javascript; charset=utf-8"),
    "/static/fusion.css": ("fusion.css", "text/css; charset=utf-8"),
}


def build_index():
    """The legacy page with the new cards spliced in, so both dashboards share one HTML source."""
    page = (LEGACY_STATIC / "index.html").read_text(encoding="utf-8")
    cards = (WEB_DIR / "cards.html").read_text(encoding="utf-8")
    page = page.replace("<title>Desk Robot Control</title>", "<title>Desk Robot · Vision &amp; Maps</title>")
    page = page.replace('<link rel="stylesheet" href="/static/styles.css">',
                        '<link rel="stylesheet" href="/static/styles.css">\n  <link rel="stylesheet" href="/static/fusion.css">')
    marker = "<!-- Ultrasonic -->"
    if marker in page:
        page = page.replace(marker, cards + "\n    " + marker, 1)
    else:
        page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<script src="/static/app.js"></script>',
                        '<script src="/static/app.js"></script>\n  <script src="/static/fusion.js"></script>')
    return page.encode("utf-8")


class FusionHandler(Handler):
    mapper = None
    vision = None
    app_cfg: AppConfig = None
    stopping = False
    server_version = "DeskRobot/2.0"

    def _json_gz(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        if "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=1)  # the maps are mostly uniform -> ~10x smaller
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, build_index(), "text/html; charset=utf-8")
        if path in NEW_STATIC:
            name, ctype = NEW_STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        if path == "/api/fusion":
            return self._json_gz(self.mapper.snapshot())
        if path == "/api/vision":
            if self.vision is None:
                return self._json(200, {"enabled": False, "reason": getattr(self, "vision_off_reason", None)})
            return self._json(200, self.vision.status())
        if path == "/camera.jpg":
            data = self.vision.jpeg() if self.vision else None
            if data is None:
                return self._json(503, {"error": "No camera frame yet"})
            return self._send(200, data, "image/jpeg")
        if path == "/camera.mjpg":
            return self._mjpeg()
        super().do_GET()

    def _mjpeg(self):
        if self.vision is None:
            return self._json(503, {"error": "Vision is off"})
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        period = 1.0 / max(1.0, self.app_cfg.vision.stream_fps)
        last = None
        try:
            while not FusionHandler.stopping:
                t0 = time.monotonic()
                res = self.vision.latest()
                seq = res.seq if res else None
                if seq is not None and seq == last:
                    time.sleep(0.02)
                    continue
                data = self.vision.jpeg()
                if data is None:
                    time.sleep(0.1)
                    continue
                last = seq
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                self.wfile.flush()
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass  # viewer closed the tab

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/fusion/reset":
            if self._read_json() is None:
                return
            self.mapper.reset()
            self.robot.log("info", "Maps cleared")
            return self._json(200, {"ok": True})
        if path == "/api/sim/shuffle":
            if self._read_json() is None:
                return
            if not hasattr(self.robot.hw, "shuffle"):
                return self._json(400, {"error": "Only available in simulation mode"})
            label, x, y = self.robot.hw.shuffle("Mug")
            self.robot.log("info", f"Simulation: moved the {label.lower()} to ({x * 100:.0f}, {y * 100:.0f}) cm on the desk")
            return self._json(200, {"ok": True})
        super().do_POST()
        if path == "/api/sim/reset" and self.robot.hw.mode == "simulation":
            self.mapper.reset()


def build_vision(camera, sim, hw, cfg: AppConfig, log=print, allow_fallback=True):
    """Start camera + detector threads. Returns the VisionPipeline (raises on failure)."""
    from ..vision.camera import FrameGrabber, open_camera
    from ..vision.pipeline import VisionPipeline

    # Detector FIRST, camera second: the camera only starts streaming once the model is ready, and
    # on Windows importing torch while an OpenCV (Media Foundation) camera is open can deadlock.
    if camera == "sim":
        from ..vision.detector import SimDetector
        detector = SimDetector()
    else:
        from ..vision.detector import YoloDetector
        from ..vision.model import resolve_model
        detector = YoloDetector(cfg.vision, resolve_model(cfg.vision, log, allow_fallback))
    source = open_camera(camera, cfg.camera, hw if sim else None)
    grabber = FrameGrabber(source).start()
    return VisionPipeline(grabber, detector, cfg.camera, cfg.vision).start()


def run_app(sim=False, host="127.0.0.1", port=8000, camera=None, cfg: AppConfig | None = None):
    """Start everything and serve until Ctrl+C. camera: 'pi' | 'webcam' | 'sim' | 'none' | index | file."""
    from ..mapping.fusion import FusionMapper
    from ..robot import make_robot

    cfg = cfg or AppConfig()
    camera = camera or ("sim" if sim else "pi")
    robot, hw = make_robot(sim)

    vision = None
    if camera != "none":
        try:
            vision = build_vision(camera, sim, hw, cfg, log=lambda m: robot.log("info", m))
            robot.log("info", f"Vision started: camera={camera}, detector={vision.detector.name}")
        except Exception as exc:
            FusionHandler.vision_off_reason = str(exc)
            robot.log("warn", f"Vision disabled: {exc}")
    else:
        FusionHandler.vision_off_reason = "started with --camera none"

    mapper = FusionMapper(robot, cfg, vision)
    mapper.start()
    robot.log("info", "Fusion mapping started (geometric + semantic + heatmap)")

    FusionHandler.mapper = mapper
    FusionHandler.vision = vision
    FusionHandler.app_cfg = cfg
    FusionHandler.stopping = False

    def on_close():
        FusionHandler.stopping = True
        mapper.stop()
        if vision:
            vision.stop()

    serve(Namespace(host=host, port=port), robot, FusionHandler, on_close=on_close)
