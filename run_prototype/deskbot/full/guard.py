"""
Guard mode: while you're away, the robot watches the desk. Anyone else who sits down is asked who they are, and
you get a snapshot on Telegram.

    "guard my desk" / "stop guarding" / the dashboard; or automatically when your phone leaves (settings auto_arm)

States: off -> armed -> (someone there) challenging -> armed (cool-down) ... -> off
    armed        2 Hz: a person box (score >= 0.6, >= 4 % of the image) for 1.5 s starts a challenge, unless the
                 owner is recognised (owner recognition) or your phone comes back: then it disarms ("Welcome back!")
    challenging  the robot turns to them, its eyes go curious, and it says: "Hi! I'm guarding this desk for my owner.
                 Who are you? Please say your name." It listens for 5 s (the robot mic; the wake word pauses).
                 - they say the guard passphrase (settings, if set) -> "Thanks, you're on the list." -> off
                 - otherwise -> "Thanks! I'll take a quick photo for my owner." -> snapshot + Telegram + log
    cool-down    COOLDOWN_S (2 min) before it asks again; at most MAX_PER_HOUR snapshots an hour

Snapshots: data/guard/<date>_<time>.jpg (the camera frame with the detector's boxes) + one events.jsonl line each
(time, what they said, owner seen?). Kept KEEP_DAYS (7) days, then deleted. Never sent to Claude; sent to Telegram
only if the Telegram bot is paired. The robot announces the photo, so nobody is photographed secretly.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

PERSON_S = 1.5
COOLDOWN_S = 120.0
MAX_PER_HOUR = 10
KEEP_DAYS = 7
LISTEN_S = 5.0


class Guard:
    def __init__(self, folder: Path, say, snapshot, listen=None, notify=None, react=None, face_user=None,
                 owner_here=lambda: False, settings=lambda: {"passphrase": "", "auto_arm": False}, wait_quiet=lambda: None,
                 clock=time.monotonic, wall=datetime.now):
        self.folder = Path(folder)
        self.say, self.snapshot = say, snapshot          # snapshot() -> jpeg bytes or None
        self.listen = listen                             # listen(seconds) -> transcript ("" if none)
        self.notify = notify or (lambda text, jpeg: None)
        self.react = react or (lambda emotion, seconds, why: None)
        self.face_user = face_user or (lambda: None)
        self.owner_here = owner_here
        self.settings = settings
        self.wait_quiet = wait_quiet
        self.clock, self.wall = clock, wall
        self.state = "off"
        self.armed_by = None
        self.person_since = None
        self.cooldown_until = 0.0
        self.shots = []                                   # monotonic times of snapshots
        self.events = []
        self._busy = False

    def arm(self, by="asked"):
        if self.state != "off":
            return False
        self.state, self.armed_by, self.person_since = "armed", by, None
        self.prune()
        return True

    def disarm(self, why="asked"):
        if self.state == "off":
            return False
        self.state, self.armed_by = "off", None
        self._log({"event": "disarmed", "why": why})
        return True

    def step(self, detections, image_area, present=False):
        """2 Hz. detections: [(label, score, box)]; present: the owner's phone is near (presence awake)."""
        if self.state == "off" or self._busy:
            return None
        now = self.clock()
        if self.owner_here():
            self.disarm("owner recognised")
            self.say("Welcome back! I kept an eye on things.")
            return "disarmed"
        if self.armed_by == "phone left" and present:
            self.disarm("phone back")
            return "disarmed"
        someone = any(d[0] == "person" and d[1] >= 0.6 and (d[2][2] - d[2][0]) * (d[2][3] - d[2][1]) >= 0.04 * image_area
                      for d in detections)
        if not someone:
            self.person_since = None
            return None
        if self.person_since is None:
            self.person_since = now
        if now - self.person_since < PERSON_S or now < self.cooldown_until:
            return None
        self._busy = True
        threading.Thread(target=self._challenge, name="guard", daemon=True).start()
        return "challenging"

    def _challenge(self):
        try:
            self.state = "challenging"
            self.face_user()
            self.react("curious", 8.0, "guarding")
            self.say("Hi! I'm guarding this desk for my owner. Who are you? Please say your name.")
            self.wait_quiet()
            heard = ""
            if self.listen is not None:
                try:
                    heard = (self.listen(LISTEN_S) or "").strip()
                except Exception:
                    heard = ""
            phrase = (self.settings().get("passphrase") or "").strip().lower()
            if phrase and phrase in heard.lower():
                self.say("Thanks, you're on the list. I'll stop guarding.")
                self._log({"event": "passphrase", "heard": heard})
                self.state = "armed"
                self.disarm("passphrase")
                return
            self.react("annoyed", 5.0, "unknown visitor")
            recent = [t for t in self.shots if self.clock() - t < 3600]
            self.shots = recent
            jpeg, file = None, None
            if len(recent) < MAX_PER_HOUR:
                self.say("Thanks! I'll take a quick photo for my owner.")
                time.sleep(1.0)
                jpeg = self.snapshot()
                if jpeg:
                    self.folder.mkdir(parents=True, exist_ok=True)
                    file = self.wall().strftime("%Y-%m-%d_%H-%M-%S") + ".jpg"
                    (self.folder / file).write_bytes(jpeg)
                    self.shots.append(self.clock())
            said = f"They said: \"{heard}\"." if heard else "They didn't say anything I could hear."
            self.notify(f"Someone is at your desk ({self.wall().strftime('%H:%M')}). {said}", jpeg)
            self._log({"event": "visitor", "heard": heard, "photo": file})
            self.state = "armed"
            self.cooldown_until = self.clock() + COOLDOWN_S
        finally:
            self._busy = False

    def _log(self, ev):
        ev = {"t": self.wall().isoformat(timespec="seconds"), **ev}
        self.events.append(ev)
        self.events = self.events[-50:]
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.folder / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        except OSError:
            pass

    def prune(self):
        if not self.folder.exists():
            return
        limit = (self.wall() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for p in self.folder.glob("*.jpg"):
            if p.name[:10] < limit:
                p.unlink(missing_ok=True)

    def photos(self, limit=12):
        if not self.folder.exists():
            return []
        return [p.name for p in sorted(self.folder.glob("*.jpg"), reverse=True)[:limit]]

    def photo(self, name):
        import re
        if not re.fullmatch(r"[\d_\-]+\.jpg", name or ""):
            return None
        p = self.folder / name
        return p if p.exists() else None

    def delete_photos(self):
        for p in self.folder.glob("*.jpg") if self.folder.exists() else []:
            p.unlink(missing_ok=True)

    def status(self):
        s = self.settings()
        return {"state": self.state, "armed_by": self.armed_by, "events": self.events[-10:][::-1], "photos": self.photos(),
                "passphrase_set": bool(s.get("passphrase")), "auto_arm": s.get("auto_arm", False)}
