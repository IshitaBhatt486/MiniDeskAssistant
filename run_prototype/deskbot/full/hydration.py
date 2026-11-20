"""
Hydration buddy: counts your drinks and reminds you when you haven't had one for a while.

Seeing a drink (camera, YOLO classes bottle / cup / wine glass, at 2 Hz):
    raised   a container overlaps the top 35 % of your (person) box for RAISE_S (0.6 s): a cup at your mouth
    lifted   a container that sat in one place disappears for 2-40 s and comes back near the same place
             (picked up and put down, often out of the camera's view)
Either counts as one drink, at most once per COOLDOWN_S (2 min). Say "I drank some water" (or press +1 on the
dashboard) to count one yourself. A day's log: data/hydration.json {"2026-11-19": [times]}.

Reminders: while you're at the desk and not in a focus session (it waits for the break), with no drink for
interval_min (45), the robot says so (pop sound, curious eyes) and then every 30 minutes, between 08:00 and 22:00.
Daily goal: 8 drinks (settings).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

CONTAINERS = ("bottle", "cup", "wine glass")
RAISE_S = 0.6
COOLDOWN_S = 120.0
LIFT_MIN_S, LIFT_MAX_S = 2.0, 40.0
REPEAT_MIN = 30
LINES = ["Time for some water!", "Sip break! When did you last drink something?", "Your water misses you. Have a sip!"]


def overlap(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


class Hydration:
    def __init__(self, path: Path, settings=lambda: {"interval_min": 45, "goal": 8, "start": "08:00", "end": "22:00"},
                 on_drink=None, on_remind=None, clock=time.monotonic, wall=datetime.now):
        self.path = Path(path)
        self.settings = settings
        self.on_drink = on_drink or (lambda how: None)
        self.on_remind = on_remind or (lambda line: None)
        self.clock, self.wall = clock, wall
        self.log = {}
        self.raise_since = None
        self.parked = {}              # label -> (centre, last seen)
        self.missing = {}             # label -> (centre, since)
        self.last_drink = None        # monotonic
        self.last_remind = None
        self.n_remind = 0
        if self.path.exists():
            try:
                self.log = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.log = {}
        today = self.log.get(self.wall().date().isoformat())
        if today:
            ago = (self.wall() - datetime.fromisoformat(today[-1])).total_seconds()
            self.last_drink = self.clock() - max(0.0, ago)

    def _save(self):
        try:
            keep = sorted(self.log)[-60:]
            self.log = {k: self.log[k] for k in keep}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.log, indent=1), encoding="utf-8")
        except OSError:
            pass

    def drink(self, how="said"):
        now = self.clock()
        if how != "said" and self.last_drink is not None and now - self.last_drink < COOLDOWN_S:
            return False
        self.last_drink, self.last_remind, self.n_remind = now, None, 0
        self.log.setdefault(self.wall().date().isoformat(), []).append(self.wall().isoformat(timespec="seconds"))
        self._save()
        self.on_drink(how)
        return True

    def today(self):
        return len(self.log.get(self.wall().date().isoformat(), []))

    def observe(self, detections, dt=0.5):
        """detections: [(label, score, box)]. Returns "raised" / "lifted" when a drink is seen, else None."""
        now = self.clock()
        persons = [d[2] for d in detections if d[0] == "person" and d[1] >= 0.5]
        cups = [(d[0], d[2]) for d in detections if d[0] in CONTAINERS and d[1] >= 0.35]
        # raised to the mouth
        near_mouth = False
        for p in persons:
            head = (p[0], p[1], p[2], p[1] + 0.35 * (p[3] - p[1]))
            if any(overlap(head, box) > 0.3 * (box[2] - box[0]) * (box[3] - box[1]) for _, box in cups):
                near_mouth = True
        if near_mouth:
            if self.raise_since is None:
                self.raise_since = now
            if now - self.raise_since >= RAISE_S and self.drink("raised"):
                self.raise_since = None
                return "raised"
        else:
            self.raise_since = None
        # lifted out of its place and put back
        seen = {}
        for label, box in cups:
            seen[label] = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        for label, (centre, last) in list(self.parked.items()):
            if label not in seen and now - last > 1.0 and label not in self.missing:
                self.missing[label] = (centre, now)
        for label, c in seen.items():
            if label in self.missing:
                old, since = self.missing.pop(label)
                gone = now - since
                close = abs(old[0] - c[0]) < 60 and abs(old[1] - c[1]) < 60
                if LIFT_MIN_S <= gone <= LIFT_MAX_S and close and self.drink("lifted"):
                    self.parked[label] = (c, now)
                    return "lifted"
            self.parked[label] = (c, now)
        for label, (_, since) in list(self.missing.items()):
            if now - since > LIFT_MAX_S:
                del self.missing[label]
                self.parked.pop(label, None)
        return None

    def tick(self, present=True, holding=False):
        """Remind if due. present: the owner is at the desk; holding: focus mode (wait for the break)."""
        s = self.settings()
        now, wall = self.clock(), self.wall()
        hm = wall.strftime("%H:%M")
        if not present or holding or not (s.get("start", "08:00") <= hm < s.get("end", "22:00")):
            return None
        since = (now - self.last_drink) if self.last_drink is not None else None
        if since is None:
            self.last_drink = now               # start counting from when the robot first sees you
            return None
        due = since >= s.get("interval_min", 45) * 60 and (self.last_remind is None or now - self.last_remind >= REPEAT_MIN * 60)
        if not due:
            return None
        line = LINES[self.n_remind % len(LINES)]
        self.last_remind = now
        self.n_remind += 1
        self.on_remind(line)
        return line

    def status(self):
        s = self.settings()
        ago = None if self.last_drink is None else round((self.clock() - self.last_drink) / 60)
        week = []
        for i in range(6, -1, -1):
            day = (self.wall() - timedelta(days=i)).date().isoformat()
            week.append({"date": day, "drinks": len(self.log.get(day, []))})
        return {"today": self.today(), "goal": s.get("goal", 8), "minutes_since": ago, "week": week, "settings": s}
