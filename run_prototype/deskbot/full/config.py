"""Settings of the full runtime: data/full.json (full_sim.json in simulation). Defaults merged with the file,
unknown keys dropped, each value checked against its type and range, written atomically."""

from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path

DEFAULTS = {
    "owner": {"name": ""},                                         # how the robot addresses you ("" = no name)
    "briefing": {"auto": True, "morning_time": "08:00", "evening_time": "21:00", "telegram": True},
    "hydration": {"interval_min": 45, "goal": 8, "start": "08:00", "end": "22:00"},
    "reader": {"ocr": "auto", "speak": True},
    "local_llm": {"text_model": "llama3.2:3b", "vision_model": "qwen2.5vl:3b", "vision_timeout_s": 300},
    "guard": {"passphrase": "", "auto_arm": False},                # changed only with the admin PIN
    "telegram": {"speak_replies": False},
}
RULES = {   # (section, key) -> (type, low, high) | (str, max_len, regex) | (bool,)
    ("owner", "name"): (str, 30, None),
    ("briefing", "auto"): (bool,), ("briefing", "telegram"): (bool,),
    ("briefing", "morning_time"): (str, 5, r"^([01]\d|2[0-3]):[0-5]\d$"), ("briefing", "evening_time"): (str, 5, r"^([01]\d|2[0-3]):[0-5]\d$"),
    ("hydration", "interval_min"): (int, 10, 240), ("hydration", "goal"): (int, 1, 20),
    ("hydration", "start"): (str, 5, r"^([01]\d|2[0-3]):[0-5]\d$"), ("hydration", "end"): (str, 5, r"^([01]\d|2[0-3]):[0-5]\d$"),
    ("reader", "ocr"): (str, 10, r"^(auto|ollama|tesseract|claude)$"), ("reader", "speak"): (bool,),
    ("local_llm", "text_model"): (str, 60, r"^[\w.:\-/]+$"), ("local_llm", "vision_model"): (str, 60, r"^[\w.:\-/]+$"),
    ("local_llm", "vision_timeout_s"): (int, 30, 1200),
    ("guard", "passphrase"): (str, 40, None), ("guard", "auto_arm"): (bool,),
    ("telegram", "speak_replies"): (bool,),
}
PROTECTED = {"guard"}     # sections that need the admin PIN


def validate(changes, allow_protected=False):
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    out = {}
    for section, values in changes.items():
        if section not in DEFAULTS or not isinstance(values, dict):
            continue
        if section in PROTECTED and not allow_protected:
            raise PermissionError(f"{section} settings need the admin PIN")
        for key, value in values.items():
            rule = RULES.get((section, key))
            if rule is None:
                continue
            typ = rule[0]
            if typ is bool:
                value = bool(value)
            elif typ is int:
                value = int(value)
                if not rule[1] <= value <= rule[2]:
                    raise ValueError(f"{section}.{key} must be {rule[1]}-{rule[2]}")
            else:
                value = " ".join(str(value).split())[: rule[1]]
                if rule[2] and not re.match(rule[2], value):
                    raise ValueError(f"{section}.{key} has the wrong format")
            out.setdefault(section, {})[key] = value
    return out


class FullSettings:
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

    def public(self):
        with self._lock:
            d = copy.deepcopy(self.data)
        d["guard"]["passphrase"] = bool(d["guard"]["passphrase"])       # never sent to the browser
        return d

    def update(self, changes, allow_protected=False):
        clean = validate(changes, allow_protected)
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
        return self.public()
