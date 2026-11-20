"""Pro runtime (20 Nov 2026): touch pads, MPU-6050 events, Groq brain + fallback order, voice pitch/speed,
profiles, accounts/APIs, the pro page and the pin table. No hardware, network or keys needed."""

import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant import voice
from deskbot.assistant.alerts import Alerts
from deskbot.assistant.brain import Brain
from deskbot.assistant.settings import Settings, validate
from deskbot.pro import apis as apis_mod
from deskbot.pro.config import ProSettings
from deskbot.pro.config import validate as pro_validate
from deskbot.pro.core import Pro
from deskbot.pro.groq_brain import GroqBrain, GroqError, extract_json, to_openai_tools
from deskbot.pro.motion import G, MotionDetector, MotionSense
from deskbot.pro.profiles import Profiles
from deskbot.pro.touch import TouchSense


def tmp():
    return Path(tempfile.mkdtemp())


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


# ---------------- touch ----------------

class TouchTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {"enabled": True, "mode": "momentary", "hold_s": 1.2, "pats_for_excited": 3, "cooldown_s": 2.0}
        self.clock = Clock()
        self.got = []
        self.t = TouchSense({"top": 7, "left": 8, "right": 14}, lambda: self.cfg, lambda k, p, i: self.got.append((k, p)),
                            log=lambda m: None, use_gpio=False, clock=self.clock)

    def tap(self, pad, held=0.2, gap=0.3):
        self.t.press(pad)
        self.clock.t += held
        self.t.tick()
        out = self.t.release(pad)
        self.clock.t += gap
        return out

    def test_pat_and_instant_touch(self):
        self.assertEqual(self.t.press("top"), ["touch"])
        self.clock.t += 0.2
        self.assertEqual(self.t.release("top"), ["pat"])
        self.assertEqual(self.t.status()["today"]["pats"], 1)
        self.assertEqual(self.t.status()["counts"]["top"], 1)

    def test_hold_reported_while_held_once(self):
        self.t.press("left")
        self.clock.t += 0.5
        self.assertEqual(self.t.tick(), [])
        self.clock.t += 1.0
        self.assertEqual(self.t.tick(), ["hold"])
        self.clock.t += 1.0
        self.assertEqual(self.t.tick(), [])          # once
        self.assertEqual(self.t.release("left"), [])  # a hold is not also a pat

    def test_pat_streak(self):
        self.assertEqual(self.tap("top"), ["pat"])
        self.assertEqual(self.tap("top"), ["pat"])
        self.assertEqual(self.tap("left"), ["pats"])
        self.assertEqual(self.tap("top"), ["pat"])    # the streak starts over

    def test_streak_window(self):
        self.tap("top", gap=3.0)
        self.tap("top", gap=3.0)
        self.assertEqual(self.tap("top"), ["pat"])    # > 4 s from the first

    def test_stroke(self):
        self.t.press("left"); self.clock.t += 0.1; self.t.release("left"); self.clock.t += 0.2
        self.t.press("top"); self.clock.t += 0.1; self.t.release("top"); self.clock.t += 0.2
        self.assertIn("stroke", self.t.press("right"))
        self.assertEqual([e["direction"] for e in self.t.status()["events"] if e["kind"] == "stroke"], ["left to right"])

    def test_slow_sequence_is_not_a_stroke(self):
        for pad in ("left", "top"):
            self.t.press(pad); self.clock.t += 0.1; self.t.release(pad); self.clock.t += 1.0
        self.assertNotIn("stroke", self.t.press("right"))

    def test_toggle_mode_counts_every_flip(self):
        self.cfg["mode"] = "toggle"
        self.t._edge("top", True)
        self.t._edge("top", False)
        self.assertEqual([k for k, _ in self.got].count("touch"), 2)

    def test_disabled_and_unknown(self):
        self.cfg["enabled"] = False
        self.assertEqual(self.t.press("top"), [])
        self.cfg["enabled"] = True
        self.assertEqual(self.t.press("nose"), [])
        with self.assertRaises(ValueError):
            self.t.simulate("nose")

    def test_reaction_errors_do_not_break_reading(self):
        t = TouchSense({"top": 7}, lambda: self.cfg, lambda *a: 1 / 0, log=lambda m: None, use_gpio=False, clock=self.clock)
        self.assertEqual(t.press("top"), ["touch"])


# ---------------- motion ----------------

def sample(**kw):
    s = {"ax": 0.0, "ay": 0.0, "az": G, "gx": 0.0, "gy": 0.0, "gz": 0.0, "gyro_norm": 0.0, "tilt": 0.0}
    s.update(kw)
    return s


class MotionTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {"enabled": True, "knock": True, "shake": True, "bump": True, "tip": True, "drop": True,
                    "knock_ms2": 4.0, "bump_ms2": 5.0, "shake_rads": 4.0, "tip_deg": 60.0}
        self.d = MotionDetector(lambda: self.cfg)

    def run_seq(self, seq, t0=10.0, **kw):
        out = []
        for dt, s in seq:
            out += [k for k, _ in self.d.update(s, t0 + dt, **kw)]
        return out

    def test_knock_and_double_knock(self):
        knock = [(0.0, sample(az=G + 6)), (0.02, sample(az=G + 7)), (0.05, sample())]
        self.assertEqual(self.run_seq(knock), ["knock"])
        self.assertEqual(self.run_seq(knock, t0=10.3), ["double_knock"])

    def test_long_push_is_not_a_knock(self):
        push = [(i * 0.02, sample(az=G + 6)) for i in range(10)] + [(0.2, sample())]
        self.assertEqual(self.run_seq(push), [])

    def test_no_knock_while_driving_or_lifted(self):
        knock = [(0.0, sample(az=G + 6)), (0.05, sample())]
        self.assertEqual(self.run_seq(knock, driving=True), [])
        self.assertEqual(self.run_seq(knock, t0=20, lifted=True), [])

    def test_bump_only_while_driving(self):
        self.assertEqual(self.run_seq([(0, sample(ax=-9.0))]), [])
        self.assertEqual(self.run_seq([(0, sample(ax=-9.0))], t0=12, driving=True), ["bump"])
        self.assertEqual(self.run_seq([(0, sample(ax=-9.0))], t0=12.5, driving=True), [])   # cool-down

    def test_shake(self):
        seq = [(i * 0.12, sample(gz=7.0 if i % 2 else -7.0, gyro_norm=7.0)) for i in range(6)]
        self.assertEqual(self.run_seq(seq), ["shake"])

    def test_slow_turning_is_not_a_shake(self):
        seq = [(i * 0.12, sample(gz=2.0, gyro_norm=2.0)) for i in range(20)]
        self.assertEqual(self.run_seq(seq), [])

    def test_tipped_then_righted(self):
        import math
        tipped = [(i * 0.1, sample(tilt=math.radians(80))) for i in range(10)]
        self.assertEqual(self.run_seq(tipped), ["tipped"])
        self.assertTrue(self.d.tipped)
        level = [(i * 0.1, sample()) for i in range(12)]
        self.assertEqual(self.run_seq(level, t0=12), ["righted"])

    def test_carried_at_an_angle_is_not_tipped(self):
        import math
        moving = [(i * 0.1, sample(tilt=math.radians(80), gyro_norm=1.5)) for i in range(20)]
        self.assertEqual(self.run_seq(moving), [])

    def test_drop(self):
        seq = [(i * 0.02, sample(az=0.5)) for i in range(6)]
        self.assertEqual(self.run_seq(seq), ["drop"])

    def test_switches(self):
        self.cfg["knock"] = False
        self.assertEqual(self.run_seq([(0.0, sample(az=G + 6)), (0.05, sample())]), [])
        self.cfg["enabled"] = False
        self.assertEqual(self.run_seq([(0, sample(az=0.1))] * 5), [])

    def test_inject_every_event(self):
        got = []
        m = MotionSense(None, lambda: self.cfg, lambda k, i: got.append(k), driving=lambda: False, lifted=lambda: False)
        for ev in ("knock", "double_knock", "bump", "shake", "drop", "tipped", "righted"):
            self.assertIn(ev, m.inject(ev), ev)
        with self.assertRaises(ValueError):
            m.inject("cartwheel")
        self.assertEqual(m.status()["counts"]["bump"], 1)


# ---------------- Groq brain ----------------

class FakeGroq:
    def __init__(self, replies):
        self.replies, self.bodies = list(replies), []

    def key(self):
        return "gsk_test"

    def chat(self, body, timeout=None):
        self.bodies.append(json.loads(json.dumps(body)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def msg(content=None, tool_calls=None):
    return {"choices": [{"message": {"content": content, "tool_calls": tool_calls}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


REPLY = {"speech": "Turning left!", "mood": "happy", "sound": "none",
         "commands": [{"action": "turn_left", "amount": 90, "from_object": "", "to_object": ""}]}


class GroqTest(unittest.TestCase):
    def brain(self, replies, **section):
        s = Settings(tmp() / "a.json")
        sec = {"enabled": True, "model": "openai/gpt-oss-120b", "reasoning_effort": "low", **section}
        return GroqBrain(s, lambda: sec, claude=None, client=FakeGroq(replies))

    def test_plain_json_reply(self):
        g = self.brain([msg(json.dumps(REPLY))])
        out = g.think("spin left", "Time: now", [])
        self.assertEqual(out["speech"], "Turning left!")
        self.assertEqual(out["commands"][0]["action"], "turn_left")
        self.assertEqual(out["usage"]["input"], 100)
        body = g.client.bodies[0]
        self.assertEqual(body["model"], "openai/gpt-oss-120b")
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertIn("get_weather", [t["function"]["name"] for t in body["tools"]])
        self.assertIn("ONE JSON object", body["messages"][0]["content"])

    def test_tool_round(self):
        call = [{"id": "c1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]
        g = self.brain([msg("", call), msg("```json\n" + json.dumps(REPLY) + "\n```")])
        out = g.think("what time is it", "", [])
        self.assertEqual(out["tools"][0]["name"], "get_time")
        tool_msg = g.client.bodies[1]["messages"][-1]
        self.assertEqual((tool_msg["role"], tool_msg["tool_call_id"]), ("tool", "c1"))
        self.assertIn("local_time", tool_msg["content"])

    def test_repair_round_in_json_mode(self):
        g = self.brain([msg("Sure! I'll turn left now."), msg(json.dumps(REPLY))])
        out = g.think("turn left", "", [])
        self.assertEqual(out["speech"], "Turning left!")
        self.assertEqual(g.client.bodies[1]["response_format"], {"type": "json_object"})

    def test_unrepairable_reply_is_spoken_as_text(self):
        g = self.brain([msg("Hello there."), msg("still not json")])
        self.assertEqual(g.think("hi", "", [])["speech"], "Hello there.")

    def test_non_gpt_oss_model_has_no_reasoning_effort(self):
        g = self.brain([msg(json.dumps(REPLY))], model="llama-3.3-70b-versatile")
        g.think("hi", "", [])
        self.assertNotIn("reasoning_effort", g.client.bodies[0])

    def test_extract_json(self):
        self.assertEqual(extract_json('noise {"a": 1} more'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 2}\n```'), {"a": 2})
        self.assertIsNone(extract_json("no json"))
        self.assertIsNone(extract_json("[1, 2]"))

    def test_tools_convert(self):
        t = to_openai_tools([{"name": "x", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
        self.assertEqual(t[0]["type"], "function")
        self.assertEqual(t[0]["function"]["parameters"]["type"], "object")

    def test_available(self):
        g = self.brain([])
        self.assertTrue(g.available())
        g.enabled = lambda: False
        self.assertFalse(g.available())
        g2 = self.brain([], enabled=False)
        self.assertFalse(g2.available())
        self.assertIn("switched off", g2.why_unavailable())

    def test_classify_error(self):
        g = self.brain([])
        self.assertIn("key", g.classify_error(GroqError("x", 401)))
        self.assertIn("rate", g.classify_error(GroqError("x", 429)))
        self.assertIn("reach", g.classify_error(GroqError("x")))


class FakeClaude:
    name = "claude"

    def __init__(self, ok=True):
        self.ok, self.calls = ok, 0
        self.extra_tools, self.extra_prompt = {}, ""

    def available(self):
        return self.ok

    def why_unavailable(self):
        return "no key"

    def think(self, *a, **kw):
        self.calls += 1
        return {"speech": "Claude here.", "mood": "neutral", "sound": "none", "commands": [], "tools": [], "usage": None}

    def classify_error(self, exc):
        return "boom"


class BrainOrderTest(unittest.TestCase):
    def make(self, groq_replies, claude_ok=True):
        s = Settings(tmp() / "a.json")
        b = Brain(s, Alerts(log=lambda *_: None))
        b.claude = FakeClaude(claude_ok)
        g = GroqBrain(s, lambda: {"enabled": True, "model": "openai/gpt-oss-20b"}, client=FakeGroq(groq_replies))
        b.primary_brains.append(g)
        return b, g

    def test_groq_first(self):
        b, g = self.make([msg(json.dumps(REPLY))])
        out = b.think("tell me something nice", "ctx")
        self.assertEqual(out["backend"], "groq")
        self.assertEqual(b.claude.calls, 0)
        self.assertEqual(b.status()["order"], ["groq", "claude", "offline"])
        self.assertEqual(b.status()["model"], "openai/gpt-oss-20b")

    def test_claude_covers_a_groq_failure(self):
        b, g = self.make([GroqError("down", 503)])
        out = b.think("tell me something nice", "ctx")
        self.assertEqual(out["backend"], "claude")
        self.assertIsNone(out["error"])
        self.assertTrue(any(a["key"] == "ai-groq" for a in b.alerts.snapshot()["active"]))

    def test_offline_when_both_fail(self):
        b, g = self.make([GroqError("down", 503)], claude_ok=False)
        out = b.think("tell me something nice", "ctx")
        self.assertEqual(out["backend"], "offline")

    def test_image_turn_goes_to_claude(self):
        b, g = self.make([msg(json.dumps(REPLY))])
        out = b.think("what colour is my mug", "ctx", image_jpeg=b"\xff\xd8")
        self.assertEqual(out["backend"], "claude")
        self.assertEqual(g.client.bodies, [])

    def test_image_turn_without_claude_still_uses_groq(self):
        b, g = self.make([msg(json.dumps(REPLY))], claude_ok=False)
        self.assertEqual(b.think("what colour is my mug", "ctx", image_jpeg=b"\xff\xd8")["backend"], "groq")

    def test_local_commands_still_skip_the_cloud(self):
        b, g = self.make([])
        self.assertEqual(b.think("turn left", "ctx")["backend"], "local")


# ---------------- voice ----------------

class VoiceTest(unittest.TestCase):
    sr = 16000

    def tone(self, f=220.0, s=1.0):
        t = np.arange(int(self.sr * s)) / self.sr
        return (0.5 * np.sin(2 * np.pi * f * t)).astype(np.float32)

    def f0(self, y):
        spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        return np.fft.rfftfreq(len(y), 1 / self.sr)[np.argmax(spec)]

    def test_time_stretch_keeps_pitch(self):
        for speed in (0.5, 0.8, 1.25, 2.0):
            y = voice.time_stretch(self.tone(), self.sr, speed)
            self.assertAlmostEqual(len(y) / self.sr, 1 / speed, delta=0.01)
            self.assertAlmostEqual(self.f0(y), 220, delta=3)

    def test_pitch_shift_keeps_duration(self):
        for st in (-12, -5, 4, 12):
            y = voice.pitch_shift(self.tone(), self.sr, st)
            self.assertAlmostEqual(len(y) / self.sr, 1.0, delta=0.01)
            self.assertAlmostEqual(self.f0(y), 220 * 2 ** (st / 12), delta=4)

    def test_noop(self):
        x = self.tone()
        self.assertIs(voice.time_stretch(x, self.sr, 1.0), x)
        self.assertIs(voice.pitch_shift(x, self.sr, 0), x)

    def test_settings(self):
        self.assertEqual(validate({"voice_pitch": 3, "voice_speed": 1.5, "voice_name": " en-gb "}),
                         {"voice_pitch": 3.0, "voice_speed": 1.5, "voice_name": "en-gb"})
        for bad in ({"voice_pitch": 13}, {"voice_speed": 0.2}, {"voice_speed": 3}):
            with self.assertRaises(ValueError):
                validate(bad)

    def test_speaker_uses_native_speed_and_voice(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.sr)
            w.writeframes((self.tone() * 32767).astype("<i2").tobytes())

        class Tts:
            name, gender, speed, voice_name = "fake", "auto", 1.0, ""

            def synth(self, text):
                return buf.getvalue()

        s = Settings(tmp() / "a.json")
        s.update({"voice_speed": 1.5, "voice_name": "en-gb", "voice_style": "natural", "voice_pitch": 0})
        sp = voice.Speaker.__new__(voice.Speaker)
        sp.settings, sp.tts = s, Tts()
        out = sp.synth("hello")
        self.assertEqual((sp.tts.speed, sp.tts.voice_name), (1.5, "en-gb"))
        with wave.open(io.BytesIO(out)) as w:     # the engine did the speed: no second stretch
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 1.0, delta=0.02)


# ---------------- profiles ----------------

class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.s = Settings(tmp() / "a.json")
        self.p = Profiles(tmp() / "profiles.json", self.s)

    def test_builtins_and_apply(self):
        names = [x["name"] for x in self.p.status()["profiles"]]
        self.assertIn("Pirate", names)
        self.p.apply("pirate")
        self.assertEqual(self.s.get("voice_style"), "deep")
        self.assertIn("Captain Pip", self.s.get("personality"))
        self.assertEqual(self.p.status()["active"], "Pirate")

    def test_save_reload_delete(self):
        self.s.update({"voice_pitch": 5, "personality": "You are a robot DJ."})
        self.p.save("DJ Pip")
        p2 = Profiles(self.p.path, self.s)
        self.assertEqual(p2.all()["DJ Pip"]["voice_pitch"], 5.0)
        p2.delete("DJ Pip")
        self.assertNotIn("DJ Pip", p2.all())
        with self.assertRaises(LookupError):
            p2.delete("Pirate")

    def test_names_and_find(self):
        with self.assertRaises(ValueError):
            self.p.save("<script>")
        self.assertEqual(self.p.find("CALM BUTLER"), "Calm butler")
        self.assertEqual(self.p.find("butler"), "Calm butler")
        self.assertIsNone(self.p.find("focus"))
        with self.assertRaises(LookupError):
            self.p.apply("nobody")


class VoiceCommandTest(unittest.TestCase):
    def setUp(self):
        self.s = Settings(tmp() / "a.json")
        self.profiles = Profiles(tmp() / "p.json", self.s)
        self.pro = Pro.__new__(Pro)
        self.pro.profiles = self.profiles

    def test_switch_and_ask(self):
        for text, name in (("switch to the pirate profile", "Pirate"), ("use the calm butler personality", "Calm butler"),
                           ("please change to sarcastic sidekick mode", "Sarcastic sidekick")):
            out = self.pro.pre_handler(text, {})
            self.assertEqual(out["speech"], f"Switched to {name}.", text)
        self.assertIn("Sarcastic sidekick", self.pro.pre_handler("which profile are you using?", {})["speech"])

    def test_other_sentences_pass_through(self):
        for text in ("switch to focus mode", "turn left", "use a deeper voice", "what's the weather"):
            self.assertIsNone(self.pro.pre_handler(text, {}), text)


# ---------------- settings, accounts, page, pins ----------------

class ConfigTest(unittest.TestCase):
    def test_validate_and_persist(self):
        p = tmp() / "pro.json"
        s = ProSettings(p)
        s.update({"touch": {"hold_s": 2, "mode": "toggle"}, "groq": {"model": "openai/gpt-oss-20b"}, "nope": {"x": 1}})
        self.assertEqual(ProSettings(p).section("touch")["mode"], "toggle")
        for bad in ({"touch": {"hold_s": 99}}, {"touch": {"mode": "sticky"}}, {"groq": {"model": "a b;c"}}):
            with self.assertRaises(ValueError):
                pro_validate(bad)


class AccountsTest(unittest.TestCase):
    def test_masking(self):
        self.assertEqual(apis_mod.mask("gsk_abcdefghijklmnop1234", "key"), "gsk_…1234")
        self.assertEqual(apis_mod.mask("sk-ant-api03-XXXXXXXXXXXXa91f", "key"), "sk-…a91f")
        self.assertEqual(apis_mod.mask("123456", "secret"), "set")
        self.assertEqual(apis_mod.mask("http://192.168.1.5:8123/x?token=abc", "url"), "http://192.168.1.5:8123")
        self.assertIsNone(apis_mod.mask("", "key"))

    def test_accounts_never_leak_a_key(self):
        secret = "gsk_" + "Z" * 40 + "wxyz"
        app = SimpleNamespace()
        inv = apis_mod.ApiInventory(app, env={"GROQ_API_KEY": secret, "ADMIN_PIN": "4321"})
        dump = json.dumps(inv.accounts(), ensure_ascii=False)
        self.assertNotIn("Z" * 8, dump)
        self.assertNotIn("4321", dump)
        self.assertIn("gsk_…wxyz", dump)

    def test_in_use_and_tool_counts(self):
        s = Settings(tmp() / "a.json")
        app = SimpleNamespace(settings=s,
                              brain=SimpleNamespace(status=lambda: {"backend": "groq", "order": ["groq", "claude", "offline"]}),
                              stt=SimpleNamespace(status=lambda: {"available": ["groq"], "last": None}),
                              speaker=SimpleNamespace(status=lambda: {"engine": "espeak-ng", "player": "aplay", "spoken": 3}))
        g = SimpleNamespace(model=lambda: "openai/gpt-oss-120b")
        inv = apis_mod.ApiInventory(app, groq=g)
        inv.on_turn({"backend": "groq", "tools": [{"name": "get_weather"}]})
        rows = inv.in_use()["rows"]
        groq = next(r for r in rows if r["name"] == "Groq chat")
        self.assertEqual((groq["state"], groq["count"]), ("active", 1))
        self.assertEqual(next(r for r in rows if r["name"] == "Anthropic Claude")["state"], "fallback")
        self.assertEqual(next(r for r in rows if r["name"].startswith("Open-Meteo"))["count"], 1)


class PageAndPinsTest(unittest.TestCase):
    def test_page(self):
        from deskbot.pro.app import build_pro_index
        from deskbot.web.server import WEB_DIR
        page = build_pro_index().decode()
        for s in ("pro-voice-card", "pro-touch-card", "pro-motion-card", "pro-brain-card", "pro-apis-card",
                  "pro-accounts-card", "/static/layout.js", "/static/pro.css", "deskbot.theme"):
            self.assertIn(s, page)
        layout = (WEB_DIR / "layout.js").read_text(encoding="utf-8")
        import re
        defaults = re.search(r"DEFAULT_VISIBLE = \[(.*?)\];", layout, re.S).group(1)
        for key in re.findall(r'"([\w-]+)"', defaults):
            if not key.startswith("c-"):
                self.assertIn(f'id="{key}"', page, f"default card {key} isn't on the page")

    def test_touch_pins(self):
        import robot_config as rc
        self.assertEqual(rc.TOUCH, {"top": 7, "left": 8, "right": 14})
        rc.validate()
        self.assertIn(("touch pad right", 14), rc.all_pins())


if __name__ == "__main__":
    unittest.main()
