"""
Bluetooth LE: hear the owner's phone and turn its signal strength (RSSI) into near / away.

Sources (both feed PhoneTracker.add(rssi)):
    BleScanner     bleak (BlueZ over D-Bus on the Pi, WinRT on Windows) in passive-ish continuous scan
                   on its own asyncio thread. Matches the phone by any of: MAC address, name substring,
                   iBeacon UUID (Apple manufacturer data 0x004C, type 0x02 0x15).
    SimPhoneSource simulation: RSSI from the simulated robot pose to the "Phone" object on the desk.

Why a matcher with three options: phones don't advertise all the time, and most randomise their
Bluetooth address every ~15 min (privacy). Reliable choices, best first:
    1. a beacon app on the phone advertising a fixed iBeacon UUID (Android: "Beacon Simulator";
       iPhone: only while an advertiser app is open) -> set ble.ibeacon_uuid
    2. a BLE tag / smartwatch / fitness band with a fixed address -> set ble.address
    3. the phone's Bluetooth name while it advertises (e.g. during pairing screens) -> ble.name
The dashboard lists everything nearby so you can pick yours.

RSSI -> distance (log-distance path loss): d = 10 ** ((TX_1M - rssi) / (10 * N)), TX_1M = -59 dBm,
N = 2.2 indoors. Expect +-50 %: bodies, pockets and orientation move RSSI by 10 dB. That's why
near/away use thresholds with hysteresis and time, not distance.
"""

from __future__ import annotations

import asyncio
import math
import random
import threading
import time
from collections import deque

TX_1M = -59.0
PATH_N = 2.2
APPLE = 0x004C


def rssi_to_m(rssi):
    return round(10 ** ((TX_1M - rssi) / (10 * PATH_N)), 2) if rssi is not None else None


def ibeacon_uuid(manufacturer_data):
    data = (manufacturer_data or {}).get(APPLE)
    if data and len(data) >= 23 and data[0] == 0x02 and data[1] == 0x15:
        h = bytes(data[2:18]).hex()
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    return None


class PhoneTracker:
    """Smoothed RSSI + near/away state machine with hysteresis.

    near  : smoothed RSSI >= near_rssi for NEAR_HOLD_S
    away  : no advertisement for away_timeout_s, or smoothed RSSI < away_rssi for AWAY_HOLD_S
    Between the two thresholds nothing changes (hysteresis), so walking around the desk doesn't
    toggle sleep/wake.
    """
    EMA = 0.3            # weight of a new sample
    NEAR_HOLD_S = 2.0
    AWAY_HOLD_S = 10.0

    def __init__(self, settings, on_change=None):
        self.settings = settings
        self.on_change = on_change
        self._lock = threading.Lock()
        self.samples = deque(maxlen=600)   # (monotonic t, rssi)
        self.smoothed = None
        self.state = "unknown"             # unknown | near | away
        self.last_seen = None
        self._born = time.monotonic()
        self._cond_since = (None, self._born)   # (condition, since)

    def add(self, rssi, t=None):
        t = time.monotonic() if t is None else t
        with self._lock:
            self.samples.append((t, float(rssi)))
            self.smoothed = rssi if self.smoothed is None else (1 - self.EMA) * self.smoothed + self.EMA * rssi
            self.last_seen = t
        self.update(t)

    def mean(self, since):
        """Mean raw RSSI of samples newer than monotonic time `since`, or None."""
        with self._lock:
            vals = [r for t, r in self.samples if t >= since]
        return sum(vals) / len(vals) if vals else None

    def update(self, now=None):
        now = time.monotonic() if now is None else now
        ble = self.settings.get("ble", {})
        near, away, timeout = ble.get("near_rssi", -67), ble.get("away_rssi", -85), ble.get("away_timeout_s", 25.0)
        with self._lock:
            if self.last_seen is None:
                cond = "away" if now - self._born > timeout else None   # never heard it since start-up
            elif now - self.last_seen > timeout:
                cond = "away"
            elif self.smoothed >= near:
                cond = "near"
            elif self.smoothed < away:
                cond = "away_weak"
            else:
                cond = None
            if cond != self._cond_since[0]:
                self._cond_since = (cond, now)
            held = now - self._cond_since[1]
            new = self.state
            if cond == "near" and held >= self.NEAR_HOLD_S:
                new = "near"
            elif cond == "away" or (cond == "away_weak" and held >= self.AWAY_HOLD_S):
                new = "away"
            changed = new != self.state
            old, self.state = self.state, new
        if changed and self.on_change:
            self.on_change(old, new)

    def status(self):
        now = time.monotonic()
        with self._lock:
            hist = [round(r) for t, r in list(self.samples)[-60:]]
            return {"state": self.state, "rssi": None if self.smoothed is None else round(self.smoothed, 1),
                    "distance_m": rssi_to_m(self.smoothed),
                    "seen_s_ago": None if self.last_seen is None else round(now - self.last_seen, 1),
                    "history": hist}


class BleScanner:
    """Continuous BLE scan on a background asyncio loop. Never raises into the app."""

    RESTART_S = 20.0     # retry after an adapter error (Bluetooth off, adapter reset, ...)

    def __init__(self, settings, tracker, alerts):
        self.settings, self.tracker, self.alerts = settings, tracker, alerts
        self.nearby = {}            # address -> {"name", "rssi", "t", "ibeacon"}
        self.error = None
        self.running = False
        self.backend = "bleak"
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        try:
            import bleak  # noqa: F401
        except Exception as exc:
            self.error = f"bleak not installed ({type(exc).__name__}); pip install bleak"
            self.alerts.warn("bluetooth", "Bluetooth library missing, so I can't sense your phone.", detail=self.error)
            return self
        self._thread = threading.Thread(target=self._run, name="ble", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _matches(self, address, name, beacon):
        ble = self.settings.get("ble", {})
        a, n, u = ble.get("address", "").lower(), ble.get("name", "").lower(), ble.get("ibeacon_uuid", "").lower()
        return bool((a and address.lower() == a) or (n and name and n in name.lower()) or (u and beacon and beacon.lower() == u))

    def _on_adv(self, device, adv):
        try:
            name = adv.local_name or device.name or ""
            beacon = ibeacon_uuid(adv.manufacturer_data)
            now = time.monotonic()
            self.nearby[device.address] = {"name": name, "rssi": adv.rssi, "t": now, "ibeacon": beacon}
            if len(self.nearby) > 200:
                for k in sorted(self.nearby, key=lambda k: self.nearby[k]["t"])[:50]:
                    self.nearby.pop(k, None)
            if self._matches(device.address, name, beacon):
                self.tracker.add(adv.rssi, now)
        except Exception:
            pass   # a malformed advertisement must not stop the scan

    def _run(self):
        from bleak import BleakScanner

        async def scan_forever():
            async with BleakScanner(detection_callback=self._on_adv):
                self.running = True
                if self.error:
                    self.alerts.resolve("bluetooth", "Bluetooth works again.")
                self.error = None
                while not self._stop.is_set():
                    await asyncio.sleep(0.5)
                    self.tracker.update()

        while not self._stop.is_set():
            try:
                asyncio.run(scan_forever())
            except Exception as exc:
                self.running = False
                msg = f"{type(exc).__name__}: {exc}"[:200]
                if msg != self.error:
                    self.error = msg
                    self.alerts.warn("bluetooth", "Bluetooth scanning failed, I'll keep retrying.", detail=msg)
                self._stop.wait(self.RESTART_S)

    def devices(self, max_age=30.0):
        now = time.monotonic()
        out = [{"address": a, "name": d["name"], "rssi": d["rssi"], "ibeacon": d["ibeacon"],
                "age_s": round(now - d["t"], 1), "match": self._matches(a, d["name"], d["ibeacon"])}
               for a, d in list(self.nearby.items()) if now - d["t"] <= max_age]
        return sorted(out, key=lambda d: -d["rssi"])[:25]

    def status(self):
        return {"backend": self.backend, "running": self.running, "error": self.error}


class SimPhoneSource:
    """Simulated phone = the 'Phone' object on the simulated desk.

    RSSI = TX_1M - 10 N log10(d) - shadow + noise. shadow = 8 dB * (1 - cos(phi)) / 2, phi = angle
    between the robot's heading and the phone: the antenna sits at the front, so the robot's own body
    (battery, motors) shades signals from behind. That body shadow is what makes "turn around and
    listen" direction finding work - in the simulator and, more weakly, on the real robot.
    """
    SHADOW_DB = 8.0
    NOISE_DB = 1.5
    HZ = 8.0

    def __init__(self, hw, tracker):
        self.hw, self.tracker = hw, tracker
        self.present = True
        self.running = False
        self.error = None
        self.backend = "simulated"
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name="sim-phone", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def rssi(self):
        s = self.hw.snapshot()
        phone = next((o for o in s["obstacles"] if o.get("label") == "Phone"), None)
        if phone is None:
            return None
        px = phone["x"] + (phone.get("w", 0) / 2 if phone["kind"] == "rect" else 0)
        py = phone["y"] + (phone.get("h", 0) / 2 if phone["kind"] == "rect" else 0)
        dx, dy = px - s["x"], py - s["y"]
        d = max(0.05, math.hypot(dx, dy))
        phi = math.atan2(dy, dx) - s["theta"]
        shadow = self.SHADOW_DB * (1 - math.cos(phi)) / 2
        return TX_1M - 10 * PATH_N * math.log10(d) - shadow + random.gauss(0, self.NOISE_DB)

    def _run(self):
        self.running = True
        while not self._stop.is_set():
            try:
                if self.present:
                    r = self.rssi()
                    if r is not None:
                        self.tracker.add(r)
                self.tracker.update()
            except Exception as exc:
                self.error = str(exc)
            self._stop.wait(1.0 / self.HZ)

    def devices(self, max_age=30.0):
        if not self.present:
            return []
        st = self.tracker.status()
        return [{"address": "SIM:PH:ON:E0:00:01", "name": "Simulated phone", "rssi": st["rssi"], "ibeacon": None,
                 "age_s": st["seen_s_ago"], "match": True}]

    def status(self):
        return {"backend": self.backend, "running": self.running, "error": self.error, "present": self.present}
