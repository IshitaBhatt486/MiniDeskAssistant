"""Synthetic maps with a known answer: used by the tests and by `navigate.py --compare`."""

from __future__ import annotations

import random

import numpy as np

from deskbot.config import NavigationConfig
from deskbot.navigation.costmap import Costmap, MapObject, MapView, Target


def blank(n=80, res=0.05, known=True):
    idx = np.ones((n, n), bool) if known else np.zeros((n, n), bool)
    return MapView(res, n, np.full((n, n), -1.0, np.float32), np.zeros((n, n), bool), idx, [], (0.0, 0.0, 0.0))


def add_object(view, x, y, radius=0.05, label="box", sigma=0.01, existence=3.0):
    view.objects.append(MapObject(len(view.objects) + 1, label, x, y, radius, sigma, existence))
    return view.objects[-1]


def add_wall(view, x0, y0, x1, y1):
    """Mark every geometric cell in the rectangle as solid."""
    h = view.n // 2
    c0, c1 = int(np.floor(x0 / view.res)) + h, int(np.floor(x1 / view.res)) + h
    r0, r1 = int(np.floor(y0 / view.res)) + h, int(np.floor(y1 / view.res)) + h
    view.L[r0:r1 + 1, c0:c1 + 1] = 3.0


def scene(name, cfg=None, seed=3):
    """(view, start, target, what the scene is meant to show)."""
    cfg = cfg or NavigationConfig()
    rng = random.Random(seed)
    v = blank()
    start = (-0.6, 0.0)
    goal = (0.6, 0.0)
    note = ""
    if name == "open desk":
        note = "nothing in the way"
    elif name == "one obstacle":
        add_object(v, 0.0, 0.0, 0.25)
        note = "one big object on the line"
    elif name == "few obstacles":
        for x, y in ((-0.25, 0.0), (0.0, 0.32), (0.05, -0.3)):
            add_object(v, x, y, 0.13)
        note = "three objects across the line"
    elif name == "many obstacles":
        start, goal = (-0.8, -0.1), (0.8, 0.1)
        placed = []
        for _ in range(2000):              # bounded: random placement can run out of room
            if len(placed) == 15:
                break
            x, y = rng.uniform(-0.45, 0.4), rng.uniform(-0.55, 0.55)
            if all((x - a) ** 2 + (y - b) ** 2 > 0.27 ** 2 for a, b in placed):
                placed.append((x, y))
                add_object(v, x, y, 0.03)
        note = "fifteen spread-out objects"
    elif name == "clutter":
        start, goal = (-0.85, 0.0), (0.85, 0.0)
        for i in range(-2, 3):
            for j in range(-3, 4):
                if (i + j) % 2 == 0:
                    add_object(v, i * 0.22, j * 0.22, 0.03)
        note = "a dense field of objects"
    elif name == "narrow gap":
        add_wall(v, -0.05, -2.0, 0.0, 0.14)
        add_wall(v, -0.05, 0.38, 0.0, 1.95)
        note = "a wall with one off-centre gap barely wider than the robot"
    elif name == "unexplored":
        v = blank(known=False)
        add_object(v, 0.0, 0.0, 0.2)
        note = "the floor was never observed"
    elif name == "long open route":
        v = blank(n=160)
        start, goal = (-3.0, -3.0), (3.0, 3.0)
        for x, y in ((-1.5, -1.5), (0.0, 0.0), (1.5, 1.5)):
            add_object(v, x, y, 0.25)
        note = "a long trip over a big map"
    elif name == "walled off":
        add_wall(v, -0.05, -2.0, 0.0, 1.95)
        note = "no way through"
    else:
        raise ValueError(name)
    t = add_object(v, *goal, 0.05, "target")
    target = Target("target", t.x, t.y, t.radius, t.id, t.label)
    v.pose = (start[0], start[1], 0.0)
    return v, start, target, note


SCENES = ["open desk", "one obstacle", "few obstacles", "many obstacles", "clutter", "narrow gap", "unexplored",
          "long open route", "walled off"]


NO_ROUTE_EXPECTED = {"walled off"}


def costmap_for(view, start, target, cfg=None, stop_distance=0.20, margin=None):
    return Costmap(view, cfg or NavigationConfig(), stop_distance, [start, (target.x, target.y)], margin=margin)
