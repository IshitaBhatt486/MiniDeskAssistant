"""Sound effects, task list, reminders, celebrations and phone notifications (19 Nov 2026).
No hardware, no network, no API key needed."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant.alerts import Alerts
from deskbot.assistant.brain import Brain, ClaudeBrain, OfflineBrain, system_prompt
from deskbot.assistant.commands import ACTIONS, CELEBRATIONS, NUDGE, RESPONSE_SCHEMA, SOUNDS, normalise
from deskbot.assistant.motifs import RATE, motif_wav, synth
from deskbot.assistant.settings import Settings
from deskbot.buddy.config import BuddySettings, validate
from deskbot.buddy.core import Buddy, in_quiet_hours
from deskbot.buddy.notify import NotificationCenter, normalise_payload, score
from deskbot.buddy.tasks import TaskStore, local_intent, reminder_text, tool_handlers
from deskbot.buddy.when import parse_due, parse_iso_or_words, say_due

NOW = datetime(2026, 11, 19, 14, 5)      # a Thursday


def tmp():
    return Path(tempfile.mkdtemp())


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


# ---------------- sound effects ----------------

class SoundTest(unittest.TestCase):
    def test_schema_has_sound_and_every_sound_plays(self):
        self.assertIn("sound", RESPONSE_SCHEMA["required"])
        self.assertEqual(RESPONSE_SCHEMA["properties"]["sound"]["enum"], list(SOUNDS))
        self.assertIn("none", SOUNDS)
        for name in SOUNDS:
            if name == "none":
                continue
            x = synth(name)
            self.assertEqual(x.dtype, np.float32, name)
            self.assertTrue(0.05 < len(x) / RATE < 2.5, name)
            self.assertLessEqual(float(np.abs(x).max()), 0.86, name)
            self.assertGreater(float(np.abs(x).max()), 0.3, name)
            self.assertTrue(motif_wav(name).startswith(b"RIFF"), name)

    def test_prompt_lists_sounds(self):
        p = system_prompt("Pirate.", "TASK RULES")
        for name in SOUNDS:
            self.assertIn(f"- {name}:", p)
        self.assertIn("TASK RULES", p)

    def test_brain_cleans_unknown_sound_and_offline_sets_one(self):
        b = Brain(Settings(tmp() / "a.json"), Alerts(log=lambda *_: None))
        b.claude.available = lambda: True
        b.claude.think = lambda *a, **k: {"speech": "hi", "mood": "happy", "sound": "airhorn", "commands": [], "tools": []}
        self.assertEqual(b.think("tell me something", "ctx")["sound"], "none")
        self.assertEqual(OfflineBrain().think("spin around", "", [])["sound"], "whoosh")
        self.assertEqual(b.history[-1]["sound"], "none")

    def test_turn_plays_sound_before_speech(self):
        from deskbot.assistant.core import Assistant
        events = []
        speaker = SimpleNamespace(chime=lambda n: events.append(("chime", n)), say=lambda t, k="reply": events.append(("say", t)))
        brain = SimpleNamespace(think=lambda *a, **k: {"speech": "Ba dum.", "mood": "happy", "sound": "rimshot", "commands": []})
        robot = SimpleNamespace(latest_reading=lambda: {"distances": {}}, snapshot=lambda: {"state": "idle"}, speed=0.5)
        sv = SimpleNamespace(robot=robot, vision=None, mapper=None, presence=None, lift=None, cam=None)
        settings = Settings(tmp() / "a.json")
        a = Assistant(sv, settings, Alerts(log=lambda *_: None), speaker, None, brain, None)
        entry = a.handle_text("tell me a pun")
        self.assertEqual(events, [("chime", "rimshot"), ("say", "Ba dum.")])
        self.assertEqual(entry["sound"], "rimshot")


# ---------------- deadlines in words ----------------

class WhenTest(unittest.TestCase):
    def test_parse(self):
        cases = {
            "submit the report by 5pm tomorrow": (datetime(2026, 11, 20, 17, 0), "submit the report"),
            "call mom in 20 minutes": (datetime(2026, 11, 19, 14, 25), "call mom"),
            "finish slides by friday": (datetime(2026, 11, 20, 17, 0), "finish slides"),
            "dentist on monday at 9 am": (datetime(2026, 11, 23, 9, 0), "dentist"),
            "water plants tonight": (datetime(2026, 11, 19, 20, 0), "water plants"),
            "email prof by end of day": (datetime(2026, 11, 19, 18, 0), "email prof"),
            "book tickets at 9": (datetime(2026, 11, 19, 21, 0), "book tickets"),        # 9 am already passed
            "read chapter 3 tomorrow morning": (datetime(2026, 11, 20, 9, 0), "read chapter 3"),
            "buy 2 apples": (None, "buy 2 apples"),                                       # a number is not a time
            "pay rent next thursday at 9": (datetime(2026, 11, 26, 9, 0), "pay rent"),
        }
        for text, want in cases.items():
            self.assertEqual(parse_due(text, NOW), want, text)

    def test_iso_and_spoken(self):
        self.assertEqual(parse_iso_or_words("2026-11-20T17:00", NOW), datetime(2026, 11, 20, 17, 0))
        self.assertEqual(parse_iso_or_words("2026-11-21", NOW), datetime(2026, 11, 21, 17, 0))
        self.assertIsNone(parse_iso_or_words("", NOW))
        self.assertEqual(parse_iso_or_words("tomorrow at 8 am", NOW), datetime(2026, 11, 20, 8, 0))
        with self.assertRaises(ValueError):
            parse_iso_or_words("whenever", NOW)
        self.assertEqual(say_due(datetime(2026, 11, 19, 14, 25), NOW), "in 20 minutes")
        self.assertEqual(say_due(datetime(2026, 11, 20, 17, 30), NOW), "tomorrow at 5:30 PM")
        self.assertEqual(say_due(datetime(2026, 11, 23, 9, 0), NOW), "on Monday at 9 AM")


# ---------------- tasks ----------------

class TaskStoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.path = tmp() / "tasks.json"
        self.s = TaskStore(self.path, clock=self.clock)
        self.events = []
        self.s.listeners.append(lambda e, t, src: self.events.append((e, t["title"], src)))

    def test_add_find_complete_persist(self):
        self.s.add("Submit the physics report", NOW + timedelta(hours=3))
        self.s.add("buy milk")
        self.s.add("call the bank about the card")
        self.assertEqual(self.s.get("physics").get("title"), "Submit the physics report")
        self.assertEqual(self.s.get("#2")["title"], "buy milk")
        done = self.s.complete("the report", source="voice")
        self.assertTrue(done["done"])
        self.assertIn(("completed", "Submit the physics report", "voice"), self.events)
        again = TaskStore(self.path, clock=self.clock)
        self.assertEqual([t["title"] for t in again.open_tasks()], ["buy milk", "call the bank about the card"])
        self.assertEqual(again.add("x")["id"], 4)                       # ids keep counting after a restart

    def test_duplicate_updates_deadline_and_ambiguous_asks(self):
        self.s.add("call mom")
        t = self.s.add("Call mom", NOW + timedelta(hours=1))
        self.assertEqual(len(self.s.open_tasks()), 1)
        self.assertIsNotNone(t["due"])
        self.s.add("call dad")
        with self.assertRaises(LookupError) as cm:
            self.s.find("call")
        self.assertIn("could be", str(cm.exception))
        with self.assertRaises(LookupError):
            self.s.find("feed the dragon")

    def test_reminders(self):
        self.s.add("submit report", NOW + timedelta(minutes=60))
        self.s.add("call mom", NOW + timedelta(minutes=5))            # added too late for its "soon" reminder
        kinds = lambda: [(t["title"], k) for t, k in self.s.reminders_due(self.clock(), 15, 60)]  # noqa: E731
        self.assertEqual(kinds(), [])
        self.clock.t = NOW + timedelta(minutes=6)
        self.assertEqual(kinds(), [("call mom", "due")])
        self.s.mark_reminded(2, "due")
        self.clock.t = NOW + timedelta(minutes=46)
        self.assertEqual(kinds(), [("submit report", "soon")])
        self.s.mark_reminded(1, "soon")
        self.clock.t = NOW + timedelta(minutes=66)
        self.assertEqual(kinds(), [("submit report", "due"), ("call mom", "overdue")])
        self.s.update(1, due=NOW + timedelta(days=1))                 # a new deadline gets new reminders
        self.assertEqual(self.s.get(1)["reminded"], [])
        task = self.s.get(2)
        self.assertIn("ago", reminder_text(task, "overdue", self.clock(), 15))

    def test_corrupt_file_is_kept_aside(self):
        p = tmp() / "tasks.json"
        p.write_text("{broken")
        s = TaskStore(p)
        self.assertIsNotNone(s.load_error)
        self.assertTrue(p.with_suffix(".corrupt.json").exists())
        self.assertEqual(s.open_tasks(), [])

    def test_ai_tools(self):
        tools = tool_handlers(self.s)
        text, err = tools["add_task"]({"title": "finish slides", "due": "2026-11-20T10:00"})
        self.assertFalse(err)
        self.assertEqual(json.loads(text)["added"]["due_spoken"], "tomorrow at 10 AM")
        tools["add_task"]({"title": "finish essay", "due": ""})
        text, err = tools["complete_task"]({"task": "finish"})
        self.assertTrue(err)                                         # two "finish" tasks: ask which
        text, err = tools["complete_task"]({"task": "slides"})
        self.assertFalse(err)
        self.assertFalse(json.loads(text)["all_done"])
        _, err = tools["update_task"]({"task": "essay", "title": "", "due": "tomorrow at 9 am"})
        self.assertFalse(err)
        listed = json.loads(tools["list_tasks"]({})[0])
        self.assertEqual(listed["open"][0]["title"], "finish essay")
        self.assertEqual(listed["done_today"], ["finish slides"])

    def test_local_intents(self):
        r = local_intent("Remind me to call the bank at 4", self.s, NOW)
        self.assertIn("call the bank", r["speech"])
        self.assertEqual(self.s.open_tasks()[0]["due"], "2026-11-19T16:00:00")
        local_intent("add buy milk to my list", self.s, NOW)
        self.assertIn("2 things", local_intent("what's on my list?", self.s, NOW)["speech"])
        r = local_intent("I finished calling the bank", self.s, NOW)
        self.assertEqual(r["mood"], "excited")
        self.assertIsNone(local_intent("what's the weather", self.s, NOW))

    def test_context_lines(self):
        self.s.add("submit report", NOW - timedelta(minutes=30))
        self.s.add("buy milk")
        lines = self.s.summary_lines(NOW)
        self.assertIn("OVERDUE", lines[0])
        self.assertIn("buy milk (no deadline)", lines[0])


# ---------------- notifications ----------------

PREFS = {"use_ai": True, "read_text": True, "vip": ["Mom"], "keywords": ["exam"], "important_apps": [], "muted_apps": ["Swiggy"]}


class NotifyTest(unittest.TestCase):
    def center(self, ai=None, prefs=None):
        return NotificationCenter(lambda: dict(PREFS, **(prefs or {})), ai, clock=lambda: 1000.0)

    def test_payload_aliases(self):
        n = normalise_payload({"app_name": "WhatsApp", "sender": "Mom", "message": "hi", "priority": "high"})
        self.assertEqual((n["app"], n["title"], n["text"], n["priority"]), ("WhatsApp", "Mom", "hi", 1))
        with self.assertRaises(ValueError):
            normalise_payload({"app": "x"})

    def test_rules(self):
        s = lambda **kw: score(normalise_payload(kw), PREFS)[0]  # noqa: E731
        self.assertIsNone(s(app="Messages", title="BANK", text="482913 is your OTP"))
        self.assertGreaterEqual(s(app="WhatsApp", title="Mom", text="hi"), 3)              # VIP
        self.assertGreaterEqual(s(app="Telegram", title="Arjun", text="call me asap"), 3)    # urgent
        self.assertLessEqual(s(app="Myntra", title="Sale", text="70% off today"), 0)         # promo
        self.assertEqual(s(app="Swiggy", title="Order", text="Your food is here"), -10)      # muted
        self.assertEqual(s(app="Telegram", title="Arjun", text="see you at 6?"), 2)          # a maybe

    def test_triage_paths(self):
        c = self.center()
        otp = c.receive({"app": "Messages", "title": "BANK", "text": "Your verification code is 1234"}, sync=True)
        e = c.history[-1]
        self.assertEqual(e["status"], "blocked")
        self.assertEqual((e["title"], e["text"]), ("(hidden)", ""))                       # never kept
        self.assertEqual(otp["status"], "blocked")
        c.receive({"app": "WhatsApp", "title": "Mom", "text": "Dinner is ready"}, sync=True)
        self.assertEqual(c.history[-1]["status"], "waiting")
        self.assertIn("Mom on WhatsApp", c.history[-1]["speech"])
        dup = c.receive({"app": "WhatsApp", "title": "Mom", "text": "Dinner is ready"}, sync=True)
        self.assertEqual(dup["status"], "duplicate")
        c.receive({"app": "Instagram", "title": "x", "text": "liked your photo"}, sync=True)
        self.assertEqual(c.history[-1]["status"], "skipped")
        self.assertEqual(len(c.take()), 1)

    def test_maybe_goes_to_the_ai_and_never_with_secrets(self):
        seen = []

        def ai(n, prefs):
            seen.append(n["text"])
            return {"important": "6" in n["text"], "reason": "plans", "speech": "Arjun asks if you're still meeting at six."}
        c = self.center(ai)
        c.receive({"app": "Telegram", "title": "Arjun", "text": "still on for 6?"}, sync=True)
        self.assertEqual(c.history[-1]["decided_by"], "ai")
        self.assertEqual(c.history[-1]["speech"], "Arjun asks if you're still meeting at six.")
        c.receive({"app": "Telegram", "title": "Arjun", "text": "lol"}, sync=True)
        self.assertEqual(c.history[-1]["status"], "skipped")
        c.receive({"app": "Telegram", "title": "Arjun", "text": "the wifi password is hunter2"}, sync=True)
        self.assertNotIn("the wifi password is hunter2", seen)

        def broken(n, prefs):
            raise ConnectionError("offline")
        c2 = self.center(broken)
        c2.receive({"app": "Telegram", "title": "Arjun", "text": "still on for 6?"}, sync=True)
        self.assertEqual(c2.history[-1]["status"], "waiting")                       # score 2 without the AI
        self.assertEqual(c2.history[-1]["decided_by"], "rules (no AI)")

    def test_settings_validation(self):
        self.assertEqual(validate({"notify": {"vip": "Mom, Dad"}})["notify"]["vip"], ["Mom", "Dad"])
        for bad in ({"notify": {"quiet_start": "25:00"}}, {"tasks": {"remind_before_min": -1}}):
            with self.assertRaises(ValueError):
                validate(bad)
        s = BuddySettings(tmp() / "b.json")
        s.update({"tasks": {"remind_before_min": 5}})
        self.assertEqual(BuddySettings(s.path).section("tasks")["remind_before_min"], 5)
        self.assertTrue(in_quiet_hours(datetime(2026, 1, 1, 23, 0), "22:00", "07:00"))
        self.assertTrue(in_quiet_hours(datetime(2026, 1, 1, 6, 59), "22:00", "07:00"))
        self.assertFalse(in_quiet_hours(datetime(2026, 1, 1, 7, 0), "22:00", "07:00"))
        self.assertTrue(in_quiet_hours(datetime(2026, 1, 1, 13, 0), "12:00", "14:00"))


# ---------------- the buddy: reactions ----------------

class FakeExecutor:
    def __init__(self):
        self.runs, self.hooks, self.current = [], [], None

    def on_command(self, fn):
        self.hooks.append(fn)

    def run(self, commands, source="ai"):
        self.runs.append(([c["action"] for c in commands], source))
        for c in commands:
            for h in self.hooks:
                h(c)
        return commands, []


class BuddyTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.said, self.chimes, self.emotions = [], [], []
        self.presence = SimpleNamespace(awake=True)
        brain = Brain(Settings(tmp() / "a.json"), Alerts(log=lambda *_: None))
        self.app = SimpleNamespace(
            speaker=SimpleNamespace(say=lambda t, k="reply": self.said.append(t), chime=self.chimes.append),
            executor=FakeExecutor(), presence=self.presence, lift=SimpleNamespace(lifted=False),
            assistant=SimpleNamespace(phase="idle", context_hooks=[]), brain=brain,
            emotion=SimpleNamespace(react=lambda e, s=None, why="": self.emotions.append(e)))
        self.settings = BuddySettings(tmp() / "b.json")
        self.store = TaskStore(tmp() / "t.json", clock=self.clock)
        self.center = NotificationCenter(lambda: self.settings.section("notify"), None, clock=lambda: 0.0)
        self.b = Buddy(self.app, self.settings, self.store, self.center, clock=self.clock)
        self.b.last_said = -1e9

    def test_wires_into_the_assistant(self):
        self.assertIn("add_task", self.app.brain.claude.extra_tools)
        self.assertIn("Task list", self.app.brain.claude.extra_prompt)
        self.store.add("buy milk")
        self.assertTrue(any("buy milk" in line for hook in self.app.assistant.context_hooks for line in hook()))

    def test_completing_a_task_celebrates(self):
        self.store.add("submit report")
        self.store.add("buy milk")
        self.store.complete("report", source="dashboard")
        self.assertEqual(self.chimes, ["fanfare"])
        self.assertIn("celebrating", self.emotions)
        self.assertEqual(self.app.executor.runs[-1], (["celebrate"], "tasks"))
        self.assertTrue(any("Nice work" in s for s in self.said))       # the dashboard doesn't speak by itself
        self.said.clear()
        self.store.complete("milk", source="ai")                         # last one: a bigger party, the AI speaks
        self.assertEqual(self.app.executor.runs[-1], (["celebrate", "spin"], "tasks"))
        self.assertEqual(self.said, [])
        self.assertTrue(self.b.last_celebration["all_done"])

    def test_no_moving_while_lifted_or_asleep(self):
        self.store.add("a")
        self.app.lift.lifted = True
        self.store.complete("a", source="dashboard")
        self.assertEqual(self.app.executor.runs, [])
        self.assertEqual(self.chimes, ["fanfare"])                      # still the sound and the eyes

    def test_reminders_wait_for_the_owner(self):
        self.store.add("call mom", NOW + timedelta(minutes=30))
        self.clock.t = NOW + timedelta(minutes=31)
        self.presence.awake = False
        self.b.tick()
        self.assertEqual(self.said, [])
        self.presence.awake = True
        self.b.tick()
        self.assertEqual(self.chimes, ["reminder"])
        self.assertIn("call mom is due now", self.said[0])
        self.assertEqual(self.app.executor.runs[-1], (["nudge"], "reminder"))
        self.b.last_said = -1e9
        self.b.tick()
        self.assertEqual(len(self.said), 1)                              # said once
        self.assertEqual(self.store.get(1)["reminded"], ["soon", "due"])

    def test_notifications_held_then_summarised(self):
        self.settings.update({"notify": {"quiet_start": "", "quiet_end": ""}})
        self.presence.awake = False
        for who in ("Mom", "Dad", "Priya", "Arjun"):
            self.center.receive({"app": "WhatsApp", "title": who, "text": "urgent, call me"}, sync=True)
        self.b.tick()
        self.assertEqual(self.said, [])
        self.presence.awake = True
        self.b.tick()
        self.assertEqual(self.said[0], "You have 4 important notifications.")
        self.assertEqual(len(self.said), 5)                               # summary + 3 + "and 1 more"
        self.assertTrue(all(e["status"] == "spoken" for e in self.center.history))

    def test_quiet_hours_hold_notifications(self):
        self.settings.update({"notify": {"quiet_start": "13:00", "quiet_end": "15:00"}})
        self.center.receive({"app": "WhatsApp", "title": "Mom", "text": "hello"}, sync=True)
        self.b.tick()
        self.assertEqual(self.said, [])
        self.clock.t = NOW.replace(hour=15, minute=1)
        self.b.tick()
        self.assertEqual(len(self.said), 1)


# ---------------- robot side ----------------

class RobotSideTest(unittest.TestCase):
    def test_new_actions(self):
        self.assertIn("celebrate", ACTIONS)
        self.assertIn("nudge", ACTIONS)
        clean, problems = normalise([{"action": "celebrate", "amount": 7}, {"action": "nudge"}])
        self.assertEqual(clean, [{"action": "celebrate", "amount": 0.0}, {"action": "nudge", "amount": 0.0}])
        for steps in [*CELEBRATIONS.values(), NUDGE]:                 # every routine ends where it started
            turn = sum(v if m == "left" else -v for m, v in steps if m in ("left", "right"))
            drive = sum(v if m == "forward" else -v for m, v in steps if m in ("forward", "backward"))
            self.assertEqual(turn % 360, 0)
            self.assertAlmostEqual(drive, 0.0)

    def test_celebrating_eyes(self):
        from PIL import Image, ImageDraw

        from deskbot.companion.animations import ANIMATIONS, EMOTIONS
        from deskbot.companion.eyes import draw_face
        self.assertEqual(EMOTIONS[-1], "celebrating")
        self.assertEqual(len(ANIMATIONS["celebrating"]), 5)
        im = Image.new("1", (128, 64))
        draw_face(ImageDraw.Draw(im), {"w": 32.0, "h": 34.0, "r": 9.0, "open": 0.0, "left": 1.0, "right": 1.0, "dx": 0.0,
                                       "dy": 0.0, "lid_in": 0.0, "lid_out": 0.0, "lid": 0.0, "cheek": 0.0, "spread": 0.0,
                                       "look": 1.0}, "confetti", 128, 64, 1.0)
        self.assertGreater(sum(im.getdata()) / 255, 10)                   # confetti pieces drawn


class ClaudeTaskTool(unittest.TestCase):
    def test_extra_tool_in_the_loop(self):
        cb = ClaudeBrain(Settings(tmp() / "a.json"))
        if cb._anthropic is None:
            self.skipTest("anthropic SDK not importable here")
        store = TaskStore(tmp() / "t.json", clock=Clock())
        b = SimpleNamespace(claude=cb)
        Brain.add_tool(b, {"name": "add_task", "description": "x", "input_schema": {"type": "object"}},
                       tool_handlers(store)["add_task"])
        blk = lambda **kw: SimpleNamespace(**kw)  # noqa: E731
        u = blk(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)
        script = [blk(stop_reason="tool_use", usage=u, content=[blk(type="tool_use", id="t1", name="add_task",
                                                                   input={"title": "buy milk", "due": ""})]),
                  blk(stop_reason="end_turn", usage=u, content=[blk(type="text", text=json.dumps(
                      {"speech": "Added!", "mood": "happy", "sound": "ding", "commands": []}))])]
        requests = []
        cb._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
            create=lambda **kw: (requests.append(kw), script.pop(0))[1])))
        out = cb.think("remind me to buy milk", "ctx", [])
        self.assertEqual(out["sound"], "ding")
        self.assertEqual(store.open_tasks()[0]["title"], "buy milk")
        self.assertIn("add_task", [t["name"] for t in requests[0]["tools"]])
        self.assertTrue(requests[0]["tools"][-1]["strict"])


if __name__ == "__main__":
    unittest.main()
