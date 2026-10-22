"""
Hardware split by process: the motor process opens ONLY the motor pins, the sensor process ONLY the
sonar + IR pins (gpiozero/lgpio lets different processes claim different pins).

Pins come from robot_config.py through dashboard/robot.py + dashboard/multisonar.py (unchanged).

Simulation: one simulated desk shared by all processes (shared.SimBlock).
    SimMotorHardware   (motor process) integrates the wheel physics and publishes the pose
    SimMirrorHardware  (sensors, camera, nav) copies the pose before every read, so the existing
                       FusionSimHardware sensor/camera code runs unchanged on the shared pose
"""

from __future__ import annotations

import copy
import math
import time

from multisonar import MAX_DISTANCE, PINS, SONARS  # dashboard/ (on sys.path via deskbot/__init__)
from robot_config import ENCODERS

from ..config import EncoderConfig, load_encoder_config
from ..robot import FusionSimHardware, RUNTIME_SIM_OBJECTS
from .shm import opt

FLOOR_VALUE = 0   # IR output LOW = floor detected (same as dashboard/robot.py)
SIM_ENCODER = EncoderConfig(left_counts_per_rev=360.0, right_counts_per_rev=360.0, calibrated=True)


# ---------------- real hardware ----------------

class GpioMotors:
    mode = "hardware"

    def __init__(self):
        from gpiozero import Motor

        p = PINS
        self.left = Motor(forward=p["left_forward"], backward=p["left_backward"], enable=p["left_enable"])
        self.right = Motor(forward=p["right_forward"], backward=p["right_backward"], enable=p["right_enable"])

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

    def tick(self):
        pass

    def close(self):
        self.stop()
        self.left.close()
        self.right.close()


class GpioEncoders:
    def __init__(self):
        from gpiozero import RotaryEncoder

        cfg = load_encoder_config()
        self.signs = (cfg.left_sign, cfg.right_sign)
        self.left = RotaryEncoder(ENCODERS["left_a"], ENCODERS["left_b"], max_steps=0)
        self.right = RotaryEncoder(ENCODERS["right_a"], ENCODERS["right_b"], max_steps=0)

    def read(self):
        return self.left.steps * self.signs[0], self.right.steps * self.signs[1]

    def close(self):
        self.left.close()
        self.right.close()


def open_encoders():
    """GpioEncoders, or None if they can't be opened (the robot still runs without them)."""
    try:
        return GpioEncoders() if load_encoder_config().enabled else None
    except Exception:
        return None


class GpioSensors:
    mode = "hardware"

    def __init__(self):
        from gpiozero import DigitalInputDevice, DistanceSensor

        self.devices = []
        try:
            self.sonars = {}
            for name, c in SONARS.items():
                self.sonars[name] = DistanceSensor(echo=c["echo"], trigger=c["trigger"],
                                                   max_distance=MAX_DISTANCE, queue_len=1)
                self.devices.append(self.sonars[name])
            self.front_ir = DigitalInputDevice(PINS["ir_front"])
            self.back_ir = DigitalInputDevice(PINS["ir_back"])
            self.devices += [self.front_ir, self.back_ir]
            self.enc = open_encoders()
            if self.enc is not None:
                self.devices.append(self.enc)
        except Exception:
            self.close()
            raise

    def distances(self):
        return {name: s.distance for name, s in self.sonars.items()}

    def encoders(self):
        return self.enc.read() if self.enc is not None else None

    def front_floor(self):
        return self.front_ir.value == FLOOR_VALUE

    def back_floor(self):
        return self.back_ir.value == FLOOR_VALUE

    def close(self):
        for d in self.devices:
            d.close()


# ---------------- simulation ----------------

class RuntimeSimHardware(FusionSimHardware):
    """The runtime's simulated desk: the in-process objects plus a user sitting across the desk."""

    def reset(self):
        super().reset()
        with self._lock:
            self.OBSTACLES = copy.deepcopy(RUNTIME_SIM_OBJECTS)


class SimMotorHardware(RuntimeSimHardware):
    """Owns the simulated physics (motor process). Publishes the pose after every physics step and
    follows reset / object changes requested by the nav process."""

    def __init__(self, sim):
        self.sim = sim
        self._reset_seen = 0
        self._objects_version = 0
        self.wheel_m = [0.0, 0.0]
        self.stuck = 0                 # 0 none, 1 left, 2 right (simulated jammed wheel)
        self._asked = (0.0, 0.0)
        super().__init__()

    def drive(self, left, right):
        self._asked = (left, right)
        super().drive(0.0 if self.stuck == 1 else left, 0.0 if self.stuck == 2 else right)

    def tick(self):
        c = self.sim.ctl.read()
        stuck = int(opt(c["stuck"]) or 0)
        if stuck != self.stuck:
            self.stuck = stuck
            self.drive(*self._asked)
        reset = int(opt(c["reset"]) or 0)
        if reset != self._reset_seen:
            self._reset_seen = reset
            self.reset()
        version = int(opt(c["objects_version"]) or 0)
        if version != self._objects_version:
            objects = self.sim.objects()
            if objects is not None:
                with self._lock:
                    self.OBSTACLES = objects
                self._objects_version = version
        with self._lock:
            self._step()

    def _step(self):
        dt = min(time.monotonic() - self._t, 0.5)
        self.wheel_m[0] += self._l * self.MAX_WHEEL_SPEED * dt
        self.wheel_m[1] += self._r * self.MAX_WHEEL_SPEED * dt
        super()._step()
        self.sim.pose.write(x=self.x, y=self.y, theta=self.theta, wheel_left=self.wheel_m[0], wheel_right=self.wheel_m[1])

    def reset(self):
        super().reset()
        if getattr(self, "sim", None) is not None:
            self.sim.pose.write(x=self.x, y=self.y, theta=self.theta)


class SimMirrorHardware(RuntimeSimHardware):
    """Read-only copy of the simulated world for the sensor, camera and nav processes."""

    def __init__(self, sim):
        self.sim = sim
        self._objects_version = -1
        super().__init__()

    def _step(self):  # called (under self._lock) before every simulated read
        p = self.sim.pose.read()
        if not math.isnan(p["x"]):
            self.x, self.y, self.theta = p["x"], p["y"], p["theta"]
        version = int(opt(self.sim.ctl.read()["objects_version"]) or 0)
        if version != self._objects_version:
            objects = self.sim.objects()
            if objects is not None:
                self.OBSTACLES = objects
                self._objects_version = version

    def drive(self, left, right):
        raise RuntimeError("the mirror cannot drive; commands go through the motor process")

    def encoders(self):
        p = self.sim.pose.read()
        if math.isnan(p["x"]):
            return 0, 0
        ml, mr = SIM_ENCODER.metres_per_count()
        return int((opt(p["wheel_left"]) or 0.0) / ml), int((opt(p["wheel_right"]) or 0.0) / mr)

    def stop(self):
        pass   # nothing to stop: the motors belong to the motor process

    def close(self):
        pass

    def shuffle(self, label="Mug", rng=None):
        """Move an object somewhere else on the desk, or the user to another seat around the desk."""
        import random

        rng = rng or random
        with self._lock:
            self._step()
            if label == "User":
                ob = next(o for o in self.OBSTACLES if o["label"] == "User")
                side = rng.choice(("bottom", "left", "right"))
                if side == "bottom":
                    ob["x"], ob["y"] = rng.uniform(0.15, self.DESK_W - 0.15), -0.30
                else:
                    ob["x"] = -0.30 if side == "left" else self.DESK_W + 0.30
                    ob["y"] = rng.uniform(0.1, self.DESK_H - 0.1)
                result = (label, ob["x"], ob["y"])
            else:
                result = super().shuffle(label, rng)
            self.sim.publish_objects(self.OBSTACLES)
            self._objects_version = int(opt(self.sim.ctl.read()["objects_version"]) or 0)
        return result

    def request_reset(self):
        self.sim.request_reset(copy.deepcopy(RUNTIME_SIM_OBJECTS))
