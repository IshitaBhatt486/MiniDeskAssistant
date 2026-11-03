"""
Picked up / put down, from the IMU and the IR edge sensors together.

Lifted when ANY of these holds for its confirm time:
    both IR sensors see no desk                     (works without the IMU)
    the robot is tilted beyond `tilt_deg`           (a desk never does this)
    motors off, yet it is being shaken or swung,    (the moment of picking up, before IR loses the desk)
    and at least one IR sensor has lost the desk

Put down when both IR sensors see the desk for `place_confirm_s` AND (with an IMU) the robot is level and still.

While lifted: motors stopped, running commands cancelled, map frozen, gestures and autonomy ignored.
After a real lift the robot is somewhere new, so LiftConfig.on_place runs, in order:
    save_figures  keep the old map      reset_map     start a new one       zero_heading  heading = 0
    greet         say something         look_around   rotate once to map    face_user     turn to the person
"""

from __future__ import annotations

import math
import time

from ..presence.lift import STUCK_WARN_S, LiftDetector
from .imu import tilt_rad
from .shared import fresh_imu, nav_bump


class ImuLiftDetector(LiftDetector):
    cfg = None           # LiftConfig, set by app.py before construction
    actions = None       # {"save_figures": fn, ...} extra actions, set by app.py
    on_change = None     # fn(lifted: bool)

    def __init__(self, robot, mapper, alerts, say, executor=None):
        super().__init__(robot, mapper, alerts, say, executor)
        self.trigger = None
        self.timers = {}
        self.place_since = None

    def _held(self, name, cond, now, need):
        """True once `cond` has been continuously true for `need` seconds."""
        if not cond:
            self.timers.pop(name, None)
            return False
        return now - self.timers.setdefault(name, now) >= need

    def _lift_reason(self, now, ff, bf, imu, motors_on):
        c = self.cfg
        if self._held("ir", not ff and not bf, now, c.lift_confirm_s):
            return "both edge sensors lost the desk"
        if imu is None:
            return None
        if self._held("tilt", tilt_rad(imu) > math.radians(c.tilt_deg), now, c.tilt_confirm_s):
            return f"tilted {math.degrees(tilt_rad(imu)):.0f} degrees"
        shaken = not motors_on and (imu["gyro_norm"] > c.shake_gyro or imu["accel_err"] > c.shake_accel)
        if self._held("shake", shaken and not (ff and bf), now, c.shake_confirm_s):
            return "moved by hand"
        return None

    def step(self, now):
        c = self.cfg
        r = self.robot.latest_reading()
        ff, bf = r.get("front_floor"), r.get("back_floor")
        if ff is None or bf is None:
            return
        imu = fresh_imu(self.robot.s, now)
        m = self.robot.motor_state()
        motors_on = m["left"] == m["left"] and (m["left"] != 0 or m["right"] != 0)

        if not self.lifted:
            reason = self._lift_reason(now, ff, bf, imu, motors_on)
            if reason:
                self._lifted(now, reason)
            return

        settled = imu is None or (tilt_rad(imu) < math.radians(c.place_tilt_deg) and imu["gyro_norm"] < 0.15
                                  and imu["accel_err"] < 0.8)
        if self._held("place", ff and bf and settled, now, c.place_confirm_s):
            self._placed(now)
        elif now - self.lifted_at > STUCK_WARN_S and not ff and not bf:
            self.alerts.warn("lift-stuck", "Both edge sensors see no desk for two minutes. "
                                           "Am I lifted, or are the IR sensors unplugged?")

    def _lifted(self, now, reason):
        self.lifted, self.lifted_at, self.trigger = True, now, reason
        self.timers.clear()
        self.lifts += 1
        if self.executor:
            self.executor.cancel()
        self.robot.stop(source="auto")
        self.mapper.paused = True
        self.robot.log("warn", f"Picked up ({reason}): motors stopped, mapping paused")
        self.say("Whoa! Put me down gently please.", "chatter")
        if self.on_change:
            self.on_change(True)

    def _placed(self, now):
        up_for = now - self.lifted_at
        self.lifted = False
        self.timers.clear()
        self.alerts.resolve("lift-stuck")
        if self.on_change:
            self.on_change(False)
        if up_for < self.cfg.reset_after_s:
            self.mapper.paused = False
            self.robot.log("info", "Back on the desk (short lift): mapping resumed")
            return
        self.resets += 1
        self.robot.log("info", f"Put down after {up_for:.1f} s: running {', '.join(self.cfg.on_place) or 'nothing'}")
        commands = []
        for name in self.cfg.on_place:
            try:
                self._action(name, commands)
            except Exception as exc:
                self.alerts.warn("lift", f"After being put down, {name} failed.", speak=False, detail=str(exc))
        self.mapper.paused = False
        if commands and self.executor:
            self.executor.run(commands, source="put down")

    def _action(self, name, commands):
        if name == "reset_map":
            self.mapper.reset()
        elif name == "zero_heading":
            nav_bump(self.robot.s.imu_ctl, "zero_seq")
            time.sleep(0.05)                 # one IMU cycle, so the map re-anchors on the new zero
            self.mapper.reanchor_heading()
        elif name == "greet":
            self.say("New spot! Let me have a look around.", "chatter")
        elif name in ("look_around", "face_user"):
            commands.append({"action": name, "amount": 0})
        elif self.actions and name in self.actions:
            self.actions[name]()
        else:
            raise ValueError(f"unknown action {name!r}")

    def status(self):
        return {**super().status(), "trigger": self.trigger if self.lifted else None,
                "on_place": list(self.cfg.on_place), "uses_imu": fresh_imu(self.robot.s, time.monotonic()) is not None}
