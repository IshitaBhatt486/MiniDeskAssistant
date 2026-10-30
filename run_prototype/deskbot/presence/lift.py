"""
Lift detection: picked up off the desk -> stop, pause mapping; put down again -> brand-new map.

Signal: the two IR edge sensors (front + rear, LOW = surface underneath). On a desk at most ONE of them
can see "no surface" (the motor process stops the robot at the first edge), so BOTH seeing nothing means
nothing is under the robot at all: it has been lifted.

    on desk  --both off >= LIFT_CONFIRM_S-->  LIFTED: stop motors, cancel commands, pause the mapper
    LIFTED   --both on  >= PLACE_CONFIRM_S-->  on desk: if it was up >= RESET_AFTER_S the robot is
                                               somewhere new -> reset the map (pose back to 0,0);
                                               a shorter blip only resumes mapping
Why pause the mapper while lifted: otherwise every update would paint "desk edge" under the robot
wherever it is carried, and those marks are permanent.

Both off for STUCK_WARN_S while never placed back is also reported (unplugged IR sensors look exactly
like a permanent lift).
"""

from __future__ import annotations

import threading
import time

LIFT_CONFIRM_S = 0.4
PLACE_CONFIRM_S = 1.0
RESET_AFTER_S = 1.0
STUCK_WARN_S = 120.0
HZ = 20.0


class LiftDetector:
    def __init__(self, robot, mapper, alerts, say, executor=None):
        self.robot, self.mapper, self.alerts, self.say = robot, mapper, alerts, say
        self.executor = executor
        self.lifted = False
        self.lifted_at = None
        self.lifts = 0
        self.resets = 0
        self._cond = (None, time.monotonic())
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="lift", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.step(time.monotonic())
            except Exception as exc:   # must never take the robot down
                self.alerts.warn("lift", "Lift detection hit an error.", speak=False, detail=str(exc))
            time.sleep(1.0 / HZ)

    def step(self, now):
        r = self.robot.latest_reading()
        ff, bf = r.get("front_floor"), r.get("back_floor")
        if ff is None or bf is None:
            return
        cond = "air" if (not ff and not bf) else ("desk" if (ff and bf) else "edge")
        if cond != self._cond[0]:
            self._cond = (cond, now)
        held = now - self._cond[1]

        if not self.lifted and cond == "air" and held >= LIFT_CONFIRM_S:
            self.lifted, self.lifted_at = True, now
            self.lifts += 1
            if self.executor:
                self.executor.cancel()
            self.robot.stop(source="auto")
            self.mapper.paused = True
            self.robot.log("warn", "Lifted off the desk: motors stopped, mapping paused")
            self.say("Whoa! Put me down gently please.", "chatter")
        elif self.lifted and cond == "desk" and held >= PLACE_CONFIRM_S:
            up_for = now - self.lifted_at
            self.lifted = False
            self.alerts.resolve("lift-stuck")
            if up_for >= RESET_AFTER_S:
                self.mapper.reset()
                self.resets += 1
                self.robot.log("info", f"Put down after {up_for:.1f} s: new map started")
                self.say("New spot! Starting a fresh map.", "chatter")
            else:
                self.robot.log("info", "Back on the desk (short lift): mapping resumed")
            self.mapper.paused = False
        elif self.lifted and now - self.lifted_at > STUCK_WARN_S and cond == "air":
            self.alerts.warn("lift-stuck", "Both edge sensors see no desk for two minutes. "
                                           "Am I lifted, or are the IR sensors unplugged?")

    def status(self):
        return {"lifted": self.lifted, "lifts": self.lifts, "map_resets": self.resets,
                "since_s": None if not self.lifted else round(time.monotonic() - self.lifted_at, 1)}
