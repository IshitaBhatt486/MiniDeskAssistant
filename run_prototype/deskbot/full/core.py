"""
The full robot: wires every feature of full/ into the hub robot (hub/core.py) and keeps them switchable.

Order of what answers a sentence (assistant/brain.py):
    1. pre_handlers (here, all local and free): a spoken rock-paper-scissors move, a routine's trigger phrase,
       a smart-home device sentence, guard / face / water / reading / briefing / game sentences
    2. plain robot commands ("turn left") 3. Claude (if on) 4. local sentence rules (tasks, ideas, focus, music)
    5. the local LLM (Ollama, if on) 6. the keyword rules

Two background loops:
    vision 2 Hz   hydration (drinks seen), guard (people at the desk), faces (1 Hz: who it is, greetings)
    tick   1 Hz   briefings due, water reminders, routine events (arrive / leave / time:HH:MM / focus_end),
                  guard auto-arm when the phone leaves

Switches (features.py) are checked where each feature acts, so switching one off takes effect at once:
the Claude tools of a switched-off feature answer "switched off", its sentences fall through, its loop idles.

Security rules here (docs/full.md, section Security):
    - voice "learn my face" only when no owner is enrolled yet, or the owner is recognised right now, and never
      while guarding; voice "stop guarding" only with the owner recognised or the passphrase in the sentence
    - a routine's guard step can arm, but disarms only with the owner recognised
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime

from ..assistant.core import Busy
from ..buddy.when import parse_due, say_due
from . import routines as routines_mod
from . import smarthome as smarthome_mod
from .features import TOOL_FEATURE, FeatureOff
from .reader import chunks

EXTRA_PROMPT = """More you can do (each also works by voice without you): read text from the camera ("read this for me";
read_this), log a drink of water (log_drink), play rock paper scissors (play_rps), give the morning or evening
briefing (briefing), guard the desk (guard), and say who is at the desk (who_is_here). If a tool says a feature is
switched off, tell the user they can switch it on in the dashboard's Features card."""

TOOLS = [
    {"name": "read_this", "description": "Read the text the camera sees, aloud; optionally summarise or make flashcards.",
     "input_schema": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["read", "summary", "flashcards"]}},
                      "required": ["mode"], "additionalProperties": False}},
    {"name": "log_drink", "description": "Count a drink of water the user just had.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "play_rps", "description": "Start a game of rock paper scissors (best of three).",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "briefing", "description": "Give the morning or evening briefing now.",
     "input_schema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["morning", "evening"]}},
                      "required": ["kind"], "additionalProperties": False}},
    {"name": "guard", "description": "Arm guard mode (watch the desk while the user is away).",
     "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"], "additionalProperties": False}},
    {"name": "who_is_here", "description": "Who the robot recognises at the desk right now.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
]


def reply(speech, mood="happy", sound="none", commands=()):
    return {"speech": speech, "mood": mood, "sound": sound, "commands": list(commands), "tools": [], "backend": "local"}


class Full:
    def __init__(self, ctx, app, comp, buddy, hub, settings, features, parts):
        self.ctx, self.app, self.comp, self.buddy, self.hub = ctx, app, comp, buddy, hub
        self.settings, self.features = settings, features
        for k, v in parts.items():          # wake, routines, smarthome, reader, ollama, local_brain, rps, hydration,
            setattr(self, k, v)             # briefings, faces, guard, telegram
        self.vision = ctx["vision"]
        self.image_area = ctx["cfg"].camera.width * ctx["cfg"].camera.height
        self._running = False
        self._was_present = None
        self._last_minute = None
        self.quiet_until = 0.0
        self._wire()

    # ---------------- wiring ----------------

    def _wire(self):
        a, f = self.app, self.features
        brain, assistant = a.brain, a.assistant
        # the AI on/off switch, and the local-only switch for the web tools
        claude_available = brain.claude.available
        brain.claude.available = lambda: f.on("ai_brain") and claude_available()
        from ..assistant import tools as tools_mod
        tools_mod.ALLOW_INTERNET[0] = lambda: f.on("web_tools")
        brain.fallback_brains.append(self.local_brain)
        # tools: new ones, then a switch check on every tool that belongs to a feature
        brain.add_prompt(routines_mod.PROMPT)
        brain.add_prompt(smarthome_mod.PROMPT)
        brain.add_prompt(EXTRA_PROMPT)
        handlers = {**routines_mod.tool_handlers(self.routines), **self._tool_handlers()}
        for spec in routines_mod.TOOL_SPECS + smarthome_mod.TOOL_SPECS + TOOLS:
            brain.add_tool(spec, handlers[spec["name"]])
        for name, (spec, fn) in list(brain.claude.extra_tools.items()):
            key = TOOL_FEATURE.get(name)
            if key:
                brain.claude.extra_tools[name] = (spec, self._gated_tool(key, fn))
        # objects of earlier layers: raise FeatureOff (an AccountError) when switched off
        self._gate_method(self.hub.spotify, "_call", "spotify")
        self._gate_method(self.hub.calendar, "_call", "google_calendar")
        self._gate_method(self.hub.focus, "start", "focus")
        import deskbot.buddy.core as buddy_core
        import deskbot.hub.ideas as ideas_mod
        for module, key in ((ideas_mod, "ideas"), (buddy_core, "tasks")):
            original = module.local_intent
            module.local_intent = (lambda orig, k: (lambda *x, **kw: orig(*x, **kw) if f.on(k) else None))(original, key)
        reminders = self.buddy._reminders
        self.buddy._reminders = lambda now, quiet: reminders(now, quiet) if f.on("tasks") else None
        # sentences, context, events
        brain.pre_handlers.append(self.pre_handler)
        assistant.context_hooks += [self.faces.context_lines, self._context_lines]
        listen = assistant.listen_robot_mic

        def listen_with_mic_released(seconds=5.0):
            self.wake.pause()
            try:
                return listen(seconds)
            finally:
                self.wake.resume()
        assistant.listen_robot_mic = listen_with_mic_released
        focus_end = self.hub.focus.on_end

        def on_focus_end(summary):
            focus_end(summary)
            self.run_event("focus_end")
        self.hub.focus.on_end = on_focus_end

        def on_feature(key, on):
            if key == "local_only":
                self.hub.focus.analyzer and setattr(self.hub.focus.analyzer, "download", not on)
            if key == "guard" and not on:
                self.guard.disarm("switched off")
            if key == "rps" and not on and self.rps.state != "idle":
                self.rps.stop(quiet=True)
        f.listeners.append(on_feature)

    def _gated_tool(self, key, fn):
        def run(args):
            if not self.features.on(key):
                try:
                    self.features.require(key)
                except FeatureOff as exc:
                    return f"Error: {exc}", True
            return fn(args)
        return run

    def _gate_method(self, obj, name, key):
        original = getattr(obj, name)

        def gated(*args, **kw):
            self.features.require(key)
            return original(*args, **kw)
        setattr(obj, name, gated)

    # ---------------- helpers ----------------

    def say(self, text):
        for part in chunks(text, 400):
            self.app.speaker.say(part, "chatter")

    def chime(self, name):
        self.app.speaker.chime(name)

    def react(self, emotion, seconds, why):
        emo = getattr(self.app, "emotion", None)
        if emo is not None:
            emo.react(emotion, seconds, why)

    def present(self):
        p = self.app.presence
        return p is None or p.awake

    def speaking(self):
        sp = self.app.speaker
        return sp.speaking is not None or sp._q.qsize() > 0 or time.monotonic() < self.quiet_until

    def wait_quiet(self, limit=15.0):
        t0 = time.monotonic()
        time.sleep(0.3)
        while self.speaking() and time.monotonic() - t0 < limit:
            time.sleep(0.1)

    def frame(self):
        v = self.vision
        if v is None:
            return None
        res = v.latest()
        return v.frame_image(res) if res is not None and hasattr(v, "frame_image") else None

    def snapshot(self):
        try:
            return self.vision.jpeg() if self.vision is not None else None
        except Exception:
            return None

    def listen(self, seconds):
        """Record from the robot mic (the wake word lets go of it) and transcribe; "" if there's no mic."""
        from ..assistant.stt import SttError, record_robot_mic
        self.wake.pause()
        try:
            wav = record_robot_mic(seconds)
            return self.app.stt.transcribe(wav)
        except SttError:
            return ""
        finally:
            self.wake.resume()

    def owner_name(self):
        return self.settings.section("owner")["name"] or self.faces.owner() or ""

    # ---------------- the wake word ----------------

    def on_wake(self):
        self.quiet_until = time.monotonic() + 1.2
        self.chime("recognition")
        self.react("curious", 4.0, "heard my name")
        p = self.app.presence
        if p is not None and not p.awake:
            p.set_awake(True, reason="wake word", announce=False)

    def on_request(self, wav, text):
        try:
            if text:
                self.app.assistant.handle_text(text, source="wake word")
            elif wav:
                self.app.assistant.handle_audio(wav, source="wake word")
            else:
                self.app.speaker.say("I didn't hear anything.", "chatter")
        except Busy:
            self.app.speaker.say("Just a moment, I'm still answering.", "chatter")
        except Exception as exc:
            self.app.alerts.warn("wake", "The wake word request failed.", speak=False, detail=str(exc))

    # ---------------- sentences (pre_handler) ----------------

    OFF_PHRASES = [   # a switched-off feature's sentences get "switched off", not a made-up answer from an AI
        ("guard", r"\b(?:guard (?:my |the )?desk|guard mode|start guarding|stop guarding|watch my desk)\b"),
        ("hydration", r"\b(?:i (?:just )?(?:drank|had)\b.*\b(?:water|drink|glass)|how much water)\b"),
        ("rps", r"\brock,? paper,? scissors?\b"),
        ("reader", r"\b(?:read (?:this|that|the page)|what does (?:this|that) say|make flash ?cards)\b"),
        ("owner_recognition", r"\b(?:learn|forget|remember) my face\b|\bwho am i\b"),
        ("briefings", r"\b(?:brief me|briefing|how was my day)\b"),
        ("smart_home", r"\b(?:turn|switch) (?:on|off) the (?:lamp|light|lights|fan|plug|heater)\b"),
    ]

    def _off_reply(self, t):
        from .features import CATALOG
        for key, rx in self.OFF_PHRASES:
            if not self.features.on(key) and re.search(rx, t):
                title = next(c[1] for c in CATALOG if c[0] == key)
                why = "local-only mode is on" if self.features.data.get("local_only") and self.features.internet(key) else "it's switched off"
                return reply(f"{title} is off because {why}. You can turn it on in the dashboard's Features card.", "neutral")
        return None

    def pre_handler(self, text, ctx):
        f = self.features
        t = " ".join(re.sub(r"[.!?]+$", "", text.lower()).split())
        off = self._off_reply(t)
        if off is not None:
            return off
        if f.on("rps") and self.rps.state != "idle":
            if re.search(r"\b(stop|quit|end) (the )?game\b", t):
                self.rps.stop()
                return reply("", "neutral")
            if self.rps.voice(t):
                return reply("", "curious")
        if f.on("routines"):
            if re.search(r"\b(stop|cancel) (the )?routine\b", t):
                self.routines.cancel()
                return reply("Routine stopped.", "neutral")
            key = self.routines.match(t)
            if key:
                self.routines.run(key, "voice")
                return reply("", "excited")
        if f.on("smart_home"):
            hit = self.smarthome.voice(t)
            if hit:
                d, action, value = hit
                try:
                    r = self.smarthome.control(d, action, value)
                except smarthome_mod.SmartHomeError as exc:
                    return reply(f"I couldn't reach the {d['name']}: {exc}.", "confused")
                if action == "status":
                    return reply(f"The {d['name']} is {r['state']}.", "neutral")
                return reply(f"{d['name'].capitalize()} {'set to ' + str(value) + ' percent' if action == 'set' else action}.", "happy")
        if f.on("rps") and re.search(r"\b(?:play|let'?s play|game of|start) (?:a game of )?rock,? paper,? scissors?\b|^rock paper scissors$", t):
            self.rps.start()
            return reply("", "excited")
        if f.on("briefings"):
            if re.match(r"^(?:hey \w+ )?good morning\b", t) and datetime.now().hour < 12:
                p = self.app.presence
                if p is not None and not p.awake:
                    p.set_awake(True, reason="good morning", announce=False)
                self.give_briefing("morning")
                return reply("", "happy")
            kind = self.briefings.kind_for(t)
            if kind:
                self.give_briefing(kind)
                return reply("", "happy")
        if f.on("hydration"):
            if re.search(r"\b(?:i (?:just )?(?:drank|had|drink)|log)\b.*\b(?:water|drink|glass|sip|tea|coffee|juice)\b", t):
                self.hydration.drink("said")
                return reply(f"Nice! That's {self.hydration.today()} today.", "happy", "pop")
            if re.search(r"\bhow much (?:water|have i (?:drunk|drank|had))\b", t):
                h = self.hydration.status()
                return reply(f"You've had {h['today']} drinks today. Your goal is {h['goal']}.", "curious")
        if f.on("guard"):
            if re.search(r"\b(?:guard (?:my |the )?desk|guard mode on|start guarding|watch my desk)\b", t):
                self.guard.arm("asked")
                return reply("Guard mode on. I'll watch your desk and tell you if anyone comes by.", "neutral", "beep_boop")
            if re.search(r"\b(?:stop guarding|guard mode off|disarm|i'?m back)\b", t) and self.guard.state != "off":
                phrase = (self.settings.section("guard")["passphrase"] or "").lower()
                if self.faces.owner_here(10) or (phrase and phrase in t):
                    self.guard.disarm("voice")
                    return reply("Guard mode off. Welcome back!", "happy")
                return reply("Only my owner can stop guard mode. Say the passphrase, or let me see your face.", "annoyed")
        if f.on("owner_recognition"):
            m = re.search(r"\b(?:learn|remember) my face\b|\bthis is (\w+),? (?:learn|remember) (?:his|her|their) face\b", t)
            if m:
                return self._voice_enroll(m.group(1))
            if re.search(r"\bforget my face\b", t):
                o = self.faces.owner()
                if o and self.faces.owner_here(10):
                    self.faces.forget(o)
                    return reply("Done, I've forgotten your face.", "neutral")
                return reply("I can only forget your face while I can see you.", "confused")
            if re.search(r"\bwho am i\b|\bdo you (?:know|recognise|recognize) me\b", t):
                names = [x["name"] for x in self.faces.now_here if x["name"]]
                return reply(f"You're {names[0]}!" if names else "I don't recognise you. Say 'learn my face' and I'll remember you.",
                             "happy" if names else "curious")
        if f.on("reader") and re.search(r"\b(?:read (?:this|that|the page|it)(?: for me| out| aloud)?|what does (?:this|that|it) say|"
                                        r"summari[sz]e (?:this|that|the page)|(?:make|create) flash ?cards)\b", t):
            extra = "summary" if "summar" in t else "flashcards" if "flash" in t else None
            return self.read_camera(extra)
        return None

    def _voice_enroll(self, other_name):
        if self.guard.state != "off":
            return reply("Not while I'm guarding the desk.", "annoyed")
        owner = self.faces.owner()
        if other_name is None and owner and not self.faces.owner_here(10):
            return reply("I already know my owner. Only they can teach me a new face, so let me see them first.", "confused")
        if other_name and not (owner is None or self.faces.owner_here(10)):
            return reply("Only my owner can introduce new people.", "confused")
        name = other_name.capitalize() if other_name else (self.settings.section("owner")["name"] or "owner")
        role = "friend" if other_name else "owner"

        def go():
            try:
                n = self.faces.enroll(name, role, self.frame)
                self.chime("tada")
                self.say(f"Got it! I'll know you from now on{', ' + name if name != 'owner' else ''}. ({n} looks)")
            except ValueError as exc:
                self.say(str(exc))
        threading.Thread(target=go, name="enroll", daemon=True).start()
        return reply("Look at me for a few seconds, and turn your head a little.", "curious")

    def read_camera(self, extra=None):
        if self.reader.busy:
            return reply("I'm still reading the last one.", "neutral")
        img = self.frame()
        if img is None:
            return reply("I can't see anything right now. You can upload a photo on the dashboard or send one on Telegram.", "confused")
        from .reader import jpeg_from_frame
        jpeg = jpeg_from_frame(img)
        speak = self.say if self.settings.section("reader")["speak"] else None
        self.reader.read_async(lambda: jpeg, "camera", extra, speak, lambda err: self.say(f"I couldn't read it. {err[:150]}"))
        return reply("Hold it still... reading.", "curious")

    def give_briefing(self, kind, to_telegram=None):
        text = self.briefings.make(kind)
        self.chime("notification")
        self.say(text)
        b = self.settings.section("briefing")
        if (b["telegram"] if to_telegram is None else to_telegram) and self.features.on("telegram"):
            self.telegram.broadcast(("☀️ " if kind == "morning" else "🌙 ") + text)
        return text

    # ---------------- tools ----------------

    def _tool_handlers(self):
        import json

        def j(x):
            return json.dumps(x, default=str), False

        def read(a):
            r = self.read_camera(None if a.get("mode") == "read" else a.get("mode"))
            return j({"status": r["speech"]})

        def guard(a):
            if a.get("on"):
                self.guard.arm("ai")
                return j({"guard": "armed"})
            return "Error: guard mode can only be switched off by the owner (passphrase, face, or the dashboard PIN)", True
        return {"read_this": read, "log_drink": lambda a: j({"drinks_today": self.hydration.drink("said") and self.hydration.today()}),
                "play_rps": lambda a: j(self.rps.start()), "briefing": lambda a: j({"said": self.give_briefing(a.get("kind", "morning"))}),
                "guard": guard, "who_is_here": lambda a: j(self.faces.status()["here"]),
                "smart_home": self._smart_tool}

    def _smart_tool(self, a):
        import json
        try:
            return json.dumps(self.smarthome.control(a.get("device", ""), a.get("action", "status"), a.get("value"))), False
        except smarthome_mod.SmartHomeError as exc:
            return f"Error: {exc}", True

    # ---------------- routine steps ----------------

    def routine_actions(self):
        def spotify(st):
            if st.get("query"):
                return str(self.hub.spotify.play(st["query"]).get("name"))
            return str(self.hub.spotify.control(st["action"], st.get("volume")))

        def guard(st):
            if st["on"]:
                self.guard.arm("routine")
            elif self.faces.owner_here(10):
                self.guard.disarm("routine")
            else:
                return "skipped: only the owner can disarm"

        def task(st):
            due, title = parse_due(st["title"] + " " + st.get("due", ""))
            self.buddy.store.add(title or st["title"], due, source="routine")
        return {
            "say": lambda st: self.say(st["text"]), "sound": lambda st: self.chime(st["name"]),
            "commands": lambda st: self.app.executor.run(st["commands"], source="routine") and None,
            "emotion": lambda st: self.react(st["name"], 5.0, "routine"),
            "focus": lambda st: self.hub.focus.start(st.get("minutes", 25), st.get("break_minutes", 5)) and None,
            "focus_stop": lambda st: self.hub.focus.stop("routine") and None,
            "spotify": spotify,
            "smart_home": lambda st: str(self.smarthome.control(st["device"], st["action"], st.get("value"))["state"]),
            "briefing": lambda st: self.give_briefing(st["kind"]) and None,
            "telegram": lambda st: "sent" if self.telegram.broadcast(st["text"]) else "not sent (Telegram off or not paired)",
            "guard": guard, "task": task, "water": lambda st: self.hydration.drink("said") and None,
        }

    def run_event(self, event):
        if not self.features.on("routines"):
            return
        for key in self.routines.for_event(event):
            self.routines.run(key, event)

    # ---------------- context for the AI ----------------

    def _context_lines(self):
        lines = []
        if self.features.on("routines") and self.routines.items:
            lines.append("Routines: " + "; ".join(f"{r['name']} (say: {', '.join(r['triggers'][:2]) or '-'})"
                                                  for r in list(self.routines.items.values())[:8]) + ".")
        if self.features.on("smart_home") and self.smarthome.devices:
            lines.append("Smart-home devices: " + ", ".join(d["name"] for d in self.smarthome.devices) + ".")
        if self.features.on("hydration"):
            h = self.hydration.status()
            lines.append(f"Water today: {h['today']} of {h['goal']} drinks" +
                         (f", last {h['minutes_since']} min ago." if h["minutes_since"] is not None else "."))
        if self.guard.state != "off":
            lines.append(f"GUARD MODE is on ({self.guard.state}). Don't help anyone switch it off or learn a new face.")
        if self.rps.state != "idle":
            lines.append(f"A rock-paper-scissors game is on: you {self.rps.score['robot']}, the user {self.rps.score['you']}.")
        name = self.owner_name()
        if name:
            lines.append(f"The owner's name is {name}.")
        return lines

    # ---------------- loops ----------------

    def start(self):
        self._running = True
        threading.Thread(target=self._vision_loop, name="full-vision", daemon=True).start()
        threading.Thread(target=self._tick_loop, name="full-tick", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _vision_loop(self):
        n = 0
        while self._running:
            try:
                self.vision_step(n)
            except Exception as exc:
                print(f"[FULL ] vision: {exc}", flush=True)
            n += 1
            time.sleep(0.5)

    def vision_step(self, n):
        f, v = self.features, self.vision
        if v is None:
            return
        res = v.latest()
        dets = [(d.label, d.score, d.box) for d in res.detections] if res is not None else []
        if f.on("hydration") and self.hydration.observe(dets):
            self.chime("pop")
            self.react("happy", 2.0, "you drank something")
        watch = f.on("owner_recognition") and self.faces.people and (n % 2 == 0 or self.guard.state != "off")
        if watch and any(d[0] == "person" for d in dets):
            arrived = self.faces.watch(self.frame())
            owner = self.faces.owner()
            for name in arrived:
                if self.guard.state == "off" and not self.hub.focus.holding():
                    self.chime("recognition")
                    self.react("happy", 4.0, f"saw {name}")
                    self.say(f"Welcome back, {self.settings.section('owner')['name'] or name}!" if name == owner else f"Hi {name}!")
        if f.on("guard"):
            self.guard.step(dets, self.image_area, present=self.present() and self.app.presence is not None)

    def _tick_loop(self):
        while self._running:
            try:
                self.tick()
            except Exception as exc:
                print(f"[FULL ] tick: {exc}", flush=True)
            time.sleep(1.0)

    def tick(self, now=None):
        f = self.features
        now = now or datetime.now()
        present = self.present()
        if self._was_present is not None and present != self._was_present:
            self.run_event("arrive" if present else "leave")
            if not present and f.on("guard") and self.settings.section("guard")["auto_arm"]:
                self.guard.arm("phone left")
        self._was_present = present
        minute = now.strftime("%H:%M")
        if minute != self._last_minute:
            self._last_minute = minute
            self.run_event(f"time:{minute}")
        if self.app.assistant.phase != "idle" or self.speaking():
            return
        if f.on("briefings") and not self.hub.focus.holding():
            kind = self.briefings.due(present)
            if kind:
                self.give_briefing(kind)
                return
        if f.on("hydration"):
            line = self.hydration.tick(present, self.hub.focus.holding())
            if line:
                self.chime("pop")
                self.react("curious", 3.0, "water reminder")
                self.say(line)

    # ---------------- Telegram commands ----------------

    def telegram_commands(self):
        store, ideas, hub = self.buddy.store, self.hub.ideas, self.hub

        def tasks(args, chat):
            open_ = store.open_tasks()
            if not open_:
                return "Your task list is empty. 🎉"
            return "\n".join(f"• {t['title']}" + (f" — due {say_due(datetime.fromisoformat(t['due']))}" if t["due"] else "") for t in open_[:20])

        def add(args, chat):
            due, title = parse_due(args)
            t = store.add(title or args, due, source="telegram")
            return f"Added: {t['title']}" + (f" (due {say_due(due)})" if due else "")

        def done(args, chat):
            return f"Done: {store.complete(args, source='telegram')['title']} ✅"

        def text(msg, chat):
            speak = self.settings.section("telegram")["speak_replies"]
            try:
                return self.app.assistant.handle_text(msg, source="telegram", speak=speak)["speech"]
            except Busy:
                return "I'm busy answering someone at the desk. Try again in a moment."

        def photo(jpeg, caption, chat):
            self.features.require("reader")
            extra = "summary" if "summar" in caption.lower() else "flashcards" if "flash" in caption.lower() else None
            rec = self.reader.read(jpeg, "telegram", extra)
            body = (self.reader.folder / rec["file"]).read_text(encoding="utf-8")
            more = f"\n\n— {rec['extra']['kind']} —\n{rec['extra']['text']}" if rec.get("extra") else ""
            return f"📄 {body.strip()}{more}\n\n(saved as {rec['file']}, read with {rec['backend']})"

        def guard(args, chat):
            if args.lower() in ("on", "arm", ""):
                self.features.require("guard")
                self.guard.arm("telegram")
                return "🛡️ Guard mode on."
            self.guard.disarm("telegram")
            return "Guard mode off."

        def snap(args, chat):
            jpeg = self.snapshot()
            if not jpeg:
                return "No camera picture right now."
            self.telegram.send_photo(jpeg, "Your desk right now", [chat])
            return None

        def status(args, chat):
            fs = hub.focus.status()
            return (f"Robot: {self.app.robot.snapshot()['state']}, {'awake' if self.present() else 'asleep'}.\n"
                    f"Tasks open: {len(store.open_tasks())}. Focus: {fs['state']}. Guard: {self.guard.state}.\n"
                    f"Water today: {self.hydration.today()}.")
        return {
            "start": lambda a, c: "Hi! Send /help to see what I can do.",
            "help": lambda a, c: ("/tasks · /add <task> · /done <task>\n/idea <text> · /ideas\n/brief · /focus [min] · /stopfocus\n"
                                  "/guard on|off · /photo · /water · /status\n/say <text>\nSend a photo of a page and I'll read it."),
            "tasks": tasks, "add": add, "done": done,
            "idea": lambda a, c: f"💡 Saved idea #{ideas.add(a, source='telegram')['id']}",
            "ideas": lambda a, c: "\n".join(f"• {i['text']}" for i in ideas.search(limit=15)) or "No ideas yet.",
            "brief": lambda a, c: self.briefings.make("morning" if datetime.now().hour < 15 else "evening"),
            "focus": lambda a, c: f"Focus mode on for {hub.focus.start(int(a) if a.isdigit() else 25)['minutes']} minutes.",
            "stopfocus": lambda a, c: "Focus mode off." if hub.focus.stop("telegram") else "Focus mode wasn't on.",
            "guard": guard, "photo": snap,
            "water": lambda a, c: f"💧 {self.hydration.today()} drinks today (goal {self.hydration.status()['goal']}).",
            "say": lambda a, c: (self.say(a[:300]), "Said it. 🔊")[1] if a else "Usage: /say <text>",
            "status": status, "_text": text, "_photo": photo,
        }

    def status(self):
        return {"features": self.features.status(), "wake": self.wake.status(), "routines": self.routines.status(),
                "smarthome": self.smarthome.status(), "reader": self.reader.status(), "rps": self.rps.status(),
                "hydration": self.hydration.status(), "briefing": self.briefings.status(), "faces": self.faces.status(),
                "guard": self.guard.status(), "telegram": self.telegram.status(),
                "local_llm": {"url": self.ollama.url, "models": self.ollama.models(), "error": self.ollama.last_error,
                              "available": self.local_brain.available()},
                "settings": self.settings.public()}
