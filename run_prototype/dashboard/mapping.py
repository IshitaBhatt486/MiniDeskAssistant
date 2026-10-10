"""
Lightweight incremental occupancy-grid mapping (ultrasonic + IR).

Runs in its own thread and never touches the motors or the safety loop.
It only *reads* two things the Robot publishes:

* ``robot.latest_reading()``  - newest sensor sample with a monotonic timestamp
* ``robot.wheel_log``         - (t, left, right) entries, written once when a move
                                starts and once when it ends

From these it dead-reckons a pose and updates a log-odds grid. The full design
is in docs/mapping.md.
"""

from __future__ import annotations

import math
import threading
import time
from array import array
from collections import deque

# ---------------- GRID ----------------

RESOLUTION = 0.05          # metres per cell (5 cm)
SIZE = 60                  # cells per side -> 3 m x 3 m, start pose at the centre

# log-odds sensor model
L_OCC = 0.85               # added at a sonar hit
L_FREE = -0.40             # added along a sonar beam before the hit
L_IR_FLOOR = -0.60         # added under an IR sensor that sees the floor
L_MIN, L_MAX = -4.0, 4.0   # clamp so cells can still change their mind
T_OCC, T_FREE = 0.85, -0.85  # classification thresholds

# cell codes sent to the dashboard
UNKNOWN, FREE, OCCUPIED, EDGE = 0, 1, 2, 3

# ---------------- SENSOR MODEL ----------------

SONAR_MAX_USEFUL = 1.2             # trust ultrasonic hits up to this range (m)
SONAR_CONE_HALF = math.radians(7.5)  # HC-SR04 is ~15 deg wide
SONAR_RAYS = 3                     # rays cast across the cone

# ---------------- ROBOT GEOMETRY / ODOMETRY CALIBRATION ----------------
# Defaults match SimHardware. Calibrate on the real robot - see mapping.md.

WHEEL_SPEED_AT_FULL = 0.25  # m/s of a wheel at 100% PWM
TRACK_WIDTH = 0.12          # m between wheel centres
SONAR_OFFSET = 0.06         # m ahead of the robot centre
IR_OFFSET = 0.07            # m ahead (front) / behind (rear) of centre

UPDATE_HZ = 10
TRAIL_LEN = 300


def _line(c0, r0, c1, r1):
    """Bresenham cells from (c0, r0) to (c1, r1), inclusive."""
    dc, dr = abs(c1 - c0), -abs(r1 - r0)
    sc = 1 if c0 < c1 else -1
    sr = 1 if r0 < r1 else -1
    err = dc + dr
    while True:
        yield c0, r0
        if c0 == c1 and r0 == r1:
            return
        e2 = 2 * err
        if e2 >= dr:
            err += dr
            c0 += sc
        if e2 <= dc:
            err += dc
            r0 += sr


class OccupancyGrid:
    """Log-odds grid with per-cell version stamps for incremental sync."""

    def __init__(self, size=SIZE, resolution=RESOLUTION):
        self.size = size
        self.resolution = resolution
        n = size * size
        self.logodds = array("f", [0.0]) * n
        self.edge = bytearray(n)
        self.cell_version = array("I", [0]) * n
        self.version = 0

    # -- coordinates: world metres, origin = start pose, grid centred on it --

    def cell(self, x, y):
        c = math.floor(x / self.resolution) + self.size // 2
        r = math.floor(y / self.resolution) + self.size // 2
        if 0 <= c < self.size and 0 <= r < self.size:
            return c, r
        return None

    def _raw_cell(self, x, y):
        return (math.floor(x / self.resolution) + self.size // 2,
                math.floor(y / self.resolution) + self.size // 2)

    def _inside(self, c, r):
        return 0 <= c < self.size and 0 <= r < self.size

    # -- updates (call begin_batch() first) --

    def begin_batch(self):
        self.version += 1

    def _add(self, c, r, delta):
        i = r * self.size + c
        v = self.logodds[i] + delta
        self.logodds[i] = L_MIN if v < L_MIN else L_MAX if v > L_MAX else v
        self.cell_version[i] = self.version

    def ray(self, ox, oy, angle, rng, hit):
        """Free cells along the beam, occupied at the end if it was a real hit."""
        c0, r0 = self._raw_cell(ox, oy)
        c1, r1 = self._raw_cell(ox + rng * math.cos(angle), oy + rng * math.sin(angle))
        cells = list(_line(c0, r0, c1, r1))
        last = len(cells) - 1
        for k, (c, r) in enumerate(cells):
            if not self._inside(c, r):
                break
            if k == last and hit:
                self._add(c, r, L_OCC)
            else:
                self._add(c, r, L_FREE)

    def floor(self, x, y, delta=L_IR_FLOOR):
        cr = self.cell(x, y)
        if cr:
            self._add(cr[0], cr[1], delta)

    def mark_edge(self, x, y):
        cr = self.cell(x, y)
        if cr:
            i = cr[1] * self.size + cr[0]
            self.edge[i] = 1
            self.cell_version[i] = self.version

    # -- reading --

    def code(self, i):
        if self.edge[i]:
            return EDGE
        v = self.logodds[i]
        if v >= T_OCC:
            return OCCUPIED
        if v <= T_FREE:
            return FREE
        return UNKNOWN

    def encode(self, since):
        """Full grid as a digit string, or a delta list of [index, code] since a version."""
        n = self.size * self.size
        if since <= 0 or since > self.version:
            return {"full": True, "cells": "".join(str(self.code(i)) for i in range(n))}
        changed = [[i, self.code(i)] for i in range(n) if self.cell_version[i] > since]
        if len(changed) > n // 4:
            return {"full": True, "cells": "".join(str(self.code(i)) for i in range(n))}
        return {"full": False, "cells": changed}

    def counts(self):
        out = [0, 0, 0, 0]
        for i in range(self.size * self.size):
            out[self.code(i)] += 1
        return {"unknown": out[0], "free": out[1], "occupied": out[2], "edge": out[3]}


class Odometry:
    """Dead reckoning from commanded wheel speeds (no encoders yet)."""

    def __init__(self):
        self.x = self.y = self.theta = 0.0

    def advance(self, left, right, dt):
        if dt <= 0 or (left == 0 and right == 0):
            return
        vl = left * WHEEL_SPEED_AT_FULL
        vr = right * WHEEL_SPEED_AT_FULL
        v = (vl + vr) / 2
        w = (vr - vl) / TRACK_WIDTH
        steps = int(dt / 0.01) + 1
        h = dt / steps
        for _ in range(steps):
            self.theta = (self.theta + w * h) % (2 * math.pi)
            self.x += v * math.cos(self.theta) * h
            self.y += v * math.sin(self.theta) * h

    def point(self, offset):
        return self.x + offset * math.cos(self.theta), self.y + offset * math.sin(self.theta)

    def transform(self, dx, dy):
        """Robot-frame point (dx forward, dy left) -> map frame."""
        c, s = math.cos(self.theta), math.sin(self.theta)
        return self.x + dx * c - dy * s, self.y + dx * s + dy * c


class Mapper:
    """Background mapping thread. Read-only consumer of the Robot's published data."""

    def __init__(self, robot):
        self.robot = robot
        self._lock = threading.Lock()
        self._running = False
        self.epoch = 0   # bumped on reset so clients know their cached grid is stale
        self._thread = None
        self._reset_state()

    def _reset_state(self):
        self.grid = OccupancyGrid()
        self.odom = Odometry()
        self.trail = deque(maxlen=TRAIL_LEN)
        self.trail.append((0.0, 0.0))
        self._wheels = (0.0, 0.0)
        self._clock = None            # time up to which odometry is integrated
        self._log_t = float("-inf")   # timestamp of the newest wheel_log entry applied
        self._last_reading_t = None
        self.updates = 0
        self._update_times = deque(maxlen=50)
        self.started = time.monotonic()

    # -- lifecycle --

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="mapper", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def reset(self):
        with self._lock:
            self._reset_state()
            self.epoch += 1

    def _loop(self):
        period = 1.0 / UPDATE_HZ
        while self._running:
            t0 = time.monotonic()
            try:
                self.step()
            except Exception as exc:  # mapping must never take the robot down
                print(f"[MAP  ] update failed: {exc}", flush=True)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    # -- one update --

    def step(self):
        reading = self.robot.latest_reading()
        t = reading.get("t")
        if t is None or t == self._last_reading_t:
            return
        log = list(self.robot.wheel_log)  # copy; the robot keeps appending

        with self._lock:
            if self._clock is None:
                # first sample: adopt the current command, start integrating from here
                self._clock = t
                for et, left, right in log:
                    if et <= t:
                        self._wheels = (left, right)
                        self._log_t = et
            else:
                # replay wheel-command changes between the last update and this reading
                for et, left, right in log:
                    if et <= self._log_t or et > t:
                        continue
                    self.odom.advance(*self._wheels, et - self._clock)
                    self._clock = max(self._clock, et)
                    self._wheels = (left, right)
                    self._log_t = et
                self.odom.advance(*self._wheels, t - self._clock)
                self._clock = t

            self._last_reading_t = t
            self._integrate(reading)

    def sonar_sources(self, reading):
        """(dx, dy, angle_rad, distance) for each ultrasonic sensor, in the robot frame.
        Override to add sensors (see multisonar.py). Default: the single front HC-SR04."""
        return [(SONAR_OFFSET, 0.0, 0.0, reading.get("distance"))]

    def _integrate(self, reading):
        g, o = self.grid, self.odom
        g.begin_batch()

        # the robot's own footprint is free space
        g.floor(o.x, o.y)

        # ultrasonic cone(s)
        for dx, dy, dtheta, d in self.sonar_sources(reading):
            if d is None:
                continue
            hit = d < SONAR_MAX_USEFUL
            rng = min(d, SONAR_MAX_USEFUL)
            ox, oy = o.transform(dx, dy)
            for k in range(SONAR_RAYS):
                frac = k / (SONAR_RAYS - 1) - 0.5 if SONAR_RAYS > 1 else 0.0
                g.ray(ox, oy, o.theta + dtheta + frac * 2 * SONAR_CONE_HALF, rng, hit)

        # IR edge sensors: floor -> free, no floor -> permanent edge mark
        for key, offset in (("front_floor", IR_OFFSET), ("back_floor", -IR_OFFSET)):
            value = reading.get(key)
            if value is None:
                continue
            x, y = o.point(offset)
            if value:
                g.floor(x, y)
            else:
                g.mark_edge(x, y)

        last = self.trail[-1]
        if math.hypot(o.x - last[0], o.y - last[1]) >= 0.02:
            self.trail.append((o.x, o.y))
        self.updates += 1
        self._update_times.append(time.monotonic())

    # -- dashboard --

    def snapshot(self, since=0, epoch=None):
        with self._lock:
            if epoch is not None and epoch != self.epoch:
                since = 0  # map was cleared since the client last synced
            g = self.grid
            times = self._update_times
            rate = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
            data = g.encode(since)
            data.update({
                "version": g.version,
                "epoch": self.epoch,
                "size": g.size,
                "resolution": g.resolution,
                "pose": {"x": self.odom.x, "y": self.odom.y, "theta": self.odom.theta},
                "trail": [[round(x, 3), round(y, 3)] for x, y in self.trail],
                "counts": g.counts(),
                "updates": self.updates,
                "rate_hz": round(rate, 1),
                "uptime": time.monotonic() - self.started,
            })
            return data
