"""Fixes ported to run_prototype from legacy/simplified_code.py (24 Nov 2026). See docs/simplified-code.md and
docs/run-prototype-fixes.md. Each test fails on the code before the fix."""

import math
import threading
import time
import unittest
from datetime import datetime

import deskbot  # noqa: F401  (puts dashboard/ on sys.path)
from deskbot.assistant.brain import OfflineBrain
from deskbot.assistant.stt import SttError, Transcriber
from deskbot.buddy.when import parse_due, say_due
from deskbot.config import AppConfig, object_depth, object_radius


class TestTimeWords(unittest.TestCase):
    NOW = datetime(2026, 11, 24, 10, 0)

    def test_bare_hour_followed_by_words(self):
        self.assertEqual(parse_due("at 9 call dad", self.NOW), (datetime(2026, 11, 24, 21, 0), "call dad"))
        self.assertEqual(parse_due("tomorrow at 9 stand-up", self.NOW), (datetime(2026, 11, 25, 9, 0), "stand-up"))

    def test_bare_hour_still_rejects_durations(self):
        due, _ = parse_due("in 9 minutes", self.NOW)
        self.assertEqual(due, datetime(2026, 11, 24, 10, 9))

    def test_relative_time_reads_back_right(self):
        now = datetime(2026, 11, 24, 10, 0, 40)          # 40 s into the minute
        due, title = parse_due("in 2 minutes stretch", now)
        self.assertEqual(say_due(due, now), "in 2 minutes")
        self.assertEqual(title, "stretch")


class TestOfflineBrainOnlyMovesOnCommands(unittest.TestCase):
    def actions(self, text):
        return [c["action"] for c in OfflineBrain().think(text, "", [])["commands"]]

    def test_conversation_does_not_move(self):
        for text in ("that's right", "what's on my left?", "I'll be back", "what's ahead?", "what is a spin bowler",
                     "is it right that the forward pass is illegal"):
            self.assertEqual(self.actions(text), [], text)

    def test_commands_still_move(self):
        cases = {"turn left": "turn_left", "hey pip, turn right 30": "turn_right", "go back 2 seconds": "move_backward",
                 "forward": "move_forward", "keep looking at me": "follow_user_on", "do a little dance": "dance",
                 "turn left and go forward": "turn_left"}
        for text, action in cases.items():
            self.assertEqual(self.actions(text)[:1], [action], text)

    def test_stop_still_works_anywhere(self):
        self.assertEqual(self.actions("whoa whoa please stop now"), ["stop"])


class FakeBackend:
    def __init__(self, text):
        self.text = text

    def available(self):
        return True

    def transcribe(self, wav, timeout=None):
        return self.text


def wav(seconds=1.0):
    import io
    import wave

    import numpy as np
    x = (np.sin(np.arange(int(16000 * seconds)) / 5) * 8000).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(x.tobytes())
    return buf.getvalue()


class TestWhisperInventions(unittest.TestCase):
    def stt(self, text):
        s = Transcriber.__new__(Transcriber)
        s.settings, s.alerts, s.last = {"stt": "auto"}, None, None
        s.backends = {"local": FakeBackend(text)}
        s.order = lambda: ["local"]
        return s

    def test_thank_you_on_silence_is_rejected(self):
        for text in ("Thank you.", " thanks for watching! ", "you"):
            with self.assertRaises(SttError) as cm:
                self.stt(text).transcribe(wav())
            self.assertIn("didn't catch that", str(cm.exception))

    def test_real_speech_passes(self):
        self.assertEqual(self.stt("turn left please").transcribe(wav()), "turn left please")


class TestObjectDepth(unittest.TestCase):
    def test_long_thin_things_use_their_depth(self):
        self.assertLess(object_depth("keyboard"), object_radius("keyboard"))
        self.assertEqual(object_depth("cup"), object_radius("cup"))


class TestEdgeCutBoxesAreNotPlaced(unittest.TestCase):
    def test_edge_cut_box_is_a_sighting_but_not_a_landmark(self):
        from deskbot.mapping.fusion import FusionMapper
        from deskbot.robot import make_robot
        from deskbot.vision.detector import Detection
        from deskbot.vision.pipeline import VisionResult

        cfg = AppConfig()
        robot, _ = make_robot(sim=True)
        try:
            m = FusionMapper(robot, cfg, None)
            w, h = cfg.camera.width, cfg.camera.height
            now = time.monotonic()
            cut = Detection("cup", 0.9, (0.0, h * 0.4, w * 0.2, h * 0.7), None)        # touches the left edge
            m._integrate_frame(VisionResult(1, now, now, [cut], 1.0), {"distances": {}})
            self.assertEqual(len(m.sem.objects), 0, "an edge-cut box must not be placed")
            whole = Detection("cup", 0.9, (w * 0.4, h * 0.4, w * 0.6, h * 0.7), None)
            m._integrate_frame(VisionResult(2, now, now, [whole], 1.0), {"distances": {}})
            self.assertEqual(len(m.sem.objects), 1)
        finally:
            robot.close()


class TestFocusIgnoresFarFaces(unittest.TestCase):
    def test_only_a_near_face_is_the_person_working(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        import numpy as np

        from deskbot.hub.focus import Focus

        far = [100, 50, 8, 9] + [0] * 11            # 72 px of a 320 x 240 picture: someone across the room
        near = [120, 60, 70, 80] + [0] * 11

        class Analyzer:
            rows = []

            def ready(self):
                return True

            def faces(self, image):
                return self.rows

        class Vision:
            def latest(self):
                return SimpleNamespace(detections=[])

            def frame_image(self, res):
                return np.zeros((240, 320, 3), np.uint8)

        a = Analyzer()
        f = Focus(Path(tempfile.mkdtemp()) / "focus.json", vision=Vision(), analyzer=a)
        a.rows = [far]
        self.assertIsNone(f.observe()[1])
        a.rows = [near, far]
        self.assertEqual(f.observe()[1], near)


def _has_gpiozero():
    import importlib.util
    return importlib.util.find_spec("gpiozero") is not None


@unittest.skipUnless(_has_gpiozero(), "gpiozero not installed (it is on the Pi; pip install gpiozero to run here)")
class TestSonarScanner(unittest.TestCase):
    """The scanner pings one sonar at a time; gpiozero's mock trigger pins play the echo."""

    def test_reads_each_sonar_in_turn(self):
        from gpiozero import Device
        from gpiozero.pins.mock import MockFactory, MockTriggerPin

        import gpiozero.pins.mock as mock

        from deskbot.runtime.sonar_scanner import SPEED_OF_SOUND, SonarScanner

        # the mock timestamps edges with time.monotonic, which ticks every 15.6 ms on Windows: a 1.7 ms echo would
        # read 0. lgpio on the Pi timestamps to the microsecond; perf_counter stands in for it here.
        old_clock, mock.monotonic = mock.monotonic, time.perf_counter
        old = Device.pin_factory
        Device.pin_factory = f = MockFactory()
        f.ticks = staticmethod(time.perf_counter)
        try:
            sonars = {"front": {"trigger": 24, "echo": 25}, "left": {"trigger": 4, "echo": 18}}
            want = {"front": 0.30, "left": 0.80}
            class ExactTrigger(MockTriggerPin):
                """Like gpiozero's, but the echo's falling edge is stamped at exactly rise + echo_time (a
                time.sleep-timed edge overshoots by a varying ~0.5-2 ms on Windows, i.e. 8-35 cm)."""
                def _echo(self):
                    time.sleep(0.001)
                    self.echo_pin.drive_high()
                    rise = self.echo_pin._last_change
                    time.sleep(self.echo_time)
                    real, mock.monotonic = mock.monotonic, (lambda: rise + self.echo_time)
                    try:
                        self.echo_pin.drive_low()
                    finally:
                        mock.monotonic = real

            for name, p in sonars.items():
                echo = f.pin(p["echo"])
                f.pin(p["trigger"], pin_class=ExactTrigger, echo_pin=echo, echo_time=want[name] * 2 / SPEED_OF_SOUND)
            sc = SonarScanner(sonars, max_distance=2.0, log=lambda *a: None)
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and any(sc.latest(n) is None for n in sonars):
                    time.sleep(0.05)
                for name in sonars:
                    self.assertIsNotNone(sc.latest(name), name)
                    self.assertAlmostEqual(sc.latest(name), want[name], delta=0.02, msg=name)
                while time.monotonic() < deadline and sc.sweeps == 0:   # the first sweep finishes after its last ping
                    time.sleep(0.02)
                self.assertGreater(sc.sweeps, 0)
            finally:
                sc.close()
        finally:
            Device.pin_factory = old
            mock.monotonic = old_clock

    def test_silent_sonar_reads_none_not_all_clear(self):
        from gpiozero import Device
        from gpiozero.pins.mock import MockFactory

        from deskbot.runtime.sonar_scanner import SonarScanner

        old = Device.pin_factory
        Device.pin_factory = MockFactory()
        try:
            sc = SonarScanner({"left": {"trigger": 4, "echo": 18}}, max_distance=2.0, log=lambda *a: None)
            try:
                time.sleep(0.4)
                self.assertIsNone(sc.latest("left"))
                self.assertIn("no echo", sc.reason("left"))
            finally:
                sc.close()
        finally:
            Device.pin_factory = old


if __name__ == "__main__":
    unittest.main()
