"""
Robot control layer used by the dashboard.

Same pins, movement and safety rules as ``3Nov-latest.py``, wrapped in a
thread-safe class so a web server can drive it. Two backends:

* ``GpioHardware`` - the real motors and sensors via gpiozero (Raspberry Pi)
* ``SimHardware``  - a small 2-D desk simulation, for running the dashboard
                     on a laptop without any hardware
"""

from __future__ import annotations

import math
import random
import sys
import threading
import time
from collections import deque
from pathlib import Path

# robot_config.py lives in the repo root, one level above dashboard/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import robot_config as cfg  # noqa: E402

# ---------------- PINS (BCM) - edit robot_config.py, not here ----------------

PINS = {
    "left_forward": cfg.LEFT_MOTOR["forward"],
    "left_backward": cfg.LEFT_MOTOR["backward"],
    "left_enable": cfg.LEFT_MOTOR["enable"],
    "right_forward": cfg.RIGHT_MOTOR["forward"],
    "right_backward": cfg.RIGHT_MOTOR["backward"],
    "right_enable": cfg.RIGHT_MOTOR["enable"],
    "us_trigger": cfg.SONARS["front"]["trigger"],
    "us_echo": cfg.SONARS["front"]["echo"],
    "ir_front": cfg.IR_FRONT,
    "ir_back": cfg.IR_BACK,
}
PHYSICAL_PIN = cfg.PHYSICAL_PIN

# ---------------- SETTINGS ----------------

FLOOR_VALUE = 0              # IR output LOW = floor detected
MAX_DISTANCE = 2.0           # ultrasonic range, metres
DEFAULT_SPEED = 0.5
DEFAULT_STOP_DISTANCE = 0.20  # 20 cm
CHECK_INTERVAL = 0.02        # safety check period during a move
SENSOR_INTERVAL = 0.1        # background sensor polling for the dashboard
MAX_DURATION = 10.0          # longest single move the dashboard allows

DIRECTIONS = ("forward", "backward", "left", "right")

# (left wheel, right wheel) sign for each direction
WHEEL_COMMANDS = {
    "forward": (1, 1),
    "backward": (-1, -1),
    "left": (-1, 1),
    "right": (1, -1),
}


# ---------------- REAL HARDWARE ----------------

class GpioHardware:
    mode = "hardware"

    def __init__(self):
        from gpiozero import DigitalInputDevice, DistanceSensor, Motor

        p = PINS
        self.left = Motor(forward=p["left_forward"], backward=p["left_backward"], enable=p["left_enable"])
        self.right = Motor(forward=p["right_forward"], backward=p["right_backward"], enable=p["right_enable"])
        self.sonar = DistanceSensor(
            echo=p["us_echo"],
            trigger=p["us_trigger"],
            max_distance=MAX_DISTANCE,
            threshold_distance=DEFAULT_STOP_DISTANCE,
            queue_len=1,
        )
        self.front_ir = DigitalInputDevice(p["ir_front"])
        self.back_ir = DigitalInputDevice(p["ir_back"])

    def drive(self, left, right):
        for motor, value in ((self.left, left), (self.right, right)):
            if value > 0:
                motor.forward(value)
            elif value < 0:
                motor.backward(-value)
            else:
                motor.stop()

    def stop(self):
        self.left.stop()
        self.right.stop()

    def distance(self):
        return self.sonar.distance

    def front_floor(self):
        return self.front_ir.value == FLOOR_VALUE

    def back_floor(self):
        return self.back_ir.value == FLOOR_VALUE

    def snapshot(self):
        return None

    def reset(self):
        raise ValueError("Reset is only available in simulation mode")

    def close(self):
        self.stop()
        for device in (self.sonar, self.front_ir, self.back_ir, self.left, self.right):
            device.close()


# ---------------- SIMULATION ----------------

class SimHardware:
    """A robot on a 1.2 m x 0.7 m desk pushed against a wall (top edge).

    Coordinates are metres, origin bottom-left, theta in radians (0 = +x).
    The other three desk edges are drops that the IR sensors can detect.
    """

    mode = "simulation"

    DESK_W = 1.2
    DESK_H = 0.7
    MAX_WHEEL_SPEED = 0.25   # m/s at 100% PWM
    TRACK = 0.12             # distance between wheels
    BODY_RADIUS = 0.075
    IR_OFFSET = 0.07         # IR sensors sit this far ahead/behind centre
    SONAR_OFFSET = 0.06

    OBSTACLES = [
        {"kind": "circle", "label": "Mug", "x": 0.93, "y": 0.42, "r": 0.045},
        {"kind": "rect", "label": "Book", "x": 0.14, "y": 0.44, "w": 0.24, "h": 0.17},
    ]

    def __init__(self):
        self._lock = threading.RLock()
        self.reset()

    def reset(self):
        with self._lock:
            self.x, self.y, self.theta = 0.6, 0.28, 0.0
            self._l = self._r = 0.0
            self._t = time.monotonic()

    # -- physics --

    def _hits(self, px, py, inflate=0.0):
        if py >= self.DESK_H - inflate:  # wall
            return True
        for ob in self.OBSTACLES:
            if ob["kind"] == "circle":
                if math.hypot(px - ob["x"], py - ob["y"]) <= ob["r"] + inflate:
                    return True
            elif (ob["x"] - inflate <= px <= ob["x"] + ob["w"] + inflate
                  and ob["y"] - inflate <= py <= ob["y"] + ob["h"] + inflate):
                return True
        return False

    def _step(self):
        now = time.monotonic()
        dt = min(now - self._t, 0.5)
        self._t = now
        vl = self._l * self.MAX_WHEEL_SPEED
        vr = self._r * self.MAX_WHEEL_SPEED
        if vl == 0 and vr == 0:
            return
        v = (vl + vr) / 2
        w = (vr - vl) / self.TRACK
        n = int(dt / 0.01) + 1
        h = dt / n
        for _ in range(n):
            self.theta = (self.theta + w * h) % (2 * math.pi)
            nx = self.x + v * math.cos(self.theta) * h
            ny = self.y + v * math.sin(self.theta) * h
            if not self._hits(nx, ny, self.BODY_RADIUS):  # stall against obstacles
                self.x, self.y = nx, ny

    def _on_desk(self, px, py):
        return 0 <= px <= self.DESK_W and 0 <= py <= self.DESK_H

    def _point(self, offset):
        return (self.x + offset * math.cos(self.theta), self.y + offset * math.sin(self.theta))

    # -- hardware interface --

    def drive(self, left, right):
        with self._lock:
            self._step()
            self._l, self._r = left, right

    def stop(self):
        self.drive(0.0, 0.0)

    def distance(self):
        with self._lock:
            self._step()
            ox, oy = self._point(self.SONAR_OFFSET)
            c, s = math.cos(self.theta), math.sin(self.theta)
            d = 0.0
            while d < MAX_DISTANCE:
                if self._hits(ox + c * d, oy + s * d):
                    break
                d += 0.004
            d = min(MAX_DISTANCE, max(0.02, d + random.gauss(0, 0.002)))
            return d

    def front_floor(self):
        with self._lock:
            self._step()
            return self._on_desk(*self._point(self.IR_OFFSET))

    def back_floor(self):
        with self._lock:
            self._step()
            return self._on_desk(*self._point(-self.IR_OFFSET))

    def snapshot(self):
        with self._lock:
            self._step()
            return {
                "x": self.x,
                "y": self.y,
                "theta": self.theta,
                "desk": {"w": self.DESK_W, "h": self.DESK_H},
                "body_radius": self.BODY_RADIUS,
                "ir_offset": self.IR_OFFSET,
                "sonar_offset": self.SONAR_OFFSET,
                "obstacles": self.OBSTACLES,
            }

    def close(self):
        self.stop()


# ---------------- CONTROLLER ----------------

class Robot:
    """Runs timed moves in a worker thread with the same safety checks as 3Nov-latest.py."""

    def __init__(self, hw):
        self.hw = hw
        self.speed = DEFAULT_SPEED
        self.stop_distance = DEFAULT_STOP_DISTANCE

        self._lock = threading.RLock()          # protects state below
        self._command_lock = threading.Lock()   # serialises move/stop commands
        self._cancel = threading.Event()
        self._worker = None
        self._running = True

        self.state = "idle"          # idle | moving | blocked | error
        self.direction = None
        self.duration = 0.0
        self._move_end = None
        self.last_stop_reason = None

        self.readings = {"distance": None, "front_floor": None, "back_floor": None, "t": None}
        # (monotonic time, left, right) wheel commands, appended when a move starts and ends.
        # Read-only for consumers such as the mapper; deque.append is atomic.
        self.wheel_log = deque(maxlen=64)
        self.history = deque(maxlen=150)        # distance samples (cm), 15 s
        self.events = deque(maxlen=80)
        self._event_id = 0
        self.stats = {"moves": 0, "completed": 0, "safety_stops": 0, "user_stops": 0}
        self.stop_counts = {"front_edge": 0, "rear_edge": 0, "turn_edge": 0, "obstacle": 0}
        self.started = time.time()

        self.log("info", f"Robot ready ({hw.mode})")
        self._sensor_thread = threading.Thread(target=self._sensor_loop, daemon=True)
        self._sensor_thread.start()

    # -- helpers --

    def log(self, level, msg):
        with self._lock:
            self._event_id += 1
            self.events.append({"id": self._event_id, "t": time.time(), "level": level, "msg": msg})
        print(f"[{level.upper():5}] {msg}", flush=True)

    def _read(self):
        reading = {
            "distance": self.hw.distance(),
            "front_floor": self.hw.front_floor(),
            "back_floor": self.hw.back_floor(),
            "t": time.monotonic(),
        }
        with self._lock:
            self.readings = reading
        return reading

    def latest_reading(self):
        """Newest sensor sample (with monotonic timestamp ``t``). Never touches hardware."""
        with self._lock:
            return dict(self.readings)

    def _sensor_loop(self):
        while self._running:
            try:
                r = self._read()
                with self._lock:
                    self.history.append(round(r["distance"] * 100, 1))
            except Exception as exc:  # keep polling even if a read fails
                self.log("error", f"Sensor read failed: {exc}")
                time.sleep(1)
            time.sleep(SENSOR_INTERVAL)

    def _check_safety(self, direction, r):
        """Return (kind, reason) if the move must stop, or None if it is safe."""
        if direction == "forward" and not r["front_floor"]:
            return "front_edge", "Front edge detected"
        if direction == "backward" and not r["back_floor"]:
            return "rear_edge", "Rear edge detected"
        if direction in ("left", "right") and not (r["front_floor"] and r["back_floor"]):
            return "turn_edge", "Edge detected during turn"
        if direction == "forward" and r["distance"] <= self.stop_distance:
            return "obstacle", f"Obstacle at {r['distance'] * 100:.1f} cm"
        return None

    # -- movement --

    def _run(self, direction, duration, cancel):
        left, right = WHEEL_COMMANDS[direction]
        end = time.monotonic() + duration
        outcome, reason, kind = "completed", None, None
        moving_logged = False
        try:
            while time.monotonic() < end:
                if cancel.is_set():
                    outcome = "cancelled"
                    break
                blocked = self._check_safety(direction, self._read())
                if blocked:
                    kind, reason = blocked
                    outcome = "blocked"
                    break
                self.hw.drive(left * self.speed, right * self.speed)
                if not moving_logged:  # once per move, after the motors actually start
                    self.wheel_log.append((time.monotonic(), left * self.speed, right * self.speed))
                    moving_logged = True
                cancel.wait(CHECK_INTERVAL)
        except Exception as exc:
            outcome, reason = "error", str(exc)
        finally:
            self.hw.stop()
            if moving_logged:
                self.wheel_log.append((time.monotonic(), 0.0, 0.0))

        with self._lock:
            self._move_end = None
            if outcome == "completed":
                self.state = "idle"
                self.stats["completed"] += 1
            elif outcome == "blocked":
                self.state = "blocked"
                self.last_stop_reason = reason
                self.stats["safety_stops"] += 1
                self.stop_counts[kind] += 1
            elif outcome == "error":
                self.state = "error"
                self.last_stop_reason = reason
        if outcome == "completed":
            self.log("info", f"Completed {direction} ({duration:g} s)")
        elif outcome == "blocked":
            self.log("warn", f"{reason}, stopped {direction}")
        elif outcome == "error":
            self.log("error", f"Move failed: {reason}")

    def _cancel_worker(self):
        worker = self._worker
        if worker and worker.is_alive():
            self._cancel.set()
            worker.join(timeout=2)
            return True
        return False

    def move(self, direction, duration):
        if direction not in DIRECTIONS:
            raise ValueError(f"Unknown direction: {direction!r}")
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            raise ValueError("Duration must be a number") from None
        if not 0 < duration <= MAX_DURATION:
            raise ValueError(f"Duration must be between 0 and {MAX_DURATION:g} s")

        with self._command_lock:
            self._cancel_worker()
            cancel = threading.Event()
            with self._lock:
                self._cancel = cancel
                self.state = "moving"
                self.direction = direction
                self.duration = duration
                self._move_end = time.monotonic() + duration
                self.last_stop_reason = None
                self.stats["moves"] += 1
            self.log("info", f"Moving {direction} for {duration:g} s")
            self._worker = threading.Thread(target=self._run, args=(direction, duration, cancel), daemon=True)
            self._worker.start()

    def stop(self):
        with self._command_lock:
            was_moving = self._cancel_worker()
            self.hw.stop()
            with self._lock:
                self.state = "idle"
                self._move_end = None
                self.last_stop_reason = None
                if was_moving:
                    self.stats["user_stops"] += 1
        if was_moving:
            self.log("info", "Stopped by user")

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

    def reset_sim(self):
        self.stop()
        self.hw.reset()
        with self._lock:
            self.history.clear()
        self.log("info", "Simulation reset")

    def snapshot(self):
        sim = self.hw.snapshot()
        with self._lock:
            moving = self.state == "moving"
            r = self.readings
            clear = None
            if r["distance"] is not None:
                clear = {d: self._check_safety(d, r) is None for d in DIRECTIONS}
            remaining = max(0.0, self._move_end - time.monotonic()) if moving and self._move_end else 0.0
            return {
                "mode": self.hw.mode,
                "state": self.state,
                "direction": self.direction,
                "duration": self.duration,
                "remaining": remaining,
                "reason": self.last_stop_reason,
                "settings": {
                    "speed": self.speed,
                    "stop_distance": self.stop_distance,
                    "check_interval": CHECK_INTERVAL,
                    "floor_value": FLOOR_VALUE,
                    "max_distance": MAX_DISTANCE,
                    "max_duration": MAX_DURATION,
                },
                "sensors": dict(self.readings),
                "history": list(self.history),
                "history_len": self.history.maxlen,
                "history_interval": SENSOR_INTERVAL,
                "events": list(self.events)[-40:],
                "stats": dict(self.stats),
                "stop_counts": dict(self.stop_counts),
                "clear": clear,
                "uptime": time.time() - self.started,
                "pins": PINS,
                "physical_pins": PHYSICAL_PIN,
                "sim": sim,
            }

    def close(self):
        self._running = False
        try:
            self.stop()
        finally:
            self.hw.close()
