"""
The companion runtime: assistant robot + IMU + PID control + lift handling + gestures + eyes + saved outputs.

Extra processes on top of runtime/ (motor, sensors, camera, nav):
    body     core 1, normal priority   MPU-6050 at 100 Hz, orientation filter, OLED eyes at 15 fps
    gesture  core 3, nice 15           MediaPipe hand gestures, 5 Hz, only while a person is in view

Extra routes on top of assistant/app.py:
    GET  /api/companion               everything the new dashboard cards show
    GET  /api/companion/pose          orientation, pose, wheels and sonars (small; for the 3D view and the MATLAB twin)
    GET  /face.png                    what is on the OLED now
    GET  /outputs/<path>              a saved file (only inside outputs/, only known file types)
    POST /api/companion/save          {}                                   save all figures now
    POST /api/companion/calibrate     {"action": "start" | "cancel"}       the complete calibration
    POST /api/companion/gestures      {"mapping": {...}} and/or {"enabled": bool}
    POST /api/companion/emotion       {"emotion": "happy"}                 show an emotion for a few seconds
    POST /api/companion/control       {"enabled": bool, "keep_distance": bool}
    POST /api/companion/zero-heading  {}
    POST /api/sim/gesture             {"gesture": "Thumb_Up"}              (simulation)

Design: docs/companion.md
"""

from __future__ import annotations

import io
import math
import threading
import time
from urllib.parse import unquote

from PIL import Image

from ..assistant.app import AssistantHandler, build_assistant_index, make_setup
from ..mapping.live import LiveFusionMapper
from ..runtime.app import run_runtime
from ..runtime.shared import CTX
from ..web.server import WEB_DIR
from .body import body_main
from .calibration import Calibration, apply_calibration
from .config import load_config
from .control import ClosedLoopFaceUser, MotionTrim
from .emotion import EmotionEngine
from .gestures import GestureController, gesture_main
from .greeter import Greeter
from .imu import load_calibration, tilt_rad
from .lift import ImuLiftDetector
from .outputs import ALLOWED_SUFFIX, OutputRecorder, resolve_download
from .shared import CompanionShared, fresh_imu, nav_bump, nav_write

STATIC = {
    "/static/companion.js": ("companion.js", "text/javascript; charset=utf-8"),
    "/static/companion.css": ("companion.css", "text/css; charset=utf-8"),
}


class ImuFusionMapper(LiveFusionMapper):
    """Odometry position from the wheels, heading from the gyro (far better than commanded wheel speeds)."""

    def _reset_state(self):
        super()._reset_state()
        self._yaw_offset = None

    def _integrate(self, reading):
        imu = fresh_imu(self.robot.s, time.monotonic())
        if imu is not None:
            if self._yaw_offset is None or self._was_reanchored():
                self._yaw_offset = imu["yaw"] - self.odom.theta
            self.odom.theta = (imu["yaw"] - self._yaw_offset) % (2 * math.pi)
        self.external_heading = imu is not None
        super()._integrate(reading)

    def _was_reanchored(self):
        again = getattr(self, "_reanchor", False)
        self._reanchor = False
        return again

    def reanchor_heading(self):
        self._reanchor = True


def extra_children(shared, cfg, sim, camera):
    procs = {"body": CTX.Process(target=body_main, args=(shared, cfg, sim), name="deskbot-body", daemon=True)}
    if camera != "none" and cfg.companion.gesture.enabled:
        procs["gesture"] = CTX.Process(target=gesture_main, args=(shared, cfg, camera, sim), name="deskbot-gesture", daemon=True)
    for p in procs.values():
        p.start()
    return procs


class Companion:
    def __init__(self, ctx, app, cfg):
        self.ctx, self.app, self.cfg = ctx, app, cfg
        self.cc = cfg.companion
        self.robot, self.s = ctx["robot"], ctx["shared"]
        self.behaviour = ctx["behaviour"]
        self.calibration = None
        self.calibration_data = load_calibration(ctx["sim"])
        app.robot, app.behaviour, app.face_png, app.control_history = self.robot, self.behaviour, self.face_png, self.control_history
        app.vision, app.image_size = ctx["vision"], (cfg.camera.width, cfg.camera.height)
        self.trim = MotionTrim(self.robot, cfg, self.calibration_data, on_stall=lambda: app.wheels.report("turn"))
        app.wheels.listeners.append(lambda which: app.emotion.react("sad", 8.0, "my wheel is stuck"))
        app.trim = self.trim
        app.emotion = EmotionEngine(self.s, self.cc.emotion, app)
        app.outputs = OutputRecorder(ctx, app, self.cc.output, "simulation" if ctx["sim"] else "robot")
        self.gestures = GestureController(self.s, self.cc.gesture, app, on_action=self._on_gesture)
        app.gestures = self.gestures
        self.greeter = Greeter(self.cc.greet, app, cfg.camera.width * cfg.camera.height)
        app.executor.on_command(self._on_command)
        app.navigator.listeners.append(self._on_navigation)
        if self.behaviour is not None:
            self.behaviour.set_calibration(self.calibration_data)
        app.lift.actions = {"save_figures": lambda: app.outputs.save_async("before new map", app.mapper.snapshot())}
        app.lift.on_change = self._on_lift
        self._running = False

    def start(self):
        self.trim.start()
        self.app.emotion.start()
        self.app.outputs.start()
        self.gestures.start()
        self._running = True
        threading.Thread(target=self._loop, name="companion", daemon=True).start()
        return self

    def halt(self):
        """Stop everything that can move the robot. Runs first at shutdown, before anything slow."""
        self._running = False
        if self.calibration:
            self.calibration.cancel.set()
        self.gestures.stop()
        self.trim.stop()
        if self.behaviour is not None:
            self.behaviour.paused = True
        self.app.executor.cancel()
        self.robot.stop(source="auto")

    def close(self):
        self.app.emotion.stop()
        self.app.outputs.close()           # the final figures; the motors are already stopped

    def _loop(self):
        while self._running:
            try:
                res = self.app_vision_latest()
                person = bool(res and any(d.label == "person" for d in res.detections))
                if not self._calibrating():
                    self.greeter.step(time.monotonic(), res.detections if res else [])
                sim_lift = self.app.sim_lift
                values = {"person": float(person)}
                nav_write(self.s.gesture_ctl, **values)
                if sim_lift is not None:
                    nav_write(self.s.imu_ctl, sim_lifted=float(sim_lift["lifted"]))
            except Exception as exc:
                print(f"[COMP ] {exc}", flush=True)
            time.sleep(0.1)

    def app_vision_latest(self):
        v = self.ctx["vision"]
        return v.latest() if v else None

    def _on_command(self, cmd):
        if cmd["action"] == "dance":
            self.app.emotion.react("excited", 6.0, "dancing")

    def _on_navigation(self, event):
        reaction = {"not_found": ("embarrassed", 8.0), "arrived": ("happy", 4.0), "failed": ("confused", 5.0),
                    "low_confidence": ("confused", 3.0)}.get(event)
        if reaction:
            self.app.emotion.react(reaction[0], reaction[1], f"navigation: {event}")

    def pose(self):
        now = time.monotonic()
        imu = fresh_imu(self.s, now)
        o = self.app.mapper.odom
        m = self.robot.motor_state()
        d = self.robot.latest_reading().get("distances") or {}
        out = {"t": round(now, 3), "imu": None, "x": round(o.x, 4), "y": round(o.y, 4), "heading": round(o.theta, 4),
               "left": None if m["left"] != m["left"] else m["left"], "right": None if m["right"] != m["right"] else m["right"],
               "sonars": {k: round(v, 3) for k, v in d.items()}}
        if imu is not None:
            out["imu"] = {k: round(imu[k], 4) for k in ("roll", "pitch", "yaw", "tilt", "gz")}
        return out

    def _on_gesture(self, name, action):
        self.app.emotion.react({"stop": "neutral", "dance": "excited", "spin": "excited", "sleep": "sleepy"}.get(action, "happy"),
                               why=f"gesture {name}")

    def _calibrating(self):
        return bool(self.calibration and self.calibration.running)

    def _on_lift(self, lifted):
        if lifted:
            self.app.speaker.chime("picked_up")
        if self.behaviour is not None:
            self.behaviour.paused = lifted or self._calibrating()   # never steer while being carried
            self.behaviour.target = None
        if not lifted:
            self.app.emotion.react("curious", 4.0, "new place")
            self.app.mapper.reanchor_heading()
        elif self._calibrating():
            self.calibration.cancel.set()

    def control_history(self):
        rows = list(self.trim.history)
        if self.behaviour is not None and hasattr(self.behaviour, "history"):
            rows += list(self.behaviour.history)
        return sorted(rows, key=lambda r: r[0])

    def face_png(self):
        f = self.s.face_frame.read()
        if f is None:
            return None
        buf = io.BytesIO()
        Image.fromarray(f[2][:, :, 0]).convert("1").save(buf, "PNG", optimize=True)
        return buf.getvalue()

    # -- calibration --

    def start_calibration(self):
        if self.calibration and self.calibration.running:
            raise ValueError("Calibration is already running")
        if self.app.lift.lifted:
            raise ValueError("Put me on the desk first")
        self.app.executor.cancel()
        self.robot.stop(source="auto")
        folder = self.app.outputs.folder / "calibration"
        self.calibration = Calibration(self.robot, self.s, self.cfg, self.ctx["sim"], folder,
                                       log=lambda m: self.robot.log("info", f"Calibration: {m}"),
                                       has_camera=self.ctx["vision"] is not None)
        self._pause(True)
        threading.Thread(target=self._calibrate, name="calibration", daemon=True).start()

    def _pause(self, paused):
        self.trim.paused = paused
        self.gestures.paused = paused
        if self.behaviour is not None:
            self.behaviour.paused = paused

    def _calibrate(self):
        cal = self.calibration
        try:
            self.app.emotion.react("curious", 600, "calibrating")
            cal.run()
            self.calibration_data = load_calibration(self.ctx["sim"])
            apply_calibration(self.calibration_data, None)
            self.trim.set_calibration(self.calibration_data)
            if self.behaviour is not None:
                self.behaviour.set_calibration(self.calibration_data)
            failed = [r["title"] for r in cal.results if r["status"] == "fail"]
            self.robot.log("warn" if failed else "info", "Calibration finished" + (f"; failed: {', '.join(failed)}" if failed else ""))
            self.app.emotion.react("confused" if failed else "happy", why="calibration done")
        except Exception as exc:
            self.app.alerts.warn("calibration", "Calibration failed.", speak=False, detail=str(exc))
        finally:
            self._pause(False)

    def status(self):
        now = time.monotonic()
        imu = fresh_imu(self.s, now)
        drive = self.calibration_data.get("drive") or {}
        b = self.behaviour
        return {
            "sim": self.ctx["sim"],
            "imu": None if imu is None else {
                "roll": round(math.degrees(imu["roll"]), 1), "pitch": round(math.degrees(imu["pitch"]), 1),
                "tilt": round(math.degrees(tilt_rad(imu)), 1), "yaw": round(math.degrees(imu["yaw"]), 1),
                "gz": round(imu["gz"], 2), "still": imu["still"] == 1.0},
            "emotion": self.app.emotion.status(),
            "control": {"trim": self.trim.status(), "face": b.status() if b else None,
                        "history": [[round(t - now, 2), m, round(s, 3), round(p, 3)] for t, m, s, p, _ in self.control_history()[-150:]]},
            "gestures": self.gestures.status(),
            "greeter": self.greeter.status(),
            "last_dance": self.app.executor.last_dance,
            "lift": self.app.lift.status(),
            "outputs": self.app.outputs.status(),
            "calibration": {"date": self.calibration_data.get("date"), "values": drive,
                            "run": self.calibration.status() if self.calibration else None},
        }


class CompanionHandler(AssistantHandler):
    comp: Companion = None
    server_version = "DeskRobot/5.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, build_companion_index(), "text/html; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        if path == "/api/companion":
            return self._json(200, self.comp.status())
        if path == "/api/companion/pose":
            return self._json(200, self.comp.pose())
        if path == "/face.png":
            png = self.comp.face_png()
            return self._send(200, png, "image/png") if png else self._json(503, {"error": "No picture yet"})
        if path.startswith("/outputs/"):
            file = resolve_download(unquote(path[len("/outputs/"):]))
            if file is None:
                return self._json(404, {"error": "Not found"})
            return self._send(200, file.read_bytes(), ALLOWED_SUFFIX[file.suffix.lower()])
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        routes = {"/api/companion/save": self._save, "/api/companion/calibrate": self._calibrate,
                  "/api/companion/gestures": self._gestures, "/api/companion/emotion": self._emotion,
                  "/api/companion/control": self._control, "/api/companion/zero-heading": self._zero,
                  "/api/sim/gesture": self._sim_gesture}
        if path not in routes:
            return super().do_POST()
        body = self._read_json()
        if body is None:
            return
        try:
            return self._json(200, routes[path](body) or {"ok": True})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:
            self.app.alerts.warn("api", "A dashboard request failed.", speak=False, detail=f"{type(exc).__name__}: {exc}")
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _save(self, body):
        return {"started": self.app.outputs.save_async("dashboard")}

    def _calibrate(self, body):
        action = body.get("action")
        if action == "start":
            self.comp.start_calibration()
        elif action == "cancel":
            if self.comp.calibration:
                self.comp.calibration.cancel.set()
        else:
            raise ValueError("action must be start or cancel")

    def _gestures(self, body):
        g = self.comp.gestures
        if "mapping" in body:
            g.set_mapping(body["mapping"])
        if "enabled" in body:
            g.enabled = bool(body["enabled"])
        return g.status()

    def _emotion(self, body):
        emotion = body.get("emotion")
        if emotion not in self.app.emotion.status()["emotions"]:
            raise ValueError("unknown emotion")
        self.app.emotion.react(emotion, 6.0, "dashboard")

    def _control(self, body):
        if "enabled" in body:
            self.comp.trim.enabled = bool(body["enabled"])
        if "keep_distance" in body and self.comp.behaviour is not None:
            self.comp.behaviour.keep_distance = bool(body["keep_distance"])

    def _zero(self, body):
        nav_bump(self.comp.s.imu_ctl, "zero_seq")
        time.sleep(0.05)                     # one IMU cycle, so the map re-anchors on the new zero
        self.app.mapper.reanchor_heading()

    def _sim_gesture(self, body):
        if not self.comp.ctx["sim"]:
            raise ValueError("Only available in simulation mode")
        self.comp.gestures.simulate(body.get("gesture"))


def build_companion_index():
    page = build_assistant_index().decode("utf-8")
    cards = (WEB_DIR / "companion_cards.html").read_text(encoding="utf-8")
    page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<link rel="stylesheet" href="/static/assistant.css">',
                        '<link rel="stylesheet" href="/static/assistant.css">\n  <link rel="stylesheet" href="/static/companion.css">')
    page = page.replace('<script src="/static/assistant.js"></script>',
                        '<script src="/static/assistant.js"></script>\n  <script src="/static/companion.js"></script>')
    page = page.replace("<title>Desk Robot · Assistant</title>", "<title>Desk Robot · Companion</title>")
    return page.encode("utf-8")


def run_companion(sim=False, host="127.0.0.1", port=8000, camera=None, https_port=8443, handler_cls=None, on_ready=None):
    """handler_cls / on_ready (19 Nov 2026): hooks for runtimes built on this one (buddy/app.py).
    handler_cls subclasses CompanionHandler; on_ready(ctx, app, comp) runs once everything is up and returns a
    close() to call first at shutdown (or None)."""
    cfg = load_config()
    apply_calibration(load_calibration(sim), cfg)
    ImuLiftDetector.cfg = cfg.companion.lift
    handler_cls = handler_cls or CompanionHandler
    base = make_setup(https_port, host, port, handler_cls=handler_cls, lift_cls=ImuLiftDetector)

    def setup(ctx):
        handler, base_close = base(ctx)
        comp = Companion(ctx, CompanionHandler.app, cfg).start()
        CompanionHandler.comp = comp
        ctx["robot"].log("info", f"Saving outputs to {CompanionHandler.app.outputs.folder}")
        extra_close = on_ready(ctx, CompanionHandler.app, comp) if on_ready else None

        def close():
            if extra_close:
                try:
                    extra_close()
                except Exception as exc:
                    print(f"[COMP ] {exc}", flush=True)
            comp.halt()
            base_close()
            comp.close()
        return handler, close

    run_runtime(sim=sim, host=host, port=port, camera=camera, cfg=cfg, mapper_cls=ImuFusionMapper, setup=setup,
                shared_cls=CompanionShared, extra_children=extra_children, behaviour_cls=ClosedLoopFaceUser)


class Rig:
    """The robot's processes without the web server: for `main.py calibrate` and `main.py imu`."""

    def __init__(self, sim=False, camera="none"):
        from ..runtime.app import start_children, stop_children, wait_ready
        from ..runtime.proxy import RobotProxy

        self.cfg = load_config()
        apply_calibration(load_calibration(sim), self.cfg)
        self.sim, self.camera = sim, camera
        self._stop_children = stop_children
        self.shared = CompanionShared(self.cfg.camera.width, self.cfg.camera.height, sim=sim)
        sim_hw = None
        if sim:
            from ..robot import RUNTIME_SIM_OBJECTS
            from ..runtime.hardware import SimMirrorHardware
            self.shared.sim.publish_objects(RUNTIME_SIM_OBJECTS)
            sim_hw = SimMirrorHardware(self.shared.sim)
        self.cfg.companion.gesture.enabled = False
        self.procs = start_children(self.shared, self.cfg, sim, camera)
        self.procs.update(extra_children(self.shared, self.cfg, sim, camera))
        self.shared.procs["nav"].write(ready=1)
        self.robot = RobotProxy(self.shared, self.cfg.runtime, sim_hw)
        ready = wait_ready(self.shared, self.procs, ["motor", "sensors", "body"])
        if not all(ready.values()):
            self.close()
            raise RuntimeError(f"{', '.join(k for k, ok in ready.items() if not ok)} did not start. Not on the Pi? Use --sim.")

    def close(self):
        self.robot.close()
        self._stop_children(self.shared, self.procs)
