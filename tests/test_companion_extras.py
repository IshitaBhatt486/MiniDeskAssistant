"""Dances, voice styles, greeting, curiosity near objects, the health report and the digital twin's files."""

import math
import random
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import deskbot
from deskbot.assistant.commands import DANCES, Executor
from deskbot.assistant.settings import validate
from deskbot.assistant.voice import VOICE_STYLES, apply_style, process, write_wav
from deskbot.companion import config
from deskbot.companion.emotion import EmotionEngine
from deskbot.companion.greeter import Greeter
from deskbot.companion.health_check import Report, _guarded
from deskbot.companion.shared import CompanionShared
from deskbot.vision.detector import Detection
from tests.test_companion import FakeRobot, motor, sensors


def person(area=0.2, score=0.9, label="person"):
    side = math.sqrt(area * 320 * 240)
    return Detection(label, score, (0, 0, side, side), 1)


class TestDances(unittest.TestCase):
    def test_every_dance_ends_about_where_it_started(self):
        self.assertGreaterEqual(len(DANCES), 4)
        for name, steps in DANCES.items():
            t = Counter()
            for move, seconds in steps:
                t[move] += seconds
            self.assertAlmostEqual(t["forward"], t["backward"], msg=name)
            self.assertAlmostEqual(t["left"], t["right"], msg=name)

    def test_random_choice_runs_every_step_and_never_repeats_twice(self):
        robot = SimpleNamespace(log=lambda *a: None)
        ex = Executor(SimpleNamespace(robot=robot), None, lambda *a, **k: None)
        ex.rng = random.Random(3)
        moves = []
        ex._move = lambda gen, d, s: moves.append((d, s))
        seen, last = set(), None
        real_sleep = time.sleep
        time.sleep = lambda s: None
        try:
            for _ in range(40):
                moves.clear()
                self.assertIsNone(ex._dance(ex._gen))
                self.assertNotEqual(ex.last_dance, last)
                last = ex.last_dance
                seen.add(last)
                self.assertEqual(moves, [m for m in DANCES[last] if m[0] != "pause"])
        finally:
            time.sleep = real_sleep
        self.assertEqual(seen, set(DANCES))


class TestVoices(unittest.TestCase):
    def setUp(self):
        self.rate = 16000
        t = np.arange(self.rate) / self.rate
        self.x = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    def test_every_style_produces_audio(self):
        wav = write_wav(self.x, self.rate)
        for style in VOICE_STYLES:
            self.assertGreater(len(process(wav, 1.6, 0.9, style)), 1000, style)

    def test_styles_do_what_their_names_say(self):
        self.assertLess(len(apply_style(self.x, self.rate, "chipmunk", 1.6)), len(self.x))
        self.assertGreater(len(apply_style(self.x, self.rate, "deep")), len(self.x))
        self.assertGreater(len(apply_style(self.x, self.rate, "cave")), len(self.x))
        self.assertIs(apply_style(self.x, self.rate, "natural"), self.x)
        self.assertFalse(np.allclose(apply_style(self.x, self.rate, "robot"), self.x))

    def test_settings_are_validated(self):
        self.assertEqual(validate({"voice_style": "robot", "voice_gender": "female"}),
                         {"voice_style": "robot", "voice_gender": "female"})
        with self.assertRaises(ValueError):
            validate({"voice_style": "opera"})
        with self.assertRaises(ValueError):
            validate({"voice_gender": "x"})


class TestGreeter(unittest.TestCase):
    def setUp(self):
        self.said, self.reactions = [], []
        self.app = SimpleNamespace(presence=None, lift=SimpleNamespace(lifted=False),
                                   speaker=SimpleNamespace(say=lambda text, kind: self.said.append(text)),
                                   emotion=SimpleNamespace(react=lambda *a, **k: self.reactions.append(a[0])),
                                   robot=SimpleNamespace(log=lambda *a: None))
        self.g = Greeter(config.GreetConfig(), self.app, 320 * 240, random.Random(1))

    def show(self, people, start, seconds=1.2):
        t = start
        while t < start + seconds:
            self.g.step(t, [person() for _ in range(people)])
            t += 0.1
        return t

    def test_greets_once_when_a_person_stays_in_view(self):
        self.show(1, 100, 3)
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.reactions, ["happy"])

    def test_detector_flicker_does_not_greet(self):
        self.show(1, 100, 0.5)
        self.show(0, 100.5, 0.5)
        self.assertEqual(self.said, [])

    def test_second_person_is_greeted_after_the_cooldown(self):
        t = self.show(1, 100)
        self.show(2, t + 31)
        self.assertEqual(len(self.said), 2)

    def test_returning_after_a_long_absence_counts_as_new(self):
        t = self.show(1, 100)
        t = self.show(0, t, 50)
        self.show(1, t)
        self.assertEqual(len(self.said), 2)

    def test_short_absence_is_not_a_new_person(self):
        t = self.show(1, 100)
        t = self.show(0, t, 5)
        self.show(1, t)
        self.assertEqual(len(self.said), 1)

    def test_silent_while_asleep_or_carried(self):
        self.app.lift.lifted = True
        self.show(1, 100)
        self.assertEqual(self.said, [])


class TestCuriousNearObjects(unittest.TestCase):
    def setUp(self):
        self.s = CompanionShared()
        self.robot = FakeRobot(self.s)
        motor(self.s, state="idle", left=0.0, right=0.0)
        self.vision = SimpleNamespace(latest=lambda: self.res)
        self.res = None
        self.app = SimpleNamespace(robot=self.robot, lift=SimpleNamespace(lifted=False), presence=None, behaviour=None,
                                   vision=self.vision, image_size=(320, 240), assistant=SimpleNamespace(status=lambda: {"log": []}))
        self.e = EmotionEngine(self.s, config.EmotionConfig(), self.app)

    def test_sonar_nearby_makes_it_curious_with_hysteresis(self):
        now = time.monotonic()
        sensors(self.s, front=0.25)
        self.e.step(now)
        self.assertEqual(self.e.emotion, "curious")
        sensors(self.s, front=0.33)
        self.e.step(now)
        self.assertEqual(self.e.emotion, "curious")
        sensors(self.s, front=0.5)
        self.e.step(now)
        self.assertEqual(self.e.emotion, "neutral")

    def test_a_large_recognised_object_counts_and_a_person_does_not(self):
        sensors(self.s)
        self.res = SimpleNamespace(detections=[person(0.2, label="cup")])
        self.e.step(time.monotonic())
        self.assertEqual(self.e.emotion, "curious")
        self.res = SimpleNamespace(detections=[person(0.2)])
        self.e.step(time.monotonic())
        self.assertEqual(self.e.emotion, "neutral")

    def test_being_carried_still_wins(self):
        sensors(self.s, front=0.2)
        self.app.lift.lifted = True
        self.e.step(time.monotonic())
        self.assertEqual(self.e.emotion, "scared")


class TestHealthReport(unittest.TestCase):
    def test_verdict_score_and_files(self):
        r = Report(live=False)
        r.start("Area")
        r.add("a", "pass", "ok")
        r.add("b", "skip", "n/a")
        self.assertEqual((r.verdict, r.score), ("HEALTHY", 100))
        r.add("c", "warn", "hm", "fix it")
        self.assertEqual((r.verdict, r.score, r.healthy), ("WORKING, WITH WARNINGS", 75, True))
        r.add("d", "fail", "no")
        self.assertEqual(r.verdict, "NEEDS ATTENTION")
        self.assertFalse(r.healthy)
        with tempfile.TemporaryDirectory() as d:
            r.save(Path(d))
            self.assertIn("NEEDS ATTENTION", (Path(d) / "report.md").read_text(encoding="utf-8"))
            self.assertTrue((Path(d) / "report.json").exists())

    def test_a_crashing_check_is_reported_and_does_not_stop_the_run(self):
        def broken(report):
            raise RuntimeError("boom")
        r = Report(live=False)
        r.start("Area")
        self.assertIsNone(_guarded(r, broken))
        self.assertEqual(r.checks[0].status, "fail")
        self.assertIn("boom", r.checks[0].detail)


class TestDigitalTwinFiles(unittest.TestCase):
    def test_every_function_file_matches_its_name_and_calls_exist(self):
        folder = deskbot.ROOT.parent / "digital_twin"
        files = {p.stem: p.read_text(encoding="utf-8") for p in folder.glob("*.m")}
        self.assertIn("run_twin", files)
        for stem, text in files.items():
            if stem != "run_twin":
                self.assertRegex(text.splitlines()[0], rf"^function .*\b{stem}\b", stem)
        import re
        called = {m for text in files.values() for m in re.findall(r"\b(twin_\w+)\(", text)}
        self.assertLessEqual(called, set(files))


if __name__ == "__main__":
    unittest.main()
