"""
Idle behaviour: keep the camera facing the user.

The camera is fixed to the chassis, so "facing the user" means turning the robot in place. Runs in the
navigation process at 5 Hz and only acts when the robot has nothing else to do:

    * not while a move is running (any source)
    * not for `user_hold_s` (8 s) after a command from the dashboard: the user is in control
    * only on a camera frame captured AFTER the last turn finished (no reacting to stale images)

What it does, in order:
    1. a person is in view            -> turn toward the nearest one (largest box) if they're more than
                                         `face_deadband_deg` off centre
    2. not in view, but the semantic  -> turn toward where the user was last mapped, if more than
       map remembers a person            `face_search_deg` away
    3. never seen                     -> look around: up to one full turn in ~35 deg steps, pausing to let
                                         the detector look; then give up for 60 s

Turns are sent as ordinary "auto" commands, so the motor process applies every safety rule (IR edges,
side sonars), and any dashboard command replaces them instantly (newest command wins).
Turn length = gain x angle / turn rate, where turn rate comes from the same odometry calibration as the
map (dashboard/mapping.py). gain < 1 avoids overshoot: the next frame corrects the rest.
"""

from __future__ import annotations

import math
import threading
import time

from mapping import TRACK_WIDTH, WHEEL_SPEED_AT_FULL  # dashboard/

from ..vision.geometry import CameraModel


def turn_rate(speed):
    """Robot yaw rate (rad/s) turning in place at this PWM speed."""
    return 2 * speed * WHEEL_SPEED_AT_FULL / TRACK_WIDTH


def plan_turn(bearing, speed, rcfg, deadband_deg=None):
    """bearing (rad, + = left) -> (direction, seconds) or None if within the deadband."""
    deadband = math.radians(rcfg.face_deadband_deg if deadband_deg is None else deadband_deg)
    if abs(bearing) <= deadband:
        return None
    seconds = rcfg.face_gain * abs(bearing) / turn_rate(speed)
    seconds = min(rcfg.face_max_turn_s, max(rcfg.face_min_turn_s, seconds))
    return ("left" if bearing > 0 else "right"), round(seconds, 3)


def pick_user(detections):
    """The nearest person = the largest 'person' box, or None."""
    people = [d for d in detections if d.label == "person"]
    if not people:
        return None
    return max(people, key=lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]))


class FaceUser:
    SCAN_STEP_DEG = 35.0
    SCAN_PAUSE_S = 1.2
    GIVE_UP_S = 60.0
    LOST_AFTER_S = 2.0

    def __init__(self, robot, vision, mapper, cfg):
        self.robot, self.vision, self.mapper = robot, vision, mapper
        self.rcfg = cfg.runtime
        self.cam = CameraModel(cfg.camera)
        self.enabled = cfg.runtime.face_user and vision is not None
        self.state = "off" if not self.enabled else "starting"
        self.last_turn_end = 0.0
        self.scanned_deg = 0.0
        self.give_up_until = 0.0
        self.turns = 0
        self.bearing_deg = None
        self.last_seen = float("-inf")   # a missed detection or two must not start a search
        self._running = False

    def set_enabled(self, on):
        self.enabled = bool(on) and self.vision is not None
        self.state = "idle" if self.enabled else "off"
        self.scanned_deg = 0.0
        self.give_up_until = 0.0

    def status(self):
        return {"enabled": self.enabled, "state": self.state, "turns": self.turns,
                "bearing_deg": None if self.bearing_deg is None else round(self.bearing_deg, 1),
                "available": self.vision is not None}

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="face-user", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.step(time.monotonic())
            except Exception as exc:  # behaviour must never take the robot down
                self.state = f"error: {exc}"
            time.sleep(0.2)

    def _turn(self, direction, seconds, now, why):
        if why != self.state:
            self.robot.log("info", f"[auto] {why}")
        self.robot.move(direction, seconds, source="auto")
        self.last_turn_end = now + seconds
        self.turns += 1
        self.state = why

    def step(self, now):
        if not self.enabled:
            self.state = "off"
            return
        if self.robot.busy():
            self.state = "robot busy"
            return
        if now - self.robot.last_user_command < self.rcfg.user_hold_s:
            self.state = "user in control"
            return
        res = self.vision.latest()
        # a frame captured after the last turn ended (+ settle), so we don't react to the old view
        if res is None or res.t_capture < self.last_turn_end + 0.15:
            return
        speed = self.robot.speed

        user = pick_user(res.detections)
        if user is not None:
            self.last_seen = now
            self.scanned_deg = 0.0
            self.give_up_until = 0.0
            b = self.cam.bearing((user.box[0] + user.box[2]) / 2)
            self.bearing_deg = math.degrees(b)
            plan = plan_turn(b, speed, self.rcfg)
            if plan is None:
                self.state = "facing user"
            else:
                self._turn(*plan, now, "turning to user")
            return

        if now - self.last_seen < self.LOST_AFTER_S:
            return  # just lost them for a frame or two: keep facing that way

        # remembered position from the semantic map
        b = self._remembered_bearing(now)
        if b is not None and abs(math.degrees(b)) > self.rcfg.face_search_deg:
            self.bearing_deg = math.degrees(b)
            plan = plan_turn(b, speed, self.rcfg, deadband_deg=self.rcfg.face_search_deg)
            if plan:
                self._turn(*plan, now, "turning to last seen user")
                return

        # look around
        if now < self.give_up_until:
            self.state = "no user found (waiting)"
            return
        if self.scanned_deg >= 360:
            self.give_up_until = now + self.GIVE_UP_S
            self.scanned_deg = 0.0
            self.state = "no user found (waiting)"
            return
        if now - self.last_turn_end < self.SCAN_PAUSE_S:
            self.state = "looking for user"
            return
        step = math.radians(self.SCAN_STEP_DEG)
        seconds = min(self.rcfg.face_max_turn_s * 2, step / turn_rate(speed))
        self.scanned_deg += math.degrees(seconds * turn_rate(speed))
        self._turn("left", round(seconds, 3), now, "looking for user")

    def _remembered_bearing(self, now):
        m = self.mapper
        if m is None:
            return None
        with m._lock:
            people = [lm for lm in m.sem.objects.values() if lm.label == "person" and m.sem.existence(lm, now) > 0]
            if not people:
                return None
            lm = max(people, key=lambda l: m.sem.existence(l, now))
            o = m.odom
            return math.atan2(math.sin(math.atan2(lm.y - o.y, lm.x - o.x) - o.theta),
                              math.cos(math.atan2(lm.y - o.y, lm.x - o.x) - o.theta))
