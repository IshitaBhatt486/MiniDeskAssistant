"""
Assistant settings (changed from the dashboard, saved to data/assistant.json) and secrets (API keys).

Secrets are NEVER accepted over HTTP. They come from environment variables or from `secrets.env` in the
repo root (git-ignored; copy secrets.env.example), lines of KEY=value:

    ANTHROPIC_API_KEY=...   the AI brain (Claude). Without it the robot uses the offline rule-based brain
    GROQ_API_KEY=...        speech-to-text with Whisper (free tier). Alternative: OPENAI_API_KEY
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

from .. import ROOT

DATA_DIR = ROOT / "data"
SETTINGS_FILE = DATA_DIR / "assistant.json"
SECRETS_FILE = ROOT / "secrets.env"

PERSONALITY_PRESETS = {
    "Cheerful helper": "You are Pip, a small, cheerful desk robot. You are upbeat, curious and a little bit silly. "
                       "You love tidy desks and you get excited when your human talks to you.",
    "Sarcastic sidekick": "You are Pip, a desk robot with a dry, sarcastic sense of humour. You help, but you "
                          "can't resist a witty remark. Never mean, just cheeky.",
    "Calm butler": "You are Pip, a polite and calm robotic butler. You speak formally and precisely, "
                   "and you address the user as 'boss'.",
    "Pirate": "You are Captain Pip, a tiny pirate robot sailing the seven desks. Talk like a pirate, "
              "call the desk 'the deck' and the user 'matey'.",
}

DEFAULTS = {
    "personality": PERSONALITY_PRESETS["Cheerful helper"],
    "robot_name": "Pip",
    "location": "",                  # city for the weather tool; empty = ask the AI to ask / use IP location
    "send_image": True,              # allow camera frames to be sent to the AI at all
    "vision_on_demand": True,        # ...and only when the request needs eyes; otherwise it gets the detections as text
    "local_commands": True,          # plain robot commands ("turn left", "go to the cup") never reach the AI
    "sounds": True,                  # short musical motifs for robot states
    "speak": True,                   # say the reply on the speaker
    "speaker_output": "laptop",      # 21 Nov 2026: laptop (browser plays it) | robot (Pi's speaker) | both
    "chipmunk": True,                # chipmunk voice effect
    "chipmunk_factor": 1.6,          # 1.0 = normal; 1.6 = classic chipmunk (pitch and tempo x1.6)
    "voice_style": "chipmunk",       # chipmunk | natural | deep | robot | radio | cave
    "voice_gender": "auto",          # auto | female | male (where the speech engine has them)
    "volume": 0.9,                   # 0..1, applied to the samples
    # 20 Nov 2026 (pro/ voice studio): pitch and speed are independent of each other and of the voice style
    "voice_pitch": 0.0,              # semitones, -12..+12 (pitch shift that keeps the duration)
    "voice_speed": 1.0,              # 0.5..2.0 talking speed (the engine's own rate where it has one)
    "voice_name": "",                # one of the engine's installed voices (Speaker.voices()); "" = its default
    "speak_alerts": True,            # say warnings out loud
    "execute_commands": True,        # run the commands the AI returns
    "model": "claude-haiku-5-5",
    "effort": "low",                 # low = fastest replies; this is a voice assistant
    "stt": "local",                  # local (never leaves the robot) | auto | groq | openai | none
    "allow_paid_apis": False,        # False: never call a billed API other than Claude (OpenAI speech-to-text)
    "local_whisper_model": "tiny.en",
    "ble": {"address": "", "name": "", "ibeacon_uuid": "", "near_rssi": -67, "away_rssi": -85,
            "away_timeout_s": 25.0, "auto_sleep": True, "auto_wake": True},
}


def load_secrets(path: Path = SECRETS_FILE):
    """Put KEY=value lines from secrets.env into os.environ (real environment variables win)."""
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def has_secret(name):
    return bool(os.environ.get(name))


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if k not in out:
            continue  # unknown keys (old versions, typos) are dropped
        if isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    """Thread-safe dict of settings, persisted as JSON. Corrupt files fall back to the defaults."""

    def __init__(self, path: Path = SETTINGS_FILE, on_warning=None):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                self.data = _merge(DEFAULTS, json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                if on_warning:
                    on_warning(f"Settings file unreadable ({exc}); using defaults")

    def get(self, key, default=None):
        with self._lock:
            return copy.deepcopy(self.data.get(key, default))

    def all(self):
        with self._lock:
            return copy.deepcopy(self.data)

    def update(self, changes: dict):
        """Validate + apply + save. Raises ValueError on a bad value."""
        clean = validate(changes)
        with self._lock:
            self.data = _merge(self.data, clean)
            snapshot = copy.deepcopy(self.data)
        self._save(snapshot)
        return snapshot

    def _save(self, data):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)   # atomic: a crash never leaves half a file
        except OSError:
            pass  # read-only SD card etc.: settings still apply until restart


def validate(changes: dict):
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    out = {}
    for key, value in changes.items():
        if key in ("personality",):
            value = str(value).strip()
            if not 1 <= len(value) <= 2000:
                raise ValueError("Personality must be 1-2000 characters")
        elif key in ("robot_name", "location"):
            value = str(value).strip()[:60]
        elif key in ("send_image", "vision_on_demand", "local_commands", "sounds", "speak", "chipmunk", "speak_alerts",
                     "execute_commands", "allow_paid_apis"):
            value = bool(value)
        elif key == "speaker_output":
            from .laptop_speaker import OUTPUTS
            if value not in OUTPUTS:
                raise ValueError(f"speaker_output must be one of {', '.join(OUTPUTS)}")
        elif key == "chipmunk_factor":
            value = float(value)
            if not 1.0 <= value <= 2.5:
                raise ValueError("Chipmunk factor must be between 1.0 and 2.5")
        elif key == "voice_style":
            from .voice import VOICE_STYLES
            if value not in VOICE_STYLES:
                raise ValueError(f"voice_style must be one of {', '.join(VOICE_STYLES)}")
        elif key == "voice_gender":
            from .voice import VOICE_GENDERS
            if value not in VOICE_GENDERS:
                raise ValueError(f"voice_gender must be one of {', '.join(VOICE_GENDERS)}")
        elif key == "voice_pitch":
            value = float(value)
            if not -12.0 <= value <= 12.0:
                raise ValueError("Pitch must be between -12 and +12 semitones")
        elif key == "voice_speed":
            value = float(value)
            if not 0.5 <= value <= 2.0:
                raise ValueError("Speed must be between 0.5 and 2.0")
        elif key == "voice_name":
            value = str(value).strip()[:80]
        elif key == "volume":
            value = float(value)
            if not 0.0 <= value <= 1.0:
                raise ValueError("Volume must be between 0 and 1")
        elif key == "effort":
            if value not in ("low", "medium", "high"):
                raise ValueError("effort must be low, medium or high")
        elif key == "model":
            value = str(value).strip()
            if not value.startswith("claude-"):
                raise ValueError("model must be a Claude model id")
        elif key == "stt":
            if value not in ("auto", "groq", "openai", "local", "windows", "none"):
                raise ValueError("stt must be auto, groq, openai, local, windows or none")
        elif key == "local_whisper_model":
            value = str(value).strip()[:40]
        elif key == "ble":
            if not isinstance(value, dict):
                raise ValueError("ble must be an object")
            ble = {}
            for k, v in value.items():
                if k in ("address", "name", "ibeacon_uuid"):
                    ble[k] = str(v).strip()[:64]
                elif k in ("near_rssi", "away_rssi"):
                    v = int(v)
                    if not -100 <= v <= -20:
                        raise ValueError(f"{k} must be between -100 and -20 dBm")
                    ble[k] = v
                elif k == "away_timeout_s":
                    ble[k] = max(5.0, min(300.0, float(v)))
                elif k in ("auto_sleep", "auto_wake"):
                    ble[k] = bool(v)
            value = ble
        else:
            continue  # ignore unknown keys
        out[key] = value
    return out
