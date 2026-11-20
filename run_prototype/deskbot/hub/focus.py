"""
Focus mode: a timed work session (Pomodoro style) in which the robot watches whether you are paying attention:
looking away from your work, or holding your phone, for too long gets a gentle nudge.

    "start focus mode" / "focus for 50 minutes" / "stop focus mode" / "how am I doing?"

Placement: put the robot next to (or under) your screen, facing you. Then "looking at your work" means your
face points roughly at the robot. At the start of a session the robot measures where your face points while
you look at your screen (the first 4 s with a face in view) and uses that as "on task", so it may sit off to
one side.

What it sees, at 2 Hz (camera frames already in shared memory; nothing is saved or sent anywhere):
    face direction   OpenCV YuNet face detector (cv2.FaceDetectorYN, model models/face_detection_yunet_2023mar.onnx,
                     230 kB, downloaded once from github.com/opencv/opencv_zoo). From its 5 landmarks:
                         yaw   = (nose_x - eye_mid_x) / eye_distance          ~0 facing, +-0.5 = turned ~30 deg
                         pitch = (nose_y - eye_mid_y) / (mouth_mid_y - eye_mid_y)   bigger = head down
                     compared with the start-of-session baseline.
    phone            the YOLO detector's "cell phone" class, in front of or near the person
    person           the YOLO "person" class

Each observation is one of:
    focused     face toward the work (|yaw - base| <= 0.35 and |pitch - base| <= 0.22), no phone
    away        face turned away, or a person but no face for 3+ observations (head turned right round)
    down        face tipped well down (pitch above baseline) - reading a phone in your lap, usually
    phone       a phone seen in front of you
    absent      nobody there (left the desk): the timer keeps running, nothing counts as distraction
    unknown     no camera, or no face model: then only the phone and person checks work

Nudges: distraction time adds up while you're not focused and resets after 3 s of focus. At 20 s (GRACE_S) the
robot nudges (sound + eyes + a short line + an optional wiggle); after that, again every 45 s of continued
distraction. A phone in view nudges after 10 s. Lines escalate gently and never repeat back to back.

While focusing, phone notifications are held (buddy hold_checks) and said at the break. Task reminders still
come: you set those deadlines.

End of session: "You were focused 86 % of 25 minutes, with 2 distractions." Above 80 % the robot celebrates;
then a break (5 min by default, 15 after every fourth session) with a chime when it ends. Sessions are logged
to data/focus.json for the dashboard (today's focused minutes, last 30 sessions).
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
MODEL_NAME = "face_detection_yunet_2023mar.onnx"
HZ = 2.0
YAW_TOL, PITCH_TOL = 0.35, 0.22
BASELINE_S = 4.0
GRACE_S, REPEAT_S, PHONE_S, RESET_S = 20.0, 45.0, 10.0, 3.0
NO_FACE_AWAY_N = 3
GOOD_SESSION = 0.8

LINES = {
    "away": ["Hey, eyes back on the work!", "Psst. Your work misses you.", "Let's get back to it, you've got this.",
             "Still with me? Back to the task."],
    "down": ["Looking down a lot. Phone? Let's focus.", "Head up, champ. Back to it."],
    "phone": ["Phone down, please. Focus time!", "The phone can wait. Back to work!", "I see that phone. Let's focus."],
}


def face_angles(face):
    """(yaw, pitch) ratios from one YuNet row: x, y, w, h, right eye, left eye, nose, right mouth, left mouth, score."""
    rex, rey, lex, ley, nx, ny, rmx, rmy, lmx, lmy = face[4:14]
    eye_mid_x, eye_mid_y = (rex + lex) / 2, (rey + ley) / 2
    eye_d = max(1.0, ((rex - lex) ** 2 + (rey - ley) ** 2) ** 0.5)
    mouth_mid_y = (rmy + lmy) / 2
    return (nx - eye_mid_x) / eye_d, (ny - eye_mid_y) / max(1.0, mouth_mid_y - eye_mid_y)


class FaceAnalyzer:
    def __init__(self, models_dir: Path, download=True, log=print):
        self.path = Path(models_dir) / MODEL_NAME
        self.detector = None
        self.error = None
        self.size = None
        self.download = download
        self.log = log

    def ready(self):
        if self.detector is not None:
            return True
        if self.error:
            return False
        try:
            import cv2
            if not hasattr(cv2, "FaceDetectorYN"):
                raise RuntimeError("OpenCV is older than 4.5.4 (no FaceDetectorYN)")
            if not self.path.exists():
                if not self.download:
                    raise RuntimeError(f"no face model at {self.path}")
                self.log(f"Downloading the focus-mode face model (230 kB) to {self.path}")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "deskbot/1.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read(2_000_000)
                if not 100_000 < len(data) < 2_000_000:
                    raise RuntimeError("the face model download looks wrong")
                self.path.write_bytes(data)
            self.detector = cv2.FaceDetectorYN.create(str(self.path), "", (320, 240), 0.6, 0.3, 5)
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            self.log(f"Focus mode: face direction off ({self.error}); phone and presence checks still work")
            return False

    def faces(self, image):
        """YuNet rows for a BGR image, largest first."""
        h, w = image.shape[:2]
        if self.size != (w, h):
            self.detector.setInputSize((w, h))
            self.size = (w, h)
        _, faces = self.detector.detect(image)
        if faces is None:
            return []
        return sorted(faces.tolist(), key=lambda f: -f[2] * f[3])


def classify(detections, face, baseline, no_face_n):
    """One observation -> (state, yaw, pitch). detections: [(label, score, box)]; face: YuNet row or None."""
    persons = [d for d in detections if d[0] == "person" and d[1] >= 0.45]
    phone = any(d[0] == "cell phone" and d[1] >= 0.4 for d in detections)
    if face is None and not persons:
        return "absent", None, None
    if phone:
        return "phone", None, None
    if face is None:
        return ("away" if no_face_n >= NO_FACE_AWAY_N else "unknown"), None, None
    yaw, pitch = face_angles(face)
    by, bp = baseline or (0.0, 0.55)
    if abs(yaw - by) > YAW_TOL:
        return "away", yaw, pitch
    if pitch - bp > PITCH_TOL:
        return "down", yaw, pitch
    if bp - pitch > PITCH_TOL * 1.5:
        return "away", yaw, pitch                  # looking right up / over the screen
    return "focused", yaw, pitch


class Focus:
    def __init__(self, log_path: Path, vision=None, analyzer=None, on_nudge=None, on_end=None, on_break_end=None,
                 clock=time.monotonic, wall=datetime.now, rng=None):
        self.log_path = Path(log_path)
        self.vision, self.analyzer = vision, analyzer
        self.on_nudge = on_nudge or (lambda kind, line: None)
        self.on_end = on_end or (lambda summary: None)
        self.on_break_end = on_break_end or (lambda: None)
        self.clock, self.wall = clock, wall
        self.rng = rng or random.Random()
        self.state = "idle"                      # idle | focusing | break
        self.session = None
        self.break_until = 0.0
        self.sessions_today = 0
        self.history = []
        self._last_line = None
        self._running = False
        self._lock = threading.Lock()
        if self.log_path.exists():
            try:
                self.history = json.loads(self.log_path.read_text(encoding="utf-8"))[-200:]
            except (OSError, ValueError):
                self.history = []

    # -- sessions --

    def start(self, minutes=25, break_minutes=5):
        minutes = max(1, min(180, int(minutes or 25)))
        now = self.clock()
        with self._lock:
            self.session = {"started": now, "started_wall": self.wall().isoformat(timespec="seconds"), "minutes": minutes,
                            "break_minutes": max(1, min(60, int(break_minutes or 5))), "end": now + minutes * 60,
                            "focused_s": 0.0, "present_s": 0.0, "phone_s": 0.0, "distractions": 0,
                            "distracted_s": 0.0, "focused_streak": 0.0, "last_nudge": None, "no_face_n": 0,
                            "baseline": None, "base_samples": [], "observation": "starting", "yaw": None, "pitch": None,
                            "tracking": self.vision is not None}
            self.state = "focusing"
        return self.status()

    def stop(self, reason="stopped"):
        with self._lock:
            if self.state == "break":
                self.state, self.break_until = "idle", 0.0
                return None
            if self.state != "focusing":
                return None
            s = self.session
            done = self.clock() - s["started"]
            summary = {"date": s["started_wall"], "planned_min": s["minutes"], "minutes": round(done / 60, 1),
                       "focused_pct": round(100 * s["focused_s"] / s["present_s"]) if s["present_s"] > 30 else None,
                       "distractions": s["distractions"], "phone_s": round(s["phone_s"]), "reason": reason,
                       "tracked": s["tracking"]}
            self.history.append(summary)
            self._save()
            self.state, self.session = "idle", None
            if reason == "finished":
                self.sessions_today += 1
                long_break = self.sessions_today % 4 == 0
                self.state = "break"
                self.break_until = self.clock() + (15 if long_break else s["break_minutes"]) * 60
                summary["break_min"] = 15 if long_break else s["break_minutes"]
        self.on_end(summary)
        return summary

    def _save(self):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text(json.dumps(self.history[-200:], indent=1), encoding="utf-8")
        except OSError:
            pass

    def holding(self):
        return self.state == "focusing"

    # -- watching --

    def start_thread(self):
        self._running = True
        threading.Thread(target=self._loop, name="focus", daemon=True).start()
        return self

    def stop_thread(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.tick()
            except Exception as exc:
                print(f"[FOCUS] {exc}", flush=True)
            time.sleep(1 / HZ)

    def observe(self):
        """(detections, face) from the newest camera result."""
        if self.vision is None:
            return None, None
        res = self.vision.latest()
        if res is None:
            return None, None
        dets = [(d.label, d.score, d.box) for d in res.detections]
        face = None
        if self.analyzer is not None and self.analyzer.ready() and hasattr(self.vision, "frame_image"):
            image = self.vision.frame_image(res)
            if image is not None:
                faces = self.analyzer.faces(image)
                face = faces[0] if faces else None
        return dets, face

    def tick(self, dt=None, observation=None):
        """One step. observation: (detections, face) for tests; otherwise read from the camera."""
        now = self.clock()
        dt = 1 / HZ if dt is None else dt
        if self.state == "break" and now >= self.break_until:
            self.state = "idle"
            self.on_break_end()
            return
        if self.state != "focusing":
            return
        s = self.session
        if now >= s["end"]:
            self.stop("finished")
            return
        dets, face = observation if observation is not None else self.observe()
        if dets is None:
            s["observation"] = "no camera"
            return
        s["no_face_n"] = 0 if face is not None else s["no_face_n"] + 1
        state, yaw, pitch = classify(dets, face, s["baseline"], s["no_face_n"])
        if s["baseline"] is None and face is not None and state not in ("phone",):
            s["base_samples"].append((yaw if yaw is not None else 0.0, pitch if pitch is not None else 0.55))
            if len(s["base_samples"]) * dt >= BASELINE_S:
                ys = sorted(p[0] for p in s["base_samples"])
                ps = sorted(p[1] for p in s["base_samples"])
                s["baseline"] = (ys[len(ys) // 2], ps[len(ps) // 2])
            state = "focused"                           # still learning what "on task" looks like
        s.update(observation=state, yaw=None if yaw is None else round(yaw, 3), pitch=None if pitch is None else round(pitch, 3))
        if state == "absent":
            return
        s["present_s"] += dt
        if state in ("focused", "unknown"):
            s["focused_s"] += dt
            s["focused_streak"] += dt
            if s["focused_streak"] >= RESET_S:
                s["distracted_s"] = 0.0
                s["last_nudge"] = None
            return
        s["focused_streak"] = 0.0
        if state == "phone":
            s["phone_s"] += dt
        if s["distracted_s"] == 0.0:
            s["distractions"] += 1
        s["distracted_s"] += dt
        limit = PHONE_S if state == "phone" else GRACE_S
        due = s["last_nudge"] is None and s["distracted_s"] >= limit
        again = s["last_nudge"] is not None and s["distracted_s"] - s["last_nudge"] >= REPEAT_S
        if due or again:
            s["last_nudge"] = s["distracted_s"]
            options = [x for x in LINES[state] if x != self._last_line] or LINES[state]
            line = self.rng.choice(options)
            self._last_line = line
            self.on_nudge(state, line)

    # -- reporting --

    def today_minutes(self):
        day = self.wall().date().isoformat()
        return round(sum(h["minutes"] * (h["focused_pct"] or 100) / 100 for h in self.history if h["date"].startswith(day)))

    def status(self):
        now = self.clock()
        out = {"state": self.state, "today_focused_min": self.today_minutes(), "history": self.history[-30:][::-1],
               "face_model": None if self.analyzer is None else ("ready" if self.analyzer.detector is not None else self.analyzer.error or "not loaded"),
               "camera": self.vision is not None}
        if self.state == "break":
            out["break_left_s"] = max(0, round(self.break_until - now))
        s = self.session
        if s:
            out.update(left_s=max(0, round(s["end"] - now)), minutes=s["minutes"], observation=s["observation"],
                       focused_pct=round(100 * s["focused_s"] / s["present_s"]) if s["present_s"] > 0 else None,
                       distractions=s["distractions"], distracted_s=round(s["distracted_s"]), calibrated=s["baseline"] is not None,
                       yaw=s["yaw"], pitch=s["pitch"])
        return out


PROMPT = """Focus mode: "start focus mode", "focus for 40 minutes", "Pomodoro" -> focus_start (default 25 minutes);
"stop focus mode" -> focus_stop; "how am I doing" during a session -> focus_status. During focus mode keep replies
very short and encourage the user to get back to work."""

TOOL_SPECS = [
    {"name": "focus_start", "description": "Start a focus session: the robot watches for looking away / phone use and nudges.",
     "input_schema": {"type": "object", "properties": {
         "minutes": {"type": "integer", "description": "Session length, default 25."},
         "break_minutes": {"type": "integer", "description": "Break after it, default 5."}},
         "required": ["minutes", "break_minutes"], "additionalProperties": False}},
    {"name": "focus_stop", "description": "End the focus session (or the break) now.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "focus_status", "description": "Time left, % focused so far, distractions.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
]


def tool_handlers(focus):
    def j(x):
        return json.dumps(x), False
    return {"focus_start": lambda a: j(focus.start(a.get("minutes") or 25, a.get("break_minutes") or 5)),
            "focus_stop": lambda a: j({"stopped": focus.stop("asked") or "nothing was running"}),
            "focus_status": lambda a: j(focus.status() | {"history": None})}
