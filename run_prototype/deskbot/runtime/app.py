"""
Supervisor: start the four processes and run the navigation process (this one).

    core 0  motor     (child)   procs.motor_main
    core 1  sensors   (child)   procs.sensors_main
    core 2  camera    (child)   procs.camera_main
    core 3  nav       (parent)  FusionMapper + FaceUser + web server (this file)

Start order: shared memory -> motor -> sensors -> camera -> pin this process -> mapper -> behaviour ->
HTTP. Shutdown (Ctrl+C): stop command -> behaviour/mapper -> `stop` event -> join the children (the
motor process stops the motors and releases its pins in its own `finally`). If this process dies
anyway, the children notice (parent check) and stop by themselves; if the sensor process dies, the
motor process stops on stale data within 0.25 s.

New HTTP routes on top of deskbot/web/server.py's FusionHandler:
    GET  /api/runtime     processes (core, policy, priority, loop rate, CPU %), command latency, behaviour
    POST /api/behaviour   {"face_user": true|false}
    POST /api/sim/shuffle {"label": "Mug"|"User"} (simulation)

Design: docs/runtime.md
"""

from __future__ import annotations

import time
from argparse import Namespace

from server import serve  # dashboard/server.py

from ..config import AppConfig
from ..web.server import FusionHandler, WEB_DIR, build_index
from . import sched
from .shared import CTX, Shared
from .shm import opt


def start_children(shared, cfg, sim, camera):
    import os

    from .procs import camera_main, motor_main, sensors_main

    # Each child owns ONE core: math libraries must not start a thread pool per core in every process
    # (4 processes x 4 BLAS threads would fight over the cores and waste memory). Children inherit this.
    for var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    os.environ.setdefault("OMP_NUM_THREADS", str(cfg.runtime.camera_threads))

    procs = {
        "motor": CTX.Process(target=motor_main, args=(shared, cfg, sim), name="deskbot-motor", daemon=True),
        "sensors": CTX.Process(target=sensors_main, args=(shared, cfg, sim), name="deskbot-sensors", daemon=True),
    }
    if camera != "none":
        procs["camera"] = CTX.Process(target=camera_main, args=(shared, cfg, camera, sim), name="deskbot-camera", daemon=True)
    for p in procs.values():
        p.start()
    return procs


def wait_ready(shared, procs, roles, timeout=30.0):
    """Wait until each role has reported ready (1) or failed (-1 / died). Returns {role: ok}."""
    end = time.monotonic() + timeout
    status = {}
    while time.monotonic() < end and len(status) < len(roles):
        for role in roles:
            if role in status:
                continue
            r = shared.procs[role].read()["ready"]
            if r == 1:
                status[role] = True
            elif r == -1 or not procs[role].is_alive():
                status[role] = False
        time.sleep(0.05)
    for role in roles:
        status.setdefault(role, False)
    return status


def stop_children(shared, procs, timeout=3.0):
    from .shared import STOP

    shared.command.write(t=time.monotonic(), tp=time.perf_counter(), kind=STOP, direction=0, duration=0, source=0)
    shared.wake.set()
    shared.stop.set()
    shared.wake.set()
    for p in procs.values():
        p.join(timeout)
        if p.is_alive():
            p.terminate()


class RuntimeHandler(FusionHandler):
    shared = None
    behaviour = None
    procs = None
    server_version = "DeskRobot/3.0"
    _cpu = {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, build_runtime_index(), "text/html; charset=utf-8")
        if path == "/static/runtime.js":
            return self._send(200, (WEB_DIR / "runtime.js").read_bytes(), "text/javascript; charset=utf-8")
        if path == "/api/runtime":
            return self._json(200, runtime_status(self.shared, self.behaviour, self.procs, RuntimeHandler._cpu))
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/behaviour":
            body = self._read_json()
            if body is None:
                return
            if self.behaviour is None:
                return self._json(400, {"error": "Behaviours need the camera"})
            if "face_user" in body:
                self.behaviour.set_enabled(bool(body["face_user"]))
                self.robot.log("info", f"Face the user: {'on' if self.behaviour.enabled else 'off'}")
            return self._json(200, self.behaviour.status())
        if path == "/api/sim/shuffle":
            body = self._read_json()
            if body is None:
                return
            if not hasattr(self.robot.hw, "shuffle"):
                return self._json(400, {"error": "Only available in simulation mode"})
            label = body.get("label", "Mug")
            if label not in ("Mug", "User"):
                return self._json(400, {"error": "label must be Mug or User"})
            label, x, y = self.robot.hw.shuffle(label)
            self.robot.log("info", f"Simulation: moved the {label.lower()} to ({x * 100:.0f}, {y * 100:.0f}) cm")
            return self._json(200, {"ok": True})
        super().do_POST()


def build_runtime_index():
    page = build_index().decode("utf-8")
    cards = (WEB_DIR / "runtime_cards.html").read_text(encoding="utf-8")
    page = page.replace("<!-- ===== end deskbot cards ===== -->", cards + "\n    <!-- ===== end deskbot cards ===== -->", 1)
    page = page.replace('<script src="/static/fusion.js"></script>',
                        '<script src="/static/fusion.js"></script>\n  <script src="/static/runtime.js"></script>')
    return page.encode("utf-8")


def runtime_status(shared, behaviour, procs, cpu_prev):
    from .proxy import proc_table

    # the nav process (this one) has no loop of its own: report its CPU time here
    shared.procs["nav"].write(cpu_s=time.process_time(), t=time.monotonic())
    table = proc_table(shared)
    for row in table:
        # CPU % between two of the process's OWN reports (cpu_s and t are written together)
        cur = (row.get("_t"), row["cpu_s"])
        prev = cpu_prev.get(row["role"])
        if prev and cur[0] and prev[0] and cur[0] - prev[0] >= 0.5 and cur[1] is not None:
            cpu_prev[row["role"]] = (cur[0], cur[1], round(100 * (cur[1] - prev[1]) / (cur[0] - prev[0]), 1))
        elif not prev and cur[0]:
            cpu_prev[row["role"]] = (cur[0], cur[1], None)
        row["cpu_pct"] = cpu_prev.get(row["role"], (None, None, None))[2]
        row.pop("_t", None)
        row["alive"] = True if row["role"] == "nav" else bool(procs and row["role"] in procs and procs[row["role"]].is_alive())
    m = shared.motor.read()
    throttle = sched.rt_throttle()
    s = shared.sensors.read()
    return {
        "processes": table,
        "motor": {k: opt(m[k]) for k in ("cmd_latency_p50", "cmd_latency_p95", "cmd_latency_max",
                                          "sensor_age_p50", "sensor_age_p95", "sensor_age_max",
                                          "moves", "preempted", "auto_moves", "loops")},
        "sensors": {"read_ms": opt(s["read_ms"])},
        "rt_throttle": None if throttle is None else {"runtime_us": throttle[0], "period_us": throttle[1]},
        "behaviour": behaviour.status() if behaviour else {"enabled": False, "available": False, "state": "camera off"},
    }


def run_runtime(sim=False, host="127.0.0.1", port=8000, camera=None, cfg: AppConfig | None = None,
                mapper_cls=None, setup=None, shared_cls=None, extra_children=None, behaviour_cls=None):
    """Start the four-process robot and serve the dashboard until Ctrl+C.

    Hooks (used by deskbot/assistant/app.py, the 17 Nov assistant runtime; both default to the 15 Nov behaviour):
        mapper_cls  FusionMapper subclass to use (e.g. mapping.live.LiveFusionMapper)
        setup       fn(dict of robot/vision/mapper/behaviour/shared/procs/cfg/sim) -> (handler_cls, on_close or None),
                    called after everything is running and before the web server starts

    Hooks used by deskbot/companion/app.py (18 Nov):
        shared_cls      Shared subclass with extra blocks (IMU, face, gestures, wheel trims)
        extra_children  fn(shared, cfg, sim, camera) -> {role: started Process}
        behaviour_cls   FaceUser subclass (closed-loop facing)
    """
    from ..mapping.fusion import FusionMapper
    from .behaviour import FaceUser
    from .proxy import RobotProxy, VisionProxy

    cfg = cfg or AppConfig()
    camera = camera or ("sim" if sim else "pi")
    shared = (shared_cls or Shared)(cfg.camera.width, cfg.camera.height, sim=sim)
    sim_hw = None
    if sim:
        from ..robot import RUNTIME_SIM_OBJECTS
        from .hardware import SimMirrorHardware
        shared.sim.publish_objects(RUNTIME_SIM_OBJECTS)
        sim_hw = SimMirrorHardware(shared.sim)

    procs = start_children(shared, cfg, sim, camera)
    if extra_children is not None:
        procs.update(extra_children(shared, cfg, sim, camera))
    # Pin + prioritise this process AFTER spawning (children would inherit nice 10 and could not lower
    # it without privileges) and BEFORE starting any thread (Linux affinity and nice are per thread;
    # only threads created afterwards inherit them).
    info = sched.apply("nav", cfg.runtime, shared.procs["nav"])
    shared.procs["nav"].write(ready=1)
    robot = RobotProxy(shared, cfg.runtime, sim_hw)
    robot.log("info", f"Navigation process (this one): core {info['core']}, nice {info['nice']}"
                      + (f" - {'; '.join(info['notes'])}" if info["notes"] else ""))
    ready = wait_ready(shared, procs, ["motor", "sensors"])
    if not all(ready.values()):
        failed = ", ".join(r for r, ok in ready.items() if not ok)
        time.sleep(0.3)  # let the drain thread print the child's error
        stop_children(shared, procs)
        raise RuntimeError(f"{failed} process failed to start (see the error above). "
                           "Not on the Pi? Use --sim.")

    vision = None
    if "camera" in procs:
        vision = VisionProxy(shared, cfg.camera, cfg.vision, camera)
        vision.detector.name = "simulated detector" if camera == "sim" else f"{cfg.vision.model_name}"
        # not waiting for the camera: loading the model can take a while; the Camera card says
        # "starting" until the camera process reports ready
    else:
        FusionHandler.vision_off_reason = "started with --camera none"

    mapper = (mapper_cls or FusionMapper)(robot, cfg, vision)
    mapper.start()
    behaviour = (behaviour_cls or FaceUser)(robot, vision, mapper, cfg).start() if vision is not None else None
    robot.log("info", "Fusion mapping started" + (" + face-the-user behaviour" if behaviour and behaviour.enabled else ""))

    RuntimeHandler.mapper = mapper
    RuntimeHandler.vision = vision
    RuntimeHandler.app_cfg = cfg
    RuntimeHandler.shared = shared
    RuntimeHandler.behaviour = behaviour
    RuntimeHandler.procs = procs
    RuntimeHandler.stopping = False
    FusionHandler.stopping = False

    handler_cls, extra_close = RuntimeHandler, None
    if setup is not None:
        handler_cls, extra_close = setup({"robot": robot, "vision": vision, "mapper": mapper, "behaviour": behaviour,
                                          "shared": shared, "procs": procs, "cfg": cfg, "sim": sim, "camera": camera})

    def on_close():
        RuntimeHandler.stopping = FusionHandler.stopping = True
        if extra_close:
            try:
                extra_close()
            except Exception as exc:
                print(f"[ERROR] shutdown hook failed: {exc}", flush=True)
        if behaviour:
            behaviour.stop()
        mapper.stop()
        stop_children(shared, procs)

    serve(Namespace(host=host, port=port), robot, handler_cls, on_close=on_close)
