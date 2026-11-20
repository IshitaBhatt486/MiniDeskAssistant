"""
Buddy settings (tasks, reminders, phone notifications): data/buddy.json, changed from the dashboard.

Same pattern as assistant/settings.py: defaults merged with the saved file, unknown keys dropped, every
change validated, written atomically. The phone's token is separate (notify_token()).
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import threading
from pathlib import Path

from .. import ROOT

DATA_DIR = ROOT / "data"
TOKEN_FILE = DATA_DIR / "notify_token"

DEFAULTS = {
    "tasks": {
        "remind_before_min": 15,      # "heads up" this long before a deadline
        "overdue_after_min": 60,      # one nudge this long after a missed deadline
        "celebrate": True,            # fanfare + eyes + victory move when a task is done
        "move": True,                 # physical reactions (celebrate / nudge); off = sound and eyes only
    },
    "notify": {
        "enabled": True,
        "use_ai": True,               # let Claude judge the unclear ones (sends app, sender, text; never codes)
        "read_text": True,            # read the message itself; off = only "new WhatsApp message from Mom"
        "vip": [],                    # names that are always important
        "keywords": [],               # words that are always important
        "important_apps": [],         # apps that are always important
        "muted_apps": [],             # apps that are never read
        "quiet_start": "22:00",       # no notifications between these times (held until the end)
        "quiet_end": "07:00",
        "hold_when_away": True,       # owner's phone away / robot asleep: hold them and summarise on return
        "move": False,                # a small nudge with each notification
        "max_age_h": 12,              # forget held notifications after this long
    },
}

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if k not in out:
            continue
        out[k] = _merge(out[k], v) if isinstance(out[k], dict) and isinstance(v, dict) else v
    return out


def _names(value, what):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a list")
    out = [" ".join(str(v).split())[:40] for v in value if str(v).strip()]
    if len(out) > 30:
        raise ValueError(f"at most 30 {what}")
    return out


def validate(changes):
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    out = {}
    t = changes.get("tasks")
    if isinstance(t, dict):
        o = {}
        for k, lo, hi in (("remind_before_min", 0, 1440), ("overdue_after_min", 5, 1440)):
            if k in t:
                v = int(t[k])
                if not lo <= v <= hi:
                    raise ValueError(f"{k} must be {lo}-{hi}")
                o[k] = v
        for k in ("celebrate", "move"):
            if k in t:
                o[k] = bool(t[k])
        out["tasks"] = o
    n = changes.get("notify")
    if isinstance(n, dict):
        o = {}
        for k in ("enabled", "use_ai", "read_text", "hold_when_away", "move"):
            if k in n:
                o[k] = bool(n[k])
        for k in ("vip", "keywords", "important_apps", "muted_apps"):
            if k in n:
                o[k] = _names(n[k], k.replace("_", " "))
        for k in ("quiet_start", "quiet_end"):
            if k in n:
                v = str(n[k]).strip()
                if v and not _TIME.match(v):
                    raise ValueError(f"{k} must look like 22:00")
                o[k] = v
        if "max_age_h" in n:
            o["max_age_h"] = max(1, min(48, int(n["max_age_h"])))
        out["notify"] = o
    return out


class BuddySettings:
    def __init__(self, path: Path = DATA_DIR / "buddy.json"):
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


def notify_token(path: Path = TOKEN_FILE):
    """The phone's shared secret: NOTIFY_TOKEN (environment / secrets.env) or a random one made once."""
    env = os.environ.get("NOTIFY_TOKEN", "").strip()
    if env:
        return env
    try:
        if path.exists():
            token = path.read_text(encoding="utf-8").strip()
            if len(token) >= 12:
                return token
        token = secrets.token_urlsafe(12)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        return token
    except OSError:
        return secrets.token_urlsafe(12)   # read-only card: valid until restart
