"""
The task list: what you tell the robot you need to do, with deadlines and reminders.

Storage: data/tasks.json (data/tasks_sim.json in simulation), written atomically after every change, so a
crash or power cut never loses the list. Times are naive local ISO strings ("2026-11-20T17:00:00").

    task = {"id": 3, "title": "submit the report", "due": "2026-11-20T17:00:00" | None,
            "created": iso, "done": False, "done_at": iso | None, "reminded": ["soon", "due"]}

Reminders (TaskStore.reminders_due): each open task with a deadline gets up to three, each said once:
    soon     remind_before_min before the deadline (default 15 min; skipped if the task was added later than that)
    due      at the deadline
    overdue  overdue_after_min after it (default 60 min), once
Changing the deadline clears the list, so the new one gets its own reminders.

Finding a task from words ("I finished the report"): TaskStore.find scores every task with difflib's
similarity of the whole strings and the share of the words that match, and accepts the best one only if it
is clearly better than the second best. Otherwise it says which tasks it could mean, so the AI can ask.

The AI gets five tools (TOOL_SPECS: add_task, complete_task, update_task, remove_task, list_tasks). Without
the AI, local_intent() understands the common sentences ("remind me to ... at 5", "I finished ...",
"what's on my list").
"""

from __future__ import annotations

import difflib
import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .when import parse_due, parse_iso_or_words, say_due, say_span

MAX_TASKS = 200
MAX_TITLE = 120
KEEP_DONE_DAYS = 14


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() if dt else None


def _dt(value):
    return datetime.fromisoformat(value) if value else None


class TaskStore:
    def __init__(self, path: Path, clock=datetime.now):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.RLock()
        self.tasks = []
        self.next_id = 1
        self.listeners = []      # fn(event, task, source): event = added | completed | reopened | removed | updated
        self.load_error = None
        self._load()

    # -- persistence --

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.tasks = [t for t in data.get("tasks", []) if isinstance(t, dict) and "id" in t and "title" in t]
            for t in self.tasks:
                t.setdefault("due", None)
                t.setdefault("done", False)
                t.setdefault("done_at", None)
                t.setdefault("reminded", [])
                t.setdefault("created", _iso(self.clock()))
            self.next_id = max([int(data.get("next_id", 1))] + [t["id"] + 1 for t in self.tasks])
        except (OSError, ValueError, TypeError) as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            backup = self.path.with_suffix(".corrupt.json")
            try:
                self.path.replace(backup)          # keep the broken file for a human; start an empty list
            except OSError:
                pass

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"next_id": self.next_id, "tasks": self.tasks}, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass   # read-only SD card: the list still works until restart

    def _emit(self, event, task, source):
        for fn in list(self.listeners):
            try:
                fn(event, dict(task), source)
            except Exception as exc:
                print(f"[TASKS] listener failed: {exc}", flush=True)

    def _prune(self):
        """Forget tasks done more than KEEP_DONE_DAYS ago, and keep at most MAX_TASKS."""
        limit = self.clock() - timedelta(days=KEEP_DONE_DAYS)
        self.tasks = [t for t in self.tasks if not (t["done"] and t["done_at"] and _dt(t["done_at"]) < limit)]
        while len(self.tasks) > MAX_TASKS:
            done = [t for t in self.tasks if t["done"]]
            self.tasks.remove(done[0] if done else self.tasks[0])

    # -- changes --

    def add(self, title, due=None, source="voice"):
        title = " ".join(str(title).split())[:MAX_TITLE].strip(" .")
        if not title:
            raise ValueError("A task needs a name")
        with self._lock:
            same = next((t for t in self.tasks if not t["done"] and t["title"].lower() == title.lower()), None)
            if same is not None:                      # said twice: update the deadline instead of a duplicate
                if due is not None:
                    return self.update(same["id"], due=due, source=source)
                return dict(same)
            task = {"id": self.next_id, "title": title, "due": _iso(due), "created": _iso(self.clock()),
                    "done": False, "done_at": None, "reminded": []}
            self.next_id += 1
            self.tasks.append(task)
            self._prune()
            self._save()
        self._emit("added", task, source)
        return dict(task)

    def complete(self, ref, source="voice"):
        with self._lock:
            task = self.get(ref)
            if task["done"]:
                return dict(task)
            task["done"], task["done_at"] = True, _iso(self.clock())
            self._save()
        self._emit("completed", task, source)
        return dict(task)

    def reopen(self, ref, source="dashboard"):
        with self._lock:
            task = self.get(ref)
            task["done"], task["done_at"], task["reminded"] = False, None, []
            self._save()
        self._emit("reopened", task, source)
        return dict(task)

    def remove(self, ref, source="voice"):
        with self._lock:
            task = self.get(ref)
            self.tasks.remove(task)
            self._save()
        self._emit("removed", task, source)
        return dict(task)

    _KEEP = object()

    def update(self, ref, title=_KEEP, due=_KEEP, source="voice"):
        with self._lock:
            task = self.get(ref)
            if title is not self._KEEP and str(title).strip():
                task["title"] = " ".join(str(title).split())[:MAX_TITLE]
            if due is not self._KEEP:
                task["due"] = _iso(due)
                task["reminded"] = []
            self._save()
        self._emit("updated", task, source)
        return dict(task)

    def mark_reminded(self, task_id, kind):
        with self._lock:
            for t in self.tasks:
                if t["id"] == task_id and kind not in t["reminded"]:
                    t["reminded"].append(kind)
                    self._save()

    # -- lookups --

    def get(self, ref):
        """A task by id (int or "#3" or "3") or by words. Raises LookupError with a speakable message."""
        with self._lock:
            if isinstance(ref, int) or re.fullmatch(r"#?\d+", str(ref).strip()):
                tid = int(str(ref).strip().lstrip("#"))
                for t in self.tasks:
                    if t["id"] == tid:
                        return t
                raise LookupError(f"there's no task number {tid}")
            return self.find(str(ref))

    def find(self, words, include_done=False):
        words = _normal(words) or " ".join(str(words).lower().split())
        pool = [t for t in self.tasks if include_done or not t["done"]] or list(self.tasks)   # all done: still findable
        if not pool:
            raise LookupError("your task list is empty")
        if not words:
            raise LookupError("which task?")
        scored = sorted(((_similarity(words, _normal(t["title"]) or t["title"].lower()), t) for t in pool), key=lambda x: -x[0])
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= 0.5 and best_score - second >= 0.12:
            return best
        if best_score >= 0.5:
            close = [t["title"] for s, t in scored if best_score - s < 0.12][:3]
            raise LookupError("that could be " + " or ".join(close))
        raise LookupError(f"I couldn't find a task like {words!r}")

    def open_tasks(self):
        """Open tasks, the ones with the nearest deadline first, then the rest in the order they were added."""
        with self._lock:
            tasks = [dict(t) for t in self.tasks if not t["done"]]
        return sorted(tasks, key=lambda t: (t["due"] is None, t["due"] or "", t["id"]))

    def done_since(self, since):
        with self._lock:
            return [dict(t) for t in self.tasks if t["done"] and t["done_at"] and _dt(t["done_at"]) >= since]

    def reminders_due(self, now=None, before_min=15, overdue_min=60):
        """[(task, kind)] that should be said now and haven't been. The caller marks them (mark_reminded)
        once actually said, so a reminder held back (owner away) is still due later."""
        now = now or self.clock()
        out = []
        with self._lock:
            for t in self.tasks:
                if t["done"] or not t["due"]:
                    continue
                due = _dt(t["due"])
                created = _dt(t["created"])
                said = t["reminded"]
                if now >= due + timedelta(minutes=overdue_min):
                    if "overdue" not in said:
                        out.append((dict(t), "overdue"))
                elif now >= due:
                    if "due" not in said:
                        out.append((dict(t), "due"))
                elif now >= due - timedelta(minutes=before_min) and "soon" not in said \
                        and created <= due - timedelta(minutes=before_min):
                    out.append((dict(t), "soon"))
        return out

    # -- for the AI and the dashboard --

    def summary_lines(self, now=None, limit=10):
        now = now or self.clock()
        tasks = self.open_tasks()
        if not tasks:
            lines = ["Task list: empty."]
        else:
            items = []
            for t in tasks[:limit]:
                if t["due"]:
                    due = _dt(t["due"])
                    late = " - OVERDUE" if due < now else ""
                    items.append(f"#{t['id']} {t['title']} (due {say_due(due, now)}{late})")
                else:
                    items.append(f"#{t['id']} {t['title']} (no deadline)")
            more = f" and {len(tasks) - limit} more" if len(tasks) > limit else ""
            lines = [f"Task list ({len(tasks)} open): " + "; ".join(items) + more + "."]
        done = self.done_since(now.replace(hour=0, minute=0, second=0, microsecond=0))
        if done:
            lines.append("Done today: " + "; ".join(t["title"] for t in done[-6:]) + ".")
        return lines

    def status(self, now=None):
        now = now or self.clock()
        with self._lock:
            tasks = [dict(t) for t in self.tasks]
        for t in tasks:
            if t["due"]:
                due = _dt(t["due"])
                t["due_text"] = say_due(due, now)
                t["overdue"] = not t["done"] and due < now
        open_ = sorted((t for t in tasks if not t["done"]), key=lambda t: (t["due"] is None, t["due"] or "", t["id"]))
        done = sorted((t for t in tasks if t["done"]), key=lambda t: t["done_at"] or "", reverse=True)[:15]
        return {"open": open_, "done": done, "load_error": self.load_error}


def _normal(text):
    text = re.sub(r"[^\w\s]", " ", str(text).lower())
    drop = {"the", "a", "an", "my", "to", "task", "with", "on", "of", "for", "that", "this"}
    return " ".join(w for w in text.split() if w not in drop)


def _similarity(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    aw, bw = set(a.split()), set(b.split())
    overlap = len(aw & bw) / max(1, min(len(aw), len(bw)))
    return max(seq, 0.85 * overlap + 0.15 * seq)


# ---------------- AI tools ----------------

PROMPT = """Task list: you keep the user's to-do list with the task tools. The current list is in robot_context.
- When the user tells you something they need to do (with or without a deadline), call add_task. Work out the
  deadline from the current time in robot_context and pass it as local ISO 8601 ("2026-11-20T17:00"); a day
  with no time means 17:00 that day; no deadline means "".
- When they say they did or finished something, call complete_task. The robot then celebrates by itself
  (fanfare, eyes and a little victory move), so congratulate them in words but use sound "none" and no commands.
- Never invent tasks. If a tool says a task is ambiguous, ask which one. Don't read task numbers aloud.
- Reminders are said automatically before and at each deadline; you don't need to schedule anything."""

_TASK = {"type": "string", "description": "The task's number (\"#3\") or a few words of its name."}
TOOL_SPECS = [
    {"name": "add_task", "description": "Add a task to the user's to-do list, optionally with a deadline.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "description": "Short task name, e.g. 'submit the physics report'."},
         "due": {"type": "string", "description": "Deadline as local ISO 8601 (2026-11-20T17:00), or \"\" for none."}},
         "required": ["title", "due"], "additionalProperties": False}},
    {"name": "complete_task", "description": "Mark a task as done (the user finished it).",
     "input_schema": {"type": "object", "properties": {"task": _TASK}, "required": ["task"], "additionalProperties": False}},
    {"name": "update_task", "description": "Rename a task or change its deadline.",
     "input_schema": {"type": "object", "properties": {
         "task": _TASK, "title": {"type": "string", "description": "New name, or \"\" to keep it."},
         "due": {"type": "string", "description": "New deadline (ISO 8601), \"\" to keep it, or \"none\" to remove it."}},
         "required": ["task", "title", "due"], "additionalProperties": False}},
    {"name": "remove_task", "description": "Delete a task the user no longer needs (not for finished tasks).",
     "input_schema": {"type": "object", "properties": {"task": _TASK}, "required": ["task"], "additionalProperties": False}},
    {"name": "list_tasks", "description": "The full task list with deadlines, and what was done recently.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
]


def _public(t, now):
    out = {"number": t["id"], "title": t["title"], "done": t["done"]}
    if t["due"]:
        out["due"] = t["due"]
        out["due_spoken"] = say_due(_dt(t["due"]), now)
    return out


def tool_handlers(store: TaskStore):
    """{name: fn(args) -> (text, is_error)} for Brain.add_tool."""

    def wrap(fn):
        def run(args):
            try:
                return json.dumps(fn(args, store.clock())), False
            except (LookupError, ValueError) as exc:
                return f"Error: {exc.args[0] if exc.args else exc}", True
        return run

    def add(args, now):
        t = store.add(args.get("title", ""), parse_iso_or_words(args.get("due", ""), now), source="ai")
        return {"added": _public(t, now), "open_tasks": len(store.open_tasks())}

    def complete(args, now):
        t = store.complete(args.get("task", ""), source="ai")
        left = store.open_tasks()
        return {"completed": _public(t, now), "open_tasks_left": len(left), "all_done": not left}

    def update(args, now):
        kw = {}
        if str(args.get("title", "")).strip():
            kw["title"] = args["title"]
        due = str(args.get("due", "")).strip()
        if due:
            kw["due"] = None if due.lower() == "none" else parse_iso_or_words(due, now)
        return {"updated": _public(store.update(args.get("task", ""), source="ai", **kw), now)}

    def remove(args, now):
        return {"removed": _public(store.remove(args.get("task", ""), source="ai"), now)}

    def list_(args, now):
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return {"now": _iso(now), "open": [_public(t, now) for t in store.open_tasks()],
                "done_today": [t["title"] for t in store.done_since(day)]}

    return {"add_task": wrap(add), "complete_task": wrap(complete), "update_task": wrap(update),
            "remove_task": wrap(remove), "list_tasks": wrap(list_)}


# ---------------- without the AI ----------------

_ADD = re.compile(r"^(?:hey |ok |okay )?(?:please |can you |could you )*(?:remind me to|remind me that i (?:need|have) to|"
                  r"add (?:a )?task(?: to)?|new task|add|i need to|i have to|i must|don'?t let me forget to)\s+(.+?)"
                  r"(?:\s+(?:to|on) (?:my |the )?(?:task|to-?do) list)?$")
_DONE = re.compile(r"^(?:i(?:'ve| have)? (?:just )?(?:finished|completed|done|did)|i'?m done with|done with|finished|"
                   r"completed|mark|tick off|check off|cross off)\s+(.+?)(?:\s+(?:as )?(?:done|complete|finished))?$")
_REMOVE = re.compile(r"^(?:please )?(?:remove|delete|cancel|forget)\s+(?:the )?(?:task\s+)?(.+?)(?:\s+from (?:my |the )?(?:task|to-?do) list)?$")
_LIST = re.compile(r"\b(?:what(?:'s| is| are)? (?:on )?my (?:tasks?|task list|to-?dos?|to-?do list|list)|"
                   r"(?:list|read|tell me) my (?:tasks?|to-?dos?)|what do i (?:have|need) to do|any tasks|my to-?do list)\b")


def local_intent(text, store: TaskStore, now=None):
    """A reply dict for a task sentence, or None. For when the AI is missing or down."""
    now = now or store.clock()
    t = re.sub(r"[.!?]+$", "", " ".join(text.lower().split()))
    reply = lambda speech, mood="happy", sound="none": {  # noqa: E731
        "speech": speech, "mood": mood, "sound": sound, "commands": [], "tools": [], "backend": "local"}
    if _LIST.search(t):
        tasks = store.open_tasks()
        if not tasks:
            return reply("Your list is empty. Nice!", "happy")
        parts = [f"{x['title']}, due {say_due(_dt(x['due']), now)}" if x["due"] else x["title"] for x in tasks[:5]]
        more = f", and {len(tasks) - 5} more" if len(tasks) > 5 else ""
        return reply(f"You have {len(tasks)} thing{'s' if len(tasks) != 1 else ''} to do: " + "; ".join(parts) + more + ".", "curious")
    m = _DONE.match(t)
    if m and store.open_tasks():
        try:
            task = store.complete(m.group(1), source="voice")
        except LookupError as exc:
            return reply(f"Hmm, {exc}.", "confused")
        left = len(store.open_tasks())
        return reply(f"Woohoo! {task['title'].capitalize()} is done." + (" That's everything!" if not left else
                     f" {left} to go."), "excited")
    m = _REMOVE.match(t)
    if m and store.open_tasks() and not m.group(1).startswith(("the map", "map")):
        try:
            task = store.remove(m.group(1), source="voice")
        except LookupError as exc:
            return reply(f"Hmm, {exc}.", "confused")
        return reply(f"Okay, I took {task['title']} off your list.", "neutral")
    m = _ADD.match(t)
    if m:
        due, title = parse_due(m.group(1), now)
        if not title:
            return None
        task = store.add(title, due, source="voice")
        when = f", due {say_due(due, now)}" if due else ""
        return reply(f"Got it: {task['title']}{when}.", "happy", "ding")
    return None


def reminder_text(task, kind, now, before_min):
    title = task["title"]
    due = _dt(task["due"])
    if kind == "soon":
        return f"Heads up! {title.capitalize()} is due in {say_span((due - now).total_seconds())}."
    if kind == "due":
        return f"It's time: {title} is due now."
    return f"{title.capitalize()} was due {say_span((now - due).total_seconds())} ago. Tell me when it's done!"
