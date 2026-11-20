"""Full robot (19 Nov 2026): features, routines, smart home, wake word, games, hydration, briefings, reader,
local AI, faces, guard, Telegram. No hardware, network, models or accounts needed."""

import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant import tools as tools_mod
from deskbot.assistant.alerts import Alerts
from deskbot.assistant.brain import Brain
from deskbot.assistant.settings import Settings
from deskbot.full import routines as rt
from deskbot.full.briefing import Briefings
from deskbot.full.config import FullSettings
from deskbot.full.faces import Faces
from deskbot.full.features import CATALOG, FeatureFlags, FeatureOff, help_text
from deskbot.full.guard import Guard
from deskbot.full.hydration import Hydration
from deskbot.full.local_llm import LocalLLMError, OllamaBrain, check_local_url
from deskbot.full.reader import Reader, chunks
from deskbot.full.rps import RockPaperScissors, judge
from deskbot.full.smarthome import SmartHome, SmartHomeError
from deskbot.full.telegram import Telegram
from deskbot.full.wake import FRAME, WakeWord
from deskbot.hub.accounts import AccountError


def tmp():
    return Path(tempfile.mkdtemp())


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------------- features + help ----------------

class FeaturesTest(unittest.TestCase):
    def test_switches_local_only_and_adapters(self):
        box = {"sounds": True}
        f = FeatureFlags(tmp() / "f.json", {"sound_effects": (lambda: box["sounds"], lambda on: box.update(sounds=on))})
        self.assertTrue(f.on("wake_word"))
        self.assertFalse(f.on("guard"))                    # privacy-sensitive: off by default
        f.set("sound_effects", False)
        self.assertFalse(box["sounds"])                    # adapters write the setting that already exists
        f.set("local_only", True)
        self.assertFalse(f.on("spotify"))                  # needs the internet: blocked
        self.assertTrue(f.status()["features"][[c[0] for c in CATALOG].index("spotify")]["switched_on"])  # but remembered
        self.assertTrue(f.on("local_llm"))
        with self.assertRaises(FeatureOff) as cm:
            f.require("telegram")
        self.assertIsInstance(cm.exception, AccountError)
        self.assertIn("local-only", str(cm.exception))
        f2 = FeatureFlags(f.path)
        self.assertTrue(f2.data["local_only"])
        with self.assertRaises(ValueError):
            f.set("teleport", True)

    def test_help_lists_everything(self):
        text = help_text()
        for key, title, *_ in CATALOG:
            self.assertIn(title, text)
        self.assertIn("python main.py full", text)
        self.assertIn("Guard mode", help_text("guard"))
        self.assertNotIn("Spotify", help_text("guard"))


# ---------------- brain hooks ----------------

class BrainHooksTest(unittest.TestCase):
    def test_pre_handlers_first_and_fallback_brain(self):
        b = Brain(Settings(tmp() / "a.json"), Alerts(log=lambda *_: None))
        b.claude.available = lambda: False
        b.pre_handlers.append(lambda t, c: {"speech": "Lamp on.", "mood": "happy", "commands": []} if "lamp" in t else None)
        self.assertEqual(b.think("turn on the lamp", "ctx")["speech"], "Lamp on.")       # before "turn" = robot command
        self.assertEqual(b.think("turn left", "ctx")["commands"][0]["action"], "turn_left")
        fb = SimpleNamespace(name="local", available=lambda: True,
                             think=lambda *a, **k: {"speech": "I'm a local model.", "mood": "happy", "sound": "none", "commands": []})
        b.fallback_brains.append(fb)
        out = b.think("tell me about yourself", "ctx")
        self.assertEqual((out["speech"], out["backend"]), ("I'm a local model.", "local"))

    def test_internet_switch_blocks_web_tools(self):
        old = tools_mod.ALLOW_INTERNET[0]
        try:
            tools_mod.ALLOW_INTERNET[0] = lambda: False
            text, err = tools_mod.run_tool("get_weather", {"location": "Delhi"}, {})
            self.assertTrue(err)
            self.assertIn("local-only", text)
        finally:
            tools_mod.ALLOW_INTERNET[0] = old


# ---------------- routines ----------------

class RoutinesTest(unittest.TestCase):
    def test_validate(self):
        bad = [{"name": "x", "triggers": ["go"], "steps": [{"do": "say", "text": "hi"}]},          # 1-word trigger
               {"name": "x", "triggers": ["go now"], "steps": [{"do": "explode"}]},
               {"name": "x", "triggers": ["go now"], "steps": [{"do": "wait", "seconds": 600}]},
               {"name": "x", "triggers": ["go now"], "steps": [{"do": "say"}]},
               {"name": "x", "events": ["sunrise"], "steps": [{"do": "say", "text": "hi"}]},
               {"name": "x", "triggers": ["go now"], "steps": [{"do": "say", "text": "x"}] * 21}]
        for b in bad:
            with self.assertRaises(ValueError, msg=b):
                rt.validate(b)
        ok = rt.validate({"name": " Movie  night ", "triggers": ["Movie Night!"], "events": ["time:20:30"],
                          "steps": [{"do": "smart_home", "device": "lamp", "action": "off", "junk": 1}]})
        self.assertEqual((ok["name"], ok["triggers"], ok["steps"][0]), ("Movie night", ["movie night"],
                                                                         {"do": "smart_home", "device": "lamp", "action": "off"}))

    def test_examples_match_run_and_events(self):
        done = []
        r = rt.Routines(tmp() / "routines", actions={"say": lambda st: done.append(st["text"]), "sound": lambda st: done.append(st["name"])},
                        log=lambda *_: None)
        self.assertEqual(set(r.items), {"study-time", "break-time"})        # examples written on first start
        self.assertEqual(r.match("Study time!"), "study-time")
        self.assertEqual(r.match("hey pip run the study time routine"), "study-time")
        self.assertIsNone(r.match("study"))
        r.save({"name": "Hello", "triggers": ["say hello"], "events": ["arrive"], "steps": [
            {"do": "say", "text": "hi"}, {"do": "wait", "seconds": 1}, {"do": "sound", "name": "tada"}, {"do": "guard", "on": True}]})
        self.assertEqual(r.for_event("arrive"), ["hello"])
        r.run("hello", wait=True)
        self.assertEqual(done, ["hi", "tada"])
        self.assertEqual([s["result"] for s in r.last_run["steps"]][-1], "failed: not available here")   # a step without an action
        with self.assertRaises(ValueError):
            r.save({"name": "Other", "triggers": ["say hello"], "steps": [{"do": "say", "text": "x"}]})   # trigger clash
        self.assertTrue(json.loads((r.folder / "hello.json").read_text())["enabled"])
        r.set_enabled("hello", False)
        self.assertIsNone(r.match("say hello"))

    def test_ai_tool(self):
        r = rt.Routines(tmp() / "r", log=lambda *_: None, write_examples=False)
        t = rt.tool_handlers(r)
        text, err = t["create_routine"]({"name": "Movie night", "triggers": ["movie night"], "description": "",
                                         "steps_json": '[{"do": "say", "text": "Popcorn!"}]'})
        self.assertFalse(err, text)
        text, err = t["create_routine"]({"name": "Bad", "triggers": ["bad one"], "description": "", "steps_json": "not json"})
        self.assertTrue(err)


# ---------------- smart home ----------------

class SmartHomeTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.sh = SmartHome(tmp() / "sh.json", http=lambda m, url, body=None, headers=None: self.calls.append((m, url, body, headers)) or {"output": True, "POWER": "ON", "state": "on"})

    def test_devices_and_voice(self):
        with self.assertRaises(SmartHomeError):
            self.sh.add({"name": "lamp", "type": "shelly", "host": "8.8.8.8"})          # not on the local network
        with self.assertRaises(SmartHomeError):
            self.sh.add({"name": "lamp", "type": "homeassistant", "entity_id": "lock.front_door"})   # only lights/switches/fans
        self.sh.add({"name": "Desk Lamp", "aliases": ["lamp"], "type": "homeassistant", "entity_id": "light.desk_lamp"})
        self.sh.add({"name": "fan", "type": "shelly", "host": "192.168.1.50"})
        self.sh.add({"name": "strip", "type": "tasmota", "host": "strip.local"})
        cases = {"turn on the desk lamp": ("desk lamp", "on", None), "switch the fan off": ("fan", "off", None),
                 "set the lamp to 30 percent": ("desk lamp", "set", 30), "is the fan on?": ("fan", "status", None),
                 "lamp off please": ("desk lamp", "off", None)}
        for text, (name, action, value) in cases.items():
            d, a, v = self.sh.voice(text)
            self.assertEqual((d["name"], a, v), (name, action, value), text)
        self.assertIsNone(self.sh.voice("turn left"))
        self.assertEqual(SmartHome(self.sh.path).devices[1]["host"], "192.168.1.50")

    def test_control_urls(self):
        self.sh.add({"name": "fan", "type": "shelly", "host": "192.168.1.50"})
        self.sh.add({"name": "strip", "type": "tasmota", "host": "192.168.1.52"})
        self.sh.add({"name": "heater", "type": "shelly1", "host": "192.168.1.51"})
        self.sh.control("fan", "on")
        self.assertEqual(self.calls[-1][1], "http://192.168.1.50/rpc/Switch.Set?id=0&on=true")
        self.sh.control("strip", "set", 40)
        self.assertEqual(self.calls[-1][1], "http://192.168.1.52/cm?cmnd=Dimmer%2040")
        self.sh.control("heater", "off")
        self.assertEqual(self.calls[-1][1], "http://192.168.1.51/relay/0?turn=off")
        self.sh.add({"name": "lamp", "type": "homeassistant", "entity_id": "light.desk_lamp"})
        with mock.patch.dict(os.environ, {"HA_URL": "", "HA_TOKEN": ""}):
            with self.assertRaises(SmartHomeError):
                self.sh.control("lamp", "on")
        with mock.patch.dict(os.environ, {"HA_URL": "http://192.168.1.10:8123", "HA_TOKEN": "secret"}):
            self.sh.control("lamp", "set", 30)
            m, url, body, headers = self.calls[-1]
            self.assertEqual((m, url, body), ("POST", "http://192.168.1.10:8123/api/services/light/turn_on",
                                              {"entity_id": "light.desk_lamp", "brightness_pct": 30}))
            self.assertEqual(headers["Authorization"], "Bearer secret")
            self.assertNotIn("secret", json.dumps(self.sh.status()))
        with mock.patch.dict(os.environ, {"HA_URL": "https://my-ha.example.com", "HA_TOKEN": "x"}):
            with self.assertRaises(SmartHomeError):
                self.sh.control("lamp", "on")                                   # a cloud URL is refused


# ---------------- wake word ----------------

def frames(level, n):
    import array
    return [array.array("h", [level if i % 2 else -level for i in range(FRAME)]).tobytes() for _ in range(n)]


class FakeMic:
    def __init__(self, script):
        self.script = list(script)
        self.name = "fake"

    def open(self):
        return self

    def read(self):
        if not self.script:
            raise RuntimeError("the microphone stopped")
        return self.script.pop(0)

    def close(self):
        pass


class WakeTest(unittest.TestCase):
    def test_record_request_until_quiet(self):
        w = WakeWord(lambda: "hey pip", on_request=lambda *a: None)
        w.mic = FakeMic(frames(50, 8) + frames(50, 10) + frames(3000, 40) + frames(50, 40))
        pcm = w.record_request()
        seconds = len(pcm) / 2 / 16000
        self.assertTrue(1.2 <= seconds <= 2.2, seconds)           # the speech plus ~0.8 s of quiet
        w.mic = FakeMic(frames(50, 8) + frames(50, 200))
        self.assertEqual(w.record_request(), b"")                 # nobody spoke

    def test_detector_loop_and_self_hearing(self):
        got = []
        speaking = {"now": True}

        class Det:
            name = "fake"
            n = 0

            def load(self):
                return self

            def feed(self, frame):
                self.n += 1
                return (self.n >= 3), ""

            def reset(self):
                self.n = 0
        script = frames(100, 5) + frames(100, 8) + frames(3000, 30) + frames(50, 40)
        w = WakeWord(lambda: "hey pip", on_request=lambda wav, text: got.append((wav, text)), speaking=lambda: speaking["now"],
                     detectors=[lambda p: Det()], mic_factory=lambda: FakeMic(script), log=lambda *_: None)
        w._setup()
        w.mic = FakeMic(script)
        for _ in range(5):                                        # while the robot talks, frames are ignored
            frame = w.mic.read()
            if w.speaking():
                w.detector.reset()
                continue
        self.assertEqual(w.detector.n, 0)
        speaking["now"] = False
        while not got:
            hit, rest = w.detector.feed(w.mic.read())
            if hit:
                w._woken(rest)
        self.assertTrue(got[0][0].startswith(b"RIFF"))
        w.simulate("what time is it")
        self.assertEqual(got[-1], (None, "what time is it"))
        self.assertEqual(w.count, 2)


# ---------------- rock paper scissors ----------------

class RpsTest(unittest.TestCase):
    def test_rules_and_match(self):
        self.assertEqual(judge("rock", "scissors"), "you")
        self.assertEqual(judge("rock", "paper"), "robot")
        self.assertEqual(judge("paper", "paper"), "draw")
        said, ends = [], []
        g = RockPaperScissors(said.append, lambda n: None, lambda *a: None, on_match_end=ends.append)
        g._next_round = lambda gen, retry=False: None                # rounds by hand in the test
        g.state = "waiting"
        g.choose = lambda: "scissors"
        g.play("rock")
        g.choose = lambda: "rock"
        g.play("rock")                                               # draw
        g.choose = lambda: "paper"
        g.play("scissors")
        self.assertEqual(g.score, {"you": 2, "robot": 0, "draws": 1})
        self.assertEqual(ends, ["you"])
        self.assertIn("You win the match", said[-1])
        self.assertEqual(g.state, "idle")

    def test_voice_and_cheeky_choice(self):
        g = RockPaperScissors(lambda t: None, lambda n: None, lambda *a: None)
        self.assertIsNone(g.voice("rock"))                            # no game on
        g.state = "waiting"
        self.assertEqual(g.voice("I choose stone"), "rock")
        g.history.update({"paper": 5})
        g.rng.random = lambda: 0.1
        self.assertEqual(g.choose(), "scissors")                     # beats their favourite


# ---------------- hydration ----------------

class HydrationTest(unittest.TestCase):
    def test_seeing_drinks_and_reminders(self):
        c = Clock(1000.0)
        wall = [datetime(2026, 11, 19, 10, 0)]
        h = Hydration(tmp() / "h.json", clock=c, wall=lambda: wall[0])
        person = ("person", 0.9, (100, 20, 220, 240))
        cup_at_mouth = ("cup", 0.6, (140, 30, 180, 80))
        cup_on_desk = ("cup", 0.6, (250, 200, 290, 238))
        self.assertIsNone(h.observe([person, cup_at_mouth]))
        c.t += 0.7
        self.assertEqual(h.observe([person, cup_at_mouth]), "raised")
        self.assertEqual(h.today(), 1)
        c.t += 10
        self.assertIsNone(h.observe([person, cup_at_mouth]))         # cool-down: the same sip isn't counted twice
        c.t += 200
        h.observe([person, cup_on_desk])
        c.t += 2
        h.observe([person])                                          # picked up
        c.t += 6
        self.assertEqual(h.observe([person, cup_on_desk]), "lifted")  # and put back
        self.assertEqual(h.today(), 2)
        # reminders
        h.drink("said")
        self.assertIsNone(h.tick())
        c.t += 46 * 60
        self.assertIsNone(h.tick(holding=True))                      # focus mode: wait for the break
        self.assertIsNone(h.tick(present=False))
        self.assertIsNotNone(h.tick())
        self.assertIsNone(h.tick())                                  # not again for 30 min
        wall[0] = datetime(2026, 11, 19, 23, 0)
        c.t += 31 * 60
        self.assertIsNone(h.tick())                                  # outside 08:00-22:00
        self.assertEqual(Hydration(h.path, wall=lambda: datetime(2026, 11, 19, 12, 0)).today(), 3)


# ---------------- briefings ----------------

class BriefingTest(unittest.TestCase):
    def test_morning_evening_and_schedule(self):
        now = [datetime(2026, 11, 19, 8, 30)]
        tasks = [{"title": "submit the report", "due": "2026-11-19T17:00:00"}, {"title": "old thing", "due": "2026-11-18T10:00:00"},
                 {"title": "buy milk", "due": None}]
        b = Briefings(tmp() / "b.json", {
            "name": lambda: "Ishita",
            "weather": lambda: {"place": "Delhi, India", "now": {"temperature_c": 21.4, "conditions": "clear sky"},
                                "forecast": [{"max_c": 28, "rain_chance_pct": 60}]},
            "tasks": lambda: tasks, "calendar": lambda hours: [{"title": "physics lab", "start": "2026-11-19T14:00:00+05:30", "all_day": False}],
            "done_today": lambda: [{"title": "email prof"}], "focus_minutes": lambda: 70, "ideas_today": lambda: 2,
            "drinks_today": lambda: 6}, clock=lambda: now[0])
        m = b.morning()
        for bit in ("Good morning, Ishita!", "21 degrees", "up to 28", "60 percent chance of rain", "physics lab",
                    "Due today: submit the report", "1 task is overdue"):
            self.assertIn(bit, m)
        now[0] = datetime(2026, 11, 19, 21, 30)
        e = b.evening()
        for bit in ("finished 1 task", "focused for 1 hour 10 minutes", "saved 2 ideas", "had 6 drinks", "Still open: 3 tasks"):
            self.assertIn(bit, e)
        now[0] = datetime(2026, 11, 19, 8, 5)
        self.assertEqual(b.due(), "morning")
        b.make("morning")
        self.assertIsNone(b.due())
        now[0] = datetime(2026, 11, 19, 21, 5)
        self.assertEqual(b.due(present=True), "evening")
        self.assertIsNone(b.due(present=False))
        self.assertEqual(b.kind_for("how was my day?"), "evening")
        self.assertEqual(b.kind_for("hello"), None)

    def test_missing_sources_are_skipped(self):
        def boom():
            raise RuntimeError("no internet")
        b = Briefings(tmp() / "b.json", {"weather": boom}, clock=lambda: datetime(2026, 11, 19, 9, 0))
        m = b.morning()
        self.assertIn("Good morning!", m)
        self.assertNotIn("degrees", m)


# ---------------- reader + local AI ----------------

class FakeOllama:
    def __init__(self, text="Photosynthesis makes sugar.", fail=False):
        self.text, self.fail = text, fail
        self.settings = lambda: {}

    def read_image(self, jpeg):
        if self.fail:
            raise LocalLLMError("can't reach Ollama")
        return self.text

    def summarise(self, text, kind):
        return f"{kind} of: {text[:20]}"

    def has(self, m):
        return True


class ReaderTest(unittest.TestCase):
    def test_read_save_speak(self):
        d = tmp()
        r = Reader(d, lambda: {"ocr": "auto"}, FakeOllama("First sentence. " * 30), allow_cloud=lambda: False,
                   clock=lambda: datetime(2026, 11, 19, 10, 0, 0))
        said = []
        rec = r.read(b"jpeg", "test", "summary", said.append)
        self.assertEqual(rec["backend"], "ollama")
        self.assertTrue((d / "2026-11-19_10-00-00.txt").exists())
        self.assertTrue((d / "2026-11-19_10-00-00.summary.txt").exists())
        self.assertTrue(said[0].startswith("summary of"))
        self.assertIsNone(r.file("../secrets.env"))
        self.assertIsNotNone(r.file("2026-11-19_10-00-00.txt"))
        self.assertNotIn("claude", r.ocr_order())                     # local-only: never the cloud

    def test_all_fail_message_and_chunks(self):
        r = Reader(tmp(), lambda: {"ocr": "auto"}, FakeOllama(fail=True), allow_cloud=lambda: False)
        with mock.patch("deskbot.full.reader.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as cm:
                r.read(b"x")
        self.assertIn("ollama", str(cm.exception))
        self.assertIn("Tesseract", str(cm.exception))
        parts = chunks("One. " * 300, 100)
        self.assertTrue(all(len(p) <= 110 for p in parts))

    def test_local_llm_rules(self):
        for ok in ("http://127.0.0.1:11434", "http://192.168.1.20:11434", "http://laptop.local:11434"):
            check_local_url(ok)
        for bad in ("https://api.example.com", "http://8.8.8.8:11434", "ftp://192.168.1.2"):
            with self.assertRaises(LocalLLMError):
                check_local_url(bad)
        fake = SimpleNamespace(has=lambda m: True, chat=lambda *a, **k: json.dumps(
            {"speech": "Spinning!", "mood": "excited", "sound": "whoosh", "commands": [{"action": "spin", "amount": 1}]}))
        b = OllamaBrain(fake, Settings(tmp() / "a.json"))
        out = b.think("spin", "ctx", [])
        self.assertEqual((out["speech"], out["commands"][0]["action"]), ("Spinning!", "spin"))
        fake.chat = lambda *a, **k: "not json at all"
        self.assertEqual(b.think("x", "ctx", [])["speech"], "not json at all")


# ---------------- faces ----------------

class FakeRec:
    def alignCrop(self, image, face):
        return face

    def feature(self, aligned):
        import numpy as np
        return np.array([aligned[0] + 1.0] + [1.0] * 127, dtype=np.float32).reshape(1, -1)


class FacesTest(unittest.TestCase):
    def make(self):
        face = [100, 50, 80, 90] + [0] * 10 + [0.95]
        analyzer = SimpleNamespace(ready=lambda: True, faces=lambda img: [face], error=None)
        f = Faces(tmp() / "faces" / "people.json", analyzer, tmp(), download=lambda: False, log=lambda *_: None)
        f.rec = FakeRec()
        return f

    def test_enroll_identify_forget(self):
        f = self.make()
        n = f.enroll("Ishita", "owner", frames=lambda: "img", seconds=10, sleep=lambda s: None)
        self.assertEqual(n, 20)
        self.assertEqual(f.owner(), "Ishita")
        self.assertEqual(f.identify("img")[0]["name"], "Ishita")
        stored = f.path.read_text()
        self.assertNotIn("img", stored)                                  # numbers only, never the picture
        if os.name == "posix":
            self.assertEqual(f.path.stat().st_mode & 0o777, 0o600)
        f.enroll("Arjun", "owner", frames=lambda: "img", seconds=10, sleep=lambda s: None)
        self.assertEqual(f.owner(), "Arjun")                             # one owner at a time
        self.assertEqual(f.people["Ishita"]["role"], "friend")
        self.assertEqual(f.watch("img"), ["Arjun"] if f.identify("img")[0]["name"] == "Arjun" else ["Ishita"])
        f.forget("Ishita")
        self.assertNotIn("Ishita", Faces(f.path, f.analyzer, tmp()).people)

    def test_strangers_and_too_few_samples(self):
        f = self.make()
        f.enroll("Ishita", "owner", frames=lambda: "img", seconds=10, sleep=lambda s: None)
        name, sim = f.identify_features([-1.0] * 128)
        self.assertIsNone(name)
        f2 = self.make()
        f2.analyzer = SimpleNamespace(ready=lambda: True, faces=lambda img: [], error=None)
        with self.assertRaises(ValueError):
            f2.enroll("X", "owner", frames=lambda: "img", seconds=0.01, sleep=lambda s: None)


# ---------------- guard ----------------

PERSON = [("person", 0.9, (0, 0, 200, 200))]


class GuardTest(unittest.TestCase):
    def make(self, heard="", owner=False, passphrase=""):
        c = Clock(0.0)
        self.said, self.sent = [], []
        g = Guard(tmp() / "guard", self.said.append, snapshot=lambda: b"\xff\xd8jpeg", listen=lambda s: heard,
                  notify=lambda text, jpeg: self.sent.append((text, jpeg)), owner_here=lambda: owner,
                  settings=lambda: {"passphrase": passphrase, "auto_arm": False}, clock=c,
                  wall=lambda: datetime(2026, 11, 19, 15, 0, 0))
        g._run_now = True
        return g, c

    def challenge(self, g, c):
        g.step(PERSON, 320 * 240)
        c.t += 2
        with mock.patch("deskbot.full.guard.time.sleep"):
            with mock.patch("deskbot.full.guard.threading.Thread") as T:
                T.side_effect = lambda target, **kw: SimpleNamespace(start=target)
                return g.step(PERSON, 320 * 240)

    def test_visitor_gets_asked_and_photographed(self):
        g, c = self.make(heard="I'm Arjun, just borrowing a pen")
        g.arm()
        self.assertEqual(self.challenge(g, c), "challenging")
        self.assertIn("Who are you?", self.said[0])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("borrowing a pen", self.sent[0][0])
        self.assertEqual(self.sent[0][1], b"\xff\xd8jpeg")
        self.assertEqual(g.photos(), ["2026-11-19_15-00-00.jpg"])
        self.assertEqual(g.state, "armed")
        c.t += 10
        self.assertIsNone(g.step(PERSON, 320 * 240))                  # cool-down

    def test_passphrase_owner_and_small_boxes(self):
        g, c = self.make(heard="the password is purple elephant", passphrase="purple elephant")
        g.arm()
        self.challenge(g, c)
        self.assertEqual(g.state, "off")
        self.assertEqual(self.sent, [])
        g2, c2 = self.make(owner=True)
        g2.arm()
        self.assertEqual(g2.step(PERSON, 320 * 240), "disarmed")
        g3, c3 = self.make()
        g3.arm()
        g3.step([("person", 0.9, (0, 0, 20, 20))], 320 * 240)          # far away / tiny: ignored
        c3.t += 5
        self.assertIsNone(g3.step([("person", 0.9, (0, 0, 20, 20))], 320 * 240))


# ---------------- Telegram ----------------

class FakeUrlopen:
    def __init__(self):
        self.requests = []

    def __call__(self, req, timeout=None):
        body = getattr(req, "data", None)
        self.requests.append((req.full_url if hasattr(req, "full_url") else req, body))
        return io.BytesIO(json.dumps({"ok": True, "result": {"username": "deskbot_test"}}).encode())


class TelegramTest(unittest.TestCase):
    def make(self):
        self.net = FakeUrlopen()
        t = Telegram(tmp() / "tg.json", {"tasks": lambda a, c: "• buy milk", "_text": lambda m, c: f"echo {m}",
                                         "_photo": lambda j, cap, c: "read"},
                     token="123:SECRET", log=lambda *_: None, urlopen=self.net)
        return t

    def sent_texts(self):
        return [json.loads(b)["text"] for url, b in self.net.requests if b and url.endswith("/sendMessage")]

    def test_pairing_and_privacy(self):
        t = self.make()
        msg = lambda text, chat=42: {"chat": {"id": chat}, "text": text}   # noqa: E731
        self.assertIn("private", t.handle(msg("/tasks")))
        self.assertIsNone(t.handle(msg("/tasks")))                     # told once an hour, then ignored
        self.assertIn("wrong or expired", t.handle(msg("/pair 000000")))
        code = t.new_pair_code()
        self.assertIn("Paired", t.handle(msg(f"/pair {code}")))
        self.assertIn("wrong or expired", t.handle(msg(f"/pair {code}", 99)))   # single use
        self.assertEqual(t.handle(msg("/tasks")), "• buy milk")
        self.assertEqual(t.handle(msg("hello robot")), "echo hello robot")
        self.assertIn("Send /help", t.handle(msg("/nope")))
        self.assertEqual(Telegram(t.path, {}, token="x").chats, [42])
        t.error = None
        self.assertNotIn("SECRET", json.dumps(t.status()))
        self.assertEqual(t._scrub("https://api.telegram.org/bot123:SECRET/getMe failed"), "https://api.telegram.org/bot***/getMe failed")

    def test_photo_upload_is_multipart(self):
        t = self.make()
        t.chats = [42]
        t.send_photo(b"\xff\xd8jpeg", "Someone is here")
        url, body = self.net.requests[-1]
        self.assertTrue(url.endswith("/sendPhoto"))
        self.assertIn(b'name="photo"; filename="desk.jpg"', body)
        self.assertIn(b"\xff\xd8jpeg", body)
        self.assertTrue(t.broadcast("hi"))
        t.enabled = lambda: False
        self.assertFalse(t.broadcast("hi"))


class SettingsTest(unittest.TestCase):
    def test_protected_and_public(self):
        s = FullSettings(tmp() / "full.json")
        with self.assertRaises(PermissionError):
            s.update({"guard": {"passphrase": "open sesame"}})
        pub = s.update({"guard": {"passphrase": "open sesame"}}, allow_protected=True)
        self.assertIs(pub["guard"]["passphrase"], True)                 # never sent to the browser
        self.assertEqual(FullSettings(s.path).section("guard")["passphrase"], "open sesame")
        for bad in ({"hydration": {"goal": 99}}, {"briefing": {"morning_time": "8am"}}, {"reader": {"ocr": "magic"}}):
            with self.assertRaises(ValueError):
                s.update(bad)


if __name__ == "__main__":
    unittest.main()
