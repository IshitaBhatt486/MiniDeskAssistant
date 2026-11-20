"""
Touch pads (20 Nov 2026): three TTP223 capacitive modules on the robot's head -> headpat reactions.

Wiring (robot_config.TOUCH): VCC -> 3.3 V, GND -> GND, I/O -> GPIO 7 (top), 8 (left), 14 (right). With the module's
jumpers open (default) the I/O pin is HIGH while touched (momentary). Jumper B closed = self-locking: the output
flips on every touch; set touch.mode = "toggle" and every flip counts as one touch (no "hold" in that mode).

Reading: gpiozero DigitalInputDevice per pin, pull-down on (pull_up=False), so an unplugged pad reads "not touched",
bounce_time 20 ms. Callbacks run on gpiozero's thread; they only record the edge, and the classification below runs
under a lock. Without GPIO (laptop, simulation) the pads exist only through simulate().

What a touch means (TouchSense.classify, pure and time-driven, so it is unit-tested):
    press              any pad goes down -> "touch" at once (the face reacts instantly)
    pat                released after < hold_s
    hold               held for >= hold_s (reported while still held, once)
    pats               the Nth pat within 4 s on any pads (N = pats_for_excited, default 3)
    stroke             left -> top -> right (or right -> top -> left) within 1.5 s
"""

from __future__ import annotations

import threading
import time
from collections import deque

PADS = ("top", "left", "right")
PATS_WINDOW_S = 4.0
STROKE_WINDOW_S = 1.5


class TouchSense:
    def __init__(self, pins, section, on_event, log=print, use_gpio=True, clock=time.monotonic):
        """pins: {"top": 7, ...}; section(): data/pro.json "touch"; on_event(kind, pad, info)."""
        self.pins, self.section, self.on_event, self.log, self.clock = dict(pins), section, on_event, log, clock
        self._lock = threading.Lock()
        self.down = {}                        # pad -> press time
        self.held_reported = set()
        self.pats = deque()                   # times of recent pats
        self.order = deque(maxlen=3)          # (pad, time) of recent presses, for strokes
        self.counts = {p: 0 for p in self.pins}
        self.events = deque(maxlen=12)        # newest events for the dashboard
        self.today = {"date": time.strftime("%Y-%m-%d"), "pats": 0}
        self.backend, self.error = "none", None
        self._devices = []
        self._running = False
        if use_gpio:
            self._open_gpio()

    # -- hardware --

    def _open_gpio(self):
        try:
            from gpiozero import DigitalInputDevice
        except Exception as exc:
            self.error = f"gpiozero unavailable: {type(exc).__name__}"
            return
        try:
            for pad, pin in self.pins.items():
                dev = DigitalInputDevice(pin, pull_up=False, bounce_time=0.02)
                dev.when_activated = lambda p=pad: self._edge(p, True)
                dev.when_deactivated = lambda p=pad: self._edge(p, False)
                self._devices.append(dev)
            self.backend = "gpio"
            self.log(f"Touch pads on GPIO {', '.join(f'{p}={n}' for p, n in self.pins.items())}")
        except Exception as exc:
            for d in self._devices:
                d.close()
            self._devices = []
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            self.log(f"Touch pads not available: {self.error}")

    def _edge(self, pad, active):
        if self.section().get("mode") == "toggle":
            if active is not None:            # every flip of a self-locking pad is one touch
                self.press(pad)
                self.release(pad)
            return
        (self.press if active else self.release)(pad)

    # -- classification --

    def _emit(self, kind, pad, **info):
        now = self.clock()
        self.events.append({"kind": kind, "pad": pad, "t": time.time(), **info})
        if kind == "pat":
            day = time.strftime("%Y-%m-%d")
            if self.today["date"] != day:
                self.today = {"date": day, "pats": 0}
            self.today["pats"] += 1
        try:
            self.on_event(kind, pad, info)
        except Exception as exc:
            self.log(f"Touch reaction failed: {type(exc).__name__}: {exc}")
        return now

    def press(self, pad):
        if pad not in self.pins or not self.section().get("enabled", True):
            return []
        out = []
        with self._lock:
            now = self.clock()
            if pad in self.down:
                return []
            self.down[pad] = now
            self.counts[pad] = self.counts.get(pad, 0) + 1
            self.order.append((pad, now))
            out.append(("touch", pad, {}))
            seq = [p for p, t in self.order if now - t <= STROKE_WINDOW_S]
            if len(seq) == 3 and seq in (["left", "top", "right"], ["right", "top", "left"]):
                out.append(("stroke", pad, {"direction": "left to right" if seq[0] == "left" else "right to left"}))
                self.order.clear()
        for kind, p, info in out:
            self._emit(kind, p, **info)
        return [k for k, _, _ in out]

    def release(self, pad):
        out = []
        with self._lock:
            now = self.clock()
            t0 = self.down.pop(pad, None)
            if t0 is None:
                return []
            held = now - t0
            if pad in self.held_reported:
                self.held_reported.discard(pad)
                return []
            if held < float(self.section().get("hold_s", 1.2)):
                self.pats.append(now)
                while self.pats and now - self.pats[0] > PATS_WINDOW_S:
                    self.pats.popleft()
                n = int(self.section().get("pats_for_excited", 3))
                if len(self.pats) >= n:
                    out.append(("pats", pad, {"count": len(self.pats)}))
                    self.pats.clear()
                else:
                    out.append(("pat", pad, {"ms": round(held * 1000)}))
        for kind, p, info in out:
            self._emit(kind, p, **info)
        return [k for k, _, _ in out]

    def tick(self):
        """Report pads that have been held long enough (called ~20 times a second)."""
        out = []
        with self._lock:
            now = self.clock()
            for pad, t0 in self.down.items():
                if pad not in self.held_reported and now - t0 >= float(self.section().get("hold_s", 1.2)):
                    self.held_reported.add(pad)
                    out.append(("hold", pad, {"s": round(now - t0, 1)}))
        for kind, p, info in out:
            self._emit(kind, p, **info)
        return [k for k, _, _ in out]

    def simulate(self, pad, hold_s=0.15):
        """A touch of `hold_s` seconds on a pad (dashboard / sim console). Runs in the background."""
        if pad not in self.pins:
            raise ValueError(f"pads: {', '.join(self.pins)}")
        hold_s = max(0.02, min(5.0, float(hold_s)))

        def run():
            self.press(pad)
            end = time.monotonic() + hold_s
            while time.monotonic() < end:
                time.sleep(0.05)
                self.tick()
            self.release(pad)
        threading.Thread(target=run, daemon=True, name="touch-sim").start()

    # -- life cycle --

    def start(self):
        self._running = True

        def loop():
            while self._running:
                self.tick()
                time.sleep(0.05)
        threading.Thread(target=loop, daemon=True, name="touch").start()

    def stop(self):
        self._running = False
        for d in self._devices:
            try:
                d.close()
            except Exception:
                pass

    def status(self):
        with self._lock:
            return {"backend": self.backend, "error": self.error, "pins": self.pins, "pressed": sorted(self.down),
                    "counts": dict(self.counts), "today": dict(self.today), "events": list(self.events)[::-1]}
