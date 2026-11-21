"""
The MPU-6050: where samples come from, and how they become an orientation.

    Mpu6050Source   the real sensor through Adafruit's driver (I2C bus 1, address 0x68)
    SimImuSource    derives gyro + accel from the simulated robot pose (with bias and noise)
    ImuFilter       calibration -> Madgwick filter (ahrs library) -> roll, pitch, continuous yaw

Robot frame: x forward, y left, z up. Yaw increases when the robot turns left, the same sign as camera
bearings and map headings. A 6-axis IMU has no absolute heading, so yaw is relative and drifts slowly;
two things keep the drift small: the gyro bias is re-estimated whenever the robot is stationary, and
yaw is frozen while it is stationary.
"""

from __future__ import annotations

import json
import math
import random
from collections import deque

import numpy as np

from .config import CALIBRATION_FILE, SIM_CALIBRATION_FILE

G = 9.80665


def calibration_file(sim=False):
    return SIM_CALIBRATION_FILE if sim else CALIBRATION_FILE


def load_calibration(sim=False):
    try:
        return json.loads(calibration_file(sim).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Mpu6050Source:
    name = "MPU-6050"

    def __init__(self, cfg):
        import adafruit_mpu6050 as m
        import board
        import busio

        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.dev = m.MPU6050(self.i2c, address=cfg.address)
        self.dev.accelerometer_range = m.Range.RANGE_4_G
        self.dev.gyro_range = m.GyroRange.RANGE_500_DPS
        self.dev.filter_bandwidth = m.Bandwidth.BAND_44_HZ
        self.dev.sample_rate_divisor = 9       # 1 kHz / (1 + 9) = 100 Hz

    def read(self, now):
        return np.array(self.dev.acceleration), np.array(self.dev.gyro), self.dev.temperature

    def close(self):
        self.i2c.deinit()


class SimImuSource:
    """What an MPU-6050 would measure on the simulated robot. The bias makes calibration meaningful."""
    name = "simulated IMU"
    BIAS = np.array([0.012, -0.009, 0.015])
    TILT = math.radians(35)

    WINDOW_S = 0.05     # the simulated pose updates in steps; differentiate over a window, like a real sensor's filter

    def __init__(self, shared):
        self.s = shared
        self.poses = deque()
        self.unwrapped = 0.0
        self.last_theta = None
        self.v = 0.0
        self.lift_t = None

    def read(self, now):
        p = self.s.sim.pose.read()
        wz, ax = 0.0, 0.0
        if not math.isnan(p["x"]):
            if self.last_theta is not None:
                self.unwrapped += (p["theta"] - self.last_theta + math.pi) % (2 * math.pi) - math.pi
            self.last_theta = p["theta"]
            self.poses.append((now, p["x"], p["y"], self.unwrapped))
            while len(self.poses) > 2 and now - self.poses[1][0] >= self.WINDOW_S:
                self.poses.popleft()
            t0, x0, y0, th0 = self.poses[0]
            if now > t0:
                dt = now - t0
                wz = (self.unwrapped - th0) / dt
                speed = ((p["x"] - x0) * math.cos(p["theta"]) + (p["y"] - y0) * math.sin(p["theta"])) / dt
                ax = max(-3.0, min(3.0, (speed - self.v) / max(dt, 0.01)))
                self.v = speed
        acc = np.array([ax, wz * self.v, G])
        gyr = np.array([0.0, 0.0, wz])
        if self.s.imu_ctl.read()["sim_lifted"] > 0.5:
            self.lift_t = self.lift_t or now
            age = now - self.lift_t
            tilt = self.TILT * min(1.0, age / 0.25)
            acc = np.array([G * math.sin(tilt), 0.0, G * math.cos(tilt) + (2.5 if age < 0.25 else 0.0)])
            gyr = np.array([0.5 * math.sin(age * 6), 0.9 * math.cos(age * 5), 0.3 * math.sin(age * 3)])
        else:
            self.lift_t = None
        noise = lambda s: np.array([random.gauss(0, s) for _ in range(3)])   # noqa: E731
        return acc + noise(0.03), gyr + self.BIAS + noise(0.002), 28.0

    def close(self):
        pass


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class ImuFilter:
    def __init__(self, cfg, cal=None, sim=False):
        from ahrs.filters import Madgwick   # imported here so a missing ahrs only breaks the IMU, not the menu

        self.cfg = cfg
        self.madgwick = Madgwick(frequency=cfg.hz, gain=cfg.madgwick_gain)
        self.q = np.array([1.0, 0.0, 0.0, 0.0])
        self.t = None
        self.yaw = 0.0
        self.tilt = 0.0
        self._raw_yaw = None
        self.still_since = None
        self.still = False
        self.apply_calibration(cal if cal is not None else load_calibration(sim))

    def apply_calibration(self, cal):
        c = cal.get("imu") or {}
        self.gyro_bias = np.array(c.get("gyro_bias", [0.0, 0.0, 0.0]), dtype=float)
        self.accel_scale = float(c.get("accel_scale", 1.0))
        self.level = np.array(c.get("level_matrix", np.eye(3).tolist()), dtype=float)
        self.yaw_sign = float(c.get("yaw_sign", 1.0))

    def zero(self):
        self.yaw = 0.0

    def update(self, raw_acc, raw_gyr, now, motors_on=False):
        """One sample -> dict of the values published to shared memory."""
        dt = 0.01 if self.t is None else min(0.2, max(1e-4, now - self.t))
        self.t = now
        acc = self.level @ (raw_acc * self.accel_scale)
        gyr = self.level @ (raw_gyr - self.gyro_bias)
        gyr[2] *= self.yaw_sign
        accel_err = abs(float(np.linalg.norm(acc)) - G)
        gyro_norm = float(np.linalg.norm(gyr))

        quiet = gyro_norm < self.cfg.still_gyro and accel_err < self.cfg.still_accel and not motors_on
        if not quiet:
            self.still_since = None
        elif self.still_since is None:
            self.still_since = now
        self.still = quiet and now - self.still_since >= self.cfg.still_hold_s
        if self.still:   # the gyro should read zero now, so what it reads is bias
            residual = gyr * np.array([1.0, 1.0, self.yaw_sign])       # undo the sign flip, back to sensor axes
            self.gyro_bias += self.cfg.bias_alpha * (self.level.T @ residual)
            gyr = np.zeros(3)

        # (the library skips the whole update, gravity correction included, for an exactly zero gyro vector)
        rates = gyr if gyr.any() else np.array([0.0, 0.0, 1e-9])
        self.q = np.asarray(self.madgwick.updateIMU(self.q, gyr=rates, acc=acc, dt=dt), dtype=float)
        norm = float(np.linalg.norm(acc))
        if norm > 1e-6:      # tilt straight from gravity: reacts at once, unlike the slowly corrected orientation
            self.tilt += 0.2 * (math.acos(max(-1.0, min(1.0, acc[2] / norm))) - self.tilt)
        w, x, y, z = self.q
        roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
        raw_yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        if self._raw_yaw is not None and not self.still:
            self.yaw += wrap(raw_yaw - self._raw_yaw)
        self._raw_yaw = raw_yaw
        return {"t": now, "ok": 1.0, "ax": acc[0], "ay": acc[1], "az": acc[2], "gx": gyr[0], "gy": gyr[1], "gz": gyr[2],
                "rax": raw_acc[0], "ray": raw_acc[1], "raz": raw_acc[2],
                "rgx": raw_gyr[0], "rgy": raw_gyr[1], "rgz": raw_gyr[2],
                "roll": roll, "pitch": pitch, "yaw": self.yaw, "tilt": self.tilt, "accel_err": accel_err, "gyro_norm": gyro_norm,
                "still": float(self.still)}


def tilt_rad(sample):
    """Angle between the robot's up axis and gravity."""
    t = sample.get("tilt")
    if t is not None and t == t:
        return t
    return math.acos(max(-1.0, min(1.0, math.cos(sample["roll"]) * math.cos(sample["pitch"]))))


__all__ = ["ImuFilter", "Mpu6050Source", "SimImuSource", "load_calibration", "tilt_rad", "wrap", "G"]
