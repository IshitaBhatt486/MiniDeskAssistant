"""
Cleans the raw sensor samples before anything acts on them (runs in the sensor process, 50 Hz).

    sonars   median of the last 3 samples removes single-sample spikes (about 20 ms of added delay)
    IR       debounce with hysteresis: "no floor" is believed after 2 samples (40 ms), "floor again" only after
             5 (100 ms), so the cautious answer always wins quickly and a noisy edge doesn't chatter

Failure detection, per sensor, over the last 25 samples (0.5 s). Faults always resolve toward STOPPING:

    no data     a sonar returned nothing for 10 samples      -> reads 0 m, so forward/turn rules stop the robot
    flickering  a sonar jumped > 30 cm and straight back     -> reads the smallest recent value
                at least 4 times                                (a real turn past an object doesn't bounce back)
    flickering  an IR output changed at least 6 times        -> reads "no floor"

A fault clears after 25 clean samples in a row.
"""

from __future__ import annotations

from collections import deque

SONARS = ("front", "left", "right", "rear")
WINDOW = 25
FAULT_BITS = {"front": 1, "left": 2, "right": 4, "rear": 8, "front_floor": 16, "back_floor": 32}


def fault_names(mask):
    mask = int(mask or 0)
    return [name for name, bit in FAULT_BITS.items() if mask & bit]


class _Sonar:
    JUMP = 0.30

    def __init__(self):
        self.recent = deque(maxlen=3)
        self.window = deque(maxlen=WINDOW)
        self.missing = 0
        self.clean = 0
        self.fault = False

    def _bounces(self):
        v = list(self.window)
        return sum(1 for a, b, c in zip(v, v[1:], v[2:]) if abs(b - a) > self.JUMP and abs(c - b) > self.JUMP
                   and (b - a) * (c - b) < 0)

    def update(self, value):
        if value is None:
            self.missing += 1
            self.clean = 0
            if self.missing >= 10:
                self.fault = True
            return (0.0 if self.fault else min(self.recent, default=0.0))
        self.missing = 0
        self.recent.append(float(value))
        self.window.append(float(value))
        bad = self._bounces() >= 4
        self.clean = 0 if bad else self.clean + 1
        if bad:
            self.fault = True
        elif self.clean >= WINDOW:
            self.fault = False
        if self.fault:
            return min(self.window)
        return sorted(self.recent)[len(self.recent) // 2]


class _Floor:
    TO_EDGE, TO_FLOOR = 2, 5

    def __init__(self):
        self.state = None
        self.count = 0
        self.changes = deque(maxlen=WINDOW)
        self.last_raw = None
        self.clean = 0
        self.fault = False

    def update(self, raw):
        raw = bool(raw)
        self.changes.append(self.last_raw is not None and raw != self.last_raw)
        self.last_raw = raw
        if self.state is None:
            self.state = raw
        if raw == self.state:
            self.count = 0
        else:
            self.count += 1
            if self.count >= (self.TO_FLOOR if raw else self.TO_EDGE):
                self.state, self.count = raw, 0
        bad = sum(self.changes) >= 6
        self.clean = 0 if bad else self.clean + 1
        if bad:
            self.fault = True
        elif self.clean >= WINDOW:
            self.fault = False
        return False if self.fault else self.state


class SensorConditioner:
    def __init__(self):
        self.sonars = {n: _Sonar() for n in SONARS}
        self.front_ir, self.back_ir = _Floor(), _Floor()

    def update(self, distances, front_floor, back_floor):
        """(clean distances, clean front floor, clean back floor, fault bitmask)."""
        out = {n: s.update(distances.get(n)) for n, s in self.sonars.items()}
        ff, bf = self.front_ir.update(front_floor), self.back_ir.update(back_floor)
        mask = sum(FAULT_BITS[n] for n, s in self.sonars.items() if s.fault)
        mask |= (FAULT_BITS["front_floor"] if self.front_ir.fault else 0) | (FAULT_BITS["back_floor"] if self.back_ir.fault else 0)
        return out, ff, bf, mask
