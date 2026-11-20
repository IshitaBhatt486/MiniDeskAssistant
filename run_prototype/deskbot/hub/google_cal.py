"""
Google Calendar reminders: events with a pop-up reminder on your phone, made by voice or synced from the task list.

    add_reminder("call the bank", due, minutes_before=10)  -> an event at `due` (15 min long) on your primary
                                                             calendar with a pop-up reminder `minutes_before`
    upcoming(hours=24)                                     -> your next events (for "what's on my calendar")

Task sync (setting "sync_tasks", on by default once Google is connected): every task with a deadline gets an
event; changing the deadline or name moves/renames it; finishing it renames it "✓ <title>" and removes the
reminder; deleting the task deletes the event. The task id -> event id map is data/google_events.json. A failed
call is reported (dashboard + alert) and never stops the task list.

API: Calendar v3 REST over HTTPS (accounts.http), scope calendar.events. Free; no billing account is needed, and
the default quota (about a million requests a day) is far above what a desk robot makes.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from .accounts import AccountError

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
EVENT_MINUTES = 15


def _rfc3339(dt):
    return dt.astimezone().isoformat(timespec="seconds")    # naive local -> with the local UTC offset


class GoogleCalendar:
    def __init__(self, accounts, map_path: Path, settings=lambda: {"sync_tasks": True, "minutes_before": 10}, alert=None):
        self.accounts = accounts
        self.map_path = Path(map_path)
        self.settings = settings
        self.alert = alert or (lambda msg: None)
        self._lock = threading.Lock()
        self.events = {}
        self.last_error = None
        if self.map_path.exists():
            try:
                self.events = json.loads(self.map_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.events = {}

    def _call(self, method, url, body=None):
        token = self.accounts.token("google")
        status, data = self.accounts.http(method, url, json_body=body, headers={"Authorization": f"Bearer {token}"})
        if status == 401:
            raise AccountError("Google said the sign-in is no longer valid. Connect it again.")
        if status == 403:
            raise AccountError("Google refused (is the Calendar API enabled in your Google Cloud project?)")
        if status >= 400 and not (method == "DELETE" and status in (404, 410)):
            raise AccountError(f"Google Calendar error {status}: {str(data.get('error', {}).get('message', ''))[:120]}")
        return data

    def available(self):
        return self.accounts.connected("google")

    # -- reminders --

    def _body(self, title, due, minutes_before, done=False):
        end = due + timedelta(minutes=EVENT_MINUTES)
        return {"summary": ("✓ " if done else "") + title, "description": "Added by your desk robot.",
                "start": {"dateTime": _rfc3339(due)}, "end": {"dateTime": _rfc3339(end)},
                "reminders": {"useDefault": False,
                              "overrides": [] if done else [{"method": "popup", "minutes": int(max(0, minutes_before))}]}}

    def add_reminder(self, title, due, minutes_before=None):
        minutes_before = self.settings().get("minutes_before", 10) if minutes_before is None else minutes_before
        ev = self._call("POST", API, self._body(title, due, minutes_before))
        return {"id": ev.get("id"), "link": ev.get("htmlLink"), "title": title, "when": due.isoformat(timespec="minutes")}

    def upcoming(self, hours=24, limit=10, now=None):
        now = now or datetime.now()
        q = urlencode({"timeMin": _rfc3339(now), "timeMax": _rfc3339(now + timedelta(hours=hours)), "singleEvents": "true",
                       "orderBy": "startTime", "maxResults": limit})
        data = self._call("GET", f"{API}?{q}")
        out = []
        for e in data.get("items", []):
            start = e.get("start", {})
            out.append({"title": e.get("summary", "(no title)"), "start": start.get("dateTime") or start.get("date"),
                        "all_day": "date" in start})
        return out

    # -- task sync (TaskStore listener) --

    def on_task(self, event, task, source):
        if not (self.settings().get("sync_tasks", True) and self.available()):
            return
        threading.Thread(target=self._sync, args=(event, task), name="gcal-sync", daemon=True).start()

    def _save_map(self):
        try:
            self.map_path.parent.mkdir(parents=True, exist_ok=True)
            self.map_path.write_text(json.dumps(self.events), encoding="utf-8")
        except OSError:
            pass

    def _sync(self, event, task):
        key = str(task["id"])
        try:
            with self._lock:
                ev_id = self.events.get(key)
                due = datetime.fromisoformat(task["due"]) if task.get("due") else None
                mins = self.settings().get("minutes_before", 10)
                if event == "removed" or (event == "updated" and due is None):
                    if ev_id:
                        self._call("DELETE", f"{API}/{quote(ev_id)}")
                        self.events.pop(key, None)
                elif due is not None and event in ("added", "updated", "reopened", "completed"):
                    body = self._body(task["title"], due, mins, done=event == "completed")
                    if ev_id:
                        self._call("PATCH", f"{API}/{quote(ev_id)}", body)
                    elif event != "completed":
                        self.events[key] = self._call("POST", API, body).get("id")
                self._save_map()
            self.last_error = None
        except AccountError as exc:
            self.last_error = str(exc)
            self.alert(f"I couldn't update your Google Calendar: {exc}")

    def status(self):
        return {"synced_events": len(self.events), "last_error": self.last_error, "settings": self.settings()}
