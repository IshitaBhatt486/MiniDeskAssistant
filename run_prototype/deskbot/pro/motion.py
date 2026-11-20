"""
More from the MPU-6050 (20 Nov 2026). The body process (companion/body.py) already reads it at 100 Hz, fuses it
(Madgwick), and the companion uses it for pick-up detection, heading hold, turn rate and the tilting eyes. This adds
event detection on the same samples, read from shared memory (no second I2C reader):

    event        rule (all thresholds in data/pro.json "motion", adjustable on the dashboard)            reaction
    knock        not driving, not lifted, |a|-g jumps above knock_ms2 for < 90 ms, gyro < 1.5 rad/s  curious; a double
                                                                                                      knock wakes it
    bump         driving and the horizontal acceleration jumps above bump_ms2                         stop, "oof", annoyed
    shake        >= 3 reversals of the strongest gyro axis above shake_rads within 1.2 s             dizzy (confused)
    tipped       tilt above tip_deg for 0.8 s while the gyro is quiet (lying on its side)              stop, scared, asks
                                                                                                      for help
    righted      tipped, then level (tilt < tip_deg - 15 deg) for 1 s                                  "phew"
    drop         |a| below 3 m/s^2 (free fall) for >= 60 ms                                            scared
Each event has a 2 s cool-down (tipped/righted are a pair instead).

MotionDetector.update() is pure (sample + time + driving/lifted in, events out), so it is unit-tested and the
dashboard's simulation buttons feed it synthetic samples (inject()).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

G = 9.80665
COOLDOWN_S = 2.0


class MotionDetector:
    def __init__(self, section):
        self.section = section
        self.last = {}                     # event -> time
        self.spike_start = None
        self.spike_peak = 0.0
        self.knocks = deque(maxlen=3)
        self.reversals = deque()
        self.prev_sign = 0
        self.tip_since = None
        self.level_since = None
        self.tipped = False
        self.fall_since = None

    def _ok(self, name, now):
        if now - self.last.get(name, -1e9) < COOLDOWN_S:
            return False
        self.last[name] = now
        return True

    def update(self, s, now, driving=False, lifted=False):
        cfg = self.section()
        ev = []
        if not cfg.get("enabled", True):
            return ev
        a = math.sqrt(s.get("ax", 0.0) ** 2 + s.get("ay", 0.0) ** 2 + s.get("az", G) ** 2)
        err = abs(a - G)
        gyro = float(s.get("gyro_norm", 0.0))
        tilt = math.degrees(float(s.get("tilt", 0.0)))
        horiz = math.hypot(s.get("ax", 0.0), s.get("ay", 0.0))

        # free fall
        if a < 3.0:
            self.fall_since = self.fall_since or now
            if cfg.get("drop", True) and now - self.fall_since >= 0.06 and self._ok("drop", now):
                ev.append(("drop", {"g": round(a / G, 2)}))
        else:
            self.fall_since = None

        # bump while driving (horizontal jolt)
        if driving and not lifted and cfg.get("bump", True) and horiz > float(cfg.get("bump_ms2", 5.0)) and self._ok("bump", now):
            ev.append(("bump", {"ms2": round(horiz, 1)}))

        # knock: a short spike while standing still on the desk
        if not driving and not lifted and gyro < 1.5:
            if err > float(cfg.get("knock_ms2", 4.0)):
                if self.spike_start is None:
                    self.spike_start, self.spike_peak = now, err
                self.spike_peak = max(self.spike_peak, err)
            elif self.spike_start is not None:
                length = now - self.spike_start
                peak = self.spike_peak
                self.spike_start = None
                if length < 0.09 and cfg.get("knock", True):
                    self.knocks.append(now)
                    double = len(self.knocks) >= 2 and self.knocks[-1] - self.knocks[-2] < 0.6
                    if double:
                        self.knocks.clear()
                        self.last["knock"] = now
                        ev.append(("double_knock", {"ms2": round(peak, 1)}))
                    elif self._ok("knock", now):
                        ev.append(("knock", {"ms2": round(peak, 1)}))
        else:
            self.spike_start = None

        # shake: the dominant rotation keeps reversing
        gx, gy, gz = s.get("gx", 0.0), s.get("gy", 0.0), s.get("gz", 0.0)
        axis = max((gx, gy, gz), key=abs)
        while self.reversals and now - self.reversals[0] > 1.2:
            self.reversals.popleft()
        if abs(axis) > float(cfg.get("shake_rads", 4.0)):
            sign = 1 if axis > 0 else -1
            if self.prev_sign and sign != self.prev_sign:
                self.reversals.append(now)
            self.prev_sign = sign
            if len(self.reversals) >= 3 and cfg.get("shake", True) and self._ok("shake", now):
                self.reversals.clear()
                ev.append(("shake", {"rads": round(abs(axis), 1)}))

        # tipped over / righted
        limit = float(cfg.get("tip_deg", 60.0))
        if not self.tipped:
            if tilt > limit and gyro < 0.6:
                self.tip_since = self.tip_since or now
                if now - self.tip_since >= 0.8 and cfg.get("tip", True):
                    self.tipped, self.level_since = True, None
                    ev.append(("tipped", {"deg": round(tilt)}))
            else:
                self.tip_since = None
        else:
            if tilt < limit - 15:
                self.level_since = self.level_since or now
                if now - self.level_since >= 1.0:
                    self.tipped, self.tip_since = False, None
                    ev.append(("righted", {"deg": round(tilt)}))
            else:
                self.level_since = None
        return ev


class MotionSense:
    """Polls the shared IMU block at ~100 Hz and hands events to on_event(kind, info)."""

    def __init__(self, shared, section, on_event, driving=lambda: False, lifted=lambda: False, log=print):
        self.shared, self.section, self.on_event = shared, section, on_event
        self.driving, self.lifted, self.log = driving, lifted, log
        self.det = MotionDetector(section)
        self.events = deque(maxlen=12)
        self.counts = {}
        self.latest = None
        self._running = False
        self._lock = threading.Lock()

    def _handle(self, events):
        for kind, info in events:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.events.append({"kind": kind, "t": time.time(), **info})
            try:
                self.on_event(kind, info)
            except Exception as exc:
                self.log(f"Motion reaction failed: {type(exc).__name__}: {exc}")

    def feed(self, sample, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            ev = self.det.update(sample, now, driving=self.driving(), lifted=self.lifted())
        self._handle(ev)
        return [k for k, _ in ev]

    def inject(self, kind):
        """Play a synthetic sample sequence through the detector (simulation and the dashboard's test buttons)."""
        seqs = {
            "knock": [(0.00, {"ax": 0.0, "az": G + 6.0}), (0.02, {"az": G + 7.0}), (0.05, {"az": G})],
            "double_knock": [(0.00, {"az": G + 6.0}), (0.03, {"az": G}), (0.25, {"az": G + 6.0}), (0.28, {"az": G})],
            "bump": [(0.0, {"ax": -9.0, "az": G})],
            "shake": [(i * 0.12, {"gz": (7.0 if i % 2 else -7.0), "gyro_norm": 7.0}) for i in range(6)],
            "drop": [(i * 0.02, {"az": 0.5}) for i in range(6)] + [(0.14, {"az": G})],
            "tipped": [(i * 0.1, {"tilt": math.radians(80)}) for i in range(10)],
            "righted": [(i * 0.1, {"tilt": 0.0}) for i in range(12)],
        }
        if kind not in seqs:
            raise ValueError(f"motion events: {', '.join(seqs)}")
        base = time.monotonic()           # real time, so live samples carry on seamlessly afterwards
        found = []
        with self._lock:
            self.det.last.pop(kind, None)
            if kind == "double_knock":
                self.det.last.pop("knock", None)
            for dt, extra in seqs[kind]:
                s = {"ax": 0.0, "ay": 0.0, "az": G, "gx": 0.0, "gy": 0.0, "gz": 0.0, "gyro_norm": 0.0, "tilt": 0.0}
                s.update(extra)
                driving = kind == "bump"
                found += self.det.update(s, base + dt, driving=driving, lifted=False)
        self._handle(found)
        return [k for k, _ in found]

    def start(self):
        if self.shared is None:
            return self
        self._running = True

        def loop():
            from ..companion.shared import fresh_imu
            last_t = None
            while self._running:
                v = fresh_imu(self.shared, time.monotonic())
                if v is not None and v["t"] != last_t:
                    last_t = v["t"]
                    self.latest = {k: round(float(v[k]), 3) for k in ("roll", "pitch", "yaw", "tilt", "accel_err", "gyro_norm")}
                    self.feed(v)
                time.sleep(0.01)
        threading.Thread(target=loop, daemon=True, name="motion").start()
        return self

    def stop(self):
        self._running = False

    def status(self):
        return {"latest": self.latest, "counts": dict(self.counts), "events": list(self.events)[::-1],
                "tipped": self.det.tipped}
