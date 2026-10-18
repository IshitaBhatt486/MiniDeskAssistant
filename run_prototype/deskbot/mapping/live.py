"""
LiveFusionMapper: FusionMapper that keeps the map current WHILE the robot moves.

Differences from FusionMapper (which updates at a fixed 10 Hz):
    - adaptive rate: MOVING_HZ (25) while the motors run, IDLE_HZ (10) otherwise. The sensor process
      publishes at 50 Hz, so while driving each map update uses a sample at most 40 ms old and the
      odometry between two updates is at most ~1 cm at full speed - sonar cones land where they were
      measured instead of being smeared over 10 cm.
    - every new sensor sample is integrated in order (no sample is reused; one is never applied twice).
    - `paused` (set by the lift detector): no updates and no odometry while the robot is in the air.
      When unpaused, odometry re-anchors on the next sample instead of integrating the carried motion.
    - counters for the dashboard: updates while moving, current rate.
    - measured wheel travel: with calibrated encoders (or in simulation) the pose advances by what the wheels
      actually did, replacing the estimate from motor commands. A gyro heading, if any, still wins.
Everything else (decaying grid, semantic map, glass/reflection handling) is inherited unchanged.
"""

from __future__ import annotations

import math
import time
from collections import deque

import mapping as odometry_constants  # dashboard/mapping.py

from .fusion import FusionMapper

MOVING_HZ = 25.0
IDLE_HZ = 10.0


class LiveFusionMapper(FusionMapper):
    def __init__(self, robot, cfg=None, vision=None):
        self.paused = False
        self.moving_updates = 0
        self._was_paused = False
        self._rate_times = deque(maxlen=50)
        super().__init__(robot, cfg, vision)

    external_heading = False           # the companion runtime sets this while the gyro provides the heading

    def _reset_state(self):
        super()._reset_state()
        self._enc_prev = None
        self._enc_pose = None

    def _encoders_usable(self):
        return self.cfg.encoders.calibrated or getattr(getattr(self.robot, "hw", None), "mode", "") == "simulation"

    def _apply_encoders(self, reading):
        counts = reading.get("encoders")
        if counts is None or not self._encoders_usable():
            return
        o = self.odom
        if self._enc_prev is None:
            self._enc_prev, self._enc_pose = counts, (o.x, o.y, o.theta)
            return
        if getattr(getattr(self.robot, "hw", None), "mode", "") == "simulation":
            from ..runtime.hardware import SIM_ENCODER as enc
        else:
            enc = self.cfg.encoders
        ml, mr = enc.metres_per_count()
        dl, dr = (counts[0] - self._enc_prev[0]) * ml, (counts[1] - self._enc_prev[1]) * mr
        x, y, th = self._enc_pose
        new_th = o.theta if self.external_heading else th + (dr - dl) / odometry_constants.TRACK_WIDTH
        mid = th + math.atan2(math.sin(new_th - th), math.cos(new_th - th)) / 2
        ds = (dl + dr) / 2
        o.x, o.y, o.theta = x + ds * math.cos(mid), y + ds * math.sin(mid), new_th % (2 * math.pi)
        self._enc_prev, self._enc_pose = counts, (o.x, o.y, o.theta)

    def _integrate(self, reading):
        self._apply_encoders(reading)
        super()._integrate(reading)

    def _loop(self):
        while self._running:
            t0 = time.monotonic()
            moving = False
            try:
                moving = self.robot.busy()
                if self.paused:
                    self._was_paused = True
                else:
                    if self._was_paused:
                        with self._lock:
                            self._clock = None       # re-anchor odometry; don't integrate the carry
                            self._enc_prev = None
                        self._was_paused = False
                    before = self.updates
                    self.step()
                    if self.updates != before:
                        self._rate_times.append(t0)
                        if moving:
                            self.moving_updates += 1
            except Exception as exc:  # mapping must never take the robot down
                print(f"[MAP  ] update failed: {exc}", flush=True)
            period = 1.0 / (MOVING_HZ if moving else IDLE_HZ)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    def rate_hz(self):
        t = list(self._rate_times)
        if len(t) < 2 or time.monotonic() - t[-1] > 1.0:
            return 0.0
        return round((len(t) - 1) / (t[-1] - t[0]), 1) if t[-1] > t[0] else 0.0

    def live_status(self):
        return {"paused": self.paused, "rate_hz": self.rate_hz(), "moving_updates": self.moving_updates,
                "updates": self.updates, "epoch": self.epoch}
