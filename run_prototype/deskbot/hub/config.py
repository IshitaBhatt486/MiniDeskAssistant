"""Hub settings: data/hub.json (hub_sim.json in simulation), changed from the dashboard. Same pattern as
buddy/config.py: defaults merged with the file, unknown keys dropped, validated, written atomically."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

DEFAULTS = {
    "costs": {"daily_cap_usd": 0.50},                      # 0 = no cap (the Console spend limit still applies)
    "google": {"sync_tasks": True, "minutes_before": 10},   # tasks with deadlines -> calendar events
    "spotify": {"device": "deskbot"},                       # preferred Spotify Connect device (name contains)
    "focus": {"minutes": 25, "break_minutes": 5, "move": True, "hold_notifications": True},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if k in out:
            out[k] = _merge(out[k], v) if isinstance(out[k], dict) and isinstance(v, dict) else v
    return out


def validate(changes):
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    out = {}
    c = changes.get("costs")
    if isinstance(c, dict) and "daily_cap_usd" in c:
        v = float(c["daily_cap_usd"])
        if not 0 <= v <= 20:
            raise ValueError("daily cap must be 0-20 dollars")
        out["costs"] = {"daily_cap_usd": round(v, 2)}
    g = changes.get("google")
    if isinstance(g, dict):
        o = {}
        if "sync_tasks" in g:
            o["sync_tasks"] = bool(g["sync_tasks"])
        if "minutes_before" in g:
            o["minutes_before"] = max(0, min(1440, int(g["minutes_before"])))
        out["google"] = o
    s = changes.get("spotify")
    if isinstance(s, dict) and "device" in s:
        out["spotify"] = {"device": " ".join(str(s["device"]).split())[:60]}
    f = changes.get("focus")
    if isinstance(f, dict):
        o = {}
        for k, lo, hi in (("minutes", 1, 180), ("break_minutes", 1, 60)):
            if k in f:
                v = int(f[k])
                if not lo <= v <= hi:
                    raise ValueError(f"{k} must be {lo}-{hi}")
                o[k] = v
        for k in ("move", "hold_notifications"):
            if k in f:
                o[k] = bool(f[k])
        out["focus"] = o
    return out


class HubSettings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                self.data = _merge(DEFAULTS, json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def section(self, name):
        with self._lock:
            return copy.deepcopy(self.data[name])

    def all(self):
        with self._lock:
            return copy.deepcopy(self.data)

    def update(self, changes):
        clean = validate(changes)
        with self._lock:
            self.data = _merge(self.data, clean)
            snap = copy.deepcopy(self.data)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
        return snap
