"""
Deadlines in plain words, both ways, with no extra packages.

    parse_due("submit the report by 5pm tomorrow", now) -> (datetime(tomorrow 17:00), "submit the report")
    say_due(due, now)                                     -> "tomorrow at 5 PM"

The AI (Claude) normally resolves times itself and passes ISO 8601 to the task tools; this parser is for
the dashboard's "add a task" box, the offline brain, and as a fallback when the AI sends words, not ISO.

Understood (case-insensitive, anywhere in the sentence):
    in 20 minutes / in an hour / in 2 hours / in half an hour / in 3 days / in a week
    today, tonight (20:00), tomorrow, the day after tomorrow, (on|by|this|next) monday..sunday
    at 5, at 5pm, at 5:30 pm, at 17:30, by 9 am, noon, midnight
    this morning / in the morning (09:00), afternoon (14:00), evening (18:00), end of (the) day (18:00)

Rules:
    - a day without a time means 17:00 that day (a deadline "by Friday" is a working-day deadline)
    - "at 5" without am/pm: 1-7 means pm; 8-11 is the next one still ahead today
    - a time with no day that has already passed today means tomorrow
    - weekday names mean the next one (today counts unless "next" is said)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SMALL = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "forty-five": 45}
UNITS = {"minute": 60, "min": 60, "mins": 60, "hour": 3600, "hr": 3600, "hrs": 3600, "day": 86400, "week": 604800}
DEFAULT_TIME = (17, 0)
PARTS = {"morning": (9, 0), "afternoon": (14, 0), "evening": (18, 0), "tonight": (20, 0), "night": (20, 0)}

_NUM = r"(\d+(?:\.\d+)?|half an?|an?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty[ -]five)"
_REL = re.compile(rf"\b(?:with)?in {_NUM} ?(minutes?|mins?|hours?|hrs?|days?|weeks?)\b")
_DAY = re.compile(r"\b(?:(?:on|by|before|this|until|till)\s+)?(?:(next)\s+)?(the day after tomorrow|tomorrow|today|tonight|"
                  + "|".join(WEEKDAYS) + r")\b")
_CLOCK = re.compile(r"\b(?:(?:at|by|before|around|until|till)\s+)?(\d{1,2})(?::|\.)(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?(?!\w)"
                    r"|\b(?:(?:at|by|before|around|until|till)\s+)?(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)(?!\w)"
                    r"|\b(?:at|by|before|around|until|till)\s+(\d{1,2})(?!\s*(?:minutes?|mins?|hours?|days?|%|\w))\b")
_NAMED = re.compile(r"\b(?:(?:at|by|before|around)\s+)?(noon|midday|midnight)\b"
                    r"|\b(?:(?:this|in the|by the|tomorrow|by)\s+)?(morning|afternoon|evening|night)\b"
                    r"|\b(?:by\s+)?(?:the\s+)?end of (?:the )?day\b|\beod\b")
_FILLER = re.compile(r"(?:\s+(?:by|at|on|before|due|until|till|for|this|next|in|the))+\s*$|^\s*(?:to|that i|i)\s+", re.I)


def _amount(word):
    word = word.strip()
    if word.startswith("half"):
        return 0.5
    try:
        return float(word)
    except ValueError:
        return float(SMALL.get(word.replace("-", " "), SMALL.get(word, 1)))


def _cut(text, m):
    return (text[:m.start()] + " " + text[m.end():]).strip()


def parse_due(text, now=None):
    """(due datetime or None, the text with the time words removed). `now` is a naive local datetime."""
    now = now or datetime.now()
    rest = " ".join(text.split())
    low = rest.lower()

    m = _REL.search(low)
    if m:
        unit = m.group(2).rstrip("s") if m.group(2) not in ("mins", "hrs") else m.group(2)
        due = now + timedelta(seconds=_amount(m.group(1)) * UNITS[unit])
        return due.replace(second=0, microsecond=0), _tidy(_cut(rest, m))

    day, hm, explicit_day = None, None, False
    m = _DAY.search(low)
    if m:
        word, nxt = m.group(2), bool(m.group(1))
        explicit_day = True
        if word == "today":
            day = now.date()
        elif word == "tonight":
            day, hm = now.date(), PARTS["tonight"]
        elif word == "tomorrow":
            day = now.date() + timedelta(days=1)
        elif word == "the day after tomorrow":
            day = now.date() + timedelta(days=2)
        else:
            ahead = (WEEKDAYS.index(word) - now.weekday()) % 7
            if nxt and ahead == 0:
                ahead = 7
            day = now.date() + timedelta(days=ahead)
        rest, low = _cut(rest, m), _cut(low, m)

    m = _CLOCK.search(low)
    if m:
        if m.group(1):
            h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        elif m.group(4):
            h, mi, ampm = int(m.group(4)), 0, m.group(5)
        else:
            h, mi, ampm = int(m.group(6)), 0, None
        if h <= 24 and mi < 60:
            if ampm:
                pm = ampm.startswith("p")
                h = h % 12 + (12 if pm else 0)
            elif 1 <= h <= 7:
                h += 12
            elif 8 <= h <= 11 and day in (None, now.date()) and now.replace(hour=h, minute=mi) <= now:
                h += 12                 # "at 9" said at 10 am means 9 pm
            hm = (h % 24, mi)
            rest, low = _cut(rest, m), _cut(low, m)
    else:
        m = _NAMED.search(low)
        if m:
            word = m.group(1) or m.group(2)
            if word in ("noon", "midday"):
                hm = (12, 0)
            elif word == "midnight":
                hm = (23, 59)
            elif word:
                hm = PARTS[word]
            else:
                hm = (18, 0)            # end of day
            if "tomorrow" in m.group(0) and day is None:
                day, explicit_day = now.date() + timedelta(days=1), True
            rest, low = _cut(rest, m), _cut(low, m)

    if day is None and hm is None:
        return None, _tidy(rest)
    if day is None:
        day = now.date()
    due = datetime.combine(day, datetime.min.time()).replace(hour=(hm or DEFAULT_TIME)[0], minute=(hm or DEFAULT_TIME)[1])
    if due <= now and not explicit_day:
        due += timedelta(days=1)
    return due, _tidy(rest)


def _tidy(text):
    text = re.sub(r"\s+", " ", text).strip(" ,.;:!?")
    for _ in range(3):
        text = _FILLER.sub("", text).strip(" ,.;:!?")
    return text


def parse_iso_or_words(value, now=None):
    """The task tools' `due`: ISO 8601 from the AI ("2026-11-20T17:00"), or words as a fallback. None = no deadline."""
    value = (value or "").strip()
    if not value or value.lower() in ("none", "no", "null", "never"):
        return None
    try:
        due = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if due.tzinfo is not None:
            due = due.astimezone().replace(tzinfo=None)    # stored as naive local time
        if len(value) <= 10:                              # a date only
            due = due.replace(hour=DEFAULT_TIME[0], minute=DEFAULT_TIME[1])
        return due.replace(second=0, microsecond=0)
    except ValueError:
        pass
    due, _ = parse_due(value, now)
    if due is None:
        raise ValueError(f"I couldn't understand the time {value!r}")
    return due


def clock(due):
    h = due.hour % 12 or 12
    return f"{h}{f':{due.minute:02d}' if due.minute else ''} {'AM' if due.hour < 12 else 'PM'}"


def say_due(due, now=None):
    """How the robot says a deadline: "in 20 minutes", "today at 5 PM", "on Friday at 9 AM"."""
    now = now or datetime.now()
    delta = (due - now).total_seconds()
    if 0 <= delta < 3600:
        mins = max(1, round(delta / 60))
        return f"in {mins} minute{'s' if mins != 1 else ''}"
    days = (due.date() - now.date()).days
    if days == 0:
        return f"today at {clock(due)}"
    if days == 1:
        return f"tomorrow at {clock(due)}"
    if days == -1:
        return f"yesterday at {clock(due)}"
    if 1 < days < 7:
        return f"on {WEEKDAYS[due.weekday()].title()} at {clock(due)}"
    return f"on {due.day} {due.strftime('%B')} at {clock(due)}"


def say_span(seconds):
    """'15 minutes', '2 hours', '3 days'."""
    seconds = abs(seconds)
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size or unit == "minute":
            n = max(1, round(seconds / size))
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return ""
