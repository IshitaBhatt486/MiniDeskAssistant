"""
The buddy: ties the task list and the phone inbox to the robot's voice, eyes and wheels.

    tasks finished  -> celebrate(): fanfare + "celebrating" eyes (confetti) + a victory move + dashboard confetti
    deadlines       -> a 1 Hz loop says reminders (reminder chime, eyes, a small nudge)
    notifications   -> the same loop reads the important ones aloud (notification chime, eyes)

When the robot may speak or move (checked every tick):
    present   the owner is around: no Bluetooth presence running, or the robot is awake
    quiet     inside the quiet hours (settings) - notifications and overdue nags wait; due reminders don't
    busy      a conversation turn is in progress (assistant phase not idle) - everything waits a moment
    may move  settings allow it, not lifted, awake, no other command sequence running, not calibrating

Held notifications (owner away or quiet hours) are said together when allowed again: up to three in full,
then "and N more on the dashboard". Missed reminders are said on return the same way (they stay due until
said: TaskStore.reminders_due doesn't mark them).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from .tasks import PROMPT, TOOL_SPECS, local_intent, reminder_text, tool_handlers

GAP_S = 6.0                  # at least this long between two things the buddy says by itself
REMINDER_ORDER = ("soon", "due", "overdue")


def in_quiet_hours(now: datetime, start: str, end: str):
    if not start or not end or start == end:
        return False
    hm = now.strftime("%H:%M")
    return start <= hm < end if start < end else (hm >= start or hm < end)


class Buddy:
    def __init__(self, app, settings, store, center, clock=datetime.now):
        """app: the assistant namespace (speaker, executor, presence, lift, assistant, brain, emotion, robot)."""
        self.app, self.settings, self.store, self.center, self.clock = app, settings, store, center, clock
        self.comp = None                    # the Companion (for "calibrating?"), set by app.py
        self.celebrations = 0
        self.last_celebration = None
        self.last_said = 0.0
        self.last_reminder = None
        self._running = False
        self._was_present = True
        self.hold_checks = []               # fn() -> True to hold notifications (hub/focus.py: during focus mode)

        store.listeners.append(self._on_task)
        app.executor.on_command(self._on_command)
        app.assistant.context_hooks.append(lambda: store.summary_lines(self.clock()))
        app.assistant.context_hooks.append(center.recent_lines)
        brain = app.brain
        brain.add_prompt(PROMPT)
        handlers = tool_handlers(store)
        for spec in TOOL_SPECS:
            brain.add_tool(spec, handlers[spec["name"]])
        brain.local_handlers.append(lambda text, ctx: local_intent(text, store, self.clock()))

    # -- life cycle --

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="buddy", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.tick()
            except Exception as exc:
                print(f"[BUDDY] {exc}", flush=True)
            time.sleep(1.0)

    # -- conditions --

    def present(self):
        p = self.app.presence
        return p is None or p.awake

    def busy(self):
        return self.app.assistant.phase != "idle"

    def may_move(self, section):
        a = self.app
        if not self.settings.section(section).get("move", True):
            return False
        if a.lift.lifted or not self.present() or a.executor.current is not None:
            return False
        cal = getattr(self.comp, "calibration", None)
        return not (cal and cal.running)

    def _react(self, emotion, seconds, why):
        emo = getattr(self.app, "emotion", None)
        if emo is not None:
            emo.react(emotion, seconds, why)

    def _say(self, text):
        self.app.speaker.say(text, "chatter")
        self.last_said = time.monotonic()

    # -- tasks --

    def _on_task(self, event, task, source):
        if event == "completed":
            self.celebrate(task, source)

    def _on_command(self, cmd):
        if cmd["action"] == "celebrate":
            self._react("celebrating", 6.0, "celebrating")
        elif cmd["action"] == "nudge":
            self._react("excited", 3.0, "getting your attention")

    def celebrate(self, task=None, source="dashboard"):
        """Fanfare, confetti eyes and a victory move. The voice and the AI say their own words; the dashboard
        and API don't speak, so the robot says something then."""
        if task is not None and not self.settings.section("tasks").get("celebrate", True):
            return
        left = len(self.store.open_tasks())
        self.celebrations += 1
        self.last_celebration = {"seq": self.celebrations, "t": time.time(), "task": task["title"] if task else None,
                                 "all_done": task is not None and left == 0}
        a = self.app
        a.speaker.chime("fanfare")
        self._react("celebrating", 7.0 if left == 0 else 5.0, f"finished {task['title']}" if task else "celebrating")
        if task is not None and source not in ("voice", "ai"):
            self._say(f"Nice work! {task['title'].capitalize()} is done." + (" That's your whole list. Amazing!" if left == 0 else ""))
        if self.may_move("tasks"):
            cmds = [{"action": "celebrate", "amount": 0}]
            if task is not None and left == 0:
                cmds.append({"action": "spin", "amount": 1})      # the whole list: a bigger party
            a.executor.run(cmds, source="tasks")

    def _reminders(self, now, quiet):
        t = self.settings.section("tasks")
        due = self.store.reminders_due(now, t["remind_before_min"], t["overdue_after_min"])
        for task, kind in due:
            if not self.present() or (quiet and kind == "overdue"):
                continue                       # stays due: said when they're back / quiet hours end
            if time.monotonic() - self.last_said < GAP_S:
                return
            a = self.app
            a.speaker.chime("reminder")
            self._react("excited" if kind == "soon" else "curious", 5.0, f"reminder: {task['title']}")
            self._say(reminder_text(task, kind, now, t["remind_before_min"]))
            if self.may_move("tasks"):
                a.executor.run([{"action": "nudge", "amount": 0}], source="reminder")
            for k in REMINDER_ORDER[: REMINDER_ORDER.index(kind) + 1]:
                self.store.mark_reminded(task["id"], k)    # a late "overdue" also covers the earlier two
            self.last_reminder = {"t": time.time(), "task": task["title"], "kind": kind}

    # -- notifications --

    def _notifications(self, quiet):
        n = self.settings.section("notify")
        self.center.expire(n["max_age_h"] * 3600)
        if not n["enabled"] or not self.center.outbox:
            return
        if quiet or (n["hold_when_away"] and not self.present()) or any(fn() for fn in self.hold_checks):
            return
        if time.monotonic() - self.last_said < GAP_S:
            return
        waiting = self.center.take()
        a = self.app
        a.speaker.chime("notification")
        self._react("curious", 4.0, "phone notification")
        if len(waiting) == 1:
            self._say(waiting[0]["speech"])
        else:
            self._say(f"You have {len(waiting)} important notifications.")
            for e in waiting[:3]:
                self._say(e["speech"])
            if len(waiting) > 3:
                self._say(f"And {len(waiting) - 3} more on the dashboard.")
        for e in waiting:
            e["status"], e["said_at"] = "spoken", time.time()
        if n.get("move") and self.may_move("notify"):
            a.executor.run([{"action": "nudge", "amount": 0}], source="notification")

    def tick(self, now=None):
        now = now or self.clock()
        if self.busy():
            return
        n = self.settings.section("notify")
        quiet = in_quiet_hours(now, n["quiet_start"], n["quiet_end"])
        self._reminders(now, quiet)
        self._notifications(quiet)

    def status(self):
        n = self.settings.section("notify")
        now = self.clock()
        return {"celebrations": self.celebrations, "last_celebration": self.last_celebration,
                "last_reminder": self.last_reminder, "present": self.present(),
                "quiet": in_quiet_hours(now, n["quiet_start"], n["quiet_end"])}
