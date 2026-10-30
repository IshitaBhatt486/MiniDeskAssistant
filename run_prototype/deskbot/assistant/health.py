"""
Health watchdog: checks every part of the robot every CHECK_S and turns problems into (spoken) alerts,
with a "back to normal" message when they clear. It never restarts anything by itself: the motor and
sensor processes already fail safe (motors stop on stale sensor data), and a restart loop on a broken
part would only hide the problem.

    process alive      motor / sensors / camera child processes (error: driving is impossible without them)
    sensor freshness   newest sensor sample older than SENSOR_STALE_S
    camera             camera process failed / never became ready within CAMERA_GRACE_S
    temperature        CPU > HOT_C (Pi thermal zone)
    power              `vcgencmd get_throttled` bit 0 = under-voltage now (weak supply -> random resets)
    internet           only when the AI brain needs it: TCP connect to api.anthropic.com:443 every NET_S
"""

from __future__ import annotations

import math
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

CHECK_S = 2.0
SENSOR_STALE_S = 1.0
CAMERA_GRACE_S = 90.0
HOT_C = 80.0
NET_S = 60.0
POWER_S = 10.0

PROC_MESSAGES = {
    "motor": ("error", "My motor process stopped, so I can't drive. Please restart me."),
    "sensors": ("error", "My sensor process stopped. I won't drive until it's back. Please restart me."),
    "camera": ("warn", "My camera process stopped. I'll keep mapping with my sonars."),
}


def cpu_temp():
    p = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(p.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def throttled():
    if not shutil.which("vcgencmd"):
        return None
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        return int(out.strip().split("=")[1], 16)
    except Exception:
        return None


def internet_ok(host="api.anthropic.com", port=443, timeout=3.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Health:
    def __init__(self, alerts, shared=None, procs=None, vision=None, brain=None):
        self.alerts, self.shared, self.procs, self.vision, self.brain = alerts, shared, procs or {}, vision, brain
        self.started = time.monotonic()
        self.status_ = {}
        self._running = False
        self._next_net = 0.0
        self._next_power = 0.0

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="health", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.check(time.monotonic())
            except Exception as exc:
                self.alerts.warn("health", "My self-check hit an error.", speak=False, detail=str(exc))
            time.sleep(CHECK_S)

    def _flag(self, key, bad, level, msg, ok_msg=None):
        if bad:
            self.alerts.report(level, key, msg)
        else:
            self.alerts.resolve(key, ok_msg)

    def check(self, now):
        st = {}
        for role, p in self.procs.items():
            alive = p.is_alive()
            st[f"{role}_alive"] = alive
            level, msg = PROC_MESSAGES.get(role, ("warn", f"{role} process stopped"))
            self._flag(f"proc-{role}", not alive, level, msg)

        if self.shared is not None:
            t = self.shared.sensors.read()["t"]
            age = None if math.isnan(t) else time.monotonic() - t
            st["sensor_age_s"] = None if age is None else round(age, 2)
            if now - self.started > 10:
                self._flag("sensors", age is None or age > SENSOR_STALE_S, "error",
                           "My sensors stopped updating, so I won't drive.", "Sensors are back.")

        if self.vision is not None and now - self.started > 5:
            vs = self.vision.status()
            failed = not vs.get("enabled") and not vs.get("starting", False)
            slow = vs.get("starting") and now - self.started > CAMERA_GRACE_S
            st["camera"] = "ok" if vs.get("enabled") else ("starting" if vs.get("starting") else "failed")
            self._flag("camera", failed or slow, "warn",
                       "My camera isn't working. I can still map with my sonars." if failed else
                       "My camera is taking very long to start.", "Camera is working again.")

        temp = cpu_temp()
        st["cpu_temp_c"] = temp
        if temp is not None:
            self._flag("hot", temp > HOT_C, "warn", f"I'm getting hot, {temp:.0f} degrees. I may slow down.",
                       "I've cooled down.")

        if now >= self._next_power:
            self._next_power = now + POWER_S
            th = throttled()
            st["throttled"] = None if th is None else hex(th)
            if th is not None:
                self._flag("power", bool(th & 0x1), "warn",
                           "My power supply is too weak. Please use a stronger power supply.", "Power is fine again.")

        if self.brain is not None and self.brain.backend() == "claude" and now >= self._next_net:
            self._next_net = now + NET_S
            ok = internet_ok()
            st["internet"] = ok
            self._flag("internet", not ok, "warn", "I lost my internet connection. I'll use simple mode.",
                       "I'm back online.")
        self.status_.update(st)

    def status(self):
        return dict(self.status_)
