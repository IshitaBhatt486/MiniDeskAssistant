"""
Voice routines: your own phrases that run several steps. One JSON file per routine in data/routines/.

    {
      "name": "Study time",
      "triggers": ["study time", "time to study"],      phrases (matched whole, ignoring case and punctuation;
                                                         "run study time" / "start the study time routine" work too)
      "events": ["time:19:00"],                         optional: arrive | leave | focus_end | time:HH:MM
      "enabled": true,
      "description": "50 minutes of focus with lo-fi",
      "steps": [
        {"do": "say", "text": "Let's study!"},
        {"do": "sound", "name": "fanfare"},
        {"do": "smart_home", "device": "desk lamp", "action": "on"},
        {"do": "spotify", "query": "lo-fi beats"},
        {"do": "focus", "minutes": 50, "break_minutes": 10}
      ]
    }

Steps ("do"), checked before a routine is saved or run (STEP_RULES): say {text}, sound {name}, wait {seconds <= 60},
commands {commands: robot actions, as the AI uses them}, emotion {name}, focus {minutes, break_minutes},
focus_stop {}, spotify {query} or {action: pause|resume|next|previous|volume, volume}, smart_home {device, action:
on|off|toggle|set, value}, briefing {kind: morning|evening}, telegram {text}, guard {on: bool}, task {title, due},
water {}. At most 20 steps; a routine can't start another routine (no loops).

Routines run on their own thread, one at a time; "stop" (or a new routine) cancels the rest. A failing step is
recorded and the routine goes on with the next one. Two examples are written the first time (study-time.json,
break-time.json); the AI can make new ones with the create_routine tool ("make a routine called movie night that
turns off the lamp and plays jazz"), and the dashboard shows, edits, runs, enables and deletes them.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

MAX_STEPS = 20
TIME_EVENT = re.compile(r"^time:([01]\d|2[0-3]):([0-5]\d)$")
EVENTS = ("arrive", "leave", "focus_end")

STEP_RULES = {   # do -> {field: (type, required)}
    "say": {"text": (str, True)},
    "sound": {"name": (str, True)},
    "wait": {"seconds": ((int, float), True)},
    "commands": {"commands": (list, True)},
    "emotion": {"name": (str, True)},
    "focus": {"minutes": (int, False), "break_minutes": (int, False)},
    "focus_stop": {},
    "spotify": {"query": (str, False), "action": (str, False), "volume": (int, False)},
    "smart_home": {"device": (str, True), "action": (str, True), "value": ((int, float), False)},
    "briefing": {"kind": (str, True)},
    "telegram": {"text": (str, True)},
    "guard": {"on": (bool, True)},
    "task": {"title": (str, True), "due": (str, False)},
    "water": {},
}

EXAMPLES = {
    "study-time": {"name": "Study time", "triggers": ["study time", "time to study"], "events": [], "enabled": True,
                   "description": "Lamp on, lo-fi music, 50 minutes of focus.",
                   "steps": [{"do": "say", "text": "Study time! Let's do this."}, {"do": "sound", "name": "fanfare"},
                             {"do": "smart_home", "device": "desk lamp", "action": "on"},
                             {"do": "spotify", "query": "lo-fi beats"},
                             {"do": "focus", "minutes": 50, "break_minutes": 10}]},
    "break-time": {"name": "Break time", "triggers": ["break time", "i need a break"], "events": [], "enabled": True,
                   "description": "Stop focusing, pause the music, a little dance.",
                   "steps": [{"do": "focus_stop"}, {"do": "spotify", "action": "pause"},
                             {"do": "say", "text": "Break time! Stretch, drink some water, look out of the window."},
                             {"do": "commands", "commands": [{"action": "dance", "amount": 0}]}]},
}


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40]
    if not s:
        raise ValueError("a routine needs a name")
    return s


def normal(text):
    return " ".join(re.sub(r"[^\w\s:]", " ", str(text).lower()).split())


def validate(data):
    """A clean copy of a routine, or ValueError explaining what's wrong (also sent back to the AI)."""
    if not isinstance(data, dict):
        raise ValueError("a routine must be a JSON object")
    name = " ".join(str(data.get("name", "")).split())[:60]
    if not name:
        raise ValueError("a routine needs a name")
    triggers = [normal(t) for t in data.get("triggers", []) if normal(t)][:8]
    events = [e for e in data.get("events", []) if isinstance(e, str)][:4]
    for e in events:
        if e not in EVENTS and not TIME_EVENT.match(e):
            raise ValueError(f"unknown event {e!r} (use arrive, leave, focus_end or time:HH:MM)")
    if not triggers and not events:
        raise ValueError("a routine needs at least one trigger phrase or event")
    for t in triggers:
        if len(t.split()) < 2 and t not in ("goodnight", "bedtime"):
            raise ValueError(f"trigger {t!r} is too short: use two or more words so it isn't said by accident")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("a routine needs a list of steps")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"at most {MAX_STEPS} steps")
    clean = []
    for i, st in enumerate(steps, 1):
        if not isinstance(st, dict) or st.get("do") not in STEP_RULES:
            raise ValueError(f"step {i}: 'do' must be one of {', '.join(STEP_RULES)}")
        rules = STEP_RULES[st["do"]]
        out = {"do": st["do"]}
        for field, (typ, required) in rules.items():
            if field not in st:
                if required:
                    raise ValueError(f"step {i} ({st['do']}) needs '{field}'")
                continue
            if not isinstance(st[field], typ) or (typ is int and isinstance(st[field], bool)):
                raise ValueError(f"step {i} ({st['do']}): '{field}' has the wrong type")
            out[field] = st[field][:500] if isinstance(st[field], str) else st[field]
        if st["do"] == "wait" and not 0 < out["seconds"] <= 60:
            raise ValueError(f"step {i}: wait must be 1-60 seconds")
        if st["do"] == "spotify" and not (out.get("query") or out.get("action")):
            raise ValueError(f"step {i}: spotify needs a query or an action")
        clean.append(out)
    return {"name": name, "triggers": triggers, "events": events, "enabled": bool(data.get("enabled", True)),
            "description": str(data.get("description", ""))[:200], "steps": clean}


class Routines:
    def __init__(self, folder: Path, actions=None, log=print, write_examples=True):
        self.folder = Path(folder)
        self.actions = actions or {}        # do -> fn(step) ; filled in by full/core.py
        self.log = log
        self.items = {}                     # slug -> routine
        self.errors = {}                    # slug -> problem in its file
        self.running = None
        self.last_run = None
        self._gen = 0
        self._lock = threading.Lock()
        self.folder.mkdir(parents=True, exist_ok=True)
        if write_examples and not any(self.folder.glob("*.json")):
            for key, data in EXAMPLES.items():
                (self.folder / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.reload()

    def reload(self):
        items, errors = {}, {}
        for p in sorted(self.folder.glob("*.json")):
            try:
                items[p.stem] = validate(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                errors[p.stem] = str(exc)
        self.items, self.errors = items, errors
        return self

    def save(self, data, key=None):
        r = validate(data)
        key = key or slug(r["name"])
        for other_key, other in self.items.items():
            clash = set(r["triggers"]) & set(other["triggers"])
            if other_key != key and clash:
                raise ValueError(f"'{sorted(clash)[0]}' already starts the routine {other['name']}")
        path = self.folder / f"{slug(key)}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(r, indent=2), encoding="utf-8")
        tmp.replace(path)
        self.reload()
        return r

    def delete(self, key):
        p = self.folder / f"{slug(key)}.json"
        if not p.exists():
            raise LookupError("no such routine")
        p.unlink()
        self.reload()

    def set_enabled(self, key, on):
        r = dict(self.items[key])
        r["enabled"] = bool(on)
        return self.save(r, key)

    def match(self, text):
        t = normal(text)
        t = re.sub(r"^(?:hey \w+ )?(?:please )?(?:run |start |do )?(?:the |my )?", "", t)
        t = re.sub(r" routine$", "", t)
        for key, r in self.items.items():
            if r["enabled"] and (t in r["triggers"] or t == normal(r["name"])):
                return key
        return None

    def for_event(self, event):
        return [k for k, r in self.items.items() if r["enabled"] and event in r["events"]]

    def run(self, key, why="voice", wait=False):
        r = self.items.get(key)
        if r is None:
            raise LookupError(f"no routine called {key!r}")
        with self._lock:
            self._gen += 1
            gen = self._gen
        t = threading.Thread(target=self._run, args=(key, r, gen, why), name=f"routine-{key}", daemon=True)
        t.start()
        if wait:
            t.join()
        return r

    def cancel(self):
        with self._lock:
            self._gen += 1

    def _run(self, key, r, gen, why):
        self.running = key
        results = []
        self.log(f"Routine {r['name']} ({why})")
        for st in r["steps"]:
            if gen != self._gen:
                results.append({"do": st["do"], "result": "cancelled"})
                continue
            try:
                if st["do"] == "wait":
                    end = time.monotonic() + st["seconds"]
                    while time.monotonic() < end and gen == self._gen:
                        time.sleep(0.1)
                    res = "ok"
                else:
                    fn = self.actions.get(st["do"])
                    if fn is None:
                        raise RuntimeError("not available here")
                    res = fn(st) or "ok"
            except Exception as exc:
                res = f"failed: {exc}"[:160]
            results.append({"do": st["do"], "result": res})
        if self.running == key:
            self.running = None
        self.last_run = {"key": key, "name": r["name"], "why": why, "t": time.time(), "steps": results}

    def status(self):
        return {"routines": [{"key": k, **r} for k, r in self.items.items()], "errors": self.errors,
                "running": self.running, "last_run": self.last_run, "folder": str(self.folder), "step_types": list(STEP_RULES)}


PROMPT = """Routines: the user's own phrases that run several steps (listed in robot_context). Saying a trigger phrase
runs it before you see it. To make or change one ("make a routine called movie night that ..."), call create_routine
with steps_json: a JSON array of steps, each {"do": ...} with do = say{text} | sound{name} | wait{seconds} |
commands{commands:[robot actions]} | emotion{name} | focus{minutes, break_minutes} | focus_stop | spotify{query} or
spotify{action: pause|resume|next|previous|volume, volume} | smart_home{device, action: on|off|toggle|set, value} |
briefing{kind: morning|evening} | telegram{text} | guard{on} | task{title, due} | water. Triggers need 2+ words."""

TOOL_SPECS = [
    {"name": "create_routine", "description": "Create or replace a voice routine.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "triggers": {"type": "array", "items": {"type": "string"}},
         "steps_json": {"type": "string", "description": "JSON array of step objects."},
         "description": {"type": "string"}},
         "required": ["name", "triggers", "steps_json", "description"], "additionalProperties": False}},
    {"name": "run_routine", "description": "Run a saved routine by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}},
    {"name": "list_routines", "description": "The saved routines and their trigger phrases.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
]


def tool_handlers(routines):
    def create(a):
        try:
            steps = json.loads(a.get("steps_json") or "[]")
            r = routines.save({"name": a.get("name"), "triggers": a.get("triggers", []), "steps": steps,
                               "description": a.get("description", ""), "enabled": True})
            return json.dumps({"saved": r}), False
        except (ValueError, json.JSONDecodeError) as exc:
            return f"Error: {exc}", True

    def run(a):
        key = routines.match(a.get("name", "")) or (slug(a.get("name", "x")) if slug(a.get("name", "x")) in routines.items else None)
        if not key:
            return f"Error: no routine called {a.get('name')!r}", True
        routines.run(key, "ai")
        return json.dumps({"running": routines.items[key]["name"]}), False

    def list_(a):
        return json.dumps([{"name": r["name"], "triggers": r["triggers"], "events": r["events"], "enabled": r["enabled"]}
                           for r in routines.items.values()]), False
    return {"create_routine": create, "run_routine": run, "list_routines": list_}
