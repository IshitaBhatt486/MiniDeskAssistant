"""
The buddy runtime (19 Nov 2026): the companion robot (companion/app.py) + a spoken task list with deadlines,
reminders and celebrations + important phone notifications read aloud.

    python main.py buddy [--sim] [--lan]          scripts/buddy.sh (on the Pi; listens on the network)

Extra routes on top of the companion's:
    GET  /api/buddy                         tasks, notifications, settings, phone setup, celebrations
    POST /api/notify                        the PHONE posts a notification here (token required, see notify.py)
    POST /api/buddy/tasks                   {"add": "submit report by 5pm"} | {"complete": id} | {"reopen": id}
                                            | {"remove": id} | {"update": {"id", "title", "due"}}
    POST /api/buddy/settings                {"tasks": {...}, "notify": {...}}
    POST /api/buddy/notifications/test      {"app", "title", "text", "category"}   (from the dashboard; no token)
    POST /api/buddy/celebrate               {}   try the celebration
    POST /api/buddy/token                   {}   make a new phone token (the old one stops working)

Design: docs/buddy.md
"""

from __future__ import annotations

import hmac
import os
import secrets
import time

from .. import ROOT
from ..companion.app import CompanionHandler, build_companion_index, run_companion
from ..web.server import WEB_DIR
from .config import TOKEN_FILE, BuddySettings, notify_token
from .core import Buddy
from .notify import NotificationCenter, make_ai_triage
from .tasks import TaskStore
from .when import parse_due, parse_iso_or_words

STATIC = {
    "/static/buddy.js": ("buddy.js", "text/javascript; charset=utf-8"),
    "/static/buddy.css": ("buddy.css", "text/css; charset=utf-8"),
}


def build_buddy_index():
    page = build_companion_index().decode("utf-8")
    cards = (WEB_DIR / "buddy_cards.html").read_text(encoding="utf-8")
    page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<link rel="stylesheet" href="/static/companion.css">',
                        '<link rel="stylesheet" href="/static/companion.css">\n  <link rel="stylesheet" href="/static/buddy.css">')
    page = page.replace('<script src="/static/companion.js"></script>',
                        '<script src="/static/companion.js"></script>\n  <script src="/static/buddy.js"></script>')
    page = page.replace("<title>Desk Robot · Companion</title>", "<title>Desk Robot · Buddy</title>")
    return page.encode("utf-8")


class BuddyHandler(CompanionHandler):
    buddy: Buddy = None
    token = None
    server_version = "DeskRobot/6.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, build_buddy_index(), "text/html; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        if path == "/api/buddy":
            return self._json(200, buddy_state(self.buddy, self))
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        routes = {"/api/notify": self._notify, "/api/buddy/tasks": self._tasks, "/api/buddy/settings": self._settings,
                  "/api/buddy/notifications/test": self._test_notification, "/api/buddy/celebrate": self._celebrate,
                  "/api/buddy/token": self._new_token}
        if path not in routes:
            return super().do_POST()
        body = self._read_json()
        if body is None:
            return
        try:
            out = routes[path](body)
            if isinstance(out, tuple):
                return self._json(*out)
            return self._json(200, out or {"ok": True})
        except (ValueError, LookupError) as exc:
            return self._json(400, {"error": str(exc.args[0] if exc.args else exc)})
        except Exception as exc:
            self.app.alerts.warn("api", "A buddy request failed.", speak=False, detail=f"{type(exc).__name__}: {exc}")
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _notify(self, body):
        given = str(self.headers.get("X-Deskbot-Token") or body.get("token") or "")
        if not hmac.compare_digest(given.encode(), str(BuddyHandler.token).encode()):
            return 403, {"error": "wrong or missing token (see the Phone notifications card on the dashboard)"}
        if not self.buddy.settings.section("notify")["enabled"]:
            return 200, {"ok": True, "status": "notifications are switched off"}
        entry = self.buddy.center.receive(body, source="phone")
        return 202, {"ok": True, "id": entry["id"], "status": entry["status"]}

    def _tasks(self, body):
        store = self.buddy.store
        now = store.clock()
        if "add" in body:
            text = str(body["add"])
            due_text = str(body.get("due") or "").strip()
            if due_text:
                due, title = parse_iso_or_words(due_text, now), text
            else:
                due, title = parse_due(text, now)
            store.add(title, due, source="dashboard")
        elif "complete" in body:
            store.complete(int(body["complete"]), source="dashboard")
        elif "reopen" in body:
            store.reopen(int(body["reopen"]))
        elif "remove" in body:
            store.remove(int(body["remove"]), source="dashboard")
        elif isinstance(body.get("update"), dict):
            u = body["update"]
            kw = {}
            if str(u.get("title", "")).strip():
                kw["title"] = u["title"]
            if "due" in u:
                kw["due"] = parse_iso_or_words(str(u["due"] or ""), now)
            store.update(int(u["id"]), source="dashboard", **kw)
        else:
            raise ValueError("send add, complete, reopen, remove or update")
        return store.status(now)

    def _settings(self, body):
        return self.buddy.settings.update(body)

    def _test_notification(self, body):
        payload = {k: body.get(k, "") for k in ("app", "title", "text", "category", "priority")}
        payload["app"] = payload["app"] or "Test"
        entry = self.buddy.center.receive(payload, source="dashboard test")
        return {"id": entry["id"], "status": entry["status"]}

    def _celebrate(self, body):
        self.buddy.celebrate(None, "dashboard")

    def _new_token(self, body):
        if os.environ.get("NOTIFY_TOKEN"):
            raise ValueError("The token comes from NOTIFY_TOKEN in secrets.env; change it there")
        token = secrets.token_urlsafe(12)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token, encoding="utf-8")
        BuddyHandler.token = token
        return {"token": token}


def buddy_state(buddy, handler):
    a = handler.app
    port = handler.server.server_address[1] if handler.server else 8000
    from ..cli import lan_ip
    ip = lan_ip() or "<robot-ip>"
    return {
        "t": time.time(),
        "tasks": buddy.store.status(),
        "notifications": buddy.center.status(),
        "settings": buddy.settings.all(),
        "buddy": buddy.status(),
        "phone": {"url": f"http://{ip}:{port}/api/notify", "token": BuddyHandler.token,
                  "token_from_env": bool(os.environ.get("NOTIFY_TOKEN"))},
        "sim": a.sim,
    }


def run_buddy(sim=False, host="127.0.0.1", port=8000, camera=None, https_port=8443, handler_cls=None, on_ready_extra=None):
    """handler_cls / on_ready_extra (19 Nov 2026): hooks for runtimes built on this one (hub/app.py).
    on_ready_extra(ctx, app, comp, buddy) runs once the buddy is up and returns a close() (or None)."""
    def on_ready(ctx, app, comp):
        settings = BuddySettings(ROOT / "data" / ("buddy_sim.json" if sim else "buddy.json"))
        store = TaskStore(ROOT / "data" / ("tasks_sim.json" if sim else "tasks.json"))
        if store.load_error:
            app.alerts.warn("tasks", "My task list file was damaged, so I started a new one.", detail=store.load_error)
        center = NotificationCenter(lambda: settings.section("notify"), make_ai_triage(app.brain, app.settings),
                                    log=lambda m: app.robot.log("info", m)).start()
        buddy = Buddy(app, settings, store, center)
        buddy.comp = comp
        buddy.start()
        BuddyHandler.buddy = buddy
        BuddyHandler.token = notify_token()
        app.buddy = buddy
        left = len(store.open_tasks())
        ctx["robot"].log("info", f"Buddy ready: {left} open task{'s' if left != 1 else ''}, phone notifications at POST /api/notify")
        extra_close = on_ready_extra(ctx, app, comp, buddy) if on_ready_extra else None

        def close():
            if extra_close:
                extra_close()
            buddy.stop()
            center.stop()
        return close

    run_companion(sim=sim, host=host, port=port, camera=camera, https_port=https_port,
                  handler_cls=handler_cls or BuddyHandler, on_ready=on_ready)
