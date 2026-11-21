"""
The assistant runtime (17 Nov 2026): the 4-process robot (runtime/app.py) + voice assistant + presence.

    python -m deskbot assistant [--sim] [--lan] [--camera ...] [--https-port 8443]
    scripts/assistant.sh                                  (same, on the Pi)

On top of the runtime's dashboard and API it adds:

    GET  /remote                      phone-sized remote control page (hold-to-drive, talk, replies)
    GET  /api/assistant               everything the assistant/presence cards show (polled ~1 Hz)
    GET  /api/assistant/speech.wav    the newest spoken reply (chipmunk), for playback in the browser
    GET  /speaker                     21 Nov 2026: the laptop as the speaker (assistant/laptop_speaker.py)
    GET  /api/speaker/clips?after=&wait=&listener=&interrupt=   long poll for new sound clips
    GET  /api/speaker/clip/<id>.wav   one clip
    POST /api/assistant/text          {"text"}                      -> reply entry
    POST /api/assistant/audio         body = 16 kHz mono WAV (<= 2 MB, Content-Type audio/wav) -> reply entry
    POST /api/assistant/listen        {"seconds"}  record with the robot's own microphone -> reply entry
    POST /api/assistant/commands      {"commands": [{"action", "amount"}]}  run commands directly
                                      (navigate also takes "from_object" and "to_object")
    GET  /api/nav/map                 map, objects, route, zones, home for the Navigation card
    POST /api/nav/memory              {"add": [[x, y], ...]} | {"remove": id} | {"clear_zones": true} | {"home": true} | {"accept": true}
    POST /api/assistant/settings      {personality, location, chipmunk, ...} (never API keys)
    POST /api/assistant/say           {"text"}   speak a test line
    POST /api/assistant/stop          stop everything: motors, running commands, speech
    POST /api/presence                {"awake": bool} | {"find_phone": true} | {"use_device": {address,name}}
    POST /api/drive                   {"direction"}  hold-to-drive from the remote: a 0.5 s move, re-sent while held
                                      (logged once per press instead of 4x a second like /api/move)
    POST /api/sim/lift                {"lifted": bool}           (simulation)
    POST /api/sim/wheel               {"stuck": "left" | "right" | "none"}  (simulation)
    POST /api/sim/phone               {"present": bool}          (simulation)

Mutating requests require a JSON (or audio/wav) Content-Type, like the rest of the API: a random web page
can't post those cross-origin without a CORS preflight, which this server never answers.

The same handler class is served on HTTP (port) and HTTPS (https_port, self-signed, for microphones).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import numpy as np

from ..config import AppConfig
from ..runtime.app import RuntimeHandler, build_runtime_index, run_runtime
from ..web.server import WEB_DIR

MAX_AUDIO_BYTES = 2_000_000

ASSISTANT_STATIC = {
    "/static/assistant.js": ("assistant.js", "text/javascript; charset=utf-8"),
    "/static/assistant.css": ("assistant.css", "text/css; charset=utf-8"),
    "/static/remote.js": ("remote.js", "text/javascript; charset=utf-8"),
    "/static/voice-recorder.js": ("voice-recorder.js", "text/javascript; charset=utf-8"),
    "/static/navigation.js": ("navigation.js", "text/javascript; charset=utf-8"),
    "/static/laptop-speaker.js": ("laptop-speaker.js", "text/javascript; charset=utf-8"),
    "/speaker": ("speaker.html", "text/html; charset=utf-8"),
    "/remote": ("remote.html", "text/html; charset=utf-8"),
    "/remote.html": ("remote.html", "text/html; charset=utf-8"),
}


def build_assistant_index():
    page = build_runtime_index().decode("utf-8")
    cards = (WEB_DIR / "assistant_cards.html").read_text(encoding="utf-8")
    # assistant cards first: they're what you use most
    page = page.replace('<main class="grid">', '<main class="grid">\n' + cards, 1)
    page = page.replace('<link rel="stylesheet" href="/static/fusion.css">',
                        '<link rel="stylesheet" href="/static/fusion.css">\n  <link rel="stylesheet" href="/static/assistant.css">')
    page = page.replace('<script src="/static/runtime.js"></script>',
                        '<script src="/static/runtime.js"></script>\n  <script src="/static/voice-recorder.js"></script>\n'
                        '  <script src="/static/assistant.js"></script>\n  <script src="/static/laptop-speaker.js"></script>')
    page = page.replace("<title>Desk Robot · Vision &amp; Maps</title>", "<title>Desk Robot · Assistant</title>")
    return page.encode("utf-8")


class AssistantHandler(RuntimeHandler):
    app = None     # SimpleNamespace: assistant, settings, alerts, speaker, executor, presence, lift, health, ...
    server_version = "DeskRobot/4.0"

    # -- GET --

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, build_assistant_index(), "text/html; charset=utf-8")
        if path in ASSISTANT_STATIC:
            name, ctype = ASSISTANT_STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        if path == "/api/assistant":
            return self._json(200, assistant_state(self.app))
        if path == "/api/nav/map":
            return self._json(200, nav_map(self.app))
        if path == "/api/speaker/clips":
            return self._speaker_clips()
        if path.startswith("/api/speaker/clip/") and path.endswith(".wav"):
            try:
                wav = self.app.speaker.laptop.clip(int(path[len("/api/speaker/clip/"):-4]))
            except ValueError:
                wav = None
            if wav is None:
                return self._json(404, {"error": "That clip is gone (only the newest ones are kept)"})
            return self._send(200, wav, "audio/wav")
        if path == "/api/assistant/speech.wav":
            wav = self.app.speaker.last_wav
            if wav is None:
                return self._json(404, {"error": "Nothing said yet"})
            return self._send(200, wav, "audio/wav")
        super().do_GET()

    def _speaker_clips(self):
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(self.path).query)

        def num(name, default):
            try:
                return float(q.get(name, [default])[0])
            except (TypeError, ValueError):
                return default
        sp = self.app.speaker
        out = sp.laptop.wait_clips(int(num("after", -1)), num("wait", 20), q.get("listener", [""])[0],
                                   int(num("interrupt", -1)))
        out.update(output=sp.output(), listeners=sp.laptop.listeners())
        return self._json(200, out)

    # -- POST --

    def _read_audio(self):
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith(("audio/wav", "audio/x-wav", "audio/wave")):
            self._json(415, {"error": "Content-Type must be audio/wav"})
            return None
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_AUDIO_BYTES:
            self._json(413, {"error": f"Audio must be 1 byte to {MAX_AUDIO_BYTES // 1_000_000} MB"})
            return None
        return self.rfile.read(length)

    def do_POST(self):
        from .core import Busy

        path = self.path.split("?", 1)[0]
        a = self.app
        handlers = {
            "/api/assistant/text", "/api/assistant/audio", "/api/assistant/listen", "/api/assistant/commands",
            "/api/assistant/settings", "/api/assistant/say", "/api/assistant/stop", "/api/presence",
            "/api/sim/lift", "/api/sim/phone", "/api/sim/wheel", "/api/drive", "/api/nav/memory",
        }
        if path not in handlers:
            return super().do_POST()
        try:
            if path == "/api/assistant/audio":
                wav = self._read_audio()
                if wav is None:
                    return
                return self._json(200, a.assistant.handle_audio(wav, source=self.headers.get("X-Source", "dashboard mic")[:30]))
            body = self._read_json()
            if body is None:
                return
            if path == "/api/drive":
                return self._drive(body)
            if path == "/api/nav/memory":
                return self._json(200, nav_memory_edit(a, body))
            if path == "/api/assistant/text":
                return self._json(200, a.assistant.handle_text(str(body.get("text", "")), source=str(body.get("source", "typed"))[:30]))
            if path == "/api/assistant/listen":
                return self._json(200, a.assistant.listen_robot_mic(float(body.get("seconds", 5))))
            if path == "/api/assistant/commands":
                clean, problems = a.executor.run(body.get("commands"), source=str(body.get("source", "api"))[:30])
                if a.presence is not None and not a.presence.awake and clean:
                    a.presence.set_awake(True, reason="command", announce=False)
                return self._json(200 if clean else 400, {"accepted": clean, "problems": problems})
            if path == "/api/assistant/settings":
                saved = a.settings.update(body)
                return self._json(200, public_settings(saved))
            if path == "/api/assistant/say":
                a.speaker.say(str(body.get("text", "Hello! I'm your desk robot."))[:300], "reply")
                return self._json(200, {"ok": True})
            if path == "/api/assistant/stop":
                a.executor.cancel()
                self.robot.stop()
                a.speaker.interrupt()
                return self._json(200, {"ok": True})
            if path == "/api/presence":
                if a.presence is None:
                    return self._json(400, {"error": "Bluetooth presence is not running"})
                if "awake" in body:
                    a.presence.set_awake(bool(body["awake"]), reason="dashboard")
                if body.get("find_phone"):
                    a.executor.run([{"action": "find_phone", "amount": 0}], source="dashboard")
                if isinstance(body.get("use_device"), dict):
                    dev = body["use_device"]
                    ble = a.settings.get("ble", {})
                    ble.update(address=str(dev.get("address", ""))[:64], name="", ibeacon_uuid=str(dev.get("ibeacon") or "")[:64])
                    a.settings.update({"ble": ble})
                return self._json(200, a.presence.status())
            if path == "/api/sim/lift":
                if a.sim_lift is None:
                    return self._json(400, {"error": "Only available in simulation mode"})
                a.sim_lift["lifted"] = bool(body.get("lifted"))
                if not a.sim_lift["lifted"]:
                    self.robot.reset_sim()   # "put down somewhere else": the simulated robot goes back to its start pose
                return self._json(200, {"lifted": a.sim_lift["lifted"]})
            if path == "/api/sim/wheel":
                if not a.sim:
                    return self._json(400, {"error": "Only available in simulation mode"})
                self.robot.s.sim.ctl.write(stuck=("none", "left", "right").index(body.get("stuck", "none")))
                return self._json(200, {"ok": True})
            if path == "/api/sim/phone":
                src = getattr(a.presence, "source", None)
                if src is None or not hasattr(src, "present"):
                    return self._json(400, {"error": "Only available in simulation mode"})
                src.present = bool(body.get("present"))
                return self._json(200, {"present": src.present})
        except Busy:
            return self._json(409, {"error": "I'm still answering the last question"})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:   # never a stack trace to the browser, never a dead server thread
            a.alerts.warn("api", "Something went wrong handling a dashboard request.", speak=False, detail=f"{type(exc).__name__}: {exc}")
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


    _last_drive = (None, 0.0)

    def _drive(self, body):
        from ..runtime.shared import DIRECTIONS, MOVE
        direction = body.get("direction")
        if direction not in DIRECTIONS:
            return self._json(400, {"error": f"direction must be one of {', '.join(DIRECTIONS)}"})
        now = time.monotonic()
        last_dir, last_t = AssistantHandler._last_drive
        if direction != last_dir or now - last_t > 1.0:
            self.robot.log("info", f"Remote: driving {direction}")
        AssistantHandler._last_drive = (direction, now)
        self.app.executor.cancel()        # the human takes over from any running AI command sequence
        r = self.robot
        r.last_user_command = now
        r.last_stop_reason = None
        r._send(MOVE, DIRECTIONS.index(direction), 0.5, 0)
        return self._json(200, {"ok": True})


def nav_memory_edit(a, body):
    nav, mem = a.navigator, a.navigator.memory
    mem.sync(nav.view().epoch)
    if "add" in body:
        mem.add_zone(body["add"], str(body.get("name", "no-go")))
    if "remove" in body:
        mem.remove_zone(int(body["remove"]))
    if body.get("clear_zones"):
        mem.clear_zones()
    if body.get("accept"):
        mem.accept()
    if body.get("home"):
        nav.mark_home()
    return mem.status()


def nav_map(a):
    nav, cfg = a.navigator, a.navigator.cfg
    view = nav.view()
    nav.memory.sync(view.epoch)
    idx = (np.arange(view.n) - view.n // 2 + 0.5) * view.res
    pts = lambda mask: [[round(float(idx[c]), 3), round(float(idx[r]), 3)] for r, c in zip(*np.nonzero(mask))]   # noqa: E731
    status = nav.status()
    return {"pose": [round(v, 3) for v in view.pose], "occupied": pts(view.L > cfg.occupied_logodds), "edges": pts(view.edge),
            "objects": [{"label": o.label, "x": round(o.x, 3), "y": round(o.y, 3), "radius": o.radius}
                        for o in view.objects if o.existence >= cfg.object_min_logodds],
            "memory": nav.memory.status(), "corridor": nav.memory.corridor_points(), "path": status.get("path"),
            "navigation": {k: status.get(k) for k in ("phase", "target", "planner", "confidence", "result")}}


def public_settings(s):
    from .settings import PERSONALITY_PRESETS, has_secret
    from .voice import VOICE_GENDERS, VOICE_STYLES
    s = dict(s)
    s["presets"] = PERSONALITY_PRESETS
    s["voice_styles"], s["voice_genders"] = VOICE_STYLES, VOICE_GENDERS
    s["keys"] = {k: has_secret(k) for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")}  # set or not, never the value
    return s


def assistant_state(a):
    return {
        "t": time.time(),
        "assistant": a.assistant.status(),
        "brain": a.brain.status(),
        "stt": a.stt.status(),
        "speaker": a.speaker.status(),
        "executor": a.executor.status(),
        "alerts": a.alerts.snapshot(),
        "presence": a.presence.status() if a.presence else None,
        "lift": a.lift.status(),
        "map": a.mapper.live_status() if hasattr(a.mapper, "live_status") else None,
        "navigation": a.navigator.status(),
        "wheels": a.wheels.status(),
        "health": a.health.status(),
        "settings": public_settings(a.settings.all()),
        "urls": a.urls,
        "sim": a.sim,
    }


def make_setup(https_port, host, port, handler_cls=None, lift_cls=None):
    """The run_runtime setup hook: build the assistant around the running robot.
    handler_cls / lift_cls: subclasses used by the companion runtime (deskbot/companion/app.py)."""
    handler_cls = handler_cls or AssistantHandler

    def setup(ctx):
        from ..mapping.live import LiveFusionMapper  # noqa: F401  (mapper class is passed separately)
        from ..navigation import Navigator
        from ..navigation.memory import NavMemory
        from .. import ROOT as PROJECT_ROOT
        from ..presence.ble import BleScanner, PhoneTracker, SimPhoneSource
        from ..presence.lift import LiftDetector
        from ..presence.manager import Presence
        from ..runtime.wheels import WheelWatch
        from ..vision.geometry import CameraModel
        from .alerts import Alerts
        from .brain import Brain
        from .commands import Executor
        from .core import Assistant
        from .health import Health
        from .settings import Settings, load_secrets
        from .stt import Transcriber
        from .voice import Speaker

        robot, vision, mapper, behaviour = ctx["robot"], ctx["vision"], ctx["mapper"], ctx["behaviour"]
        cfg, sim = ctx["cfg"], ctx["sim"]
        alerts = Alerts(log=robot.log)
        loaded = load_secrets()
        if loaded:
            robot.log("info", f"Loaded {', '.join(loaded)} from secrets.env")
        settings = Settings(on_warning=lambda m: alerts.warn("settings", m, speak=False))
        speaker = Speaker(settings, alerts)
        def spoken_alert(al):
            speaker.chime("warning")
            speaker.say(al["msg"], "alert")
        alerts.subscribe(spoken_alert)

        # simulation: "lift" the robot from the dashboard by making both IR sensors read "no floor"
        sim_lift = None
        if sim:
            sim_lift = {"lifted": False}
            real_reading = robot.latest_reading

            def lifted_reading():
                r = real_reading()
                if sim_lift["lifted"] and r.get("t") is not None:
                    r = dict(r, front_floor=False, back_floor=False)
                return r
            robot.latest_reading = lifted_reading

        cam = CameraModel(cfg.camera)
        tracker = PhoneTracker(settings)
        sv = SimpleNamespace(robot=robot, vision=vision, mapper=mapper, behaviour=behaviour, presence=None,
                             lift=None, cam=cam)
        memory = NavMemory(PROJECT_ROOT / "data" / ("nav_memory_sim.json" if sim else "nav_memory.json"))
        sv.navigator = navigator = Navigator(robot, mapper, cfg.navigation, speaker.say, behaviour, memory)
        motif_for = {"recognised": "recognition", "navigating": "navigation", "arrived": "arrival", "failed": "confusion",
                     "not_found": "embarrassed", "low_confidence": "low_confidence"}
        navigator.listeners.append(lambda event: speaker.chime(motif_for[event]))
        executor = Executor(sv, alerts, speaker.say)
        source = None
        try:
            source = SimPhoneSource(robot.hw, tracker).start() if sim else BleScanner(settings, tracker, alerts).start()
        except Exception as exc:
            alerts.warn("bluetooth", "Bluetooth didn't start, so I can't sense your phone.", detail=str(exc))
        presence = Presence(robot, settings, alerts, speaker.say, tracker, source, behaviour, vision, cam)
        presence.executor = executor
        sv.presence = presence
        lift = (lift_cls or LiftDetector)(robot, mapper, alerts, speaker.say, executor).start()
        sv.lift = lift
        brain = Brain(settings, alerts)
        stt = Transcriber(settings, alerts)
        assistant = Assistant(sv, settings, alerts, speaker, stt, brain, executor)
        health = Health(alerts, ctx["shared"], ctx["procs"], vision, brain).start()
        wheels = WheelWatch(robot, speaker.say, alerts, executor, speaker.chime).start()

        urls = {"http": f"http://<this-device>:{port}"}
        https_server = None
        if https_port:
            try:
                from .. import ROOT
                from ..web.tls import ensure_cert, local_names, serve_https
                cert, key = ensure_cert(ROOT / "data" / "tls")
                https_server = serve_https(host, https_port, handler_cls, cert, key)
                from ..cli import lan_ip
                names, _ = local_names()
                lan = [i for i in (lan_ip(),) if i and not i.startswith("127.")]   # the address in use now
                urls["https"] = [f"https://{h}:{https_port}" for h in ([f"{names[0]}.local"] if names else []) + lan]
                robot.log("info", f"HTTPS (for microphones) on port {https_port}: " + ", ".join(urls["https"]))
            except Exception as exc:
                alerts.warn("https", "HTTPS didn't start, so browsers can't use their microphone. Typing still works.",
                            speak=False, detail=str(exc))

        AssistantHandler.app = SimpleNamespace(
            assistant=assistant, settings=settings, alerts=alerts, speaker=speaker, executor=executor, brain=brain,
            stt=stt, presence=presence, lift=lift, health=health, mapper=mapper, navigator=navigator, wheels=wheels,
            sim_lift=sim_lift, urls=urls,
            sim=bool(sim))

        name = settings.get("robot_name", "Pip")
        speaker.say(f"Hi! I'm {name}. " + ("My AI brain is ready." if brain.backend() == "claude" else "I'm in simple mode."), "chatter")
        robot.log("info", f"Assistant ready: brain {brain.backend()}, speech-to-text {stt.order() or 'none'}, "
                          f"voice {speaker.engine or 'none'}, Bluetooth {'simulated' if sim else 'bleak'}")

        def on_close():
            for part in (health, lift, source, wheels):
                try:
                    part.stop() if part else None
                except Exception:
                    pass
            executor.cancel()
            speaker.close()
            if https_server:
                https_server.shutdown()

        return handler_cls, on_close

    return setup


def run_assistant(sim=False, host="127.0.0.1", port=8000, camera=None, https_port=8443, cfg: AppConfig | None = None):
    from ..mapping.live import LiveFusionMapper
    run_runtime(sim=sim, host=host, port=port, camera=camera, cfg=cfg, mapper_cls=LiveFusionMapper,
                setup=make_setup(https_port, host, port))


__all__ = ["run_assistant", "AssistantHandler", "assistant_state", "json"]
