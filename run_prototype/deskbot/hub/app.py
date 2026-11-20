"""
The hub runtime (19 Nov 2026): the buddy robot (buddy/app.py) + "remember this idea", focus mode, Google Calendar
reminders, Spotify, a Connected accounts card and a cost meter with a daily Claude cap.

    python main.py hub [--sim] [--lan]            scripts/hub.sh (on the Pi; listens on the network)

Extra routes on top of the buddy's:
    GET  /api/hub                          accounts (never tokens), ideas, focus, costs, settings
    GET  /api/hub/ideas.md                 all ideas as a Markdown file
    GET  /oauth/<provider>/callback        where Google / Spotify send the browser after sign-in (state checked)
    POST /api/hub/accounts                 {"pin", "action": "start"|"finish"|"disconnect", "provider", "url"}
    POST /api/hub/ideas                    {"add": "text"} | {"remove": id}
    POST /api/hub/focus                    {"start": minutes, "break": minutes} | {"stop": true}
    POST /api/hub/spotify                  {"play": "query", "kind": ""} | {"action": "pause"|..., "volume": n}
    POST /api/hub/settings                 {"costs": {...}, "google": {...}, "spotify": {...}, "focus": {...}}

Design and security: docs/hub.md
"""

from __future__ import annotations

import html
import urllib.parse

from .. import MODELS_DIR, ROOT
from ..buddy.app import BuddyHandler, build_buddy_index, run_buddy
from ..buddy.notify import make_ai_triage
from ..web.server import WEB_DIR
from .accounts import PROVIDERS, AccountError, Accounts, PinGate
from .config import HubSettings
from .core import Hub
from .costs import CostMeter
from .focus import FaceAnalyzer, Focus
from .google_cal import GoogleCalendar
from .ideas import IdeaStore
from .spotify import Spotify

STATIC = {
    "/static/hub.js": ("hub.js", "text/javascript; charset=utf-8"),
    "/static/hub.css": ("hub.css", "text/css; charset=utf-8"),
}

CALLBACK_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Desk Robot · {title}</title><style>body{{font:16px system-ui,sans-serif;max-width:520px;margin:15vh auto;padding:0 16px;
background:#f2f1ed;color:#1d1d1b}}@media(prefers-color-scheme:dark){{body{{background:#121211;color:#ecebe6}}}}</style></head>
<body><h1>{title}</h1><p>{message}</p><p><a href="/">Back to the dashboard</a></p></body></html>"""


def build_hub_index():
    page = build_buddy_index().decode("utf-8")
    cards = (WEB_DIR / "hub_cards.html").read_text(encoding="utf-8")
    page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<link rel="stylesheet" href="/static/buddy.css">',
                        '<link rel="stylesheet" href="/static/buddy.css">\n  <link rel="stylesheet" href="/static/hub.css">')
    page = page.replace('<script src="/static/buddy.js"></script>',
                        '<script src="/static/buddy.js"></script>\n  <script src="/static/hub.js"></script>')
    page = page.replace("<title>Desk Robot · Buddy</title>", "<title>Desk Robot · Hub</title>")
    return page.encode("utf-8")


class HubHandler(BuddyHandler):
    hub: Hub = None
    pin: PinGate = None
    server_version = "DeskRobot/7.0"

    def _page(self, status, title, message):
        body = CALLBACK_PAGE.format(title=html.escape(title), message=html.escape(message)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")         # the address holds a one-time code
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            return self._send(200, build_hub_index(), "text/html; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        if path == "/api/hub":
            return self._json(200, self.hub.status())
        if path == "/api/hub/ideas.md":
            return self._send(200, self.hub.ideas.markdown().encode("utf-8"), "text/markdown; charset=utf-8")
        if path.startswith("/oauth/") and path.endswith("/callback"):
            provider = path.split("/")[2]
            if provider not in PROVIDERS:
                return self._page(404, "Not found", "Unknown account type.")
            q = urllib.parse.parse_qs(query)
            one = lambda k: (q.get(k) or [None])[0]   # noqa: E731
            try:
                row = self.hub.accounts.finish(one("code"), one("state"), one("error"))
                return self._page(200, f"{PROVIDERS[provider]['title']} connected",
                                  f"Signed in as {row.get('account')}. You can close this tab.")
            except AccountError as exc:
                return self._page(400, "Couldn't connect", str(exc))
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        routes = {"/api/hub/accounts": self._accounts, "/api/hub/ideas": self._ideas, "/api/hub/focus": self._focus,
                  "/api/hub/spotify": self._spotify, "/api/hub/settings": self._settings_hub}
        if path not in routes:
            return super().do_POST()
        body = self._read_json()
        if body is None:
            return
        try:
            return self._json(200, routes[path](body) or {"ok": True})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc)})
        except (AccountError, ValueError, LookupError) as exc:
            return self._json(400, {"error": str(exc.args[0] if exc.args else exc)})
        except Exception as exc:
            self.app.alerts.warn("api", "A hub request failed.", speak=False, detail=f"{type(exc).__name__}: {exc}")
            return self._json(500, {"error": f"{type(exc).__name__}"})

    def _accounts(self, body):
        HubHandler.pin.check(body.get("pin"))
        a = self.hub.accounts
        provider = body.get("provider")
        action = body.get("action")
        if action == "finish":
            return a.finish_from_url(str(body.get("url", ""))[:4000])
        if provider not in PROVIDERS:
            raise ValueError("provider must be google or spotify")
        if action == "start":
            return a.start(provider)
        if action == "disconnect":
            return a.disconnect(provider)
        raise ValueError("action must be start, finish or disconnect")

    def _ideas(self, body):
        if "add" in body:
            self.hub.ideas.add(str(body["add"]), source="dashboard")
        elif "remove" in body:
            self.hub.ideas.remove(str(int(body["remove"])))
        else:
            raise ValueError("send add or remove")
        return self.hub.ideas.status()

    def _focus(self, body):
        f = self.hub.focus
        if body.get("stop"):
            f.stop("asked")
        elif "start" in body:
            cfg = self.hub.settings.section("focus")
            f.start(body.get("start") or cfg["minutes"], body.get("break") or cfg["break_minutes"])
        return f.status()

    def _spotify(self, body):
        s = self.hub.spotify
        if "play" in body:
            return s.play(str(body["play"])[:120], str(body.get("kind", "")))
        if body.get("action") == "now":
            return s.now_playing()
        return s.control(str(body.get("action", "")), body.get("volume"))

    def _settings_hub(self, body):
        return self.hub.settings.update(body)


def run_hub(sim=False, host="127.0.0.1", port=8000, camera=None, https_port=8443, handler_cls=None, on_ready_extra=None):
    """handler_cls / on_ready_extra (19 Nov 2026): hooks for runtimes built on this one (full/app.py).
    on_ready_extra(ctx, app, comp, buddy, hub) runs once the hub is up and returns a close() (or None)."""
    data = ROOT / "data"
    suffix = "_sim" if sim else ""

    def on_ready(ctx, app, comp, buddy):
        settings = HubSettings(data / f"hub{suffix}.json")
        log = lambda m: app.robot.log("info", m)   # noqa: E731
        accounts = Accounts(data / f"accounts{suffix}", port=port, log=log)
        alert = lambda m: app.alerts.warn("hub", m)   # noqa: E731
        costs = CostMeter(data / f"usage{suffix}.json", cap_usd=lambda: settings.section("costs")["daily_cap_usd"], alert=alert)
        costs.refresh_rate()
        buddy.center.ai_triage = make_ai_triage(app.brain, app.settings, on_usage=costs.add)
        calendar = GoogleCalendar(accounts, data / f"google_events{suffix}.json", lambda: settings.section("google"), alert)
        spotify = Spotify(accounts, lambda: settings.section("spotify"))
        ideas = IdeaStore(data / f"ideas{suffix}.json")
        vision = ctx["vision"]
        focus = Focus(data / f"focus{suffix}.json", vision=vision,
                      analyzer=FaceAnalyzer(MODELS_DIR, log=log) if vision is not None else None).start_thread()
        hub = Hub(app, buddy, settings, accounts, calendar, spotify, ideas, focus, costs)
        HubHandler.hub = hub
        HubHandler.pin = hub.pin = PinGate()
        if not hub.pin.pin:
            log("Connected accounts are locked: set ADMIN_PIN in secrets.env to connect Google or Spotify")
        if accounts.vault.encryption != "fernet":
            log(f"Account tokens are not encrypted ({accounts.vault.encryption}); see docs/hub.md")
        connected = [p for p, r in accounts.status().items() if r["connected"]]
        log(f"Hub ready: {len(ideas.ideas)} ideas, accounts connected: {', '.join(connected) or 'none'}")
        extra_close = on_ready_extra(ctx, app, comp, buddy, hub) if on_ready_extra else None

        def close():
            if extra_close:
                extra_close()
            focus.stop_thread()
        return close

    run_buddy(sim=sim, host=host, port=port, camera=camera, https_port=https_port,
              handler_cls=handler_cls or HubHandler, on_ready_extra=on_ready)
