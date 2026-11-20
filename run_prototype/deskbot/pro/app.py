"""
The pro runtime (20 Nov 2026): the full robot (full/app.py) + a configurable dashboard (add / remove / drag cards,
light / dark theme), headpats on three touch pads, more from the MPU-6050 (knock, bump, shake, tipped, drop),
Groq as the first AI brain with Claude as its fallback, a voice studio (pitch, speed, engine voice, profiles),
and view-only Accounts / APIs-in-use cards.

    python main.py pro [--sim] [--lan]          scripts/pro.sh (on the Pi; listens on the network)

Extra routes on top of the full robot's (POSTs need Content-Type: application/json):
    GET  /api/pro                     touch, motion, Groq, profiles, voice settings, pro settings
    GET  /api/pro/apis                every API/service and whether it's in use right now
    GET  /api/pro/accounts            keys (masked) and linked accounts; view only
    GET  /api/pro/voices              the speech engine's installed voices
    POST /api/pro/settings            {"touch": {...}, "motion": {...}, "groq": {...}}
    POST /api/pro/profiles            {"apply": name} | {"save": name} | {"delete": name}
    POST /api/pro/touch/test          {"pad": "top"|"left"|"right", "hold_s": 0.15}   pretend a touch
    POST /api/pro/motion/test         {"event": "knock"|"double_knock"|"bump"|"shake"|"tipped"|"righted"|"drop"}
Voice settings (pitch, speed, voice, style, volume) go through the existing POST /api/assistant/settings.

Design: docs/pro.md
"""

from __future__ import annotations

from .. import ROOT
from ..full.app import FullHandler, build_full_index, run_full
from ..web.server import WEB_DIR
from .apis import ApiInventory
from .config import ProSettings
from .core import Pro
from .groq_brain import GroqBrain
from .motion import MotionSense
from .profiles import Profiles
from .touch import TouchSense

STATIC = {
    "/static/pro.js": ("pro.js", "text/javascript; charset=utf-8"),
    "/static/pro.css": ("pro.css", "text/css; charset=utf-8"),
    "/static/layout.js": ("layout.js", "text/javascript; charset=utf-8"),
}


def build_pro_index():
    page = build_full_index().decode("utf-8")
    cards = (WEB_DIR / "pro_cards.html").read_text(encoding="utf-8")
    page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<link rel="stylesheet" href="/static/full.css">',
                        '<link rel="stylesheet" href="/static/full.css">\n  <link rel="stylesheet" href="/static/pro.css">')
    # the theme is applied before the page paints (no light flash for dark-mode users)
    page = page.replace("</head>", '  <script>try{var t=localStorage.getItem("deskbot.theme");'
                                   'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}</script>\n</head>', 1)
    page = page.replace('<script src="/static/full.js"></script>',
                        '<script src="/static/full.js"></script>\n  <script src="/static/pro.js"></script>\n'
                        '  <script src="/static/layout.js"></script>')
    page = page.replace("<title>Desk Robot · Full</title>", "<title>Desk Robot · Pro</title>")
    return page.encode("utf-8")


class ProHandler(FullHandler):
    pro: Pro = None
    server_version = "DeskRobot/9.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, build_pro_index(), "text/html; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        routes = {"/api/pro": lambda: self.pro.status(), "/api/pro/apis": lambda: self.pro.apis.in_use(),
                  "/api/pro/accounts": lambda: self.pro.apis.accounts(),
                  "/api/pro/voices": lambda: {"engine": self.app.speaker.engine, "voices": self.app.speaker.voices()}}
        if path in routes:
            return self._json(200, routes[path]())
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        routes = {"/api/pro/settings": self._settings_pro, "/api/pro/profiles": self._profiles,
                  "/api/pro/touch/test": self._touch_test, "/api/pro/motion/test": self._motion_test}
        if path not in routes:
            return super().do_POST()
        body = self._read_json()
        if body is None:
            return
        try:
            return self._json(200, routes[path](body) or {"ok": True})
        except (ValueError, LookupError) as exc:
            return self._json(400, {"error": str(exc.args[0] if exc.args else exc)})
        except Exception as exc:
            self.app.alerts.warn("api", "A request failed.", speak=False, detail=f"{type(exc).__name__}: {exc}")
            return self._json(500, {"error": type(exc).__name__})

    def _settings_pro(self, body):
        return self.pro.settings.update(body)

    def _profiles(self, body):
        p = self.pro.profiles
        if body.get("apply"):
            p.apply(str(body["apply"]))
        elif body.get("save"):
            p.save(str(body["save"]))
        elif body.get("delete"):
            p.delete(str(body["delete"]))
        return p.status()

    def _touch_test(self, body):
        self.pro.touch.simulate(str(body.get("pad", "top")), float(body.get("hold_s", 0.15)))
        return {"ok": True}

    def _motion_test(self, body):
        return {"events": self.pro.motion.inject(str(body.get("event", "")))}


def build(ctx, app, comp, buddy, hub, full, sim):
    from robot_config import TOUCH

    data = ROOT / "data"
    sfx = "_sim" if sim else ""
    log = lambda m: app.robot.log("info", m)   # noqa: E731
    settings = ProSettings(data / f"pro{sfx}.json")
    features = full.features
    groq = GroqBrain(app.settings, lambda: settings.section("groq"), claude=app.brain.claude,
                     enabled=lambda: features.on("ai_brain") and not features.data.get("local_only"))
    profiles = Profiles(data / f"profiles{sfx}.json", app.settings)
    holder = {}
    touch = TouchSense(TOUCH, lambda: settings.section("touch"), lambda k, p, i: holder["pro"].on_touch(k, p, i),
                       log=log, use_gpio=not sim)
    motion = MotionSense(ctx.get("shared"), lambda: settings.section("motion"), lambda k, i: holder["pro"].on_motion(k, i),
                         driving=lambda: holder["pro"].moving(), lifted=lambda: holder["pro"].lifted(), log=log)
    apis = ApiInventory(app, hub=hub, full=full, groq=groq)
    pro = Pro(ctx, app, comp, full, settings, groq, profiles, touch, motion, apis)
    holder["pro"] = pro

    brain = app.brain
    brain.primary_brains.append(groq)
    brain.pre_handlers.insert(0, pro.pre_handler)
    app.assistant.context_hooks.append(pro.context_lines)
    app.assistant.turn_listeners.append(apis.on_turn)
    app.assistant.turn_listeners.append(lambda e: hub.costs.add(e.get("usage")) if e.get("backend") == "groq" else None)
    if groq.available():
        app.alerts.resolve("ai", "Groq is my AI brain.", speak=False)    # the "no Claude key, simple mode" warning
    elif not brain.claude.available():
        app.alerts.warn("ai", "No AI brain connected, so I'm in simple mode. Add a GROQ_API_KEY (free) to secrets.env.",
                        speak=False, detail=f"Groq: {groq.why_unavailable()}; Claude: {brain.claude.why_unavailable()}")
    return pro


def run_pro(sim=False, host="127.0.0.1", port=8000, camera=None, https_port=8443):
    def on_ready(ctx, app, comp, buddy, hub, full):
        pro = build(ctx, app, comp, buddy, hub, full, sim)
        ProHandler.pro = pro
        pro.touch.start()
        pro.motion.start()
        order = " -> ".join(app.brain.order())
        ctx["robot"].log("info", f"Pro robot ready: brain {order}; touch pads {pro.touch.backend}; "
                                 f"profile {pro.profiles.active or 'custom'}")

        def close():
            pro.touch.stop()
            pro.motion.stop()
        return close

    run_full(sim=sim, host=host, port=port, camera=camera, https_port=https_port, handler_cls=ProHandler, on_ready_extra=on_ready)
