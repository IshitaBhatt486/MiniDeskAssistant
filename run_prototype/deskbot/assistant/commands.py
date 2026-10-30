"""
The command vocabulary: the ONLY things the AI may ask the robot to do, and the executor that does them.

The AI's reply is JSON (enforced with structured outputs, see brain.py):

    {"speech": "Spinning!", "mood": "excited",
     "commands": [{"action": "spin", "amount": 1}, {"action": "move_forward", "amount": 0.5}]}

`amount` means different things per action (ACTIONS[...]["amount"]); it is clamped to a safe range, so a
confused model can't ask for a 60 s drive. At most MAX_COMMANDS run per reply.

The same JSON can be POSTed to /api/assistant/commands by any other program on the LAN ("passed on for
further action"), and `Executor.on_command(fn)` lets your own code see (or veto) every command first.
New actions: add an entry to ACTIONS and a branch in Executor._do.

Motion goes through the normal RobotProxy.move, so every safety rule (IR edges, sonar obstacles, stale
sensors) still applies. Commands run one after another on a worker thread; each waits for the robot to
be idle. A safety stop aborts the rest of the sequence, and the reason is spoken.
"""

from __future__ import annotations

import math
import random
import threading
import time

MAX_COMMANDS = 5
MAX_OBJECT_NAME = 40

# Pre-coded dances: (move, seconds). Each one has equal forward/backward and left/right time, so the robot
# ends about where it started. One is picked at random, never the same one twice running.
DANCES = {
    "wiggle": [("left", 0.2), ("right", 0.4), ("left", 0.4), ("right", 0.2)],
    "shimmy": [("forward", 0.15), ("backward", 0.15)] * 3,
    "twirl": [("left", 0.9), ("pause", 0.2), ("right", 0.9)],
    "cha-cha": [("forward", 0.25), ("backward", 0.25), ("left", 0.15), ("right", 0.3), ("left", 0.15),
                ("forward", 0.25), ("backward", 0.25)],
    "moonwalk": [("backward", 0.4), ("left", 0.2), ("right", 0.2), ("forward", 0.4)],
    "robot": [("left", 0.2), ("pause", 0.25), ("right", 0.4), ("pause", 0.25), ("left", 0.2),
              ("forward", 0.15), ("pause", 0.2), ("backward", 0.15)],
}

# action -> amount: (min, max, default, unit) or None when the action takes no amount
ACTIONS = {
    "move_forward":   {"amount": (0.2, 3.0, 1.0, "seconds"), "help": "drive forward"},
    "move_backward":  {"amount": (0.2, 3.0, 1.0, "seconds"), "help": "drive backward"},
    "turn_left":      {"amount": (5, 360, 90, "degrees"), "help": "turn left in place"},
    "turn_right":     {"amount": (5, 360, 90, "degrees"), "help": "turn right in place"},
    "spin":           {"amount": (1, 3, 1, "full turns"), "help": "spin around in place"},
    "dance":          {"amount": None, "help": "dance: one of several pre-coded routines, chosen at random"},
    "look_around":    {"amount": None, "help": "turn slowly once around to look at (and map) the desk"},
    "stop":           {"amount": None, "help": "stop moving now"},
    "face_user":      {"amount": None, "help": "turn to face the person once"},
    "follow_user_on": {"amount": None, "help": "keep facing the user automatically"},
    "follow_user_off": {"amount": None, "help": "stop turning toward the user"},
    "find_phone":     {"amount": None, "help": "find the owner's phone by Bluetooth and drive to it (stops at the desk edge)"},
    "navigate":       {"amount": None, "help": "plan a route around obstacles and drive to to_object; with from_object, "
                                               "visit that one first (\"go from the cup to the bottle\"). Use the names on "
                                               "the map, or \"obstacle 1\", \"nearest obstacle\", \"farthest obstacle\""},
    "set_home":       {"amount": None, "help": "remember the robot's current spot as home (go back with navigate, to_object \"home\")"},
    "sleep":          {"amount": None, "help": "go to sleep (quiet, no autonomous moves)"},
    "wake":           {"amount": None, "help": "wake up"},
    "reset_map":      {"amount": None, "help": "forget the map and start a new one"},
    "set_speed":      {"amount": (10, 100, 50, "percent"), "help": "set driving speed"},
}
MOODS = ["happy", "neutral", "excited", "curious", "sleepy", "sad", "confused"]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "speech": {"type": "string", "description": "What the robot says out loud. 1-3 short sentences, no emoji or markdown."},
        "mood": {"type": "string", "enum": MOODS},
        "commands": {
            "type": "array",
            "description": "Robot actions to run in order. Empty if the user didn't ask for movement.",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "amount": {"type": "number", "description": "See the action list; 0 = default."},
                    "from_object": {"type": "string", "description": "navigate only: where to go first. Otherwise empty."},
                    "to_object": {"type": "string", "description": "navigate only: the destination. Otherwise empty."},
                },
                "required": ["action", "amount", "from_object", "to_object"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["speech", "mood", "commands"],
    "additionalProperties": False,
}


def describe_actions():
    lines = []
    for name, a in ACTIONS.items():
        amt = a["amount"]
        unit = f" (amount = {amt[3]}, {amt[0]:g}-{amt[1]:g}, default {amt[2]:g})" if amt else " (amount = 0)"
        lines.append(f"- {name}: {a['help']}{unit}")
    return "\n".join(lines)


def _object_name(value):
    return " ".join(str(value or "").split())[:MAX_OBJECT_NAME]


def normalise(commands):
    """Validate + clamp a list of {"action", "amount"} (navigate also keeps from_object / to_object).
    Returns (clean list, list of problems)."""
    clean, problems = [], []
    if not isinstance(commands, list):
        return [], ["commands must be a list"]
    for c in commands[:MAX_COMMANDS]:
        if not isinstance(c, dict) or c.get("action") not in ACTIONS:
            problems.append(f"unknown command {c!r}"[:80])
            continue
        if c["action"] == "navigate":
            to_object = _object_name(c.get("to_object"))
            if not to_object:
                problems.append("navigate needs to_object")
                continue
            clean.append({"action": "navigate", "amount": 0.0, "from_object": _object_name(c.get("from_object")),
                          "to_object": to_object})
            continue
        spec = ACTIONS[c["action"]]["amount"]
        amount = 0.0
        if spec:
            try:
                amount = float(c.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            if amount <= 0 or math.isnan(amount):
                amount = spec[2]
            amount = max(spec[0], min(spec[1], amount))
        clean.append({"action": c["action"], "amount": amount})
    if len(commands) > MAX_COMMANDS:
        problems.append(f"only the first {MAX_COMMANDS} commands run")
    return clean, problems


class Executor:
    IDLE_TIMEOUT_S = 15.0

    def __init__(self, services, alerts, say):
        """services: object with .robot, .behaviour (or None), .mapper, .presence (or None)."""
        self.sv = services
        self.alerts = alerts
        self.say = say
        self._lock = threading.Lock()
        self._gen = 0                     # bumped to cancel the running sequence
        self._listeners = []
        self.current = None               # the command running now
        self.last = None                  # {"commands", "result", "t"}
        self.rng = random.Random()
        self.last_dance = None

    def on_command(self, fn):
        """fn(command dict) -> False to veto it. Called on the worker thread before each command."""
        self._listeners.append(fn)

    def cancel(self):
        with self._lock:
            self._gen += 1

    def run(self, commands, source="ai"):
        clean, problems = normalise(commands)
        if not clean:
            return clean, problems
        with self._lock:
            self._gen += 1
            gen = self._gen
        threading.Thread(target=self._run, args=(clean, gen, source), name="executor", daemon=True).start()
        return clean, problems

    # -- worker --

    def _cancelled(self, gen):
        return gen != self._gen

    def _wait_idle(self, gen, timeout=None):
        end = time.monotonic() + (timeout or self.IDLE_TIMEOUT_S)
        time.sleep(0.08)    # let the motor process pick the command up
        while time.monotonic() < end:
            if self._cancelled(gen):
                return "cancelled"
            m = self.sv.robot.snapshot()
            if m["state"] == "blocked":
                return m.get("reason") or "blocked by a safety rule"
            if m["state"] != "moving":
                return None
            time.sleep(0.05)
        return "timed out"

    def _move(self, gen, direction, seconds):
        """One move (split into <=10 s pieces). Returns None or why it stopped early."""
        from robot import MAX_DURATION   # dashboard/robot.py
        while seconds > 0.05:
            if self._cancelled(gen):
                return "cancelled"
            piece = min(seconds, MAX_DURATION)
            self.sv.robot.move(direction, round(piece, 3))
            why = self._wait_idle(gen, piece + 3)
            if why:
                return why
            seconds -= piece
        return None

    def _turn(self, gen, direction, degrees):
        from ..runtime.behaviour import turn_rate
        return self._move(gen, direction, math.radians(degrees) / turn_rate(self.sv.robot.speed))

    def _run(self, commands, gen, source):
        results = []
        for cmd in commands:
            if self._cancelled(gen):
                results.append({**cmd, "result": "cancelled"})
                continue
            veto = False
            for fn in self._listeners:
                try:
                    if fn(cmd) is False:
                        veto = True
                except Exception as exc:
                    self.alerts.warn("commands", "A command hook failed.", speak=False, detail=str(exc))
            if veto:
                results.append({**cmd, "result": "vetoed"})
                continue
            self.current = cmd
            try:
                why = self._do(cmd, gen)
            except Exception as exc:
                why = f"failed: {type(exc).__name__}: {exc}"
                self.alerts.warn("commands", f"I couldn't do {cmd['action'].replace('_', ' ')}.", detail=str(exc))
            results.append({**cmd, "result": why or "ok"})
            if why and why != "cancelled" and cmd["action"] not in ("find_phone", "navigate"):  # those two speak for themselves
                if not why.startswith("failed"):
                    self.say(f"I stopped. {why}.", kind="alert")
                for rest in commands[len(results):]:
                    results.append({**rest, "result": "skipped"})
                break
        self.current = None
        self.last = {"commands": results, "t": time.time(), "source": source}

    def _do(self, cmd, gen):
        a, amt = cmd["action"], cmd["amount"]
        sv = self.sv
        if a == "move_forward":
            return self._move(gen, "forward", amt)
        if a == "move_backward":
            return self._move(gen, "backward", amt)
        if a == "turn_left":
            return self._turn(gen, "left", amt)
        if a == "turn_right":
            return self._turn(gen, "right", amt)
        if a == "spin":
            return self._turn(gen, "left", 360 * amt)
        if a == "dance":
            return self._dance(gen)
        if a == "look_around":
            for _ in range(8):           # 8 x 45 deg with pauses, so the camera gets sharp frames to map
                why = self._turn(gen, "left", 45)
                if why:
                    return why
                time.sleep(0.6)
            return None
        if a == "stop":
            sv.robot.stop()
            return None
        if a in ("face_user", "follow_user_on", "follow_user_off"):
            if sv.behaviour is None:
                return "I need the camera for that"
            if a == "face_user":
                return self._face_user_once(gen)
            sv.behaviour.set_enabled(a == "follow_user_on")
            return None
        if a == "find_phone":
            if sv.presence is None:
                return "Bluetooth is not available"
            return sv.presence.find_phone(cancelled=lambda: self._cancelled(gen))
        if a == "navigate":
            nav = getattr(sv, "navigator", None)
            if nav is None:
                return "navigation is not available"
            return nav.go(cmd["to_object"], cmd.get("from_object", ""), cancelled=lambda: self._cancelled(gen))
        if a == "set_home":
            nav = getattr(sv, "navigator", None)
            return "navigation is not available" if nav is None else nav.mark_home()
        if a in ("sleep", "wake"):
            if sv.presence is not None:
                sv.presence.set_awake(a == "wake", reason="asked")
            return None
        if a == "reset_map":
            sv.mapper.reset()
            return None
        if a == "set_speed":
            sv.robot.update_settings(speed=amt / 100.0)
            return None
        return f"unknown action {a}"

    def _dance(self, gen):
        self.last_dance = self.rng.choice([n for n in DANCES if n != self.last_dance])
        self.sv.robot.log("info", f"Dancing: {self.last_dance}")
        for move, seconds in DANCES[self.last_dance]:
            if self._cancelled(gen):
                return "cancelled"
            if move == "pause":
                time.sleep(seconds)
                continue
            why = self._move(gen, move, seconds)
            if why:
                return why
        return None

    def _face_user_once(self, gen):
        from ..runtime.behaviour import pick_user
        res = self.sv.behaviour.vision.latest()
        user = pick_user(res.detections) if res else None
        if user is None:
            return "I can't see you right now"
        b = self.sv.behaviour.cam.bearing((user.box[0] + user.box[2]) / 2)
        deg = math.degrees(b)
        if abs(deg) < 5:
            return None
        # bearing > 0 = to the left (robot frame: y left)
        return self._turn(gen, "left" if deg > 0 else "right", abs(deg))

    def status(self):
        return {"current": self.current, "last": self.last, "last_dance": self.last_dance}
