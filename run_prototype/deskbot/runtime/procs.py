"""
The three child processes. Each one pins itself to its core, sets its priority, then loops.

    motor_main    core 0, highest priority. Owns the motor pins. Newest command wins: a new command
                  preempts the running move immediately. Every 20 ms (and on every new sensor sample)
                  it applies the same safety rules as 3Nov-latest.py / multisonar.py, using the newest
                  sensor sample from shared memory. It stops by itself if the samples go stale or the
                  parent process dies.
    sensors_main  core 1, second priority. Owns the sonar + IR pins. Publishes all six readings at
                  50 Hz and wakes the motor process after each sample.
    camera_main   core 2, medium priority. Owns the camera + detector. Detects every N frames, moves
                  the boxes with optical flow in between, publishes frames and results.

The navigation process (mapper, behaviour, web server) is the parent: runtime/app.py.
"""

from __future__ import annotations

import math
import time
import traceback
from collections import deque

import numpy as np

from . import sched
from .shared import (DET_HEADER, DET_ROW, DET_WIDTH, DIRECTIONS, DRIVE, MAX_DETS, MOVE, SOURCES, STATES,
                     STOP, STOP_KINDS)


from ..vision.adaptive import AdaptiveInterval  # noqa: E402  (numpy only)


def _log(shared, level, msg, **extra):
    try:
        shared.log.put_nowait({"level": level, "msg": msg, **extra})
    except Exception:
        pass  # a full log queue must never block a real-time loop


def _parent_alive():
    import multiprocessing as mp

    parent = mp.parent_process()
    return parent is None or parent.is_alive()


def _pct(values, q):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


# ---------------- motor (core 0) ----------------

WHEELS = {"forward": (1, 1), "backward": (-1, -1), "left": (-1, 1), "right": (1, -1)}
CONTROL_STALE_S = 0.3   # wheel trims older than this are ignored (the controller stopped or crashed)


def wheel_direction(left, right):
    """Which safety rule applies to these wheel values: forward/backward, left/right, or None (stopped)."""
    v, w = (left + right) / 2, (right - left) / 2
    if v == 0 and w == 0:
        return None
    if abs(w) >= abs(v):
        return "left" if w > 0 else "right"
    return "forward" if v > 0 else "backward"


def _clamp_wheel(v):
    return round(max(-1.0, min(1.0, v)), 3)


def motor_main(shared, cfg, sim):
    rcfg = cfg.runtime
    pblock = shared.procs["motor"]
    info = sched.apply("motor", rcfg, pblock)
    hw = None
    try:
        if sim:
            from .hardware import SimMotorHardware
            hw = SimMotorHardware(shared.sim)
        else:
            from .hardware import GpioMotors
            hw = GpioMotors()
        _log(shared, "info", f"Motor process ready (core {info['core']}, {info['policy']}"
                             f"{' ' + str(info['priority']) if info['policy'] != 'other' else ''}, nice {info['nice']})"
                             + (f" - {'; '.join(info['notes'])}" if info["notes"] else ""), proc="motor")
        pblock.write(ready=1)
        MotorLoop(shared, rcfg, hw).run()
    except Exception as exc:
        _log(shared, "error", f"Motor process failed: {exc}", proc="motor", trace=traceback.format_exc())
        raise
    finally:
        if hw is not None:
            try:
                hw.stop()
            finally:
                hw.close()


class MotorLoop:
    """Command arbitration + safety checks. Separate from motor_main so tests can drive it directly."""

    def __init__(self, shared, rcfg, hw):
        from .safety import SafetyRules

        self.s = shared
        self.rcfg = rcfg
        self.hw = hw
        self.rules = SafetyRules()
        self.active = None            # dict for the running move
        self.state = "idle"
        self.direction = None
        self.duration = 0.0
        self.move_end = None
        self.source = 0
        self.stop_source = 0
        self.wheels = (0.0, 0.0)
        self.stats = {k: 0 for k in ("moves", "completed", "safety_stops", "user_stops", "preempted", "auto_moves")}
        self.stops = {k: 0 for k in STOP_KINDS}
        self.cmd_lat = deque(maxlen=256)
        self.sensor_age = deque(maxlen=512)
        self.last_seq = self.s.command.version
        self.loop = sched.LoopStats(self.s.procs["motor"])
        self.loops = 0

    def _set_wheels(self, left, right):
        if (left, right) == self.wheels:
            return
        if left == 0 and right == 0:
            self.hw.stop()
        else:
            self.hw.drive(left, right)
        self.wheels = (left, right)
        self.s.wheel_log.append((time.monotonic(), left, right))

    def _finish(self, outcome, kind=None, reason=None):
        a = self.active
        self._set_wheels(0.0, 0.0)
        self.active = None
        self.move_end = None
        if outcome == "completed":
            self.state = "idle"
            self.stats["completed"] += 1
            if a["source"] == "user":   # autonomous turns finish many times a minute; don't flood the log
                _log(self.s, "info", f"Completed {a['direction']} ({a['duration']:g} s)", source=a["source"])
        elif outcome == "blocked":
            self.state = "blocked"
            self.stats["safety_stops"] += 1
            self.stops[kind] += 1
            _log(self.s, "warn", f"{reason}, stopped {a['direction']}", reason=reason, source=a["source"])
        elif outcome == "user_stop":
            self.state = "idle"
            self.stats["user_stops"] += 1
            if self.stop_source == 0:
                _log(self.s, "info", "Stopped by user")
        elif outcome == "preempted":
            self.stats["preempted"] += 1

    def _sensor_reading(self, now):
        v = self.s.sensors.read()
        if math.isnan(v["t"]):
            return None, None
        d = {n: v[n] for n in ("front", "left", "right", "rear")}
        r = {"distance": d["front"], "distances": d, "front_floor": v["front_floor"] > 0.5,
             "back_floor": v["back_floor"] > 0.5, "t": v["t"]}
        return r, time.perf_counter() - v["tp"]

    def step(self):
        """One iteration: newest command, then safety. Returns quickly (~0.1 ms)."""
        now = time.monotonic()
        settings = self.s.settings.read()
        if not math.isnan(settings["speed"]):
            self.rules.stop_distance = settings["stop_distance"]
            self.rules.side_stop_distance = settings["side_stop_distance"]
            speed = settings["speed"]
        else:
            speed = 0.5

        # 1) newest command wins: anything newer than what we executed replaces it, immediately
        seq = self.s.command.version
        if seq != self.last_seq:
            self.last_seq = seq
            c = self.s.command.read()
            self.cmd_lat.append((time.perf_counter() - c["tp"]) * 1000)
            if int(c["kind"]) == STOP:
                self.stop_source = int(c["source"])
                if self.active:
                    self._finish("user_stop")
                else:
                    self._set_wheels(0.0, 0.0)
                    self.state = "idle"
            elif int(c["kind"]) == MOVE:
                if self.active:
                    self._finish("preempted")
                direction = DIRECTIONS[int(c["direction"])]
                self.active = {"direction": direction, "duration": c["duration"], "source": SOURCES[int(c["source"])],
                               "end": now + c["duration"], "speed": speed}
                self.state, self.direction, self.duration = "moving", direction, c["duration"]
                self.move_end, self.source = self.active["end"], int(c["source"])
                self.stats["moves"] += 1
                if self.source == 1:
                    self.stats["auto_moves"] += 1
            elif int(c["kind"]) == DRIVE:
                self._drive_command(c, now, speed)

        # 2) safety, with the newest sensor sample (same rules as the single-process robot)
        if self.active:
            a = self.active
            r, age = self._sensor_reading(now)
            if r is None or age > self.rcfg.sensor_stale_s:
                self._finish("blocked", "stale_sensors",
                             "Sensor data stale" if r is None else f"Sensor data {age * 1000:.0f} ms old")
            else:
                self.sensor_age.append(age * 1000)
                blocked = self.rules.check(a["direction"], r)
                if blocked:
                    self._finish("blocked", *blocked)
                elif now >= a["end"]:
                    self._finish("completed")
                elif a.get("wheels"):
                    self._set_wheels(*a["wheels"])
                else:
                    left, right = WHEELS[a["direction"]]
                    self._set_wheels(*self._trimmed(left * speed, right * speed, now))
        self.hw.tick()
        self.loops += 1
        self._publish(now)

    def _drive_command(self, c, now, speed):
        """Closed-loop wheel values. Repeated commands update the running drive in place; if they stop
        arriving, `duration` (a fraction of a second) runs out and the motors stop: a deadman."""
        left, right = _clamp_wheel(c["left"]), _clamp_wheel(c["right"])
        direction = wheel_direction(left, right)
        source = SOURCES[int(c["source"])]
        if direction is None:
            if self.active:
                self._finish("completed")
            return
        if self.active and self.active.get("wheels") and self.active["source"] == source:
            self.active.update(direction=direction, wheels=(left, right), end=now + c["duration"], duration=c["duration"])
        else:
            if self.active:
                self._finish("preempted")
            self.active = {"direction": direction, "duration": c["duration"], "source": source,
                           "end": now + c["duration"], "speed": speed, "wheels": (left, right)}
            self.stats["moves"] += 1
            self.stats["auto_moves"] += int(source == "auto")
        self.state, self.direction, self.duration = "moving", direction, c["duration"]
        self.move_end, self.source = self.active["end"], int(c["source"])

    def _trimmed(self, left, right, now):
        """Apply the closed-loop wheel gains (companion runtime) to a timed move, if they are fresh."""
        block = getattr(self.s, "control", None)
        if block is None:
            return left, right
        c = block.read()
        if math.isnan(c["t"]) or now - c["t"] > CONTROL_STALE_S:
            return left, right
        return _clamp_wheel(left * c["left"]), _clamp_wheel(right * c["right"])

    def _publish(self, now):
        lat, age = list(self.cmd_lat), list(self.sensor_age)
        self.s.motor.write(
            drive=float(bool(self.active and self.active.get("wheels"))),
            t=now, state=STATES.index(self.state), direction=-1 if self.direction is None else DIRECTIONS.index(self.direction),
            duration=self.duration, move_end=self.move_end, source=self.source, cmd_seq=self.last_seq,
            left=self.wheels[0], right=self.wheels[1], loops=self.loops,
            cmd_latency_p50=_pct(lat, 0.5), cmd_latency_p95=_pct(lat, 0.95), cmd_latency_max=max(lat) if lat else None,
            sensor_age_p50=_pct(age, 0.5), sensor_age_p95=_pct(age, 0.95), sensor_age_max=max(age) if age else None,
            **self.stats, **{f"stop_{k}": v for k, v in self.stops.items()})

    def run(self):
        wake, stop = self.s.wake, self.s.stop
        period = self.rcfg.check_interval
        parent_check = 0
        while not stop.is_set():
            wake.wait(period)          # a new command or sensor sample wakes us at once
            wake.clear()
            t0 = time.monotonic()
            self.step()
            parent_check += 1
            if parent_check >= 25:     # ~0.5 s: if the nav process died, stop and exit
                parent_check = 0
                if not _parent_alive():
                    break
            self.loop.tick(time.monotonic() - t0)
        if self.active:
            self._finish("user_stop")
        self._set_wheels(0.0, 0.0)


# ---------------- sensors (core 1) ----------------

def sensors_main(shared, cfg, sim):
    rcfg = cfg.runtime
    pblock = shared.procs["sensors"]
    info = sched.apply("sensors", rcfg, pblock)
    hw = None
    try:
        if sim:
            from .hardware import SimMirrorHardware
            hw = SimMirrorHardware(shared.sim)
        else:
            from .hardware import GpioSensors
            hw = GpioSensors()
        _log(shared, "info", f"Sensor process ready (core {info['core']}, {info['policy']}, {rcfg.sensor_hz:g} Hz)", proc="sensors")
        pblock.write(ready=1)
        period = 1.0 / rcfg.sensor_hz
        loop = sched.LoopStats(pblock)
        nxt = time.monotonic()
        failures = 0
        from .sensor_filter import SensorConditioner
        conditioner = SensorConditioner()
        while not shared.stop.is_set():
            t0 = time.monotonic()
            try:
                d = hw.distances()
                ff, bf = hw.front_floor(), hw.back_floor()
                d, ff, bf, faults = conditioner.update(d, ff, bf)
                enc = hw.encoders()
                t = time.monotonic()
                shared.sensors.write(t=t, tp=time.perf_counter(), front=d["front"], left=d["left"], right=d["right"], rear=d["rear"],
                                     front_floor=float(ff), back_floor=float(bf), read_ms=(t - t0) * 1000, faults=faults,
                                     enc_left=None if enc is None else enc[0], enc_right=None if enc is None else enc[1])
                shared.wake.set()
                failures = 0
            except Exception as exc:  # keep trying; the motor process stops on stale data meanwhile
                failures += 1
                if failures in (1, 50):
                    _log(shared, "error", f"Sensor read failed: {exc}", proc="sensors")
            loop.tick(time.monotonic() - t0)
            nxt += period
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.monotonic()   # overran: don't try to catch up with a burst
            if not _parent_alive():
                break
    except Exception as exc:
        _log(shared, "error", f"Sensor process failed: {exc}", proc="sensors", trace=traceback.format_exc())
        raise
    finally:
        if hw is not None:
            hw.close()


# ---------------- camera (core 2) ----------------

def encode_result(seq, t_capture, t_done, infer_ms, detections, detected, camera_fps, detect_fps, flow_ms, error=0):
    from ..vision.coco import index

    row = np.zeros(DET_WIDTH)
    dets = detections[:MAX_DETS]
    row[:len(DET_HEADER)] = (seq, t_capture, t_done, infer_ms, len(dets), float(detected),
                             camera_fps, detect_fps, flow_ms, error)
    k = len(DET_HEADER)
    w = len(DET_ROW)
    for j, d in enumerate(dets):
        row[k + j * w:k + (j + 1) * w] = (index(d.label), d.score, *d.box, -1 if d.track_id is None else d.track_id)
    return row


def decode_result(row):
    from ..vision.coco import name
    from ..vision.detector import Detection

    h = dict(zip(DET_HEADER, row[:len(DET_HEADER)].tolist()))
    k, w = len(DET_HEADER), len(DET_ROW)
    dets = []
    for j in range(int(h["n"])):
        c, s, x1, y1, x2, y2, tr = row[k + j * w:k + (j + 1) * w].tolist()
        dets.append(Detection(name(c), s, (x1, y1, x2, y2), None if tr < 0 else int(tr)))
    h["detections"] = dets
    return h


def camera_main(shared, cfg, camera, sim):
    import dataclasses

    rcfg = cfg.runtime
    pblock = shared.procs["camera"]
    info = sched.apply("camera", rcfg, pblock)
    grabber = None
    try:
        vcfg = dataclasses.replace(cfg.vision, threads=rcfg.camera_threads)
        if camera == "sim":
            from ..vision.detector import SimDetector
            detector = SimDetector()
        else:
            from ..vision.detector import make_detector
            from ..vision.model import resolve_model
            detector = make_detector(vcfg, resolve_model(vcfg, lambda m: _log(shared, "info", m, proc="camera")))
        from ..vision.camera import FrameGrabber, open_camera
        from ..vision.flow import FlowTracker

        hw = None
        if sim:
            from .hardware import SimMirrorHardware
            hw = SimMirrorHardware(shared.sim)
        source = open_camera(camera, cfg.camera, hw)
        grabber = FrameGrabber(source).start()
        _log(shared, "info", f"Camera process ready (core {info['core']}, nice {info['nice']}, "
                             f"{detector.name}, detect every {cfg.vision.detect_every} frames)", proc="camera")
        pblock.write(ready=1)
        CameraLoop(shared, cfg, grabber, detector, FlowTracker(cfg.vision.flow_points)).run()
    except Exception as exc:
        _log(shared, "error", f"Vision disabled: {exc}", proc="camera", trace=traceback.format_exc())
        pblock.write(ready=-1)
    finally:
        if grabber is not None:
            grabber.stop()


class CameraLoop:
    def __init__(self, shared, cfg, grabber, detector, flow):
        self.s, self.cfg = shared, cfg
        self.grabber, self.detector, self.flow = grabber, detector, flow
        self.every = max(1, cfg.vision.detect_every)
        self.adaptive = AdaptiveInterval(cfg.vision) if cfg.vision.adaptive_detection else None
        self.reset_seen = 0
        self.loop = sched.LoopStats(shared.procs["camera"])
        self.det_times = deque(maxlen=20)
        self.infer = deque(maxlen=20)

    def _motion(self):
        m = self.s.motor.read()
        if math.isnan(m["state"]) or STATES[int(m["state"])] != "moving":
            return False, False
        d = int(m["direction"]) if m["direction"] == m["direction"] else -1
        return True, d >= 0 and DIRECTIONS[d] in ("left", "right")

    def run(self):
        s = self.s
        last, last_det = 0, -10 ** 9
        warmed = False
        while not s.stop.is_set():
            frame = self.grabber.wait_newer(last, timeout=1.0)
            if frame is None:
                continue
            last = frame.seq
            t0 = time.monotonic()
            s.frames.write(frame.seq, frame.t, frame.image)
            ctl = s.vision_ctl.read()
            if not math.isnan(ctl["reset"]) and int(ctl["reset"]) != self.reset_seen:
                self.reset_seen = int(ctl["reset"])
                self.detector.reset()
                self.flow.tracks = []
            if not math.isnan(ctl["detect_every"]) and ctl["detect_every"] >= 1:
                self.every = int(ctl["detect_every"])      # a manual value switches the adaptive interval off
                self.adaptive = None
            try:
                if not warmed:
                    self.detector.warmup(frame.image)
                    warmed = True
                    continue
                moving, turning = self._motion()
                since = frame.seq - last_det
                if self.adaptive is not None:
                    detect = self.adaptive.should_detect(frame.image, since, len(self.flow.tracks), moving, turning)
                else:
                    detect = since >= self.every or not self.flow.tracks
                if detect:
                    a = time.monotonic()
                    dets = self.detector(frame)
                    b = time.monotonic()
                    self.flow.reset(frame.image, dets)
                    last_det = frame.seq
                    if self.adaptive is not None:
                        every = self.adaptive.detected(frame.image, len(dets), moving, turning)
                        s.vision_stats.write(every=every, change=self.adaptive.change)
                    self.det_times.append(b)
                    self.infer.append((b - a) * 1000)
                    flow_ms = 0.0
                else:
                    a = time.monotonic()
                    dets = self.flow.update(frame.image)
                    b = time.monotonic()
                    flow_ms = (b - a) * 1000
                err = 0
            except Exception as exc:
                _log(s, "error", f"Detection failed: {exc}", proc="camera")
                time.sleep(0.5)
                continue
            dt = self.det_times
            det_fps = (len(dt) - 1) / (dt[-1] - dt[0]) if len(dt) > 1 and dt[-1] > dt[0] else 0.0
            infer = sum(self.infer) / len(self.infer) if self.infer else 0.0
            row = encode_result(frame.seq, frame.t, time.monotonic(), infer if detect else 0.0, dets, detect,
                                self.grabber.fps, det_fps, flow_ms, err)
            s.latest.append(row)
            if detect:
                s.detections.append(row)
            self.loop.tick(time.monotonic() - t0)
            if not _parent_alive():
                break
