"""Assistant + presence logic (17 Nov 2026). No hardware, no network, no API key needed."""

import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant import brain as brain_mod
from deskbot.assistant.alerts import Alerts
from deskbot.assistant.brain import Brain, ClaudeBrain, OfflineBrain
from deskbot.assistant.commands import ACTIONS, RESPONSE_SCHEMA, normalise
from deskbot.assistant.settings import Settings, validate
from deskbot.assistant.stt import SttError, Transcriber, wav_info
from deskbot.assistant.voice import chipmunk, process, read_wav, write_wav
from deskbot.presence.ble import PhoneTracker, ibeacon_uuid, rssi_to_m
from deskbot.presence.lift import LiftDetector
from deskbot.presence.manager import Presence


def tone(freq=300, seconds=1.0, rate=16000, amp=0.3):
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32), rate


def tmp_settings():
    d = tempfile.mkdtemp()
    return Settings(Path(d) / "assistant.json")


class SettingsTest(unittest.TestCase):
    def test_defaults_update_persist(self):
        s = tmp_settings()
        self.assertEqual(s.get("model"), "claude-haiku-5-5")
        s.update({"location": "  Delhi ", "chipmunk_factor": 1.8, "unknown": 1, "ble": {"near_rssi": -60}})
        s2 = Settings(s.path)
        self.assertEqual(s2.get("location"), "Delhi")
        self.assertEqual(s2.get("chipmunk_factor"), 1.8)
        self.assertEqual(s2.get("ble")["near_rssi"], -60)
        self.assertEqual(s2.get("ble")["away_rssi"], -85)   # nested defaults kept

    def test_rejects_bad_values(self):
        for bad in ({"volume": 2}, {"chipmunk_factor": 9}, {"model": "gpt-x"}, {"personality": ""},
                    {"ble": {"near_rssi": 5}}, {"stt": "magic"}):
            with self.assertRaises(ValueError, msg=bad):
                validate(bad)

    def test_corrupt_file_falls_back(self):
        d = Path(tempfile.mkdtemp()) / "a.json"
        d.write_text("{not json")
        warned = []
        s = Settings(d, on_warning=warned.append)
        self.assertEqual(s.get("speak"), True)
        self.assertTrue(warned)


class CommandsTest(unittest.TestCase):
    def test_normalise_clamps_and_filters(self):
        clean, problems = normalise([{"action": "move_forward", "amount": 60}, {"action": "turn_left", "amount": 0},
                                     {"action": "rm -rf"}, {"action": "stop", "amount": 5}])
        self.assertEqual(clean[0], {"action": "move_forward", "amount": 3.0})   # 60 s -> 3 s max
        self.assertEqual(clean[1]["amount"], 90)                                  # 0 -> default
        self.assertEqual(clean[2], {"action": "stop", "amount": 0.0})
        self.assertEqual(len(problems), 1)

    def test_max_commands(self):
        clean, problems = normalise([{"action": "stop", "amount": 0}] * 9)
        self.assertEqual(len(clean), 5)
        self.assertTrue(problems)

    def test_schema_matches_actions(self):
        enum = RESPONSE_SCHEMA["properties"]["commands"]["items"]["properties"]["action"]["enum"]
        self.assertEqual(set(enum), set(ACTIONS))
        self.assertFalse(RESPONSE_SCHEMA["additionalProperties"])


class AlertsTest(unittest.TestCase):
    def test_dedupe_cooldown_resolve(self):
        spoken = []
        a = Alerts(log=lambda *_: None)
        a.subscribe(lambda al: spoken.append(al["msg"]))
        a.warn("cam", "Camera broke")
        a.warn("cam", "Camera broke")            # repeat: not logged or spoken again
        self.assertEqual(spoken, ["Camera broke"])
        self.assertTrue(a.is_active("cam"))
        a.resolve("cam", "Camera back")
        self.assertFalse(a.is_active("cam"))
        self.assertEqual(spoken[-1], "Camera back")
        self.assertFalse(a.resolve("cam", "again"))   # not active -> nothing said

    def test_global_gap(self):
        spoken = []
        a = Alerts(log=lambda *_: None)
        a.subscribe(lambda al: spoken.append(al["key"]))
        a.warn("a", "x")
        a.warn("b", "y")                         # within SPEAK_GLOBAL_GAP_S -> listed but not spoken
        self.assertEqual(spoken, ["a"])
        self.assertEqual(len(a.snapshot()["active"]), 2)

    def test_guard_and_call(self):
        a = Alerts(log=lambda *_: None)
        with a.guard("w", "weather failed", speak=False):
            raise RuntimeError("boom")
        self.assertTrue(a.is_active("w"))
        self.assertEqual(a.call("x", lambda: 1 / 0, fallback=7, speak=False), 7)


class VoiceTest(unittest.TestCase):
    def test_chipmunk_pitch_and_length(self):
        x, rate = tone(300, 1.0)
        y = chipmunk(x, 1.6)
        self.assertAlmostEqual(len(y) / len(x), 1 / 1.6, places=2)
        spec = np.abs(np.fft.rfft(y))
        peak_hz = np.argmax(spec) * rate / len(y)
        self.assertAlmostEqual(peak_hz, 480, delta=5)     # 300 Hz x 1.6

    def test_process_roundtrip_volume(self):
        x, rate = tone(440, 0.5, amp=0.05)
        out, r2 = read_wav(process(write_wav(x, rate), 1.0, 0.5))
        self.assertEqual(r2, rate)
        self.assertAlmostEqual(float(np.max(np.abs(out))), 0.475, delta=0.01)  # normalised to 0.95, x0.5


class SttTest(unittest.TestCase):
    def test_rejects_silence_and_short(self):
        s = tmp_settings()
        t = Transcriber(s)
        silent = write_wav(np.zeros(16000, np.float32), 16000)
        with self.assertRaises(SttError):
            t.transcribe(silent)
        short = write_wav(tone(300, 0.1)[0], 16000)
        with self.assertRaises(SttError):
            t.transcribe(short)
        self.assertAlmostEqual(wav_info(write_wav(*tone(300, 2.0)))[0], 2.0, places=2)

    def test_fallback_order(self):
        s = tmp_settings()
        t = Transcriber(s)
        calls = []

        class Fake:
            def __init__(self, name, ok):
                self.name, self.ok = name, ok

            def available(self):
                return True

            def transcribe(self, wav, timeout=None):
                calls.append(self.name)
                if not self.ok:
                    raise RuntimeError("down")
                return "hello robot"
        t.settings.update({"stt": "auto"})
        t.backends = {"local": Fake("local", False), "groq": Fake("groq", True), "openai": Fake("openai", True)}
        self.assertEqual(t.transcribe(write_wav(*tone(300, 1.0))), "hello robot")
        self.assertEqual(calls, ["local", "groq"])        # free and offline first, then the next one

    def test_local_setting_never_falls_back_to_the_cloud(self):
        s = tmp_settings()
        self.assertEqual(s.get("stt"), "local")
        t = Transcriber(s)
        t.backends = {n: SimpleNamespace(available=lambda: True) for n in ("local", "groq", "openai")}
        self.assertEqual(t.order(), ["local"])
        t.backends["local"] = SimpleNamespace(available=lambda: False)
        self.assertEqual(t.order(), [])


# ---------------- brain ----------------

def block(**kw):
    return SimpleNamespace(**kw)


class FakeClient:
    """Scripted beta.messages.create: first a tool call, then the final JSON."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.requests.append(dict(kw, messages=list(kw["messages"])))   # snapshot: the loop appends later
        return self.script.pop(0)


def usage():
    return block(input_tokens=100, output_tokens=20, cache_read_input_tokens=80)


class BrainTest(unittest.TestCase):
    def test_claude_tool_loop_and_schema(self):
        s = tmp_settings()
        cb = ClaudeBrain(s)
        if cb._anthropic is None:
            self.skipTest("anthropic SDK not importable here")
        final = json.dumps({"speech": "It's ten past ten.", "mood": "happy",
                            "commands": [{"action": "spin", "amount": 1}]})
        client = FakeClient([
            block(stop_reason="tool_use", usage=usage(),
                  content=[block(type="tool_use", id="tu_1", name="get_time", input={})]),
            block(stop_reason="end_turn", usage=usage(), content=[block(type="text", text=final)]),
        ])
        cb._client = client
        out = cb.think("what time is it", "ctx", [], image_jpeg=b"\xff\xd8jpeg", tool_ctx={})
        self.assertEqual(out["speech"], "It's ten past ten.")
        self.assertEqual(out["tools"][0]["name"], "get_time")
        self.assertFalse(out["tools"][0]["error"])
        first, second = client.requests
        self.assertEqual(first["model"], "claude-haiku-5-5")
        self.assertNotIn("fallbacks", first)                  # Haiku has no server-side refusal fallback
        self.assertNotIn("betas", first)
        self.assertEqual(first["output_config"]["format"]["schema"], RESPONSE_SCHEMA)
        self.assertEqual(first["output_config"]["effort"], "low")
        self.assertEqual(first["messages"][-1]["content"][0]["type"], "image")
        # second request: assistant tool_use turn + ONE user message with the tool result
        self.assertEqual(second["messages"][-1]["content"][0]["tool_use_id"], "tu_1")
        self.assertEqual(out["usage"]["cache_read"], 160)

    def test_refusal(self):
        s = tmp_settings()
        cb = ClaudeBrain(s)
        if cb._anthropic is None:
            self.skipTest("anthropic SDK not importable here")
        cb._client = FakeClient([block(stop_reason="refusal", usage=usage(), content=[])])
        self.assertIn("can't help", cb.think("x", "ctx", [])["speech"])

    def test_api_failure_falls_back_to_offline(self):
        s = tmp_settings()
        spoken = []
        alerts = Alerts(log=lambda *_: None)
        alerts.subscribe(lambda al: spoken.append(al["msg"]))
        b = Brain(s, alerts)
        b.claude.available = lambda: True

        def boom(*a, **k):
            raise ConnectionError("no network")
        b.claude.think = boom
        out = b.think("please could we turn right 30 degrees", "ctx")      # not a plain command: goes to the AI first
        self.assertEqual(out["backend"], "offline")
        self.assertEqual(out["commands"], [{"action": "turn_right", "amount": 30.0}])
        self.assertTrue(alerts.is_active("ai"))

    def test_plain_commands_never_call_the_api(self):
        b = Brain(tmp_settings(), Alerts(log=lambda *_: None))
        b.claude.available = lambda: True
        b.claude.think = lambda *a, **k: self.fail("the API was called")
        out = b.think("turn right 30 degrees", "ctx")
        self.assertEqual(out["backend"], "local")
        self.assertEqual(out["commands"], [{"action": "turn_right", "amount": 30.0}])

    def test_offline_intents(self):
        o = OfflineBrain()
        cases = {"please stop": "stop", "spin around twice": "spin", "come here": "move_forward",
                 "go back 2 seconds": "move_backward", "find my phone": "find_phone", "good night": "sleep",
                 "forget the map": "reset_map", "do a little dance": "dance"}
        for text, action in cases.items():
            cmds = o.think(text, "", [])["commands"]
            self.assertEqual(cmds[0]["action"], action, text)
        self.assertEqual(o.think("spin around two times", "", [])["commands"][0]["amount"], 2)

    def test_system_prompt_has_personality_and_actions(self):
        p = brain_mod.system_prompt("You are a pirate.")
        self.assertIn("You are a pirate.", p)
        for a in ACTIONS:
            self.assertIn(a, p)


# ---------------- presence ----------------

class TrackerTest(unittest.TestCase):
    def test_near_away_hysteresis(self):
        s = tmp_settings()
        changes = []
        tr = PhoneTracker(s, on_change=lambda o, n: changes.append(n))
        t = 1000.0
        tr._born = t
        for i in range(30):                 # 3 s of strong signal
            tr.add(-55, t + i * 0.1)
        self.assertEqual(tr.state, "near")
        for i in range(30, 80):             # in-between signal: hysteresis, stays near
            tr.add(-75, t + i * 0.1)
        self.assertEqual(tr.state, "near")
        tr.update(t + 8 + 26)               # silence > away_timeout_s (25 s)
        self.assertEqual(tr.state, "away")
        self.assertEqual(changes, ["near", "away"])

    def test_helpers(self):
        self.assertAlmostEqual(rssi_to_m(-59), 1.0, places=2)
        data = {0x004C: bytes([0x02, 0x15]) + bytes(range(16)) + bytes([0, 1, 0, 2, 0xC5])}
        self.assertEqual(ibeacon_uuid(data), "00010203-0405-0607-0809-0a0b0c0d0e0f")

    def test_best_heading_circular(self):
        r = [-80] * 12
        r[11], r[0], r[1] = -60, -58, -61     # best around index 0, wrapping
        idx, spread = Presence.best_heading(r)
        self.assertEqual(idx, 0)
        self.assertGreater(spread, 10)
        self.assertEqual(Presence.best_heading([None] * 12), (None, 0.0))


class FakeRobot:
    def __init__(self):
        self.reading = {"front_floor": True, "back_floor": True, "t": 1.0}
        self.stops = 0

    def latest_reading(self):
        return dict(self.reading)

    def stop(self, source="user"):
        self.stops += 1

    def log(self, *a):
        pass


class FakeMapper:
    def __init__(self):
        self.paused = False
        self.resets = 0

    def reset(self):
        self.resets += 1


class LiftTest(unittest.TestCase):
    def test_lift_pause_and_reset(self):
        robot, mapper = FakeRobot(), FakeMapper()
        said = []
        lift = LiftDetector(robot, mapper, Alerts(log=lambda *_: None), lambda t, k=None: said.append(t))
        t = 0.0
        lift.step(t)
        robot.reading.update(front_floor=False)            # one sensor over an edge: NOT a lift
        for i in range(20):
            lift.step(t + i * 0.05)
        self.assertFalse(lift.lifted)
        robot.reading.update(front_floor=False, back_floor=False)
        for i in range(20, 40):
            lift.step(t + i * 0.05)
        self.assertTrue(lift.lifted)
        self.assertTrue(mapper.paused)
        self.assertGreaterEqual(robot.stops, 1)
        robot.reading.update(front_floor=True, back_floor=True)
        for i in range(40, 80):
            lift.step(t + i * 0.05)
        self.assertFalse(lift.lifted)
        self.assertFalse(mapper.paused)
        self.assertEqual(mapper.resets, 1)
        self.assertEqual(len(said), 2)


if __name__ == "__main__":
    unittest.main()
