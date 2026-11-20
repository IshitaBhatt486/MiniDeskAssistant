"""
The hub: plugs ideas, focus mode, Google Calendar, Spotify and the cost meter into the buddy robot.

For each feature it registers (see buddy/core.py for the same pattern):
    - Claude tools + a prompt paragraph            Brain.add_tool / add_prompt (stable list, so it stays cached)
    - sentences that work without the AI           Brain.local_handlers (the ideas one first: it can be
                                                   waiting for "the next sentence")
    - words that must never be a plain robot command   Brain.not_local ("stop the music" is not "stop")
    - lines for the AI's context                   Assistant.context_hooks
Focus mode also holds phone notifications (Buddy.hold_checks) and reacts with sound, eyes and a nudge.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from ..buddy.when import parse_due, parse_iso_or_words, say_due
from . import focus as focus_mod
from . import ideas as ideas_mod
from .accounts import AccountError

NOT_LOCAL = re.compile(r"\b(music|song|songs|spotify|playlist|track|album|volume|focus|pomodoro|idea|ideas|calendar)\b")

GOOGLE_PROMPT = """Google Calendar: if the user asks to put something on their (Google) calendar or to set a Google
reminder, call google_add_reminder (local ISO 8601 time; minutes_before -1 = their default). Tasks with deadlines
are already copied to Google Calendar automatically when it is connected, so add_task alone is enough for normal
reminders. "What's on my calendar" -> calendar_upcoming. If Google isn't connected, say they can connect it on the
dashboard."""
SPOTIFY_PROMPT = """Music: "play <song/artist/playlist>" -> spotify_play; pause, resume, next, previous, volume ->
spotify_control; "what's playing" -> spotify_now_playing. Keep the reply to a few words ("Playing Blinding Lights")."""

GOOGLE_TOOLS = [
    {"name": "google_add_reminder", "description": "Add an event with a pop-up reminder to the user's Google Calendar.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "when": {"type": "string", "description": "Local ISO 8601, e.g. 2026-11-20T16:00"},
         "minutes_before": {"type": "integer", "description": "Pop-up this many minutes before; -1 = default."}},
         "required": ["title", "when", "minutes_before"], "additionalProperties": False}},
    {"name": "calendar_upcoming", "description": "The user's next Google Calendar events.",
     "input_schema": {"type": "object", "properties": {"hours": {"type": "integer", "description": "How far ahead, e.g. 24."}},
                      "required": ["hours"], "additionalProperties": False}},
]
SPOTIFY_TOOLS = [
    {"name": "spotify_play", "description": "Play a song, artist, album or playlist on Spotify (empty query = resume).",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "kind": {"type": "string", "enum": ["", "track", "artist", "playlist", "album"]}},
         "required": ["query", "kind"], "additionalProperties": False}},
    {"name": "spotify_control", "description": "Pause, resume, skip, go back, or set the volume (0-100).",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["pause", "resume", "next", "previous", "volume"]},
         "volume": {"type": "integer", "description": "Only for volume; otherwise 0."}},
         "required": ["action", "volume"], "additionalProperties": False}},
    {"name": "spotify_now_playing", "description": "What is playing on Spotify now.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
]


def _wrap(fn):
    def run(args):
        try:
            return json.dumps(fn(args), default=str), False
        except (AccountError, LookupError, ValueError) as exc:
            return f"Error: {exc}", True
    return run


class Hub:
    def __init__(self, app, buddy, settings, accounts, calendar, spotify, ideas, focus, costs):
        self.app, self.buddy, self.settings = app, buddy, settings
        self.accounts, self.calendar, self.spotify = accounts, calendar, spotify
        self.ideas, self.focus, self.costs = ideas, focus, costs
        brain, assistant = app.brain, app.assistant

        # cost meter: every Claude call is counted, and the daily cap switches the AI off until midnight
        costs.guard(brain.claude)
        assistant.turn_listeners.append(lambda entry: costs.add(entry.get("usage")) if entry.get("backend") == "claude" else None)

        brain.not_local.append(NOT_LOCAL)
        for prompt, specs, handlers in (
                (ideas_mod.PROMPT, ideas_mod.TOOL_SPECS, ideas_mod.tool_handlers(ideas)),
                (focus_mod.PROMPT, focus_mod.TOOL_SPECS, focus_mod.tool_handlers(focus)),
                (GOOGLE_PROMPT, GOOGLE_TOOLS, self._google_tools()),
                (SPOTIFY_PROMPT, SPOTIFY_TOOLS, self._spotify_tools())):
            brain.add_prompt(prompt)
            for spec in specs:
                brain.add_tool(spec, handlers[spec["name"]])
        brain.local_handlers.insert(0, lambda text, ctx: ideas_mod.local_intent(text, ideas))
        brain.local_handlers.append(lambda text, ctx: self.local_intent(text))
        assistant.context_hooks += [ideas.context_lines, self._focus_lines, self._music_lines]

        buddy.store.listeners.append(calendar.on_task)
        buddy.hold_checks.append(lambda: focus.holding() and settings.section("focus")["hold_notifications"])
        focus.on_nudge, focus.on_end, focus.on_break_end = self._nudge, self._session_end, self._break_end

    # -- tools --

    def _google_tools(self):
        def add(a):
            due = parse_iso_or_words(a.get("when", ""))
            if due is None:
                raise ValueError("when is needed")
            mins = a.get("minutes_before", -1)
            r = self.calendar.add_reminder(a.get("title", "Reminder"), due, None if mins is None or mins < 0 else mins)
            return {"added": r, "spoken_when": say_due(due)}
        return {"google_add_reminder": _wrap(add),
                "calendar_upcoming": _wrap(lambda a: {"events": self.calendar.upcoming(max(1, min(168, a.get("hours") or 24)))})}

    def _spotify_tools(self):
        return {"spotify_play": _wrap(lambda a: self.spotify.play(a.get("query", ""), a.get("kind", ""))),
                "spotify_control": _wrap(lambda a: self.spotify.control(a.get("action", ""), a.get("volume"))),
                "spotify_now_playing": _wrap(lambda a: self.spotify.now_playing())}

    # -- context for the AI --

    def _focus_lines(self):
        st = self.focus.status()
        if st["state"] == "focusing":
            return [f"FOCUS MODE ON: {st['left_s'] // 60} min left, {st.get('focused_pct') or 0}% focused so far, "
                    f"{st['distractions']} distractions. Keep replies very short."]
        if st["state"] == "break":
            return [f"Focus break: {st['break_left_s'] // 60} min left."]
        return []

    def _music_lines(self):
        last = self.spotify.last
        if last and last.get("action") == "play":
            return [f"Last music request: {last.get('name')}{' by ' + last['by'] if last.get('by') else ''} on {last.get('device')}."]
        return []

    # -- focus reactions --

    def _nudge(self, kind, line):
        a = self.app
        a.speaker.chime("gasp" if kind == "phone" else "pop")
        emo = getattr(a, "emotion", None)
        if emo is not None:
            emo.react("annoyed" if kind == "phone" else "sad", 4.0, f"focus: {kind}")
        a.speaker.say(line, "chatter")
        if self.settings.section("focus")["move"] and self.buddy.may_move("tasks"):
            a.executor.run([{"action": "nudge", "amount": 0}], source="focus")

    def _session_end(self, summary):
        a = self.app
        pct = summary.get("focused_pct")
        if summary["reason"] != "finished":
            a.speaker.say(f"Focus mode off after {round(summary['minutes'])} minutes.", "chatter")
            return
        part = f"You were focused {pct} percent of the time" if pct is not None else "Session done"
        dist = summary["distractions"]
        a.speaker.say(f"Time's up! {part}, with {dist} distraction{'s' if dist != 1 else ''}. "
                      f"Take a {summary.get('break_min', 5)} minute break.", "chatter")
        if pct is None or pct >= focus_mod.GOOD_SESSION * 100:
            self.buddy.celebrate(None, "focus")

    def _break_end(self):
        self.app.speaker.chime("reminder")
        self.app.speaker.say("Break's over! Say start focus mode when you're ready for another round.", "chatter")

    # -- without the AI --

    def local_intent(self, text):
        t = re.sub(r"[.!?]+$", "", " ".join(text.lower().split()))
        reply = lambda speech, mood="happy", sound="none": {  # noqa: E731
            "speech": speech, "mood": mood, "sound": sound, "commands": [], "tools": [], "backend": "local"}
        f = self.settings.section("focus")
        m = re.search(r"\b(?:start (?:a )?(?:focus(?: mode| session)?|pomodoro)|focus mode on|let'?s focus|focus for)"
                      r"(?:\s+(?:for\s+)?(\d+)\s*(?:min(?:ute)?s?)?)?", t)
        if m and not t.startswith(("stop", "end")):
            st = self.focus.start(int(m.group(1)) if m.group(1) else f["minutes"], f["break_minutes"])
            return reply(f"Focus mode on for {st['minutes']} minutes. Look at your screen for a moment so I learn "
                         "what focused looks like. I'll hold your notifications.", "neutral", "ding")
        if re.search(r"\b(?:stop|end|cancel) (?:the )?(?:focus(?: mode| session)?|pomodoro|break)\b|\bfocus mode off\b", t):
            s = self.focus.stop("asked")
            return None if s is None else reply("Focus mode off.", "neutral")
        if re.search(r"\bhow am i doing\b", t) and self.focus.holding():
            st = self.focus.status()
            return reply(f"{st['left_s'] // 60} minutes left, {st.get('focused_pct') or 0} percent focused. Keep going!", "happy")
        try:
            if re.search(r"\b(?:pause|stop) (?:the )?music\b|\bpause spotify\b", t):
                self.spotify.control("pause")
                return reply("Paused.", "neutral")
            if re.search(r"\b(?:resume|unpause|continue) (?:the )?music\b|\bresume spotify\b", t):
                self.spotify.control("resume")
                return reply("Resuming.", "happy")
            if re.search(r"\b(?:next|skip)(?: (?:the )?(?:song|track))?\b", t) and NOT_LOCAL.search(t) or t in ("next song", "skip"):
                self.spotify.control("next")
                return reply("Skipping.", "happy", "whoosh")
            if re.search(r"\b(?:previous|last) (?:song|track)\b", t):
                self.spotify.control("previous")
                return reply("Going back.", "happy")
            m = re.search(r"\bvolume (?:to )?(\d{1,3})\b", t)
            if m:
                self.spotify.control("volume", int(m.group(1)))
                return reply(f"Volume {m.group(1)}.", "neutral")
            if re.search(r"\bwhat(?:'s| is) (?:this song|playing)\b", t):
                np = self.spotify.now_playing()
                return reply(f"This is {np['name']} by {np['by']}." if np.get("name") else "Nothing is playing.", "curious")
            m = re.match(r"^(?:please )?(?:play|put on)\s+(?:some\s+)?(.+?)(?:\s+on spotify)?$", t)
            if m:
                hit = self.spotify.play(m.group(1))
                return reply(f"Playing {hit['name']}" + (f" by {hit['by']}." if hit.get("by") else "."), "excited")
            m = re.match(r"^(?:add|put) (.+?) (?:to|on|in) (?:my )?(?:google )?calendar$", t)
            if m:
                due, title = parse_due(m.group(1))
                if due is None:
                    return reply("When should I put it on your calendar?", "curious")
                self.calendar.add_reminder(title, due)
                return reply(f"Added {title} to your Google Calendar, {say_due(due)}.", "happy", "ding")
            if re.search(r"\bwhat(?:'s| is) on my calendar\b|\bmy calendar today\b", t):
                events = self.calendar.upcoming(24)
                if not events:
                    return reply("Nothing on your calendar in the next day.", "happy")
                parts = []
                for e in events[:4]:
                    when = "all day" if e["all_day"] else say_due(datetime.fromisoformat(e["start"]).astimezone().replace(tzinfo=None))
                    parts.append(f"{e['title']} {when}")
                return reply("Coming up: " + "; ".join(parts) + ".", "curious")
        except AccountError as exc:
            return reply(str(exc), "confused")
        return None

    def status(self):
        return {"accounts": self.accounts.status(), "encryption": self.accounts.vault.encryption,
                "pin_set": bool(self.app_pin_set()), "calendar": self.calendar.status(), "spotify": {"last": self.spotify.last},
                "ideas": self.ideas.status(), "focus": self.focus.status(), "costs": self.costs.status(),
                "settings": self.settings.all()}

    def app_pin_set(self):
        return getattr(self, "pin", None) is not None and bool(self.pin.pin)
