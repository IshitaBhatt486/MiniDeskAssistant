"""
Closed-loop control: the robot corrects itself from what its sensors and camera report (simple-pid).

    MotionTrim         runs during ordinary timed moves (dashboard, voice, gestures), 25 Hz
        heading PID    gyro yaw -> left/right wheel difference, so "forward" really is straight
        rate PID       measured turn rate -> speed scale, so turns keep their speed as the battery sags
        slow-down      front/rear sonar -> speed scale near obstacles
        stall check    a commanded turn with no rotation -> the robot stops and reports it

    ClosedLoopFaceUser  replaces the timed "turn a bit, look again" behaviour when the IMU is available
        yaw PID         (camera bearing + gyro heading) -> desired turn rate
        rate PID        desired vs measured turn rate -> wheel command (cascade)
        distance PID    front sonar -> forward/backward speed (optional: keep_distance)

Camera results are late, so a bearing is added to the heading the robot had WHEN THE FRAME WAS TAKEN.
The gyro then carries the loop at 25 Hz between frames, which is what removes the overshoot of acting on
old images. Everything is sent through the motor process, which keeps applying every safety rule.
Without an IMU, facing falls back to the original timed behaviour and only the sonar slow-down remains.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

import numpy as np
from simple_pid import PID

from ..runtime.behaviour import FaceUser, pick_user, turn_rate
from ..runtime.shared import DIRECTIONS, STATES
from .shared import fresh_imu

HISTORY = 500       # ~20 s at 25 Hz, for the dashboard plot and saved figures


def motor_status(robot):
    m = robot.motor_state()
    if math.isnan(m["state"]):
        return {"state": "idle", "direction": None, "drive": False, "seq": 0}
    d = int(m["direction"]) if m["direction"] == m["direction"] else -1
    return {"state": STATES[int(m["state"])], "direction": DIRECTIONS[d] if d >= 0 else None,
            "drive": m["drive"] == 1.0, "seq": m["cmd_seq"]}


def _pid(kp, ki, kd, low, high):
    return PID(kp, ki, kd, setpoint=0.0, output_limits=(low, high), sample_time=None)


class MotionTrim:
    def __init__(self, robot, cfg, calibration=None, on_stall=None):
        self.robot, self.s = robot, robot.s
        self.cc = cfg.companion.control
        c = self.cc
        self.heading = _pid(c.heading_kp, c.heading_ki, c.heading_kd, -c.heading_limit, c.heading_limit)
        self.rate = _pid(c.rate_kp, c.rate_ki, c.rate_kd, c.rate_limit_low, c.rate_limit_high)
        self.on_stall = on_stall
        self.gains = (1.0, 1.0)
        self.set_calibration(calibration or {})
        self.paused = False            # during calibration: measure the raw robot
        self.enabled = c.enabled
        self.seq = None
        self.started = 0.0
        self.stall_t = None
        self.stalls = 0
        self.last = {"mode": "idle", "setpoint": None, "measured": None, "output": None, "scale": 1.0}
        self.history = deque(maxlen=HISTORY)
        self._running = False

    def set_calibration(self, cal):
        d = cal.get("drive") or {}
        self.gains = (float(d.get("left_gain", 1.0)), float(d.get("right_gain", 1.0)))

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="motion-trim", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        period = 1.0 / self.cc.hz
        while self._running:
            t0 = time.monotonic()
            try:
                self.step(t0, period)
            except Exception as exc:   # a controller bug must never stop the robot being driven safely
                self.last["mode"] = f"error: {exc}"
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    def _obstacle_scale(self, direction, reading):
        d = (reading.get("distances") or {}).get({"forward": "front", "backward": "rear"}.get(direction))
        if d is None:
            return 1.0
        c = self.cc
        f = (d - self.robot.stop_distance) / c.slow_zone_m
        return max(c.min_speed_scale, min(1.0, f))

    def step(self, now, dt):
        m = motor_status(self.robot)
        lg, rg = self.gains
        left, right = lg, rg
        active = self.enabled and not self.paused and m["state"] == "moving" and not m["drive"]
        if self.paused:
            left, right = 1.0, 1.0
        if active:
            imu = fresh_imu(self.s, now)
            if m["seq"] != self.seq:
                self.seq, self.started, self.stall_t = m["seq"], now, None
                self.heading.reset()
                self.rate.reset()
                self.heading.setpoint = imu["yaw"] if imu else 0.0
            d = m["direction"]
            scale = 1.0
            if d in ("forward", "backward"):
                scale = self._obstacle_scale(d, self.robot.latest_reading())
                out = 0.0
                if imu:
                    out = float(self.heading(imu["yaw"], dt=dt))    # + = turn left
                    self._record(now, "heading", self.heading.setpoint, imu["yaw"], out)
                sign = 1.0 if d == "forward" else -1.0
                left, right = lg * scale * (1 - sign * out), rg * scale * (1 + sign * out)
            elif imu:
                target = turn_rate(self.robot.speed)
                measured = abs(imu["gz"])
                self.rate.setpoint = target
                out = float(self.rate(measured, dt=dt))
                scale = 1.0 + out
                left, right = scale, scale
                self._record(now, "turn rate", target, measured, out)
                self._check_stall(now, measured, target)
            self.last["scale"] = round(scale, 2)
        else:
            self.seq = None
            self.last.update(mode="idle", scale=1.0)
        self.s.control.write(t=now, left=left, right=right)

    def _record(self, now, mode, setpoint, measured, output):
        self.last.update(mode=mode, setpoint=round(setpoint, 3), measured=round(measured, 3), output=round(output, 3))
        self.history.append((now, mode, setpoint, measured, output))

    def _check_stall(self, now, measured, target):
        c = self.cc
        if measured >= c.stall_fraction * target or now - self.started < 0.3:
            self.stall_t = None
            return
        self.stall_t = self.stall_t or now
        if now - self.stall_t >= c.stall_after_s:
            self.stall_t = None
            self.stalls += 1
            self.robot.stop(source="auto")
            self.robot.log("warn", "Commanded a turn but the gyro saw no rotation: stopped (wheels stuck or battery low?)")
            if self.on_stall:
                self.on_stall()

    def status(self):
        return {**self.last, "enabled": self.enabled, "stalls": self.stalls, "paused": self.paused,
                "gains": [round(g, 3) for g in self.gains]}


class ClosedLoopFaceUser(FaceUser):
    """FaceUser with the same switch and status, but continuous PID control while the IMU is working."""
    LOOP_HZ = 20.0

    def __init__(self, robot, vision, mapper, cfg):
        super().__init__(robot, vision, mapper, cfg)
        self.cc = cfg.companion.control
        c = self.cc
        self.s = robot.s
        self.image_size = (cfg.camera.width, cfg.camera.height)
        self.yaw_pid = _pid(c.yaw_kp, c.yaw_ki, c.yaw_kd, -c.max_turn_rate, c.max_turn_rate)
        self.rate_pid = _pid(c.face_rate_kp, c.face_rate_ki, 0.0, -c.face_pwm_limit, c.face_pwm_limit)
        self.dist_pid = _pid(c.distance_kp, c.distance_ki, c.distance_kd, -c.distance_limit, c.distance_limit)
        self.dist_pid.setpoint = c.distance_m
        self.keep_distance = c.keep_distance
        self.min_pwm = 0.0
        self.paused = False
        self.yaws = deque(maxlen=60)       # (t, yaw): ~3 s, to look up the heading at capture time
        self.target = None
        self.target_t = -math.inf
        self.frame_seen = None
        self.driving = False
        self.history = deque(maxlen=HISTORY)
        self.gaze = (0.0, 0.0)
        self.user_seen_t = -math.inf

    def set_calibration(self, cal):
        self.min_pwm = float((cal.get("drive") or {}).get("min_turn_pwm", 0.0))

    def _loop(self):
        while self._running:
            t0 = time.monotonic()
            try:
                self.step(t0)
            except Exception as exc:
                self.state = f"error: {exc}"
            time.sleep(max(0.0, 1.0 / self.LOOP_HZ - (time.monotonic() - t0)))

    def _update_gaze(self, user):
        """Where the eyes should look: the upper part of the person's box, -1..1 in the image."""
        w, h = self.image_size
        x1, y1, x2, y2 = user.box
        self.gaze = (max(-1.0, min(1.0, ((x1 + x2) / 2 - w / 2) / (w / 2))),
                     max(-1.0, min(1.0, ((y1 + 0.2 * (y2 - y1)) - h / 2) / (h / 2))))

    def yaw_at(self, t):
        if not self.yaws:
            return None
        ts, ys = zip(*self.yaws)
        return float(np.interp(t, ts, ys))

    def _halt(self):
        if self.driving:
            self.robot.drive(0.0, 0.0)
            self.driving = False
            self.yaw_pid.reset()
            self.rate_pid.reset()
            self.dist_pid.reset()

    def _observe(self, now, imu):
        res = self.vision.latest()
        if res is None or res.seq == self.frame_seen:
            return
        self.frame_seen = res.seq
        user = pick_user(res.detections)
        if user is None:
            return
        self.user_seen_t = self.last_seen = now
        self._update_gaze(user)
        self.scanned_deg, self.give_up_until = 0.0, 0.0
        bearing = self.cam.bearing((user.box[0] + user.box[2]) / 2)
        self.bearing_deg = math.degrees(bearing)
        if imu is not None:
            then = self.yaw_at(res.t_capture)
            self.target = (imu["yaw"] if then is None else then) + bearing
            self.target_t = now

    def step(self, now):
        imu = fresh_imu(self.s, now)
        if imu is not None:
            self.yaws.append((imu["t"], imu["yaw"]))
        self._observe(now, imu)
        if self.paused:
            self._halt()
            self.state = "paused"
            return
        if imu is None or not self.enabled:
            self._halt()
            if int(now * self.LOOP_HZ) % 4 == 0:   # the original logic expects 5 Hz
                super().step(now)
            return
        m = motor_status(self.robot)
        if m["state"] == "moving" and not m["drive"]:
            self.driving = False
            self.state = "robot busy"
            return
        if now - self.robot.last_user_command < self.rcfg.user_hold_s:
            self._halt()
            self.state = "user in control"
            return
        if self.target is None or now - self.target_t > self.LOST_AFTER_S:
            self._halt()
            if int(now * self.LOOP_HZ) % 4 == 0:
                super().step(now)     # search with timed turns, as before
            return
        self._track(now, imu)

    def _track(self, now, imu):
        c = self.cc
        dt = 1.0 / self.LOOP_HZ
        error = self.target - imu["yaw"]
        forward = self._distance_output(error, dt)
        aligned = abs(error) <= math.radians(c.face_deadband_deg)
        if aligned and forward == 0.0:
            self._halt()
            self.state = "facing user"
            return
        turn = 0.0
        desired = 0.0
        if not aligned:
            self.yaw_pid.setpoint = self.target
            desired = float(self.yaw_pid(imu["yaw"], dt=dt))
            per_pwm = turn_rate(1.0)                   # rad/s of turn per unit of wheel command
            self.rate_pid.setpoint = desired
            turn = desired / per_pwm + float(self.rate_pid(imu["gz"], dt=dt))
            if self.min_pwm:
                turn += math.copysign(self.min_pwm, turn)
            turn = max(-c.face_pwm_limit, min(c.face_pwm_limit, turn))
        self.robot.drive(forward - turn, forward + turn)
        self.turns += int(not self.driving)
        self.driving = True
        self.state = "tracking user"
        self.history.append((now, "yaw", self.target, imu["yaw"], desired))

    def _distance_output(self, error, dt):
        c = self.cc
        if not self.keep_distance or abs(error) > math.radians(10):
            return 0.0
        d = (self.robot.latest_reading().get("distances") or {}).get("front")
        if d is None or d >= 1.5 or abs(d - c.distance_m) < c.distance_deadband_m:
            return 0.0
        return -float(self.dist_pid(d, dt=dt))         # farther than the setpoint -> drive forward

    def status(self):
        return {**super().status(), "keep_distance": self.keep_distance,
                "closed_loop": fresh_imu(self.s, time.monotonic()) is not None}
