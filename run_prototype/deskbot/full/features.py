"""
Every feature in one list: what it does, how to use it, and whether it can be switched off.

The same CATALOG feeds three things:
    python main.py help [topic]     the terminal guide to every feature and command (works without a robot)
    the dashboard's Features card   on/off switches (FeatureFlags), with the example commands
    local-only mode                 features marked internet=True are forced off while "local_only" is on,
                                    without forgetting their own setting, so switching local-only off restores them

FeatureFlags stores the new switches in data/features.json. Switches for older features are "adapters" onto the
setting that already controls them (e.g. sound_effects -> the assistant's "sounds" setting), so there is one
source of truth for each.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ..hub.accounts import AccountError


class FeatureOff(AccountError):
    """Raised by a switched-off feature. A subclass of AccountError, so every existing handler of account
    problems already turns it into a spoken / shown message instead of a crash."""


# key, title, group, what it does, voice / text examples, where (dashboard card / CLI), internet needed, default
CATALOG = [
    # --- talking ---
    ("ai_brain", "Claude AI brain", "Talking", "Understands anything you say, uses tools, picks moods and sounds.",
     ["what's the weather in Delhi?", "tell me a joke", "what do you see?"], "Assistant card", True, True),
    ("local_llm", "Local AI brain (Ollama)", "Talking", "A model on the robot or your laptop answers when Claude is off or missing. Free and private.",
     ["(anything; used when Claude isn't)"], "Features card · docs/local-only.md", False, True),
    ("wake_word", "\"Hey Pip\" wake word", "Talking", "Say the robot's name to talk, no button. Recognised on the robot (Vosk), nothing streamed.",
     ["hey pip, what time is it?", "hey pip ... turn left"], "Wake word card", False, True),
    ("sound_effects", "Sound effects and motifs", "Talking", "The AI's sound field (ta-da, rimshot, ...) and the robot's state tunes.",
     ["tell me a pun"], "Assistant settings", False, True),
    # --- doing ---
    ("routines", "Voice routines", "Doing", "Your own phrases that run several steps: focus, music, lights, messages.",
     ["study time", "break time", "make a routine called movie night that turns off the lamp and plays jazz"],
     "Routines card · data/routines/*.json", False, True),
    ("smart_home", "Smart home", "Doing", "Lights and plugs through Home Assistant, Shelly or Tasmota on your Wi-Fi.",
     ["turn on the desk lamp", "turn off the fan", "set the lamp to 30 percent"], "Smart home card", False, True),
    ("tasks", "Tasks and reminders", "Doing", "A spoken to-do list with deadlines, reminders and celebrations.",
     ["remind me to submit the report by 5 tomorrow", "I finished the report", "what's on my list?"], "Tasks card", False, True),
    ("ideas", "Ideas notebook", "Doing", "Say an idea, it's saved.", ["remember this idea: ...", "what were my ideas?"], "Ideas card", False, True),
    ("reader", "Read this for me", "Doing", "Reads a page from the camera, a dashboard upload or a Telegram photo; saves the text; can summarise.",
     ["read this for me", "summarise this page", "what does this say?"], "Reader card · data/reads/", False, True),
    ("focus", "Focus mode", "Doing", "Timed sessions; nudges when you look away or pick up your phone.",
     ["start focus mode", "focus for 50 minutes", "how am I doing?"], "Focus card", False, True),
    ("hydration", "Hydration buddy", "Doing", "Notices you drinking (camera) and reminds you when you haven't for a while.",
     ["I drank some water", "how much water have I had?"], "Hydration card", False, True),
    ("briefings", "Morning and evening briefings", "Doing", "Weather, calendar, deadlines in the morning; what you got done at night.",
     ["good morning", "brief me", "how was my day?"], "Briefing card", False, True),
    # --- fun ---
    ("rps", "Rock, paper, scissors", "Fun", "Play with your hand (camera gestures) or by voice; best of three.",
     ["let's play rock paper scissors", "rock"], "Games card", False, True),
    ("celebrations", "Celebrations", "Fun", "Fanfare, confetti eyes and a victory dance when you finish something.", ["I finished the report"], "Tasks settings", False, True),
    ("gestures", "Hand gestures", "Fun", "Thumbs up = dance, open palm = stop, and so on.", ["(show a gesture)"], "Gestures card", False, True),
    # --- watching ---
    ("owner_recognition", "Owner recognition", "Watching", "Learns your face (on the robot only) to greet you and tell you from visitors.",
     ["learn my face", "forget my face", "who am I?"], "People card", False, True),
    ("guard", "Guard mode", "Watching", "While you're away: asks anyone else at the desk who they are, takes a snapshot, tells you on Telegram.",
     ["guard my desk", "stop guarding"], "Guard card · data/guard/", False, False),
    ("phone_notifications", "Phone notifications", "Watching", "Reads only important notifications aloud.", ["(automatic)"], "Phone notifications card", False, True),
    ("notify_ai", "AI notification triage", "Watching", "Claude judges unclear notifications (never codes or passwords).", ["(automatic)"], "Phone notifications settings", True, True),
    # --- accounts and messages ---
    ("telegram", "Telegram bot", "Connected", "Message the robot from anywhere: tasks, ideas, photos to read, guard alerts.",
     ["/tasks", "/add buy milk", "/photo", "send a photo of a page"], "Telegram card", True, False),
    ("google_calendar", "Google Calendar", "Connected", "Reminders and task deadlines on your calendar.", ["what's on my calendar?"], "Connected accounts", True, True),
    ("spotify", "Spotify", "Connected", "Play, pause, skip, volume.", ["play lo-fi beats", "pause the music", "next song"], "Music card", True, True),
    ("web_tools", "Web tools", "Connected", "Weather, Wikipedia, jokes, exchange rates (free APIs, no keys).", ["what's the weather?", "who is Ada Lovelace?"], "-", True, True),
]
KEYS = [c[0] for c in CATALOG]

TOOL_FEATURE = {   # Claude tool -> feature; a switched-off feature's tools answer "switched off"
    "add_task": "tasks", "complete_task": "tasks", "update_task": "tasks", "remove_task": "tasks", "list_tasks": "tasks",
    "save_idea": "ideas", "list_ideas": "ideas", "delete_idea": "ideas",
    "focus_start": "focus", "focus_stop": "focus", "focus_status": "focus",
    "google_add_reminder": "google_calendar", "calendar_upcoming": "google_calendar",
    "spotify_play": "spotify", "spotify_control": "spotify", "spotify_now_playing": "spotify",
    "get_weather": "web_tools", "wikipedia_summary": "web_tools", "tell_joke": "web_tools", "convert_currency": "web_tools",
    "create_routine": "routines", "run_routine": "routines", "list_routines": "routines",
    "read_this": "reader", "smart_home": "smart_home", "log_drink": "hydration", "play_rps": "rps",
    "briefing": "briefings", "guard": "guard", "telegram_send": "telegram", "who_is_here": "owner_recognition",
}

# terminal-only things, for `python main.py help`
CLI_COMMANDS = [
    ("python main.py", "menu of everything (first offers the health check)"),
    ("python main.py full [--sim] [--lan]", "the robot with every feature (this guide's features)"),
    ("python main.py hub | buddy | start", "earlier, smaller versions (kept working)"),
    ("python main.py help [topic]", "this guide; topic = a feature name or group, e.g. help talking"),
    ("python main.py health [--sim]", "test every sensor and part"),
    ("python main.py calibrate [--sim]", "the complete calibration"),
    ("python main.py face --preview", "save every eye animation as pictures"),
    ("python main.py gestures", "show or change the gesture map"),
    ("python main.py imu | outputs | check", "IMU readout · saved files · library check"),
    ("python main.py shell | navigate | e2e | benchmarks", "tools (from the full repository)"),
    ("python main.py setup | deploy | service | hotspot", "install, copy to the Pi, start on boot, own Wi-Fi"),
]


class FeatureFlags:
    def __init__(self, path: Path, adapters=None):
        self.path = Path(path)
        self.adapters = adapters or {}        # key -> (get() -> bool, set(bool))
        self._lock = threading.Lock()
        self.data = {c[0]: c[7] for c in CATALOG}
        self.data["local_only"] = False
        self.listeners = []                    # fn(key, on)
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update({k: bool(v) for k, v in saved.items() if k in self.data})
            except (OSError, ValueError):
                pass

    def internet(self, key):
        return next((c[6] for c in CATALOG if c[0] == key), False)

    def raw(self, key):
        if key in self.adapters:
            try:
                return bool(self.adapters[key][0]())
            except Exception:
                return False
        return bool(self.data.get(key, False))

    def on(self, key):
        """Is this feature usable right now? (switched on, and allowed by local-only mode)."""
        if self.data.get("local_only") and self.internet(key):
            return False
        return self.raw(key)

    def require(self, key):
        if not self.on(key):
            title = next((c[1] for c in CATALOG if c[0] == key), key)
            why = " (local-only mode is on)" if self.data.get("local_only") and self.internet(key) else ""
            raise FeatureOff(f"{title} is switched off{why}. Turn it on in the dashboard's Features card.")

    def set(self, key, on):
        if key != "local_only" and key not in KEYS:
            raise ValueError(f"unknown feature {key!r}")
        on = bool(on)
        if key in self.adapters:
            self.adapters[key][1](on)
        with self._lock:
            self.data[key] = on
            snap = dict(self.data)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(snap, indent=1), encoding="utf-8")
        except OSError:
            pass
        for fn in self.listeners:
            try:
                fn(key, on)
            except Exception as exc:
                print(f"[FEAT ] {exc}", flush=True)
        return self.status()

    def status(self):
        local = bool(self.data.get("local_only"))
        return {"local_only": local, "features": [
            {"key": k, "title": t, "group": g, "what": w, "examples": ex, "where": where, "internet": net,
             "switched_on": self.raw(k), "on": self.on(k)}
            for k, t, g, w, ex, where, net, _ in CATALOG]}


def help_text(topic=""):
    """Plain-text guide (used by `python main.py help` when rich tables aren't wanted)."""
    topic = topic.lower().strip()
    lines = []
    groups = []
    for c in CATALOG:
        if c[2] not in groups:
            groups.append(c[2])
    for g in groups:
        items = [c for c in CATALOG if c[2] == g and (not topic or topic in (c[0], c[2].lower()) or topic in c[1].lower())]
        if not items:
            continue
        lines.append(f"\n{g.upper()}")
        for k, title, _, what, ex, where, net, default in items:
            lines.append(f"  {title}  [{k}{', needs internet' if net else ''}{', off by default' if not default else ''}]")
            lines.append(f"      {what}")
            lines.append("      say: " + " · ".join(f'"{e}"' if not e.startswith("(") else e for e in ex))
            lines.append(f"      see: {where}")
    if not topic or topic in ("cli", "commands", "terminal"):
        lines.append("\nTERMINAL COMMANDS (run inside run_prototype/)")
        for cmd, what in CLI_COMMANDS:
            lines.append(f"  {cmd:<48} {what}")
    return "\n".join(lines).strip() + "\n"
