"""
Say hello when a new person appears.

The camera doesn't recognise faces, so "new" means: more people are in view than a moment ago, or someone
appears after nobody (or fewer people) had been there for `absent_s`. A count must hold for `confirm_s`, which
filters out detector flicker, and greetings are at least `cooldown_s` apart. No greeting while the robot is
asleep or being carried.
"""

from __future__ import annotations

import random


class Greeter:
    def __init__(self, cfg, app, image_area, rng=None):
        self.cfg, self.app, self.image_area = cfg, app, image_area
        self.rng = rng or random.Random()
        self.candidate = 0
        self.candidate_since = None
        self.known = 0
        self.fewer_since = None
        self.last_greeting = float("-inf")
        self.greetings = 0
        self.last_phrase = None

    def count(self, detections):
        c = self.cfg
        n = 0
        for d in detections:
            x1, y1, x2, y2 = d.box
            if d.label == "person" and d.score >= c.min_score and (x2 - x1) * (y2 - y1) >= c.min_box_fraction * self.image_area:
                n += 1
        return n

    def step(self, now, detections):
        c = self.cfg
        n = self.count(detections)
        if n != self.candidate or self.candidate_since is None:
            self.candidate, self.candidate_since = n, now
        if now - self.candidate_since < c.confirm_s:
            return False
        if n >= self.known:
            self.fewer_since = None
        else:                                  # someone left: forget them only after a while
            self.fewer_since = self.fewer_since if self.fewer_since is not None else now
            if now - self.fewer_since >= c.absent_s:
                self.known, self.fewer_since = n, None
            return False
        if n == self.known:
            return False
        self.known = n
        return self._greet(now)

    def _greet(self, now):
        a, c = self.app, self.cfg
        asleep = a.presence is not None and not a.presence.awake
        if not c.enabled or asleep or a.lift.lifted or now - self.last_greeting < c.cooldown_s:
            return False
        self.last_greeting = now
        self.greetings += 1
        self.last_phrase = self.rng.choice([p for p in c.phrases if p != self.last_phrase] or c.phrases)
        a.speaker.say(self.last_phrase, "chatter")
        a.emotion.react("happy", 5.0, "greeting someone new", now)
        a.robot.log("info", f"Greeted a new person: {self.last_phrase}")
        return True

    def status(self):
        return {"enabled": self.cfg.enabled, "people": self.known, "greetings": self.greetings, "last": self.last_phrase}
