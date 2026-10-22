"""
Is a wheel really turning? Compares what the motors are told with what the encoders count.

WheelMonitor is the pure logic. WheelWatch runs it at 10 Hz in the navigation process: on a stuck wheel it stops
the robot, cancels the running commands, says so and tells its listeners (the companion shows a sad face).
It also reports sensors that sensor_filter.py has flagged as unreliable.

An encoder that has never moved proves nothing (it may be unplugged), so a wheel is only called stuck
once its encoder has been seen working.
"""

from __future__ import annotations

import math
import threading
import time

from .sensor_filter import fault_names


class WheelMonitor:
    MIN_COMMAND = 0.2       # weaker commands may legitimately not move the wheel
    MIN_COUNTS = 2
    STUCK_AFTER_S = 0.8

    def __init__(self):
        self.base = [None, None]
        self.since = [None, None]
        self.working = [False, False]
        self.last = None

    def update(self, now, left, right, counts):
        """None, or "left" / "right" / "both"."""
        if counts is None:
            return None
        if self.last is not None:
            for i in (0, 1):
                self.working[i] = self.working[i] or counts[i] != self.last[i]
        self.last = counts
        stuck = []
        for i, cmd in enumerate((left, right)):
            if abs(cmd) < self.MIN_COMMAND:
                self.since[i] = None
            elif self.since[i] is None or abs(counts[i] - self.base[i]) >= self.MIN_COUNTS:
                self.since[i], self.base[i] = now, counts[i]
            elif self.working[i] and now - self.since[i] >= self.STUCK_AFTER_S:
                stuck.append(i)
        if len(stuck) == 2:
            return "both"
        return ("left", "right")[stuck[0]] if stuck else None


class WheelWatch:
    COOLDOWN_S = 12.0

    def __init__(self, robot, say, alerts=None, executor=None, chime=None):
        self.robot, self.say, self.alerts, self.executor, self.chime = robot, say, alerts, executor, chime
        self.monitor = WheelMonitor()
        self.listeners = []
        self.last_report = -math.inf
        self.stuck_wheel = None
        self.faults = []
        self.events = 0
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="wheel-watch", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.step(time.monotonic())
            except Exception as exc:     # monitoring must never take the robot down
                print(f"[WHEEL] {exc}", flush=True)
            time.sleep(0.1)

    def step(self, now):
        m = self.robot.motor_state()
        r = self.robot.latest_reading()
        left, right = m["left"], m["right"]
        moving = left == left and right == right
        which = self.monitor.update(now, left if moving else 0.0, right if moving else 0.0, r.get("encoders"))
        if which:
            self.report(which, now)
        self._check_faults(fault_names(r.get("faults")))

    def _check_faults(self, faults):
        if faults == self.faults or self.alerts is None:
            self.faults = faults
            return
        self.faults = faults
        if faults:
            names = ", ".join(f.replace("_floor", " edge") for f in faults)
            self.alerts.warn("sensor-fault", f"My {names} sensor is giving unreliable readings, so I'm playing it safe.",
                             detail=f"faults: {faults}")
        else:
            self.alerts.resolve("sensor-fault", "My sensors look fine again.")

    def report(self, which="wheel", now=None):
        """A wheel (or, from the gyro check, the whole turn) is stuck."""
        now = time.monotonic() if now is None else now
        if now - self.last_report < self.COOLDOWN_S:
            return False
        self.last_report = now
        self.stuck_wheel, self.events = which, self.events + 1
        if self.executor:
            self.executor.cancel()
        self.robot.stop(source="auto")
        self.robot.log("warn", f"Wheel stuck ({which}): motors stopped")
        if self.chime:
            self.chime("confusion")
        self.say("Oops, looks like my wheel is stuck.", "alert")
        for fn in self.listeners:
            fn(which)
        return True

    def status(self):
        return {"stuck_wheel": self.stuck_wheel, "events": self.events, "working": self.monitor.working,
                "sensor_faults": self.faults}
