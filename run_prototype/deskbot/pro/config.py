"""Settings of the pro runtime: data/pro.json (pro_sim.json in simulation). Same rules as full/config.py: defaults
merged with the file, unknown keys dropped, every value checked against its type and range, written atomically.
Voice/personality profiles are kept here too (profiles.py)."""

from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"      # Groq production model with tool use + JSON mode (checked 20 Nov 2026)

DEFAULTS = {
    "touch": {"enabled": True, "mode": "momentary", "speak": True, "move": True, "cooldown_s": 2.0, "hold_s": 1.2,
              "pats_for_excited": 3},
    "motion": {"enabled": True, "knock": True, "shake": True, "bump": True, "tip": True, "drop": True, "speak": True,
               "knock_ms2": 4.0, "bump_ms2": 5.0, "shake_rads": 4.0, "tip_deg": 60.0},
    "groq": {"enabled": True, "model": GROQ_DEFAULT_MODEL, "reasoning_effort": "low"},
}
RULES = {
    ("touch", "enabled"): (bool,), ("touch", "speak"): (bool,), ("touch", "move"): (bool,),
    ("touch", "mode"): (str, 10, r"^(momentary|toggle)$"),
    ("touch", "cooldown_s"): (float, 0.5, 30.0), ("touch", "hold_s"): (float, 0.5, 5.0),
    ("touch", "pats_for_excited"): (int, 2, 10),
    ("motion", "enabled"): (bool,), ("motion", "knock"): (bool,), ("motion", "shake"): (bool,), ("motion", "bump"): (bool,),
    ("motion", "tip"): (bool,), ("motion", "drop"): (bool,), ("motion", "speak"): (bool,),
    ("motion", "knock_ms2"): (float, 1.5, 20.0), ("motion", "bump_ms2"): (float, 2.0, 30.0),
    ("motion", "shake_rads"): (float, 1.0, 15.0), ("motion", "tip_deg"): (float, 35.0, 85.0),
    ("groq", "enabled"): (bool,), ("groq", "model"): (str, 80, r"^[\w.:\-/]+$"),
    ("groq", "reasoning_effort"): (str, 6, r"^(low|medium|high)$"),
}


def validate(changes):
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    out = {}
    for section, values in changes.items():
        if section not in DEFAULTS or not isinstance(values, dict):
            continue
        for key, value in values.items():
            rule = RULES.get((section, key))
            if rule is None:
                continue
            typ = rule[0]
            if typ is bool:
                value = bool(value)
            elif typ in (int, float):
                value = typ(value)
                if not rule[1] <= value <= rule[2]:
                    raise ValueError(f"{section}.{key} must be {rule[1]}-{rule[2]}")
            else:
                value = " ".join(str(value).split())[: rule[1]]
                if rule[2] and not re.match(rule[2], value):
                    raise ValueError(f"{section}.{key} has the wrong format")
            out.setdefault(section, {})[key] = value
    return out


class ProSettings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                for section, values in saved.items():
                    if section in self.data and isinstance(values, dict):
                        self.data[section].update({k: v for k, v in values.items() if k in self.data[section]})
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
            for section, values in clean.items():
                self.data[section].update(values)
            snap = copy.deepcopy(self.data)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
        return snap
