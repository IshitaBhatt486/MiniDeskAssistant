"""
Presence manager: awake/asleep, wake-on-approach, sleep-on-leave and "find my phone".

Asleep means: face-the-user behaviour off, running commands cancelled, motors stopped, no idle chatter.
The dashboard shows a sleeping face. Talking to the robot (voice, text or the remote) wakes it.

Find my phone (one Bluetooth antenna, so direction comes from the robot's own body shadow):
    1. SCAN    turn in SCAN_STEPS x 30 deg steps; at each heading wait SETTLE_S, average RSSI for LISTEN_S
    2. CHOOSE  circular [1 2 1] smoothing over the headings, take the strongest. A spread < 3 dB means
               "no clear direction" (phone very close, or too far) -> it says so and still tries
    3. FACE    turn to that heading (left or right, whichever is shorter)
    4. APPROACH hops of HOP_S forward. Before a hop, a 'cell phone' camera detection (if any) refines
               the heading. After a hop: re-measure.
               - RSSI >= ARRIVE_RSSI           -> arrived
               - a safety stop at the desk edge -> "the phone should be just past the edge" (success:
                 it never drives off the desk, the motor process's IR rule stops it)
               - an obstacle                   -> stop and say so
               - RSSI fell DROP_DB below the best for 2 hops -> rescan once (it drove past or turned wrong)
"""

from __future__ import annotations

import math
import threading
import time

SCAN_STEPS = 12
STEP_DEG = 30
SETTLE_S = 0.35
LISTEN_S = 1.0
HOP_S = 0.6
MAX_HOPS = 14
ARRIVE_RSSI = -45.0
DROP_DB = 6.0
MIN_SPREAD_DB = 3.0


class Presence:
    def __init__(self, robot, settings, alerts, say, tracker, source, behaviour=None, vision=None, cam=None):
        self.robot, self.settings, self.alerts, self.say = robot, settings, alerts, say
        self.tracker, self.source = tracker, source
        self.behaviour, self.vision, self.cam = behaviour, vision, cam
        self.executor = None            # set by the app (to cancel sequences when falling asleep)
        self.awake = True
        self.sleep_reason = None
        self._behaviour_was = None
        self.find = {"phase": "idle"}   # dashboard: phase, scan [rssi per heading], best_deg, hops, result
        self._lock = threading.Lock()
        tracker.on_change = self._on_presence_change

    # -- sleep / wake --

    def set_awake(self, awake, reason="asked", announce=True):
        with self._lock:
            if awake == self.awake:
                return False
            self.awake = awake
            self.sleep_reason = None if awake else reason
        if not awake:
            if self.executor:
                self.executor.cancel()
            self.robot.stop(source="auto")
            if self.behaviour is not None:
                self._behaviour_was = self.behaviour.enabled
                self.behaviour.set_enabled(False)
            if announce:
                self.say("Bye! Going to sleep." if reason == "phone left" else "Going to sleep. Talk to me to wake me up.", "chatter")
        else:
            if self.behaviour is not None and self._behaviour_was:
                self.behaviour.set_enabled(True)
            if announce:
                self.say("Welcome back!" if reason == "phone near" else "I'm awake!", "chatter")
        self.robot.log("info", f"{'Awake' if awake else 'Asleep'} ({reason})")
        return True

    def _on_presence_change(self, old, new):
        ble = self.settings.get("ble", {})
        if new == "near" and not self.awake and ble.get("auto_wake", True):
            self.set_awake(True, reason="phone near")
        elif new == "away" and old == "near" and self.awake and ble.get("auto_sleep", True):
            self.set_awake(False, reason="phone left")

    # -- find my phone (runs on the executor thread) --

    def _listen(self, cancelled):
        time.sleep(SETTLE_S)
        t0 = time.monotonic()
        end = t0 + LISTEN_S
        while time.monotonic() < end:
            if cancelled():
                return None
            time.sleep(0.05)
        return self.tracker.mean(t0)

    def _turn(self, direction, degrees, cancelled):
        from ..runtime.behaviour import turn_rate
        return self._drive(direction, math.radians(degrees) / turn_rate(self.robot.speed), cancelled)

    def _drive(self, direction, seconds, cancelled):
        if seconds < 0.03:
            return None
        self.robot.move(direction, round(seconds, 3))
        time.sleep(0.08)
        end = time.monotonic() + seconds + 3
        while time.monotonic() < end:
            if cancelled():
                self.robot.stop()
                return "cancelled"
            s = self.robot.snapshot()
            if s["state"] == "blocked":
                return s.get("reason") or "blocked"
            if s["state"] != "moving":
                return None
            time.sleep(0.04)
        return "timed out"

    def _scan(self, cancelled):
        readings = []
        for i in range(SCAN_STEPS):
            self.find.update(phase="scanning", step=i)
            readings.append(self._listen(cancelled))
            self.find["scan"] = [None if r is None else round(r, 1) for r in readings]
            if cancelled():
                return None
            why = self._turn("left", STEP_DEG, cancelled)
            if why:
                return why
        return readings

    @staticmethod
    def best_heading(readings):
        """(index of the strongest heading after circular [1 2 1] smoothing, spread dB) or (None, 0)."""
        n = len(readings)
        smooth = []
        for i in range(n):
            num = den = 0.0
            for off, w in ((-1, 1.0), (0, 2.0), (1, 1.0)):
                r = readings[(i + off) % n]
                if r is not None:
                    num += w * r
                    den += w
            smooth.append(num / den if den else None)
        valid = [(s, i) for i, s in enumerate(smooth) if s is not None]
        if not valid:
            return None, 0.0
        best = max(valid)
        return best[1], best[0] - min(valid)[0]

    def _camera_phone_bearing(self):
        if self.vision is None or self.cam is None:
            return None
        res = self.vision.latest()
        phones = [d for d in (res.detections if res else []) if d.label == "cell phone"]
        if not phones:
            return None
        p = max(phones, key=lambda d: d.score)
        return math.degrees(self.cam.bearing((p.box[0] + p.box[2]) / 2))

    def find_phone(self, cancelled=lambda: False):
        """Returns None when done (found / reached the edge), else why it stopped. Speaks progress."""
        if self.tracker.last_seen is None or time.monotonic() - self.tracker.last_seen > 8:
            self.find = {"phase": "done", "result": "phone not heard"}
            self.say("I can't hear your phone's Bluetooth. Is its beacon on?", "alert")
            return "phone not heard"
        if not self.awake:
            self.set_awake(True, reason="find phone", announce=False)
        behaviour_was = self.behaviour.enabled if self.behaviour is not None else None
        if self.behaviour is not None:
            self.behaviour.set_enabled(False)      # don't fight the face-the-user turns
        self.find = {"phase": "scanning", "scan": [], "step": 0, "hops": 0, "best_deg": None, "result": None,
                     "started": time.time()}
        self.say("Looking for your phone.", "chatter")
        try:
            return self._find(cancelled)
        finally:
            if self.behaviour is not None and behaviour_was:
                self.behaviour.set_enabled(True)

    def _find(self, cancelled):
        rescans = 0
        while True:
            readings = self._scan(cancelled)
            if not isinstance(readings, list):
                return self._done(readings or "cancelled")
            idx, spread = self.best_heading(readings)
            if idx is None:
                self.say("I lost your phone's signal.", "alert")
                return self._done("signal lost")
            deg = idx * STEP_DEG
            self.find.update(phase="turning", best_deg=deg, spread_db=round(spread, 1))
            if spread < MIN_SPREAD_DB:
                self.say("The signal is about the same everywhere, but I'll try this way.", "chatter")
            why = self._turn("left", deg, cancelled) if deg <= 180 else self._turn("right", 360 - deg, cancelled)
            if why:
                return self._done(why)

            best = self.tracker.mean(time.monotonic() - 1.0) or -100
            drops = 0
            for hop in range(MAX_HOPS):
                if cancelled():
                    return self._done("cancelled")
                cam = self._camera_phone_bearing()
                if cam is not None and abs(cam) > 10:
                    self._turn("left" if cam > 0 else "right", abs(cam) * 0.8, cancelled)
                self.find.update(phase="approaching", hops=hop + 1)
                why = self._drive("forward", HOP_S, cancelled)
                if why:
                    if "edge" in why.lower():
                        self.say("I'm at the edge of the desk. Your phone should be just ahead of me.", "chatter")
                        return self._done(None, "reached the desk edge")
                    if why == "cancelled":
                        return self._done(why)
                    self.say("Something is in my way, so I stopped.", "alert")
                    return self._done(why)
                r = self._listen(cancelled)
                if r is None:
                    continue
                self.find["rssi"] = round(r, 1)
                if r >= ARRIVE_RSSI:
                    self.say("Found it! Your phone is right here.", "chatter")
                    return self._done(None, "arrived")
                if r > best:
                    best, drops = r, 0
                elif r < best - DROP_DB:
                    drops += 1
                    if drops >= 2:
                        break
            if rescans >= 1:
                self.say("I got close, but I'm not sure exactly where it is.", "chatter")
                return self._done(None, "gave up after rescan")
            rescans += 1
            self.say("Hmm, the signal got weaker. Let me look again.", "chatter")

    def _done(self, why, result=None):
        self.find.update(phase="done", result=result or why)
        return why

    def status(self):
        return {"awake": self.awake, "sleep_reason": self.sleep_reason, "tracker": self.tracker.status(),
                "source": self.source.status() if self.source else None, "find": dict(self.find),
                "devices": self.source.devices() if self.source else []}
