"""
Pings the HC-SR04 sonars ONE AT A TIME from one background thread (24 Nov 2026, from legacy/simplified_code.py).

Why: gpiozero's DistanceSensor gives every sensor its own thread. A lock stops two pinging at the same instant,
but each fires the moment the previous echo ends, while that ping is still bouncing around, so it hears it.
Measured on the robot on 23 Nov 2026: the right sonar, normally 200 cm, read 16.3 cm (the front sonar's
obstacle) 11 times in 4 s, and the rear one dropped to 18 cm 70 times. Each false reading stopped the move.

Here each ping has the air to itself: trigger, time the echo pulse with the pin factory's edge timestamps (lgpio
alerts on the Pi, microsecond resolution), wait GAP for the echoes to die down, then the next sensor. Four
sonars take about 4 x (echo time + 15 ms), i.e. each is read roughly 10-15 times a second.

latest(name) -> metres, or None when the sensor gave no echo (wiring / out of range with the echo never rising)
or has no fresh reading. sensor_filter.py turns repeated None into a fault that stops the robot, which is safer
than gpiozero's behaviour of reporting "max distance" (all clear) for a silent sensor.
"""

from __future__ import annotations

import threading
import time

SPEED_OF_SOUND = 343.0      # m/s at ~20 C


class SonarScanner:
    ECHO_TIMEOUT = 0.07     # s: no complete echo pulse by then (the rising edge never came = no echo / wiring)
    GAP = 0.015             # s of silence after each ping so its echoes fade before the next sensor fires
    STALE = 0.5             # s: a reading older than this is not reported

    def __init__(self, sonars, max_distance, log=print):
        """sonars: {name: {"trigger": bcm, "echo": bcm}}; max_distance: m reported when the echo is too long."""
        from gpiozero import Device

        self.max_distance, self.log = max_distance, log
        self.factory = Device.pin_factory
        if self.factory is None:          # the sensor process opens no other gpiozero device first
            self.factory = Device.pin_factory = Device._default_pin_factory()
        self.pins, self.errors, self._callbacks = {}, {}, []
        self.readings = {name: (None, 0.0) for name in sonars}
        self.no_echo = {name: 0 for name in sonars}
        self.sweeps = 0
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._active = self._rise = self._fall = None
        for name, p in sonars.items():
            trig = echo = None
            try:
                trig = self.factory.pin(p["trigger"])
                trig.function, trig.state = "output", False
                echo = self.factory.pin(p["echo"])
                echo.function, echo.pull = "input", "down"
                echo.edges, echo.bounce = "both", None
                cb = (lambda ticks, state, n=name: self._edge(n, ticks, state))
                self._callbacks.append(cb)       # gpiozero only keeps a weak reference to when_changed
                echo.when_changed = cb
                self.pins[name] = (trig, echo)
            except Exception as exc:
                for pin in (trig, echo):
                    try:
                        pin and pin.close()
                    except Exception:
                        pass
                self.errors[name] = f"{type(exc).__name__}: {exc}"
                self.log(f"[sonar] {name} sonar unavailable: {self.errors[name]}")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sonars")
        self._thread.start()

    def _edge(self, name, ticks, state):
        if name != self._active:
            return
        if state:
            self._rise = ticks
        elif self._rise is not None:
            self._fall = ticks
            self._done.set()

    def ping(self, name):
        """One measurement in metres (max_distance = nothing in range), or None (no echo at all)."""
        trig, _ = self.pins[name]
        self._rise = self._fall = None
        self._done.clear()
        self._active = name
        trig.state = True
        time.sleep(0.00001)              # >= 10 us trigger pulse (Python makes it ~50-100 us, which is fine)
        trig.state = False
        got = self._done.wait(self.ECHO_TIMEOUT)
        self._active = None
        if not got:
            return self.max_distance if self._rise is not None else None   # echo still high = nothing in range
        dt = self.factory.ticks_diff(self._fall, self._rise)
        return max(0.0, min(self.max_distance, dt * SPEED_OF_SOUND / 2))

    def _run(self):
        while not self._stop.is_set():
            if not self.pins:
                self._stop.wait(1.0)
                continue
            for name in self.pins:
                if self._stop.is_set():
                    return
                try:
                    d = self.ping(name)
                except Exception as exc:
                    d = None
                    self.errors[name] = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self.readings[name] = (d, time.monotonic())
                    self.no_echo[name] = self.no_echo[name] + 1 if d is None else 0
                self._stop.wait(self.GAP)
            self.sweeps += 1

    def latest(self, name):
        """The newest reading in metres, or None (no echo, unavailable, or nothing fresh)."""
        with self._lock:
            d, t = self.readings.get(name, (None, 0.0))
        return d if d is not None and time.monotonic() - t <= self.STALE else None

    def reason(self, name):
        if name in self.errors:
            return self.errors[name]
        if self.no_echo.get(name, 0) >= 2:
            return "no echo - check its wiring (TRIG, ECHO through the 1k/2k divider, 5 V, GND)"
        return ""

    def close(self):
        self._stop.set()
        self._thread.join(timeout=0.5)
        for trig, echo in self.pins.values():
            for pin in (echo, trig):
                try:
                    if pin is echo:
                        pin.when_changed = None
                    pin.close()
                except Exception:
                    pass
