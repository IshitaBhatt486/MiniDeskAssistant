"""Simulation test console (20 Nov 2026): tools/sim_console.py and the Windows speech-to-text backend.
No hardware or server needed; the Windows round trip (TTS -> WAV -> recogniser) only runs on Windows."""

import importlib.util
import io
import math
import os
import struct
import unittest
import wave
from pathlib import Path
from unittest import mock

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant import stt

_spec = importlib.util.spec_from_file_location("sim_console", Path(__file__).resolve().parents[1] / "tools" / "sim_console.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


def make_wav(rate, channels, seconds=0.5, freq=440.0, amp=10000):
    n = int(rate * seconds)
    frames = b"".join(struct.pack("<" + "h" * channels, *([int(amp * math.sin(2 * math.pi * freq * i / rate))] * channels))
                      for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


class FakeApi:
    def __init__(self):
        self.log, self.posts, self.last_move = [], [], {}

    def get(self, path, **kw):
        return 200, {"assistant": {"log": self.log, "phase": "idle"}, "executor": {"last": self.last_move}}

    def post(self, path, body=None, **kw):
        self.posts.append((path, body, kw))
        if path == "/api/assistant/text":
            self.log.append({"id": len(self.log) + 1, "user": body["text"], "source": "sim console",
                             "speech": "Turning left.", "mood": "neutral", "backend": "local", "ms": 3,
                             "commands": [{"action": "turn_left", "amount": 90}]})
        return 200, {"ok": True}


class TestAudio(unittest.TestCase):
    def test_48k_stereo_becomes_16k_mono(self):
        out = sc.to_16k_mono(make_wav(48000, 2, seconds=0.5))
        info = stt.wav_info(out)
        with wave.open(io.BytesIO(out)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (16000, 1, 2))
            self.assertAlmostEqual(w.getnframes(), 8000, delta=1)
        self.assertAlmostEqual(info[0], 0.5, places=2)
        self.assertGreater(info[1], -12)          # a 440 Hz tone survives the box filter almost unchanged

    def test_44k1_and_passthrough(self):
        out = sc.to_16k_mono(make_wav(44100, 1, seconds=1.0))
        with wave.open(io.BytesIO(out)) as w:
            self.assertAlmostEqual(w.getnframes(), 16000, delta=2)
        already = make_wav(16000, 1)
        self.assertIs(sc.to_16k_mono(already), already)

    def test_rejects_8_bit(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(1); w.setframerate(11025); w.writeframes(b"\x80" * 100)
        with self.assertRaises(RuntimeError):
            sc.to_16k_mono(buf.getvalue())


class TestConsole(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.con = sc.Console(self.api, "full")

    def test_split(self):
        self.assertEqual(sc.split_commands("turn left; :lift on"), ["turn left", " :lift on"])
        self.assertEqual(sc.split_commands(':post /api/x {"a": ";"}'), [':post /api/x {"a": ";"}'])

    def test_text_reply_and_expectations(self):
        self.con.run_line("turn left; expect left|right; expect move turn_left; expect banana; expect move spin")
        self.assertEqual(self.api.posts[0][0], "/api/assistant/text")
        self.assertEqual(self.con.last_reply, "Turning left.")
        self.assertEqual([w for w, _ in self.con.failures], ["banana", "move spin"])

    def test_commands_go_to_the_right_routes(self):
        with mock.patch.object(sc.Console, "drain"):
            self.con.run_line(":lift on; :phone off; :stuck left; :gesture thumb up; :do turn_left 45; :wake hi; "
                              ":notify Mum: call me")
        paths = [(p, b) for p, b, _ in self.api.posts]
        self.assertIn(("/api/sim/lift", {"lifted": True}), paths)
        self.assertIn(("/api/sim/phone", {"present": False}), paths)
        self.assertIn(("/api/sim/wheel", {"stuck": "left"}), paths)
        self.assertIn(("/api/sim/gesture", {"gesture": "Thumb_Up"}), paths)
        self.assertIn(("/api/assistant/commands", {"commands": [{"action": "turn_left", "amount": 45.0}],
                                                   "source": "sim console"}), paths)
        self.assertIn(("/api/full/wake", {"text": "hi"}), paths)
        self.assertIn(("/api/buddy/notifications/test", {"app": "Mum", "title": "Mum", "text": "call me"}), paths)

    def test_bad_input_does_not_crash(self):
        self.con.run_line(":lift maybe; :gesture wave; :nonsense")
        self.assertEqual(self.api.posts, [])

    def test_background_moves_are_reported(self):
        self.api.last_move = {"t": 5.0, "source": "gesture Thumb_Up", "commands": [{"action": "dance", "result": "ok"}]}
        self.con.drain()
        self.assertIn("dance", self.con.last_moves)

    def test_quit(self):
        self.assertEqual(self.con.run_line(":quit"), "quit")


class TestWindowsBackend(unittest.TestCase):
    def _transcriber(self, pref, windows):
        t = stt.Transcriber({"stt": pref})
        for name, b in t.backends.items():
            b.available = (lambda ok: (lambda: ok))(name == "windows" and windows)
        return t

    def test_order(self):
        self.assertEqual(self._transcriber("auto", True).order(), ["windows"])
        self.assertEqual(self._transcriber("local", True).order(), ["windows"])    # on-device, so strict local allows it
        self.assertEqual(self._transcriber("auto", False).order(), [])
        self.assertEqual(self._transcriber("none", True).order(), [])

    def test_setting_accepts_windows(self):
        from deskbot.assistant.settings import validate
        self.assertEqual(validate({"stt": "windows"}), {"stt": "windows"})
        with self.assertRaises(ValueError):
            validate({"stt": "dolphin"})

    @unittest.skipUnless(os.name == "nt", "Windows speech only exists on Windows")
    def test_round_trip(self):
        wav = sc.synth_wav("turn right")
        self.assertEqual(stt.wav_info(wav)[0] > 0.3, True)
        self.assertIn("right", stt.WindowsSpeech().transcribe(wav).lower())


if __name__ == "__main__":
    unittest.main()
