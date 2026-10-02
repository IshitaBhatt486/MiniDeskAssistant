"""
Build the robot from the proven dashboard/ classes (4 ultrasonic sensors + IR + motors + safety loop).

    make_robot(sim=False)  -> MultiSonarRobot on MultiSonarGpioHardware (real Pi)
    make_robot(sim=True)   -> MultiSonarRobot on FusionSimHardware      (laptop)

FusionSimHardware is the 4-sonar desk simulator with objects the camera can recognise (COCO
names, heights, colours) and a `shuffle()` that moves one object while the robot isn't looking,
to demonstrate how the maps handle stale data.
"""

from __future__ import annotations

import copy
import math
import random

from multisonar import MultiSonarGpioHardware, MultiSonarRobot, MultiSonarSimHardware  # dashboard/

# label = shown on the desk card, coco = what the detector would call it, height in metres,
# flat = lies on the desk (the ultrasonic beam passes over it; only the camera can see it)
SIM_OBJECTS = [
    {"kind": "circle", "label": "Mug", "coco": "cup", "x": 0.93, "y": 0.42, "r": 0.045, "height": 0.10, "color": (42, 120, 214)},
    {"kind": "rect", "label": "Book", "coco": "book", "x": 0.14, "y": 0.44, "w": 0.24, "h": 0.17, "height": 0.04, "color": (98, 80, 214)},
    {"kind": "circle", "label": "Bottle", "coco": "bottle", "x": 1.02, "y": 0.13, "r": 0.035, "height": 0.20, "color": (122, 175, 27)},
    {"kind": "rect", "label": "Phone", "coco": "cell phone", "x": 0.30, "y": 0.06, "w": 0.07, "h": 0.14, "height": 0.01, "color": (40, 40, 40), "flat": True},
]

# The multi-process runtime (deskbot/runtime/) also simulates the user sitting across the desk, in front
# of its bottom edge, so "face the user" can be tried without hardware. Off the desk: the robot can't
# reach it; the sonars and the camera can see it.
SIM_USER = {"kind": "circle", "label": "User", "coco": "person", "x": 0.60, "y": -0.30, "r": 0.15,
            "height": 0.22, "color": (60, 90, 200), "user": True}
RUNTIME_SIM_OBJECTS = SIM_OBJECTS + [SIM_USER]


class FusionSimHardware(MultiSonarSimHardware):
    def reset(self):
        super().reset()
        with self._lock:
            self.OBSTACLES = copy.deepcopy(SIM_OBJECTS)  # per instance; also undoes shuffle()

    def _hits(self, px, py, inflate=0.0):
        if py >= self.DESK_H - inflate:  # wall
            return True
        for ob in self.OBSTACLES:
            if ob.get("flat"):
                continue
            if ob["kind"] == "circle":
                if math.hypot(px - ob["x"], py - ob["y"]) <= ob["r"] + inflate:
                    return True
            elif (ob["x"] - inflate <= px <= ob["x"] + ob["w"] + inflate
                  and ob["y"] - inflate <= py <= ob["y"] + ob["h"] + inflate):
                return True
        return False

    def shuffle(self, label="Mug", rng=random):
        """Move one object to a random free spot on the desk. Returns (label, x, y)."""
        with self._lock:
            ob = next(o for o in self.OBSTACLES if o["label"] == label)
            others = [o for o in self.OBSTACLES if o is not ob]
            for _ in range(200):
                x = rng.uniform(0.1, self.DESK_W - 0.1)
                y = rng.uniform(0.1, self.DESK_H - 0.12)
                if math.hypot(x - self.x, y - self.y) < 0.25:
                    continue
                ob_backup = dict(ob)
                if ob["kind"] == "circle":
                    ob["x"], ob["y"] = x, y
                else:
                    ob["x"], ob["y"] = x - ob["w"] / 2, y - ob["h"] / 2
                self.OBSTACLES = others  # test the spot against the other objects only
                clash = self._hits(x, y, 0.08)
                self.OBSTACLES = others + [ob]
                if not clash:
                    return label, x, y
                ob.update(ob_backup)
            return label, ob["x"], ob["y"]


def make_robot(sim=False):
    """(robot, hardware). Raises if the GPIO hardware can't be opened."""
    hw = FusionSimHardware() if sim else MultiSonarGpioHardware()
    return MultiSonarRobot(hw), hw
