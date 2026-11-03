"""
How the robot feels, worked out from what is happening. Runs at 5 Hz in the navigation process and tells
the body process which emotion to show and where to look.

Highest priority first:

    scared      being held in the air
    annoyed     a safety rule just stopped a move
    confused    a stalled turn, or a failed command, or the AI's reply mood
    <reaction>  a short-lived event: gesture, put back down, the AI's mood, a dashboard test
    sleepy      asleep (Bluetooth presence / voice command), or nothing has happened for a long time
    happy       a person just came into view
    curious     close to an object (sonar or camera; the eyes look at it), or moving / searching
    sad         nobody seen for a while
    neutral     otherwise
"""

from __future__ import annotations

import threading
import time

from .animations import EMOTIONS

MOOD_ALIASES = {"neutral": "neutral", "happy": "happy", "excited": "excited", "curious": "curious",
                "sleepy": "sleepy", "sad": "sad", "confused": "confused", "embarrassed": "embarrassed"}


class EmotionEngine:
    GREET_S = 6.0

    def __init__(self, shared, cfg, app):
        self.s, self.cfg, self.app = shared, cfg, app      # app: the assistant namespace + .behaviour, .trim
        self.emotion = None
        self.why = ""
        self.reaction = None               # (emotion, until, why)
        self.seq = 0
        self.started = time.monotonic()
        self.last_activity = self.started
        self.user_visible = False
        self.greet_until = 0.0
        self.last_blocks = None
        self.annoyed_until = 0.0
        self.last_log_id = 0
        self.near = False
        self.near_gaze = (0.0, 0.0)
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="emotion", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.step(time.monotonic())
            except Exception as exc:
                print(f"[EMOTE] {exc}", flush=True)
            time.sleep(0.2)

    def react(self, emotion, seconds=None, why="event", now=None):
        """Show `emotion` for a while (gesture, put down, dashboard button, ...)."""
        if emotion in EMOTIONS:
            now = time.monotonic() if now is None else now
            self.reaction = (emotion, now + (seconds or self.cfg.event_hold_s), why)
            self.last_activity = now

    def _assistant_mood(self, now):
        log = self.app.assistant.status()["log"]
        if log and log[-1]["id"] != self.last_log_id:
            self.last_log_id = log[-1]["id"]
            mood = MOOD_ALIASES.get(log[-1].get("mood"))
            if mood and mood != "neutral":
                self.react(mood, 8.0, "assistant reply", now)

    def _update_near(self, user_visible):
        """Is something close? Sonar readings use hysteresis; a large recognised object counts too."""
        c = self.cfg
        d = (self.app.robot.latest_reading().get("distances") or {})
        limit = c.near_clear_m if self.near else c.near_object_m
        # a person standing in front is greeted, not investigated
        sides = {"left": -0.8, "right": 0.8, "rear": 0.0, **({} if user_visible else {"front": 0.0})}
        close = [(d[k], gx) for k, gx in sides.items() if d.get(k) is not None and 0.03 <= d[k] < limit]
        self.near, self.near_gaze = bool(close), (min(close)[1], 0.0) if close else (0.0, 0.0)
        vision = getattr(self.app, "vision", None)
        res = vision.latest() if vision else None
        size = getattr(self.app, "image_size", (320, 240))
        for det in (res.detections if res else []):
            x1, y1, x2, y2 = det.box
            if det.label != "person" and det.score >= 0.5 and (x2 - x1) * (y2 - y1) >= c.near_box_fraction * size[0] * size[1]:
                self.near = True
                self.near_gaze = (((x1 + x2) / size[0]) - 1.0, ((y1 + y2) / size[1]) - 1.0)
                break

    def decide(self, now):
        a = self.app
        snap_state = a.robot.motor_state()
        blocks = snap_state["safety_stops"]
        if blocks == blocks:
            if self.last_blocks is not None and blocks > self.last_blocks:
                self.annoyed_until = now + self.cfg.event_hold_s
                self.last_activity = now
            self.last_blocks = blocks
        moving = snap_state["left"] == snap_state["left"] and (snap_state["left"] != 0 or snap_state["right"] != 0)
        if moving:
            self.last_activity = now

        b = a.behaviour
        seen_recently = b is not None and now - getattr(b, "user_seen_t", -1e9) < 3.0
        if seen_recently and not self.user_visible:
            self.greet_until = now + self.GREET_S
        if seen_recently:
            self.last_activity = now
        self.user_visible = seen_recently
        self._update_near(seen_recently)

        if a.lift.lifted:
            return "scared", "picked up"
        if now < self.annoyed_until:
            return "annoyed", "a safety rule stopped me"
        if self.reaction and now < self.reaction[1]:
            return self.reaction[0], self.reaction[2]
        if a.presence is not None and not a.presence.awake:
            return "sleepy", "asleep"
        if now - self.last_activity > self.cfg.idle_sleepy_s:
            return "sleepy", "nothing happening"
        if now < self.greet_until:
            return "happy", "I can see you"
        if self.near:
            return "curious", "something is close"
        if moving or (b is not None and b.state.startswith(("looking", "turning"))):
            return "curious", "moving around"
        if b is not None and b.enabled and now - getattr(b, "user_seen_t", -1e9) > self.cfg.lonely_s \
                and now - self.started > self.cfg.lonely_s:
            return "sad", "nobody around"
        return "neutral", "calm"

    def step(self, now):
        self._assistant_mood(now)
        emotion, self.why = self.decide(now)
        if emotion != self.emotion:
            self.emotion = emotion
            self.seq += 1
        b = self.app.behaviour
        gx, gy = (0.0, 0.0)
        if b is not None and now - getattr(b, "user_seen_t", -1e9) < 2.0:
            gx, gy = b.gaze
        elif emotion == "curious" and self.near:
            gx, gy = self.near_gaze
        self.s.face.write(emotion=EMOTIONS.index(emotion), seq=self.seq, gaze_x=gx, gaze_y=gy)

    def status(self):
        return {"emotion": self.emotion, "why": self.why, "emotions": list(EMOTIONS)}
