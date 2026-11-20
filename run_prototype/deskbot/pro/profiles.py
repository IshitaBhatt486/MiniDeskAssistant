"""
Personality profiles (20 Nov 2026): a personality text bundled with a voice (style, engine voice, gender, pitch,
speed, chipmunk amount, volume), switched with one click on the Voice studio card or by saying "switch to the
pirate profile". Applying a profile writes those keys into the assistant settings (data/assistant.json), which
the brain and the speaker read on every turn, so the switch is immediate.

Built-in profiles come from assistant/settings.PERSONALITY_PRESETS, each with a voice that suits it; they can't be
deleted but can be overwritten. Your own are saved in data/profiles.json (profiles_sim.json in simulation).
"""

from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path

from ..assistant.settings import PERSONALITY_PRESETS, validate as validate_assistant

VOICE_KEYS = ("voice_style", "voice_gender", "voice_name", "voice_pitch", "voice_speed", "chipmunk_factor", "volume")
KEYS = ("personality",) + VOICE_KEYS

BUILTIN_VOICES = {
    "Cheerful helper": {"voice_style": "chipmunk", "chipmunk_factor": 1.6, "voice_pitch": 0.0, "voice_speed": 1.0},
    "Sarcastic sidekick": {"voice_style": "robot", "voice_pitch": -2.0, "voice_speed": 0.95},
    "Calm butler": {"voice_style": "natural", "voice_pitch": -3.0, "voice_speed": 0.85},
    "Pirate": {"voice_style": "deep", "voice_pitch": 0.0, "voice_speed": 0.9},
}


def builtins():
    out = {}
    for name, text in PERSONALITY_PRESETS.items():
        p = {"personality": text, "voice_style": "natural", "voice_gender": "auto", "voice_name": "", "voice_pitch": 0.0,
             "voice_speed": 1.0, "chipmunk_factor": 1.6, "volume": 0.9}
        p.update(BUILTIN_VOICES.get(name, {}))
        out[name] = p
    return out


class Profiles:
    def __init__(self, path: Path, settings):
        self.path, self.settings = Path(path), settings
        self._lock = threading.Lock()
        self.custom, self.active = {}, ""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.custom = {str(k)[:40]: {kk: v[kk] for kk in KEYS if kk in v} for k, v in data.get("profiles", {}).items()
                               if isinstance(v, dict)}
                self.active = str(data.get("active", ""))
            except (OSError, ValueError):
                pass

    def all(self):
        with self._lock:
            out = builtins()
            out.update(copy.deepcopy(self.custom))
            return out

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"active": self.active, "profiles": self.custom}, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def apply(self, name):
        profiles = self.all()
        key = self.find(name)
        if key is None:
            raise LookupError(f"no profile called {name!r}")
        self.settings.update({k: v for k, v in profiles[key].items() if k in KEYS})
        with self._lock:
            self.active = key
            self._save()
        return key

    def find(self, name):
        """Case-insensitive, and "pirate" finds "Pirate" (for voice commands)."""
        names = list(self.all())
        n = (name or "").strip().lower()
        for k in names:
            if k.lower() == n:
                return k
        hits = [k for k in names if n and n in k.lower()]
        return hits[0] if len(hits) == 1 else None

    def save(self, name, values=None):
        """Save the current settings (or `values`) as profile `name`."""
        name = " ".join(str(name).split())[:40]
        if not re.match(r"^[\w .,'&-]{1,40}$", name):
            raise ValueError("Profile names are 1-40 letters, digits, spaces and . , ' & -")
        src = values if values is not None else self.settings.all()
        clean = validate_assistant({k: src[k] for k in KEYS if k in src})
        with self._lock:
            if name not in self.custom and len(self.custom) >= 30:
                raise ValueError("That's 30 profiles already: delete one first")
            self.custom[name] = clean
            self.active = name
            self._save()
        return name

    def delete(self, name):
        with self._lock:
            if name not in self.custom:
                raise LookupError("Only your own profiles can be deleted" if name in PERSONALITY_PRESETS else f"no profile {name!r}")
            del self.custom[name]
            if self.active == name:
                self.active = ""
            self._save()

    def status(self):
        all_ = self.all()
        return {"active": self.active, "builtin": list(PERSONALITY_PRESETS),
                "profiles": [{"name": k, "builtin": k in PERSONALITY_PRESETS and k not in self.custom, **v} for k, v in all_.items()]}
