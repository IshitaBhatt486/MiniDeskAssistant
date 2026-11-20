"""
Morning and evening briefings, spoken (and sent on Telegram if it's connected).

    morning   "Good morning! It's 21 degrees and clear in Delhi, up to 28 today. You have 2 things on your calendar:
              physics lab at 2 PM. Due today: submit the report at 5 PM. 1 task is overdue. Want to start with a
              focus session?"
    evening   "Here's your day: you finished 4 tasks, including the report. You focused for 1 hour 10 minutes, saved
              2 ideas and had 6 drinks. Still open: 3 tasks; the next deadline is tomorrow at 9 AM. Good night!"

When: automatically, once a day each, the first time you're at the desk after morning_time (08:00, until noon) and
after evening_time (21:00, until midnight); or when asked: "good morning" (before noon), "brief me", "morning
briefing", "how was my day?", "evening briefing". Parts whose source is missing or switched off are left out
(no weather in local-only mode, no calendar without Google). Made from templates: no AI, so it's free and instant.
State (the days already briefed): data/briefings.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from ..buddy.when import say_due


def _plural(n, word):
    return f"{n} {word}{'s' if n != 1 else ''}"


def _span(minutes):
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{_plural(h, 'hour')} {_plural(m, 'minute')}"
    return _plural(h, "hour") if h else _plural(m, "minute")


class Briefings:
    def __init__(self, path: Path, sources, settings=lambda: {"auto": True, "morning_time": "08:00", "evening_time": "21:00"},
                 clock=datetime.now):
        """sources: dict of callables, each may be missing or raise: weather() tasks() done_today() calendar(hours)
        focus_minutes() ideas_today() drinks_today() name()."""
        self.path = Path(path)
        self.src = sources
        self.settings = settings
        self.clock = clock
        self.state = {}
        self.last = None
        if self.path.exists():
            try:
                self.state = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.state = {}

    def _get(self, key, *args, default=None):
        fn = self.src.get(key)
        if fn is None:
            return default
        try:
            return fn(*args)
        except Exception:
            return default

    def morning(self):
        now = self.clock()
        name = self._get("name", default="")
        parts = [f"Good morning{', ' + name if name else ''}!"]
        w = self._get("weather")
        if w:
            today = (w.get("forecast") or [{}])[0]
            rain = today.get("rain_chance_pct")
            parts.append(f"It's {round(w['now']['temperature_c'])} degrees with {w['now']['conditions']} in {w['place'].split(',')[0]}"
                         + (f", up to {round(today['max_c'])} today" if today.get("max_c") is not None else "")
                         + (f", and a {rain} percent chance of rain" if rain and rain >= 40 else "") + ".")
        events = self._get("calendar", 16, default=None)
        if events:
            first = events[0]
            when = "all day" if first.get("all_day") else "at " + say_due(datetime.fromisoformat(first["start"]).astimezone().replace(tzinfo=None), now).split(" at ")[-1]
            parts.append(f"You have {_plural(len(events), 'thing')} on your calendar, starting with {first['title']} {when}.")
        tasks = self._get("tasks", default=[]) or []
        end = now.replace(hour=23, minute=59)
        due_today = [t for t in tasks if t.get("due") and now <= datetime.fromisoformat(t["due"]) <= end]
        overdue = [t for t in tasks if t.get("due") and datetime.fromisoformat(t["due"]) < now]
        if due_today:
            parts.append("Due today: " + "; ".join(f"{t['title']} {say_due(datetime.fromisoformat(t['due']), now).replace('today ', '')}"
                                                  for t in due_today[:3]) + ".")
        if overdue:
            parts.append(f"{_plural(len(overdue), 'task')} {'is' if len(overdue) == 1 else 'are'} overdue, starting with {overdue[0]['title']}.")
        if not due_today and not overdue and tasks:
            parts.append(f"Nothing is due today; you have {_plural(len(tasks), 'open task')}.")
        if not tasks and not events:
            parts.append("Your day looks clear.")
        parts.append("Want to start with a focus session? Just say start focus mode.")
        return " ".join(parts)

    def evening(self):
        now = self.clock()
        parts = ["Here's your day."]
        done = self._get("done_today", default=[]) or []
        if done:
            parts.append(f"You finished {_plural(len(done), 'task')}" + (f", including {done[-1]['title']}" if done else "") + ".")
        else:
            parts.append("No tasks ticked off today, and that's okay.")
        extras = []
        mins = self._get("focus_minutes", default=0) or 0
        if mins:
            extras.append(f"focused for {_span(mins)}")
        ideas = self._get("ideas_today", default=0) or 0
        if ideas:
            extras.append(f"saved {_plural(ideas, 'idea')}")
        drinks = self._get("drinks_today", default=None)
        if drinks:
            extras.append(f"had {_plural(drinks, 'drink')}")
        if extras:
            parts.append("You " + ", ".join(extras[:-1]) + (" and " if len(extras) > 1 else "") + extras[-1] + ".")
        tasks = self._get("tasks", default=[]) or []
        if tasks:
            nxt = next((t for t in tasks if t.get("due") and datetime.fromisoformat(t["due"]) > now), None)
            parts.append(f"Still open: {_plural(len(tasks), 'task')}" +
                         (f"; the next deadline is {nxt['title']} {say_due(datetime.fromisoformat(nxt['due']), now)}." if nxt else "."))
        events = self._get("calendar", 36, default=None)
        tomorrow = (now + timedelta(days=1)).date()
        first = next((e for e in (events or []) if not e.get("all_day")
                      and datetime.fromisoformat(e["start"]).astimezone().date() == tomorrow), None)
        if first:
            parts.append(f"Tomorrow starts with {first['title']} {say_due(datetime.fromisoformat(first['start']).astimezone().replace(tzinfo=None), now)}.")
        parts.append("Good night!" if now.hour >= 20 else "Nice work today!")
        return " ".join(parts)

    def make(self, kind):
        text = self.morning() if kind == "morning" else self.evening()
        self.last = {"kind": kind, "text": text, "t": self.clock().isoformat(timespec="seconds")}
        self.state[kind] = self.clock().date().isoformat()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.state), encoding="utf-8")
        except OSError:
            pass
        return text

    def due(self, present=True):
        """"morning" / "evening" if an automatic briefing is due now, else None."""
        s = self.settings()
        if not s.get("auto", True) or not present:
            return None
        now = self.clock()
        hm, today = now.strftime("%H:%M"), now.date().isoformat()
        if s.get("morning_time", "08:00") <= hm < "12:00" and self.state.get("morning") != today:
            return "morning"
        if hm >= s.get("evening_time", "21:00") and self.state.get("evening") != today:
            return "evening"
        return None

    def kind_for(self, text):
        t = text.lower()
        if any(w in t for w in ("how was my day", "evening briefing", "daily summary", "day summary", "end of day")):
            return "evening"
        if any(w in t for w in ("brief me", "briefing", "what's my day", "what is my day")):
            return "morning" if self.clock().hour < 15 else "evening"
        return None

    def status(self):
        return {"last": self.last, "done": self.state, "settings": self.settings()}
