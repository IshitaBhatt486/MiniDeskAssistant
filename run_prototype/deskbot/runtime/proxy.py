"""
Stand-ins that live in the navigation process and look like the single-process objects, so the
existing FusionMapper, web handlers and dashboard JavaScript work unchanged on the multi-process robot.

    RobotProxy   ~ MultiSonarRobot   move/stop/settings -> shared command block (+ wake the motor process)
                                     latest_reading / wheel_log / snapshot <- shared memory
    VisionProxy  ~ VisionPipeline    latest / results_since / jpeg / status <- camera process's shared memory
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from multisonar import PINS, SIDE_STOP_DISTANCE, SONARS  # dashboard/
from robot import (CHECK_INTERVAL, DEFAULT_SPEED, DEFAULT_STOP_DISTANCE, FLOOR_VALUE, MAX_DISTANCE,  # dashboard/
                   MAX_DURATION, PHYSICAL_PIN, SENSOR_INTERVAL)

from .procs import decode_result
from .shared import DIRECTIONS, DRIVE, MOVE, SOURCES, STATES, STOP, STOP_KINDS
from .shm import opt


class _HardwareInfo:
    """robot.hw for the real robot (the GPIO lives in the child processes)."""
    mode = "hardware"

    def snapshot(self):
        return None

    def close(self):
        pass


class RobotProxy:
    def __init__(self, shared, rcfg, sim_hw=None):
        self.s = shared
        self.rcfg = rcfg
        self.hw = sim_hw or _HardwareInfo()
        self.speed = DEFAULT_SPEED
        self.stop_distance = DEFAULT_STOP_DISTANCE
        self.side_stop_distance = SIDE_STOP_DISTANCE
        self._cmd_lock = threading.Lock()    # several HTTP threads + the behaviour thread write commands
        self._lock = threading.Lock()
        self.events = deque(maxlen=80)
        self._event_id = 0
        self.history = deque(maxlen=150)
        self.last_stop_reason = None
        self.last_user_command = float("-inf")
        self.started = time.time()
        self._running = True
        self._push_settings()
        self.log("info", f"Robot ready ({self.hw.mode}, multi-process)")
        threading.Thread(target=self._drain, name="robot-events", daemon=True).start()

    # -- events --

    def log(self, level, msg):
        with self._lock:
            self._event_id += 1
            self.events.append({"id": self._event_id, "t": time.time(), "level": level, "msg": msg})
        print(f"[{level.upper():5}] {msg}", flush=True)

    def _drain(self):
        """Child-process log lines -> dashboard event list; 10 Hz distance history for the chart."""
        import queue

        next_hist = time.monotonic()
        while self._running:
            try:
                ev = self.s.log.get(timeout=0.1)
                if ev.get("reason"):
                    self.last_stop_reason = ev["reason"]
                if ev.get("source") == "auto" and ev["level"] == "info":
                    ev["msg"] = "[auto] " + ev["msg"]
                self.log(ev["level"], ev["msg"])
                if ev.get("trace"):
                    print(ev["trace"], flush=True)
            except queue.Empty:
                pass
            except (EOFError, OSError):
                break
            now = time.monotonic()
            if now >= next_hist:
                next_hist = now + SENSOR_INTERVAL
                v = self.s.sensors.read()
                if not math.isnan(v["front"]):
                    with self._lock:
                        self.history.append(round(v["front"] * 100, 1))

    # -- commands (newest wins) --

    def _send(self, kind, direction=0, duration=0.0, source=0, left=0.0, right=0.0):
        with self._cmd_lock:
            self.s.command.write(t=time.monotonic(), tp=time.perf_counter(), kind=kind, direction=direction,
                                 duration=duration, source=source, left=left, right=right)
        self.s.wake.set()

    def drive(self, left, right, duration=0.25, source="auto"):
        """Direct wheel values (-1..1) from a closed-loop controller. Every safety rule still applies in the
        motor process, and the motors stop by themselves if this isn't repeated within `duration`."""
        self._send(DRIVE, 0, float(duration), SOURCES.index(source), float(left), float(right))

    def move(self, direction, duration, source="user"):
        if direction not in DIRECTIONS:
            raise ValueError(f"Unknown direction: {direction!r}")
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            raise ValueError("Duration must be a number") from None
        if not 0 < duration <= MAX_DURATION:
            raise ValueError(f"Duration must be between 0 and {MAX_DURATION:g} s")
        if source == "user":
            self.last_user_command = time.monotonic()
            self.log("info", f"Moving {direction} for {duration:g} s")
        self.last_stop_reason = None
        self._send(MOVE, DIRECTIONS.index(direction), duration, SOURCES.index(source))

    def stop(self, source="user"):
        if source == "user":
            self.last_user_command = time.monotonic()
        self.last_stop_reason = None
        self._send(STOP, source=SOURCES.index(source))

    def _push_settings(self):
        self.s.settings.write(speed=self.speed, stop_distance=self.stop_distance,
                              side_stop_distance=self.side_stop_distance)

    def update_settings(self, speed=None, stop_distance=None):
        if speed is not None:
            speed = float(speed)
            if not 0.1 <= speed <= 1.0:
                raise ValueError("Speed must be between 0.1 and 1.0")
            self.speed = speed
            self.log("info", f"Speed set to {speed * 100:.0f}%")
        if stop_distance is not None:
            stop_distance = float(stop_distance)
            if not 0.05 <= stop_distance <= 1.0:
                raise ValueError("Stop distance must be between 5 and 100 cm")
            self.stop_distance = stop_distance
            self.log("info", f"Stop distance set to {stop_distance * 100:.0f} cm")
        self._push_settings()

    def reset_sim(self):
        if not hasattr(self.hw, "request_reset"):
            raise ValueError("Reset is only available in simulation mode")
        self.stop()
        self.hw.request_reset()
        with self._lock:
            self.history.clear()
        self.log("info", "Simulation reset")

    # -- state --

    def motor_state(self):
        return self.s.motor.read()

    def busy(self):
        m = self.s.motor.read()
        return not math.isnan(m["state"]) and STATES[int(m["state"])] == "moving"

    def latest_reading(self):
        v = self.s.sensors.read()
        if math.isnan(v["t"]):
            return {"distance": None, "distances": None, "front_floor": None, "back_floor": None, "t": None,
                    "encoders": None, "faults": 0}
        d = {n: v[n] for n in ("front", "left", "right", "rear")}
        return {"distance": d["front"], "distances": d, "front_floor": v["front_floor"] > 0.5,
                "back_floor": v["back_floor"] > 0.5, "t": v["t"],
                "encoders": None if math.isnan(v["enc_left"]) else (int(v["enc_left"]), int(v["enc_right"])),
                "faults": 0 if math.isnan(v["faults"]) else int(v["faults"])}

    @property
    def wheel_log(self):
        return [tuple(r) for r in self.s.wheel_log.rows().tolist()]

    def _check(self, direction, r):
        from .safety import SafetyRules
        return SafetyRules(self.stop_distance, self.side_stop_distance).check(direction, r)

    def snapshot(self):
        """Same JSON as MultiSonarRobot.snapshot(), so dashboard/static/app.js works unchanged."""
        m = self.s.motor.read()
        r = self.latest_reading()
        now = time.monotonic()
        state = "idle" if math.isnan(m["state"]) else STATES[int(m["state"])]
        direction = None if math.isnan(m["direction"]) or m["direction"] < 0 else DIRECTIONS[int(m["direction"])]
        remaining = max(0.0, m["move_end"] - now) if state == "moving" and not math.isnan(m["move_end"]) else 0.0
        clear = None if r["distance"] is None else {d: self._check(d, r) is None for d in DIRECTIONS}
        stat = lambda k: 0 if math.isnan(m[k]) else int(m[k])  # noqa: E731
        sim = self.hw.snapshot()
        with self._lock:
            events = list(self.events)[-40:]
            history = list(self.history)
        distances = r["distances"] or {}
        return {
            "mode": self.hw.mode,
            "runtime": "multi-process",
            "state": state,
            "direction": direction,
            "duration": 0.0 if math.isnan(m["duration"]) else m["duration"],
            "remaining": remaining,
            "reason": self.last_stop_reason if state == "blocked" else None,
            "source": SOURCES[stat("source")] if state == "moving" else None,
            "settings": {
                "speed": self.speed, "stop_distance": self.stop_distance,
                "side_stop_distance": self.side_stop_distance, "check_interval": self.rcfg.check_interval or CHECK_INTERVAL,
                "floor_value": FLOOR_VALUE, "max_distance": MAX_DISTANCE, "max_duration": MAX_DURATION,
            },
            "sensors": {k: r[k] for k in ("distance", "distances", "front_floor", "back_floor", "t")},
            "history": history,
            "history_len": self.history.maxlen,
            "history_interval": SENSOR_INTERVAL,
            "events": events,
            "stats": {k: stat(k) for k in ("moves", "completed", "safety_stops", "user_stops")},
            "stop_counts": {k: stat(f"stop_{k}") for k in STOP_KINDS},
            "clear": clear,
            "uptime": time.time() - self.started,
            "pins": PINS,
            "physical_pins": PHYSICAL_PIN,
            "sim": sim,
            "sonars": [
                {"name": name, "distance": distances.get(name), "x": c["x"], "y": c["y"], "angle": c["angle"],
                 "trigger": c["trigger"], "echo": c["echo"],
                 "stop": self.side_stop_distance if name in ("left", "right") else self.stop_distance,
                 "used_for": {"front": "forward", "rear": "backward", "left": "turns", "right": "turns"}[name]}
                for name, c in SONARS.items()
            ],
        }

    def close(self):
        self._running = False


class _DetectorHandle:
    """vision.detector for the mapper: reset() asks the camera process to drop its tracks."""

    def __init__(self, shared):
        self.s = shared
        self.name = "?"

    def reset(self):
        v = self.s.vision_ctl.read()
        self.s.vision_ctl.write(reset=(0 if math.isnan(v["reset"]) else v["reset"]) + 1)


class _Result:
    __slots__ = ("seq", "t_capture", "t_done", "detections", "infer_ms", "detected", "image")

    def __init__(self, h):
        self.seq = int(h["seq"])
        self.t_capture = h["t_capture"]
        self.t_done = h["t_done"]
        self.detections = h["detections"]
        self.infer_ms = h["infer_ms"]
        self.detected = h["detected"] > 0.5
        self.image = None

    @property
    def latency_ms(self):
        return (self.t_done - self.t_capture) * 1000


class VisionProxy:
    def __init__(self, shared, ccfg, vcfg, camera_name):
        from ..vision.pipeline import BOX_COLORS

        self.s = shared
        self.ccfg, self.vcfg = ccfg, vcfg
        self.camera_name = camera_name
        self.detector = _DetectorHandle(shared)
        self.colors = BOX_COLORS
        self.label_colors = {}
        self._jpeg = (None, -1)
        self._jpeg_lock = threading.Lock()
        self._lat = deque(maxlen=30)
        self.error = None

    def latest(self):
        rows = self.s.latest.rows()
        return _Result(decode_result(rows[-1])) if len(rows) else None

    def results_since(self, seq):
        """Results from REAL detections newer than `seq` (optical-flow frames are not new evidence)."""
        return [r for r in (_Result(decode_result(row)) for row in self.s.detections.rows()) if r.seq > seq]

    def color_for(self, label):
        if label not in self.label_colors:
            self.label_colors[label] = len(self.label_colors) % len(self.colors)
        return self.colors[self.label_colors[label]]

    def frame_image(self, res):
        """The camera image closest to this result (BGR), or None."""
        frame = self.s.frames.read(res.seq if res else None)
        return None if frame is None else frame[2]

    def jpeg(self):
        from ..vision.pipeline import annotate

        res = self.latest()
        frame = self.s.frames.read(res.seq if res else None)
        if frame is None:
            return None
        seq, _, img = frame
        dets = res.detections if res and res.seq == seq else (res.detections if res else [])
        with self._jpeg_lock:
            data, cached = self._jpeg
            if cached == seq and data is not None:
                return data
            data = annotate(img, dets, self.color_for, self.vcfg.jpeg_quality)
            self._jpeg = (data, seq)
            return data

    def status(self):
        p = self.s.procs["camera"].read()
        if p["ready"] != 1:
            failed = p["ready"] == -1
            return {"enabled": False, "starting": not failed,
                    "reason": "camera process failed (see the terminal)" if failed else "starting: loading the camera and model…"}
        res = self.latest()
        now = time.monotonic()
        if res is not None:
            self._lat.append(res.latency_ms)
        rows = self.s.detections.rows()
        det_lat = [(_Result(decode_result(r)).latency_ms) for r in rows[-8:]]
        h = decode_result(self.s.latest.rows()[-1]) if res else None
        return {
            "enabled": True,
            "camera": self.camera_name,
            "camera_model": self.camera_name,
            "detector": self.detector.name,
            "camera_fps": None if h is None else round(h["camera_fps"], 1),
            "detect_fps": None if h is None else round(h["detect_fps"], 1),
            "infer_ms": None if not rows.size else round(float(decode_result(rows[-1])["infer_ms"]), 1),
            "latency_ms": round(sum(det_lat) / len(det_lat), 1) if det_lat else None,
            "frame_latency_ms": None if res is None else round(res.latency_ms, 1),
            "flow_ms": None if h is None else round(h["flow_ms"], 2),
            "detect_every": self.vcfg.detect_every,
            "detect_every_now": opt(self.s.vision_stats.read()["every"]),
            "adaptive": self.vcfg.adaptive_detection,
            "frame_age_ms": None if res is None else round((now - res.t_capture) * 1000),
            "size": [self.ccfg.width, self.ccfg.height],
            "imgsz": self.vcfg.imgsz,
            "detections": [] if res is None else [d.as_dict() for d in res.detections],
            "propagated": bool(res and not res.detected),
            "error": self.error,
        }

    def stop(self):
        pass


def proc_table(shared):
    """[{role, pid, core, policy, priority, nice, loop_hz, loop_max_ms, cpu_pct}] for /api/runtime."""
    from .shared import POLICIES

    out = []
    now = time.monotonic()
    for role, block in shared.procs.items():     # the companion runtime adds its own roles
        p = block.read()
        if math.isnan(p["pid"]):
            continue
        out.append({
            "role": role, "pid": int(p["pid"]),
            "core": None if p["core"] < 0 else int(p["core"]),
            "policy": POLICIES[int(p["policy"])], "priority": int(p["priority"]),
            "nice": opt(p["nice"]),
            "loop_hz": None if math.isnan(p["loop_hz"]) else round(p["loop_hz"], 1),
            "loop_max_ms": None if math.isnan(p["loop_max_ms"]) else round(p["loop_max_ms"], 2),
            "cpu_s": opt(p["cpu_s"]),
            "age_s": None if math.isnan(p["t"]) else round(now - p["t"], 1),
            "_t": None if math.isnan(p["t"]) else p["t"],
            "ready": opt(p["ready"]),
        })
    return out
