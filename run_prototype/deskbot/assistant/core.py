"""
The assistant pipeline:

    audio (dashboard mic / robot mic) --stt--> text --+
    typed text (dashboard / remote) ------------------+--> context (camera detections + frame, sensors,
                                                           map memory, presence, time) + personality
                                                      --> brain (Claude or offline) --> reply JSON
                                                      --> conversation log (dashboard), speaker (chipmunk
                                                          voice), executor (robot commands)

One conversation turn at a time (a second request while thinking gets "busy"). Every step is guarded:
STT, the brain, the speaker and the executor each fail on their own, with a spoken explanation, and the
turn still produces a reply on the dashboard.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime

from .brain import local_vision_answer, needs_image
from ..vision.describe import dominant_colour
from .stt import SttError, record_robot_mic


class Busy(Exception):
    pass


class Assistant:
    def __init__(self, sv, settings, alerts, speaker, stt, brain, executor):
        """sv: services (.robot, .vision, .mapper, .behaviour, .presence, .lift, .cam)."""
        self.sv, self.settings, self.alerts = sv, settings, alerts
        self.speaker, self.stt, self.brain, self.executor = speaker, stt, brain, executor
        self.log = deque(maxlen=40)
        self._id = 0
        self._busy = threading.Lock()
        self.phase = "idle"        # idle | listening | transcribing | thinking
        self._seen_items = []      # newest detections with their colours

    # -- entry points --

    def handle_audio(self, wav: bytes, source="dashboard mic"):
        if not self._busy.acquire(blocking=False):
            raise Busy()
        try:
            self.phase = "transcribing"
            t0 = time.perf_counter()
            try:
                text = self.stt.transcribe(wav)
            except SttError as exc:
                return self._error_turn(str(exc), source)
            stt_ms = round((time.perf_counter() - t0) * 1000)
            if not text.strip():
                return self._error_turn("I didn't catch any words. Try again a bit closer to the mic.", source)
            return self._turn(text, source, stt_ms=stt_ms)
        finally:
            self.phase = "idle"
            self._busy.release()

    def handle_text(self, text: str, source="typed"):
        text = (text or "").strip()[:500]
        if not text:
            raise ValueError("Say something first")
        if not self._busy.acquire(blocking=False):
            raise Busy()
        try:
            return self._turn(text, source)
        finally:
            self.phase = "idle"
            self._busy.release()

    def listen_robot_mic(self, seconds=5.0):
        if not self._busy.acquire(blocking=False):
            raise Busy()
        try:
            self.phase = "listening"
            self.speaker.say("Listening.", "chatter")
            time.sleep(0.6)    # let the cue finish before recording (it would be transcribed otherwise)
            try:
                wav = record_robot_mic(seconds)
            except SttError as exc:
                return self._error_turn(str(exc), "robot mic")
        finally:
            self.phase = "idle"
            self._busy.release()
        return self.handle_audio(wav, source="robot mic")

    # -- one turn --

    def _turn(self, text, source, stt_ms=None):
        presence = self.sv.presence
        if presence is not None and not presence.awake:
            presence.set_awake(True, reason="spoken to", announce=False)
        self.phase = "thinking"
        image = None
        wanted = needs_image(text) or not self.settings.get("vision_on_demand", True)
        if wanted and self.settings.get("send_image", True) and self.sv.vision is not None:
            image = self.alerts.call("camera-frame", self.sv.vision.jpeg, fallback=None,
                                     message="Couldn't grab a camera frame for the AI.", speak=False)
        context, seen = self.context()
        if image is not None and local_vision_answer(text, self._seen_items):
            image = None                  # the on-board detector can answer this one
        out = self.brain.think(text, context, image_jpeg=image, tool_ctx={
            "default_location": self.settings.get("location", ""),
            "robot_status": self.robot_status, "robot_name": self.settings.get("robot_name", "Pip"),
            "seen_labels": seen, "seen_items": self._seen_items})
        if self.settings.get("speak", True):
            self.speaker.say(out["speech"], "reply")
        executed = []
        if out["commands"] and self.settings.get("execute_commands", True):
            executed, _ = self.executor.run(out["commands"], source="ai")
        return self._record(text, source, out, stt_ms=stt_ms, image=image is not None, executed=bool(executed))

    def _error_turn(self, message, source):
        self.speaker.say(message, "alert")
        return self._record(None, source, {"speech": message, "mood": "confused", "commands": [], "backend": "system",
                                           "error": message, "ms": 0, "tools": []})

    def _record(self, text, source, out, **extra):
        self._id += 1
        entry = {"id": self._id, "t": time.time(), "user": text, "source": source,
                 "speech": out.get("speech"), "mood": out.get("mood"), "commands": out.get("commands", []),
                 "backend": out.get("backend"), "ms": out.get("ms"), "tools": out.get("tools", []),
                 "error": out.get("error"), "problems": out.get("problems", []), "usage": out.get("usage"), **extra}
        self.log.append(entry)
        return entry

    # -- what the AI gets told --

    def context(self):
        """(context text, labels currently seen)."""
        sv = self.sv
        now = time.monotonic()
        lines = [f"Time: {datetime.now().astimezone().strftime('%A %d %B %Y, %H:%M')}"]
        r = sv.robot.latest_reading()
        snap_state = sv.robot.snapshot()["state"]
        d = r.get("distances") or {}
        fmt = lambda v: "none" if v is None or v >= 1.99 else f"{v * 100:.0f} cm"   # noqa: E731
        lines.append(f"Robot: {snap_state}, speed {sv.robot.speed * 100:.0f}%. Sonar distances: front {fmt(d.get('front'))}, "
                     f"left {fmt(d.get('left'))}, right {fmt(d.get('right'))}, rear {fmt(d.get('rear'))}. "
                     f"Floor under front IR: {r.get('front_floor')}, rear IR: {r.get('back_floor')}.")
        if sv.lift is not None and sv.lift.lifted:
            lines.append("The robot is currently LIFTED off the desk (someone is holding it).")
        if sv.presence is not None:
            ps = sv.presence.tracker.status()
            lines.append(f"Owner's phone (Bluetooth): {ps['state']}"
                         + (f", about {ps['distance_m']} m away" if ps["distance_m"] is not None and ps["state"] != "away" else "")
                         + ("" if sv.presence.awake else ". The robot was asleep and just woke up."))
        seen = []
        self._seen_items = []
        if sv.vision is None:
            lines.append("Camera: off.")
        else:
            res = sv.vision.latest()
            if res is None:
                lines.append("Camera: no frame yet.")
            else:
                items = []
                image = sv.vision.frame_image(res) if hasattr(sv.vision, "frame_image") else None
                for det in sorted(res.detections, key=lambda x: -x.score)[:8]:
                    colour = dominant_colour(image, det.box) if image is not None else None
                    x1, y1, x2, y2 = det.box
                    self._seen_items.append({"label": det.label, "colour": colour, "area": (x2 - x1) * (y2 - y1)})
                    bearing = math.degrees(sv.cam.bearing((det.box[0] + det.box[2]) / 2)) if sv.cam else 0.0
                    side = "ahead" if abs(bearing) < 6 else f"{abs(bearing):.0f} deg {'left' if bearing > 0 else 'right'}"
                    dist = ""
                    if abs(bearing) < 10 and d.get("front") is not None and d["front"] < 1.5:
                        dist = f", ~{d['front'] * 100:.0f} cm (front sonar)"
                    items.append(f"{colour + ' ' if colour else ''}{det.label} ({det.score * 100:.0f}%, {side}{dist})")
                    seen.append(det.label)
                age = (now - res.t_capture) * 1000
                lines.append(f"Camera now ({age:.0f} ms old): " + ("; ".join(items) if items else "nothing recognised") + ".")
        mem = self._map_memory()
        if mem:
            lines.append("Remembered on the map (relative to the robot now): " + "; ".join(mem) + ".")
        nav = getattr(sv, "navigator", None)
        if nav is not None:
            try:
                extra = nav.known_obstacles()["unlabelled"]
            except Exception:
                extra = []
            if extra:
                lines.append("Unidentified obstacles you can navigate to: "
                             + "; ".join(f"{o['name']} ({o['distance_m'] * 100:.0f} cm away)" for o in extra) + ".")
        return "\n".join(lines), sorted(set(seen))

    def _map_memory(self):
        m = self.sv.mapper
        if m is None or not hasattr(m, "sem"):
            return []
        now = time.monotonic()
        out = []
        try:
            with m._lock:
                pose = (m.odom.x, m.odom.y, m.odom.theta)
                objs = [(lm.label, lm.x, lm.y, m.sem.existence(lm, now)) for lm in m.sem.objects.values()]
        except Exception:
            return []
        for label, x, y, e in sorted(objs, key=lambda o: -o[3])[:8]:
            if e < 0.5:
                continue
            dx, dy = m._to_robot(pose, x, y)
            dist = math.hypot(dx, dy)
            ang = math.degrees(math.atan2(dy, dx))
            where = "ahead" if abs(ang) < 15 else ("behind" if abs(ang) > 150 else f"{abs(ang):.0f} deg {'left' if ang > 0 else 'right'}")
            out.append(f"{label} {dist * 100:.0f} cm {where}")
        return out

    def robot_status(self):
        """robot_status tool: a structured version of the context."""
        text, seen = self.context()
        st = {"summary": text, "seen_now": seen}
        if self.sv.mapper is not None and hasattr(self.sv.mapper, "live_status"):
            st["map"] = self.sv.mapper.live_status()
        return st

    def status(self):
        return {"phase": self.phase, "log": list(self.log)[-20:]}
