"""
Owner recognition: the robot learns your face so it can greet you and tell you apart from visitors.

Models (OpenCV, opencv_zoo, Apache-2.0; downloaded once into models/): YuNet finds faces (shared with focus mode),
SFace (face_recognition_sface_2021dec.onnx, 37 MB) turns an aligned face into 128 numbers. Two faces are the same
person when the cosine similarity of their numbers is >= MATCH (0.363, OpenCV's published threshold for SFace).

    "learn my face"   ~8 s: look at the robot, turn your head a little; samples are taken every 0.4 s while exactly
                      one clear face (>= 60 px, detector score >= 0.8) is in view; 8+ samples are needed, 20 kept
    "this is Arjun, learn his face" / the dashboard: other people, as "friend"
    "forget my face" / the dashboard's Forget: deletes that person's numbers

What is stored: only the numbers (data/faces/people.json, mode 0600), never a picture. They stay on the robot: not
sent to Claude, Telegram or anywhere. Use: greeting ("Welcome back, <name>!" after 30+ minutes away), guard mode
(the owner disarms it just by being seen), and a line in the AI's context ("<name> is at the desk").

Accuracy: the camera runs at 320x240, so faces must be within about a metre and lit from the front. It's a
convenience, not a lock: a good photo of you could fool it.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SFACE = "face_recognition_sface_2021dec.onnx"
SFACE_URL = f"https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/{SFACE}"
MATCH = 0.363
MIN_FACE_PX, MIN_SCORE = 60, 0.8
SAMPLES_NEEDED, SAMPLES_KEPT = 8, 20
WELCOME_AFTER_S = 1800


class Faces:
    def __init__(self, path: Path, analyzer, models_dir: Path, download=lambda: True, log=print):
        self.path = Path(path)
        self.analyzer = analyzer            # hub/focus.py FaceAnalyzer (YuNet)
        self.model_path = Path(models_dir) / SFACE
        self.download = download
        self.log = log
        self.rec = None
        self.error = None
        self.people = {}                    # name -> {"role", "features": [[128]], "added"}
        self.enrolling = None
        self.seen = {}                      # name -> last seen (monotonic)
        self.now_here = []                  # [{"name" | None, "similarity"}]
        self._lock = threading.Lock()
        if self.path.exists():
            try:
                self.people = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.people = {}

    def ready(self):
        if self.rec is not None:
            return True
        try:
            import cv2
            if not self.analyzer.ready():
                raise RuntimeError(self.analyzer.error or "no face detector")
            if not self.model_path.exists():
                if not self.download():
                    raise RuntimeError(f"no face model at {self.model_path} (local-only mode: download it first)")
                self.log(f"Downloading the face recognition model (37 MB) to {self.model_path}")
                with urllib.request.urlopen(urllib.request.Request(SFACE_URL, headers={"User-Agent": "deskbot/1.0"}), timeout=120) as r:
                    data = r.read(60_000_000)
                if len(data) < 30_000_000:
                    raise RuntimeError("the face model download looks wrong")
                self.model_path.write_bytes(data)
            self.rec = cv2.FaceRecognizerSF.create(str(self.model_path), "")
            self.error = None
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            return False

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.people, f)
        tmp.replace(self.path)

    def features(self, image, face):
        import numpy as np
        aligned = self.rec.alignCrop(image, np.array(face[:15], dtype=np.float32))
        return self.rec.feature(aligned).flatten().tolist()

    def similarity(self, a, b):
        import numpy as np
        a, b = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
        return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    def identify_features(self, feat):
        """(name or None, best similarity)."""
        best, name = 0.0, None
        for person, rec in self.people.items():
            for f in rec["features"]:
                s = self.similarity(feat, f)
                if s > best:
                    best, name = s, person
        return (name if best >= MATCH else None), round(best, 3)

    def identify(self, image):
        """[{"name" | None, "similarity", "box"}] for every clear face in the image."""
        if not self.ready():
            return []
        out = []
        for face in self.analyzer.faces(image):
            if face[2] < MIN_FACE_PX * 0.7 or face[-1] < MIN_SCORE * 0.9:
                continue
            name, sim = self.identify_features(self.features(image, face))
            out.append({"name": name, "similarity": sim, "box": [round(v) for v in face[:4]]})
        return out

    # -- learning --

    def enroll(self, name, role, frames, seconds=8.0, sleep=time.sleep):
        """frames(): the newest camera image. Returns the number of samples kept. Raises ValueError if too few."""
        if not self.ready():
            raise ValueError(f"face recognition isn't available ({self.error})")
        name = " ".join(str(name).split())[:30] or "owner"
        samples, end = [], time.monotonic() + seconds
        self.enrolling = {"name": name, "samples": 0}
        try:
            while time.monotonic() < end and len(samples) < SAMPLES_KEPT:
                img = frames()
                if img is not None:
                    faces = [f for f in self.analyzer.faces(img) if f[2] >= MIN_FACE_PX and f[-1] >= MIN_SCORE]
                    if len(faces) == 1:
                        samples.append(self.features(img, faces[0]))
                        self.enrolling["samples"] = len(samples)
                sleep(0.4)
        finally:
            self.enrolling = None
        if len(samples) < SAMPLES_NEEDED:
            raise ValueError(f"I only got {len(samples)} good looks at you; I need {SAMPLES_NEEDED}. "
                             "Sit about half a metre away, facing me, in good light")
        with self._lock:
            if role == "owner":
                for p in [p for p, r in self.people.items() if r["role"] == "owner" and p != name]:
                    self.people[p]["role"] = "friend"        # one owner
            self.people[name] = {"role": role, "features": samples, "added": datetime.now().isoformat(timespec="seconds")}
            self._save()
        return len(samples)

    def forget(self, name):
        with self._lock:
            if name not in self.people:
                raise LookupError(f"I don't know {name!r}")
            del self.people[name]
            self._save()

    def owner(self):
        return next((p for p, r in self.people.items() if r["role"] == "owner"), None)

    # -- watching (called at 1-2 Hz with the newest frame) --

    def watch(self, image, now=None):
        """Returns a list of names that just arrived (for greetings)."""
        now = time.monotonic() if now is None else now
        found = self.identify(image) if image is not None and self.people else []
        self.now_here = found
        arrived = []
        for f in found:
            if f["name"]:
                if now - self.seen.get(f["name"], -1e9) > WELCOME_AFTER_S:
                    arrived.append(f["name"])
                self.seen[f["name"]] = now
        return arrived

    def owner_here(self, within=3.0):
        o = self.owner()
        return bool(o and time.monotonic() - self.seen.get(o, -1e9) < within)

    def context_lines(self):
        if not self.now_here:
            return []
        names = [f["name"] for f in self.now_here if f["name"]]
        unknown = sum(1 for f in self.now_here if not f["name"])
        bits = [f"{n} ({self.people[n]['role']})" for n in names] + ([f"{unknown} person I don't know"] if unknown else [])
        return ["Faces I recognise at the desk now: " + ", ".join(bits) + "."]

    def status(self):
        return {"ready": self.rec is not None, "error": self.error, "enrolling": self.enrolling,
                "people": [{"name": p, "role": r["role"], "samples": len(r["features"]), "added": r["added"]} for p, r in self.people.items()],
                "here": [{"name": f["name"], "similarity": f["similarity"]} for f in self.now_here]}
