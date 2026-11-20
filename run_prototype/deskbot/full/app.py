"""
The full runtime (19 Nov 2026): the hub robot (hub/app.py) + "Hey Pip", routines, smart home, reading, a local AI,
rock-paper-scissors, hydration, briefings, owner recognition, guard mode, a Telegram bot and on/off switches for
every feature.

    python main.py full [--sim] [--lan]            scripts/full.sh (on the Pi; listens on the network)
    python main.py help [topic]                     every feature and command, in the terminal

Extra routes on top of the hub's (all POSTs need Content-Type: application/json unless noted):
    GET  /api/full                         every card's state (no secrets: no passphrase, tokens or face numbers)
    GET  /api/full/reads/<name>.txt        a saved reading
    POST /api/full/features                {"key", "on"} | {"local_only": bool}        (guard / owner_recognition /
                                           telegram / local_only need "pin")
    POST /api/full/settings                {"owner": {...}, "briefing": {...}, ...}   ("guard" needs "pin")
    POST /api/full/wake                    {"text"}   simulate "Hey Pip, <text>"
    POST /api/full/routines                {"save": routine, "key"?} | {"delete"} | {"run"} | {"enable", "on"} | {"reload"}
    POST /api/full/read                    body = the image (Content-Type image/jpeg or image/png, <= 8 MB), ?extra=summary
                                           | JSON {"camera": true, "extra": "summary"|"flashcards"|null}
    POST /api/full/rps                     {"start"} | {"stop"} | {"move": "rock"}
    POST /api/full/hydration               {"drink": true}
    POST /api/full/briefing                {"kind": "morning"|"evening"}
    POST /api/full/smarthome               {"add": device} | {"remove": name} | {"control": {device, action, value}} | {"discover": true}
    POST /api/full/faces                   {"pin", "learn": {"name", "role"}} | {"pin", "forget": name}
    POST /api/full/guard                   {"arm": true} | {"pin", "disarm": true} | {"pin", "photo": name} | {"pin", "delete_photos": true}
    POST /api/full/telegram                {"pin", "pair": true} | {"pin", "unpair": true} | {"test": true}

Design: docs/full.md · running without the internet: docs/local-only.md
"""

from __future__ import annotations

import base64
import threading
import urllib.parse

from .. import MODELS_DIR, ROOT
from ..hub.app import HubHandler, build_hub_index, run_hub
from ..hub.focus import FaceAnalyzer
from ..web.server import WEB_DIR
from .briefing import Briefings
from .config import FullSettings
from .core import Full
from .faces import Faces
from .features import FeatureFlags
from .guard import Guard
from .hydration import Hydration
from .local_llm import Ollama, OllamaBrain
from .reader import Reader
from .routines import Routines
from .rps import RockPaperScissors
from .smarthome import SmartHome, SmartHomeError
from .telegram import Telegram
from .wake import VoskDetector, WakeWord, WhisperDetector

STATIC = {
    "/static/full.js": ("full.js", "text/javascript; charset=utf-8"),
    "/static/full.css": ("full.css", "text/css; charset=utf-8"),
}
PIN_FEATURES = {"guard", "owner_recognition", "telegram", "local_only"}
MAX_IMAGE = 8_000_000


def build_full_index():
    page = build_hub_index().decode("utf-8")
    cards = (WEB_DIR / "full_cards.html").read_text(encoding="utf-8")
    page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<link rel="stylesheet" href="/static/hub.css">',
                        '<link rel="stylesheet" href="/static/hub.css">\n  <link rel="stylesheet" href="/static/full.css">')
    page = page.replace('<script src="/static/hub.js"></script>',
                        '<script src="/static/hub.js"></script>\n  <script src="/static/full.js"></script>')
    page = page.replace("<title>Desk Robot · Hub</title>", "<title>Desk Robot · Full</title>")
    return page.encode("utf-8")


class FullHandler(HubHandler):
    full: Full = None
    server_version = "DeskRobot/8.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, build_full_index(), "text/html; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        if path == "/api/full":
            return self._json(200, self.full.status())
        if path.startswith("/api/full/reads/"):
            p = self.full.reader.file(urllib.parse.unquote(path.rsplit("/", 1)[1]))
            if p is None:
                return self._json(404, {"error": "Not found"})
            return self._send(200, p.read_bytes(), "text/plain; charset=utf-8")
        super().do_GET()

    def _pin(self, body):
        HubHandler.pin.check(body.get("pin"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/full/read" and self.headers.get("Content-Type", "").startswith(("image/jpeg", "image/png")):
            return self._read_upload()
        routes = {"/api/full/features": self._features, "/api/full/settings": self._settings_full, "/api/full/wake": self._wake,
                  "/api/full/routines": self._routines, "/api/full/read": self._read_json_route, "/api/full/rps": self._rps,
                  "/api/full/hydration": self._hydration, "/api/full/briefing": self._briefing,
                  "/api/full/smarthome": self._smarthome, "/api/full/faces": self._faces, "/api/full/guard": self._guard,
                  "/api/full/telegram": self._telegram}
        if path not in routes:
            return super().do_POST()
        body = self._read_json()
        if body is None:
            return
        try:
            return self._json(200, routes[path](body) or {"ok": True})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc)})
        except (ValueError, LookupError, SmartHomeError) as exc:
            return self._json(400, {"error": str(exc.args[0] if exc.args else exc)})
        except Exception as exc:
            if exc.__class__.__name__ in ("FeatureOff", "AccountError", "TelegramError"):
                return self._json(400, {"error": str(exc)})
            self.app.alerts.warn("api", "A request failed.", speak=False, detail=f"{type(exc).__name__}: {exc}")
            return self._json(500, {"error": type(exc).__name__})

    # -- routes --

    def _features(self, body):
        f = self.full.features
        if "local_only" in body:
            self._pin(body)
            return f.set("local_only", body["local_only"])
        key = body.get("key")
        if key in PIN_FEATURES:
            self._pin(body)
        return f.set(key, body.get("on"))

    def _settings_full(self, body):
        protected = "guard" in body
        if protected:
            self._pin(body)
        body = {k: v for k, v in body.items() if k != "pin"}
        return self.full.settings.update(body, allow_protected=protected)

    def _wake(self, body):
        self.full.features.require("wake_word")
        text = str(body.get("text", "")).strip()[:300] or "hello"
        threading.Thread(target=self.full.wake.simulate, args=(text,), daemon=True).start()
        return {"ok": True}

    def _routines(self, body):
        r = self.full.routines
        if "save" in body:
            r.save(body["save"], body.get("key"))
        elif "delete" in body:
            r.delete(str(body["delete"]))
        elif "run" in body:
            self.full.features.require("routines")
            r.run(str(body["run"]), "dashboard")
        elif "enable" in body:
            r.set_enabled(str(body["enable"]), body.get("on", True))
        elif body.get("reload"):
            r.reload()
        return r.status()

    def _read_upload(self):
        try:
            self.full.features.require("reader")
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_IMAGE:
                return self._json(413, {"error": "The picture must be under 8 MB"})
            data = self.rfile.read(n)
            if self.headers.get("Content-Type", "").startswith("image/png"):
                import cv2
                import numpy as np
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    return self._json(400, {"error": "That isn't a picture I can open"})
                from .reader import jpeg_from_frame
                data = jpeg_from_frame(img)
            extra = urllib.parse.parse_qs(self.path.partition("?")[2]).get("extra", [None])[0]
            extra = extra if extra in ("summary", "flashcards") else None
            f = self.full
            speak = f.say if f.settings.section("reader")["speak"] else None
            f.reader.read_async(lambda: data, "upload", extra, speak, lambda e: f.app.alerts.warn("reader", "Reading failed.", speak=False, detail=e))
            return self._json(202, {"ok": True, "status": "reading"})
        except Exception as exc:
            return self._json(400, {"error": str(exc)})

    def _read_json_route(self, body):
        self.full.features.require("reader")
        extra = body.get("extra") if body.get("extra") in ("summary", "flashcards") else None
        return {"status": self.full.read_camera(extra)["speech"]}

    def _rps(self, body):
        f = self.full
        f.features.require("rps")
        if body.get("start"):
            return f.rps.start()
        if body.get("stop"):
            f.rps.stop()
        elif body.get("move") in ("rock", "paper", "scissors"):
            if f.rps.state == "idle":
                raise ValueError("Start a game first")
            f.rps.voice(body["move"])
        return f.rps.status()

    def _hydration(self, body):
        self.full.features.require("hydration")
        if body.get("drink"):
            self.full.hydration.drink("dashboard")
        return self.full.hydration.status()

    def _briefing(self, body):
        self.full.features.require("briefings")
        kind = body.get("kind") if body.get("kind") in ("morning", "evening") else "morning"
        return {"text": self.full.give_briefing(kind, to_telegram=False)}

    def _smarthome(self, body):
        s = self.full.smarthome
        if "add" in body:
            s.add(body["add"])
        elif "remove" in body:
            s.remove(str(body["remove"]))
        elif isinstance(body.get("control"), dict):
            self.full.features.require("smart_home")
            c = body["control"]
            return s.control(str(c.get("device", "")), str(c.get("action", "")), c.get("value"))
        elif body.get("discover"):
            return {"found": s.discover()}
        return s.status()

    def _faces(self, body):
        self._pin(body)
        fc = self.full.faces
        if isinstance(body.get("learn"), dict):
            self.full.features.require("owner_recognition")
            learn = body["learn"]
            role = "owner" if learn.get("role") == "owner" else "friend"
            name = str(learn.get("name", "")).strip() or (self.full.settings.section("owner")["name"] or "owner")
            threading.Thread(target=self._enroll, args=(name, role), daemon=True).start()
            return {"ok": True, "status": "Look at the robot for about 8 seconds"}
        if "forget" in body:
            fc.forget(str(body["forget"]))
        return fc.status()

    def _enroll(self, name, role):
        f = self.full
        try:
            n = f.faces.enroll(name, role, f.frame)
            f.say(f"Got it, {name}. I'll recognise you now.")
            f.app.robot.log("info", f"Learned {name}'s face ({n} samples)")
        except ValueError as exc:
            f.say(str(exc))

    def _guard(self, body):
        g = self.full.guard
        if body.get("arm"):
            self.full.features.require("guard")
            g.arm("dashboard")
        elif body.get("disarm"):
            self._pin(body)
            g.disarm("dashboard")
        elif body.get("photo"):
            self._pin(body)
            p = g.photo(str(body["photo"]))
            if p is None:
                raise LookupError("no such photo")
            return {"jpeg": base64.b64encode(p.read_bytes()).decode()}
        elif body.get("delete_photos"):
            self._pin(body)
            g.delete_photos()
        return g.status()

    def _telegram(self, body):
        t = self.full.telegram
        if body.get("pair"):
            self._pin(body)
            if not t.configured():
                raise ValueError("Add TELEGRAM_BOT_TOKEN to secrets.env first (from @BotFather), then restart")
            return {"code": t.new_pair_code(), "bot": t.username}
        if body.get("unpair"):
            self._pin(body)
            t.unpair()
        if body.get("test"):
            if not t.broadcast("👋 Test message from your desk robot."):
                raise ValueError(t.error or "Telegram isn't paired yet")
        return t.status()


def build(ctx, app, comp, buddy, hub, sim):
    data = ROOT / "data"
    sfx = "_sim" if sim else ""
    log = lambda m: app.robot.log("info", m)   # noqa: E731
    settings = FullSettings(data / f"full{sfx}.json")
    adapters = {
        "sound_effects": (lambda: app.settings.get("sounds", True), lambda on: app.settings.update({"sounds": on})),
        "gestures": (lambda: comp.gestures.enabled, lambda on: setattr(comp.gestures, "enabled", on)),
        "phone_notifications": (lambda: buddy.settings.section("notify")["enabled"], lambda on: buddy.settings.update({"notify": {"enabled": on}})),
        "notify_ai": (lambda: buddy.settings.section("notify")["use_ai"], lambda on: buddy.settings.update({"notify": {"use_ai": on}})),
        "celebrations": (lambda: buddy.settings.section("tasks")["celebrate"], lambda on: buddy.settings.update({"tasks": {"celebrate": on}})),
    }
    features = FeatureFlags(data / f"features{sfx}.json", adapters)
    online = lambda: not features.data.get("local_only")   # noqa: E731
    ollama = Ollama(lambda: settings.section("local_llm"))
    local_brain = OllamaBrain(ollama, app.settings, enabled=lambda: features.on("local_llm"))
    local_brain.model = lambda: settings.section("local_llm")["text_model"]
    analyzer = hub.focus.analyzer or (FaceAnalyzer(MODELS_DIR, log=log) if ctx["vision"] is not None else None)
    if analyzer is not None:
        analyzer.download = online()
    holder = {}
    say = lambda text: holder["full"].say(text)   # noqa: E731
    parts = {
        "ollama": ollama, "local_brain": local_brain,
        "routines": Routines(data / f"routines{sfx}", log=log),
        "smarthome": SmartHome(data / f"smart_home{sfx}.json"),
        "reader": Reader(data / f"reads{sfx}", lambda: settings.section("reader"), ollama, app.brain.claude,
                         model=lambda: app.settings.get("model", "claude-haiku-5-5"),
                         allow_cloud=lambda: features.on("ai_brain"), on_usage=hub.costs.add),
        "rps": RockPaperScissors(say, lambda n: app.speaker.chime(n), lambda e, s, w: holder["full"].react(e, s, w),
                                 gesture_now=lambda: comp.gestures.current,
                                 pause_gestures=lambda p: setattr(comp.gestures, "paused", p),
                                 speaking=lambda: holder["full"].speaking(),
                                 on_match_end=lambda w: buddy.celebrate(None, "game") if w == "you" else
                                 app.executor.run([{"action": "dance", "amount": 0}], source="game")),
        "hydration": Hydration(data / f"hydration{sfx}.json", lambda: settings.section("hydration")),
        "faces": Faces(data / f"faces{sfx}" / "people.json", analyzer or FaceAnalyzer(MODELS_DIR, download=False, log=log),
                       MODELS_DIR, download=online, log=log),
        "telegram": Telegram(data / f"telegram{sfx}.json", {}, enabled=lambda: features.on("telegram"), log=log),
    }
    parts["briefings"] = Briefings(data / f"briefings{sfx}.json", {
        "name": lambda: settings.section("owner")["name"] or parts["faces"].owner() or "",
        "weather": lambda: __import__("deskbot.assistant.tools", fromlist=["get_weather"]).get_weather("", app.settings.get("location", "")),
        "tasks": buddy.store.open_tasks,
        "done_today": lambda: buddy.store.done_since(__import__("datetime").datetime.now().replace(hour=0, minute=0, second=0)),
        "calendar": lambda hours: hub.calendar.upcoming(hours) if hub.calendar.available() else None,
        "focus_minutes": hub.focus.today_minutes,
        "ideas_today": lambda: sum(1 for i in hub.ideas.ideas if i["created"][:10] == __import__("datetime").date.today().isoformat()),
        "drinks_today": parts["hydration"].today,
    }, lambda: settings.section("briefing"))
    parts["guard"] = Guard(data / f"guard{sfx}", say, lambda: holder["full"].snapshot(), listen=lambda s: holder["full"].listen(s),
                           notify=lambda text, jpeg: parts["telegram"].broadcast(text, jpeg),
                           react=lambda e, s, w: holder["full"].react(e, s, w),
                           face_user=lambda: app.executor.run([{"action": "face_user", "amount": 0}], source="guard"),
                           owner_here=lambda: parts["faces"].owner_here(3.0) if features.on("owner_recognition") else False,
                           settings=lambda: settings.section("guard"), wait_quiet=lambda: holder["full"].wait_quiet())
    phrase = lambda: f"hey {app.settings.get('robot_name', 'Pip')}".lower()   # noqa: E731
    parts["wake"] = WakeWord(phrase, on_request=lambda wav, text: holder["full"].on_request(wav, text),
                             on_wake=lambda: holder["full"].on_wake(), speaking=lambda: holder["full"].speaking(),
                             detectors=[lambda p: VoskDetector(MODELS_DIR, p, download=online(), log=log),
                                        lambda p: WhisperDetector(app.stt, p)],
                             log=log, enabled=lambda: features.on("wake_word"))
    full = Full(ctx, app, comp, buddy, hub, settings, features, parts)
    holder["full"] = full
    parts["routines"].actions = full.routine_actions()
    parts["telegram"].commands = full.telegram_commands()
    parts["hydration"].on_drink = lambda how: None
    return full


def run_full(sim=False, host="127.0.0.1", port=8000, camera=None, https_port=8443, handler_cls=None, on_ready_extra=None):
    """handler_cls / on_ready_extra (20 Nov 2026): hooks for runtimes built on this one (pro/app.py).
    on_ready_extra(ctx, app, comp, buddy, hub, full) runs once the full robot is up and returns a close() (or None)."""
    def on_ready(ctx, app, comp, buddy, hub):
        full = build(ctx, app, comp, buddy, hub, sim)
        FullHandler.full = full
        full.start()
        full.wake.start()
        full.telegram.start()
        on = [k for k in full.features.data if full.features.on(k)]
        ctx["robot"].log("info", f"Full robot ready: {len(on)} features on; routines: {', '.join(full.routines.items) or 'none'}")
        extra_close = on_ready_extra(ctx, app, comp, buddy, hub, full) if on_ready_extra else None

        def close():
            if extra_close:
                extra_close()
            full.stop()
            full.wake.stop()
            full.telegram.stop()
            full.routines.cancel()
        return close

    run_hub(sim=sim, host=host, port=port, camera=camera, https_port=https_port, handler_cls=handler_cls or FullHandler, on_ready_extra=on_ready)
