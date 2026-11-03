"""
Extra shared memory of the companion runtime, on top of runtime/shared.py.

    who writes   block       read by
    ----------   -----       -------
    body         imu         nav       filtered + raw IMU, orientation, "stationary" flag
    nav          imu_ctl     body      zero the heading, reload calibration, simulated lift
    nav          control     motor     wheel gains for timed moves (ignored after 0.3 s)
    nav          face        body      emotion to show + where to look
    body         face_frame  nav       the picture on the OLED, for the dashboard
    gesture      gesture     nav       newest recognised hand gesture
    nav          gesture_ctl gesture   person in view? simulated gesture
"""

from __future__ import annotations

import threading

from ..runtime.shared import Shared
from ..runtime.shm import FrameRing, SeqBlock

_nav_lock = threading.Lock()   # several threads of the navigation process write the control blocks


def nav_write(block, **values):
    with _nav_lock:
        block.write(**values)


def nav_bump(block, field, **values):
    """Increment a counter field (and set others) as one step."""
    with _nav_lock:
        block.write(**{field: block.read()[field] + 1}, **values)

IMU_FIELDS = ["t", "ok", "ax", "ay", "az", "gx", "gy", "gz", "rax", "ray", "raz", "rgx", "rgy", "rgz",
              "roll", "pitch", "yaw", "tilt", "accel_err", "gyro_norm", "still", "temp"]
IMU_CTL_FIELDS = ["zero_seq", "reload_seq", "sim_lifted"]
CONTROL_FIELDS = ["t", "left", "right"]
FACE_FIELDS = ["emotion", "seq", "gaze_x", "gaze_y"]
GESTURE_FIELDS = ["t", "seq", "gesture", "score", "backend"]
GESTURE_CTL_FIELDS = ["person", "sim_gesture", "sim_seq"]

GESTURES = ("None", "Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Down", "Thumb_Up", "Victory", "ILoveYou")
GESTURE_BACKENDS = ("off", "mediapipe", "simulated")


class CompanionShared(Shared):
    OLED_W, OLED_H = 128, 64

    def __init__(self, width=320, height=240, sim=False):
        super().__init__(width, height, sim)
        self.imu = SeqBlock(IMU_FIELDS)
        self.imu_ctl = SeqBlock(IMU_CTL_FIELDS)
        self.control = SeqBlock(CONTROL_FIELDS)
        self.face = SeqBlock(FACE_FIELDS)
        self.face_frame = FrameRing(self.OLED_H, self.OLED_W)
        self.gesture = SeqBlock(GESTURE_FIELDS)
        self.gesture_ctl = SeqBlock(GESTURE_CTL_FIELDS)
        self.procs["body"] = SeqBlock(self.procs["motor"].fields)
        self.procs["gesture"] = SeqBlock(self.procs["motor"].fields)
        self.imu_ctl.write(zero_seq=0, reload_seq=0, sim_lifted=0)
        self.gesture_ctl.write(person=0, sim_gesture=0, sim_seq=0)


def fresh_imu(shared, now, max_age=0.3):
    """The newest IMU sample as a dict, or None if the IMU is missing or silent."""
    v = shared.imu.read()
    if v["ok"] != 1.0 or not now - v["t"] <= max_age:
        return None
    return v
