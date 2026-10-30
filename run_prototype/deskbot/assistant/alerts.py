"""
One place every part of the robot reports problems to. Nothing in the assistant layer is allowed to
crash the robot: failures become alerts, and alerts are

    - printed + added to the dashboard event log (robot.log)
    - listed on the dashboard's Alerts card (with a "resolved" state when the problem goes away)
    - spoken out loud (the Speaker subscribes), rate-limited so a flapping sensor can't spam the speaker

Usage:
    alerts.warn("camera", "Camera stopped. I can still map with my sonars.")    # key = "camera"
    alerts.resolve("camera", "Camera is back.")                                  # only spoken if it was active
    with alerts.guard("weather", "I couldn't get the weather"):                  # exception -> alert, no crash
        ...
    value = alerts.call("stt", fn, fallback=None, message="Speech to text failed")
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from contextlib import contextmanager

LEVELS = ("info", "warn", "error")


class Alerts:
    SPEAK_COOLDOWN_S = 60.0     # the same alert key is spoken at most once a minute
    SPEAK_GLOBAL_GAP_S = 4.0    # and no two spoken alerts closer than this

    def __init__(self, log=None):
        self._log = log or (lambda level, msg: print(f"[{level.upper():5}] {msg}", flush=True))
        self._lock = threading.Lock()
        self.active = {}                    # key -> alert dict (current problems)
        self.history = deque(maxlen=60)     # everything, newest last
        self._spoken = {}                   # key -> last time spoken
        self._last_spoken = 0.0
        self._listeners = []                # fn(alert) -> called for alerts that should be spoken
        self._id = 0

    def subscribe(self, fn):
        self._listeners.append(fn)

    def set_logger(self, log):
        self._log = log

    # -- reporting --

    def report(self, level, key, message, speak=True, detail=None):
        now = time.time()
        with self._lock:
            self._id += 1
            alert = {"id": self._id, "t": now, "level": level, "key": key, "msg": message,
                     "detail": detail, "resolved": False}
            repeat = key in self.active and self.active[key]["msg"] == message
            if level != "info":
                self.active[key] = alert
            if not repeat:
                self.history.append(alert)
            say = (speak and level != "info" and not repeat
                   and now - self._spoken.get(key, 0) >= self.SPEAK_COOLDOWN_S
                   and now - self._last_spoken >= self.SPEAK_GLOBAL_GAP_S)
            if say:
                self._spoken[key] = now
                self._last_spoken = now
        if not repeat:
            self._safe_log("error" if level == "error" else ("warn" if level == "warn" else "info"),
                           f"{key}: {message}" + (f" ({detail})" if detail else ""))
        if say:
            for fn in list(self._listeners):
                try:
                    fn(alert)
                except Exception:   # a broken speaker must not break alerting
                    pass
        return alert

    def info(self, key, message, speak=False):
        return self.report("info", key, message, speak=speak)

    def warn(self, key, message, speak=True, detail=None):
        return self.report("warn", key, message, speak=speak, detail=detail)

    def error(self, key, message, speak=True, detail=None):
        return self.report("error", key, message, speak=speak, detail=detail)

    def resolve(self, key, message=None, speak=True):
        """The problem behind `key` went away. Says `message` only if the alert was active."""
        with self._lock:
            alert = self.active.pop(key, None)
            if alert:
                alert["resolved"] = True
        if alert and message:
            self.report("info", key, message, speak=False)
            if speak:
                for fn in list(self._listeners):
                    try:
                        fn({"level": "info", "key": key, "msg": message})
                    except Exception:
                        pass
        return alert is not None

    def is_active(self, key):
        with self._lock:
            return key in self.active

    # -- helpers --

    @contextmanager
    def guard(self, key, message, level="warn", speak=True, reraise=False):
        """Turn any exception inside the block into an alert instead of a crash."""
        try:
            yield
        except Exception as exc:
            self.report(level, key, message, speak=speak, detail=_short(exc))
            if reraise:
                raise

    def call(self, key, fn, *args, fallback=None, message=None, level="warn", speak=True, **kwargs):
        """fn(*args, **kwargs), or `fallback` (after an alert) if it raises."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            self.report(level, key, message or f"{key} failed", speak=speak, detail=_short(exc))
            return fallback

    def snapshot(self):
        with self._lock:
            return {"active": sorted(self.active.values(), key=lambda a: -a["t"]),
                    "history": list(self.history)[-30:]}

    def _safe_log(self, level, msg):
        try:
            self._log(level, msg)
        except Exception:
            print(f"[{level.upper():5}] {msg}", flush=True)


def _short(exc):
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) < 300 else text[:297] + "..."


def format_exc():
    return traceback.format_exc(limit=4)
