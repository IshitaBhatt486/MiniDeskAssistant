"""
Four HC-SR04 ultrasonic sensors (front, left, right, rear) - 13 Nov 2026.

Extends the existing classes without changing them:

* MultiSonarGpioHardware / MultiSonarSimHardware - read all four sensors
* MultiSonarRobot   - extra safety rules (rear sonar for reversing, side sonars for turns)
* MultiSonarMapper  - feeds all four beams into the occupancy grid

Design notes: docs/multisonar.md
"""

from __future__ import annotations

import math
import random
import time

import robot_config as cfg  # importable: robot.py puts the repo root on sys.path
from mapping import Mapper
from robot import MAX_DISTANCE, PINS as BASE_PINS, GpioHardware, Robot, SimHardware

# ---------------- SENSOR LAYOUT ----------------
# Robot frame: x forward, y left, metres from the robot centre (midpoint of the wheels).
# angle = direction the sensor faces, degrees, counter-clockwise from forward.
# Pins come from robot_config.py; only the mounting geometry lives here.

MOUNTS = {
    "front": {"x": 0.06, "y": 0.0, "angle": 0.0},
    "left": {"x": 0.0, "y": 0.065, "angle": 90.0},
    "right": {"x": 0.0, "y": -0.065, "angle": -90.0},
    "rear": {"x": -0.06, "y": 0.0, "angle": 180.0},
}

SONARS = {name: {**cfg.SONARS[name], **mount} for name, mount in MOUNTS.items()}

# Turning in place only sweeps the robot's own footprint, so the side sensors use a
# much shorter limit than the forward/backward stop distance.
SIDE_STOP_DISTANCE = 0.08  # 8 cm

PINS = dict(BASE_PINS)
for _name, _cfg in SONARS.items():
    if _name != "front":
        PINS[f"us_{_name}_trigger"] = _cfg["trigger"]
        PINS[f"us_{_name}_echo"] = _cfg["echo"]


# ---------------- HARDWARE ----------------

class MultiSonarGpioHardware(GpioHardware):
    def __init__(self):
        super().__init__()  # motors, IR and the front sonar (self.sonar)
        from gpiozero import DistanceSensor

        self.sonars = {"front": self.sonar}
        try:
            for name, cfg in SONARS.items():
                if name == "front":
                    continue
                self.sonars[name] = DistanceSensor(
                    echo=cfg["echo"], trigger=cfg["trigger"], max_distance=MAX_DISTANCE, queue_len=1
                )
        except Exception:
            self.close()
            raise

    def distances(self):
        return {name: sensor.distance for name, sensor in self.sonars.items()}

    def close(self):
        for name, sensor in getattr(self, "sonars", {}).items():
            if name != "front":  # the front sensor is closed by GpioHardware.close()
                sensor.close()
        super().close()


class MultiSonarSimHardware(SimHardware):
    def _ray(self, dx, dy, angle_deg):
        c, s = math.cos(self.theta), math.sin(self.theta)
        ox = self.x + dx * c - dy * s
        oy = self.y + dx * s + dy * c
        a = self.theta + math.radians(angle_deg)
        ca, sa = math.cos(a), math.sin(a)
        d = 0.0
        while d < MAX_DISTANCE:
            if self._hits(ox + ca * d, oy + sa * d):
                break
            d += 0.004
        return min(MAX_DISTANCE, max(0.02, d + random.gauss(0, 0.002)))

    def distances(self):
        with self._lock:
            self._step()
            return {n: self._ray(c["x"], c["y"], c["angle"]) for n, c in SONARS.items()}

    def distance(self):
        return self.distances()["front"]


# ---------------- CONTROLLER ----------------

class MultiSonarRobot(Robot):
    def __init__(self, hw):
        self.side_stop_distance = SIDE_STOP_DISTANCE
        super().__init__(hw)
        with self._lock:
            self.stop_counts.update({"rear_obstacle": 0, "side_obstacle": 0})
            self.readings.setdefault("distances", None)

    def _read(self):
        d = self.hw.distances()
        reading = {
            "distance": d["front"],          # kept so every existing consumer still works
            "distances": d,
            "front_floor": self.hw.front_floor(),
            "back_floor": self.hw.back_floor(),
            "t": time.monotonic(),
        }
        with self._lock:
            self.readings = reading
        return reading

    def _check_safety(self, direction, r):
        blocked = super()._check_safety(direction, r)  # IR edges + front sonar, unchanged
        if blocked:
            return blocked
        d = r.get("distances") or {}
        if direction == "backward" and d.get("rear") is not None and d["rear"] <= self.stop_distance:
            return "rear_obstacle", f"Rear obstacle at {d['rear'] * 100:.1f} cm"
        if direction in ("left", "right"):
            for side in ("left", "right"):
                v = d.get(side)
                if v is not None and v <= self.side_stop_distance:
                    return "side_obstacle", f"{side.capitalize()} obstacle at {v * 100:.1f} cm"
        return None

    def snapshot(self):
        s = super().snapshot()
        distances = s["sensors"].get("distances") or {}
        s["pins"] = PINS
        s["settings"]["side_stop_distance"] = self.side_stop_distance
        s["sonars"] = [
            {
                "name": name,
                "distance": distances.get(name),
                "x": cfg["x"],
                "y": cfg["y"],
                "angle": cfg["angle"],
                "trigger": cfg["trigger"],
                "echo": cfg["echo"],
                "stop": self.side_stop_distance if name in ("left", "right") else self.stop_distance,
                "used_for": {"front": "forward", "rear": "backward", "left": "turns", "right": "turns"}[name],
            }
            for name, cfg in SONARS.items()
        ]
        return s


# ---------------- MAPPING ----------------

class MultiSonarMapper(Mapper):
    def sonar_sources(self, reading):
        d = reading.get("distances")
        if not d:
            return super().sonar_sources(reading)
        return [(c["x"], c["y"], math.radians(c["angle"]), d.get(n)) for n, c in SONARS.items()]
