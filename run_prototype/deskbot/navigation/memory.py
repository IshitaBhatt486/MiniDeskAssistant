"""
What the robot remembers about its desk between trips and restarts (data/nav_memory.json):

    home       a pose the user marked ("this is home")
    zones      no-go polygons drawn on the dashboard: the robot's body never enters them
    avoid      places where a safety rule stopped it: routes keep away from them when they can
    corridor   floor it has driven without trouble: routes prefer it

Everything is stored in map coordinates, and the map's origin is wherever the robot was when the map
started. After a restart or a map reset that origin may be somewhere else, so the memory is marked "not
aligned" and is NOT used: a no-go zone in the wrong place would be worse than an honest warning.
It becomes usable again in one of two ways:

    "this is home" with the robot back on its home spot   every stored place is moved to match
    accept()                                              the user confirms it started from the same spot
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

CELL = 0.05
MAX_ZONES = 24
MAX_AVOID = 200
MAX_MAP_M = 4.0


def _transform(x, y, old, new):
    """Rigid motion taking pose `old` onto pose `new`, applied to a point."""
    a = new[2] - old[2]
    c, s = math.cos(a), math.sin(a)
    dx, dy = x - old[0], y - old[1]
    return new[0] + c * dx - s * dy, new[1] + s * dx + c * dy


class NavMemory:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.home = None
        self.zones = []
        self.avoid = []
        self.corridor = {}
        self._next_id = 1
        self.epoch = None
        loaded = self._load()
        self.aligned = not loaded

    # -- files --

    def _load(self):
        if self.path is None or not self.path.exists():
            return False
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.home = d.get("home")
            self.zones = d.get("zones", [])
            self.avoid = d.get("avoid", [])
            self.corridor = {k: int(v) for k, v in d.get("corridor", {}).items()}
            self._next_id = 1 + max([z["id"] for z in self.zones] or [0])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return self._has_data()

    def _has_data(self):
        return bool(self.home or self.zones or self.avoid or self.corridor)

    def save(self):
        if self.path is None:
            return
        with self._lock:
            data = {"home": self.home, "zones": self.zones, "avoid": self.avoid, "corridor": self.corridor,
                    "saved": time.time()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass      # read-only SD card: the memory still works until restart

    # -- keeping coordinates honest --

    def sync(self, epoch):
        """Call with the map's epoch: a new map means a new origin."""
        if self.epoch is not None and epoch != self.epoch and self._has_data():
            self.aligned = False
        self.epoch = epoch

    def accept(self):
        self.aligned = True

    def clear(self):
        with self._lock:
            self.home, self.zones, self.avoid, self.corridor = None, [], [], {}
            self.aligned = True
        self.save()

    def mark_home(self, pose):
        """Returns True if stored places were re-aligned using the old home."""
        pose = [float(v) for v in pose]
        moved = False
        with self._lock:
            if not self.aligned and self.home:
                old = self.home
                self.zones = [{**z, "points": [list(_transform(x, y, old, pose)) for x, y in z["points"]]} for z in self.zones]
                self.avoid = [list(_transform(x, y, old, pose)) for x, y in self.avoid]
                cells = {}
                for key, n in self.corridor.items():
                    c, r = map(int, key.split(","))
                    x, y = _transform((c + 0.5) * CELL, (r + 0.5) * CELL, old, pose)
                    cells[f"{math.floor(x / CELL)},{math.floor(y / CELL)}"] = n
                self.corridor = cells
                self.aligned = moved = True
            self.home = pose
            if not (self.zones or self.avoid or self.corridor):
                self.aligned = True
        self.save()
        return moved

    # -- editing --

    def add_zone(self, points, name="no-go"):
        if not self.aligned:
            raise ValueError("The saved places don't line up with this map yet. Confirm the start spot or mark home first")
        try:
            pts = [[float(p[0]), float(p[1])] for p in points]
        except (TypeError, ValueError, IndexError):
            raise ValueError("points must be [[x, y], ...] in metres") from None
        if not 3 <= len(pts) <= 12:
            raise ValueError("A zone needs 3 to 12 points")
        if any(not (math.isfinite(x) and math.isfinite(y)) or abs(x) > MAX_MAP_M or abs(y) > MAX_MAP_M for x, y in pts):
            raise ValueError("Zone points must be on the map")
        area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2
        if area < 0.0005:
            raise ValueError("That zone is too small")
        with self._lock:
            if len(self.zones) >= MAX_ZONES:
                raise ValueError(f"At most {MAX_ZONES} zones")
            zone = {"id": self._next_id, "name": str(name)[:30], "points": pts}
            self._next_id += 1
            self.zones.append(zone)
        self.save()
        return zone

    def remove_zone(self, zone_id):
        with self._lock:
            before = len(self.zones)
            self.zones = [z for z in self.zones if z["id"] != zone_id]
            removed = len(self.zones) != before
        self.save()
        return removed

    def clear_zones(self):
        with self._lock:
            self.zones = []
        self.save()

    def add_avoid(self, x, y):
        if not self.aligned:
            return
        with self._lock:
            if all(math.hypot(x - a, y - b) > CELL for a, b in self.avoid):
                self.avoid = (self.avoid + [[x, y]])[-MAX_AVOID:]

    def visit(self, x, y):
        if self.aligned:
            key = f"{math.floor(x / CELL)},{math.floor(y / CELL)}"
            with self._lock:
                self.corridor[key] = self.corridor.get(key, 0) + 1

    # -- reading --

    def corridor_points(self, min_visits=2):
        with self._lock:
            items = list(self.corridor.items())
        out = []
        for key, n in items:
            if n >= min_visits:
                c, r = map(int, key.split(","))
                out.append([(c + 0.5) * CELL, (r + 0.5) * CELL])
        return out

    def layers(self):
        """What planning should use now (nothing while the coordinates can't be trusted)."""
        if not self.aligned:
            return None
        with self._lock:
            zones = [z["points"] for z in self.zones]
            avoid = list(self.avoid)
        return {"nogo": zones, "avoid": avoid, "corridor": self.corridor_points()}

    def status(self):
        with self._lock:
            return {"aligned": self.aligned, "home": self.home, "zones": list(self.zones), "avoid": list(self.avoid),
                    "corridor_cells": len(self.corridor)}
