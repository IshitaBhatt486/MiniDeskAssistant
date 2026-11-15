"""Sensor conditioning, stuck wheels, adaptive detection, on-board colour answers (18 Nov 2026)."""

import unittest
from types import SimpleNamespace

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant.brain import local_vision_answer
from deskbot.config import EncoderConfig, VisionConfig
from deskbot.runtime.sensor_filter import SensorConditioner, fault_names
from deskbot.runtime.wheels import WheelMonitor, WheelWatch
from deskbot.vision.adaptive import AdaptiveInterval
from deskbot.vision.describe import dominant_colour

OK = {"front": 0.5, "left": 0.5, "right": 0.5, "rear": 0.5}


class SensorFilterTest(unittest.TestCase):
    def test_single_spike_is_ignored(self):
        f = SensorConditioner()
        for _ in range(5):
            f.update(OK, True, True)
        out, *_ = f.update({**OK, "front": 0.03}, True, True)
        self.assertAlmostEqual(out["front"], 0.5)
        f.update({**OK, "front": 0.03}, True, True)
        out, *_ = f.update({**OK, "front": 0.03}, True, True)
        self.assertAlmostEqual(out["front"], 0.03)                 # a real obstacle gets through quickly

    def test_ir_hysteresis_prefers_the_cautious_answer(self):
        f = SensorConditioner()
        f.update(OK, True, True)
        self.assertTrue(f.update(OK, False, True)[1])
        self.assertFalse(f.update(OK, False, True)[1])             # edge believed after 2 samples
        for _ in range(4):
            self.assertFalse(f.update(OK, True, True)[1])
        self.assertTrue(f.update(OK, True, True)[1])               # floor only after 5

    def test_flickering_sonar_reports_a_fault_and_reads_near(self):
        f = SensorConditioner()
        mask = 0
        for i in range(25):
            out, _, _, mask = f.update({**OK, "front": 0.1 if i % 2 else 1.5}, True, True)
        self.assertEqual(fault_names(mask), ["front"])
        self.assertAlmostEqual(out["front"], 0.1)
        for _ in range(60):                                         # the bounces must leave the window first
            _, _, _, mask = f.update(OK, True, True)
        self.assertEqual(mask, 0)

    def test_turning_past_an_object_is_not_a_fault(self):
        f = SensorConditioner()
        for d in [1.5] * 10 + [0.3] * 5 + [1.5] * 10:
            *_, mask = f.update({**OK, "front": d}, True, True)
        self.assertEqual(mask, 0)

    def test_dead_sonar_reads_zero(self):
        f = SensorConditioner()
        for _ in range(12):
            out, _, _, mask = f.update({**OK, "left": None}, True, True)
        self.assertEqual(out["left"], 0.0)
        self.assertEqual(fault_names(mask), ["left"])

    def test_flickering_ir_reads_no_floor(self):
        f = SensorConditioner()
        for i in range(12):
            _, ff, _, mask = f.update(OK, bool(i % 2), True)
        self.assertFalse(ff)
        self.assertEqual(fault_names(mask), ["front_floor"])


class WheelTest(unittest.TestCase):
    def run_wheels(self, counts_fn, seconds=1.5):
        m, out = WheelMonitor(), None
        for k in range(int(seconds * 10)):
            out = m.update(k / 10, 0.5, 0.5, counts_fn(k)) or out
        return out

    def test_healthy_wheels(self):
        self.assertIsNone(self.run_wheels(lambda k: (k * 5, k * 5)))

    def test_one_wheel_stops(self):
        self.assertEqual(self.run_wheels(lambda k: (min(k, 3) * 5, k * 5)), "left")

    def test_dead_encoder_is_not_called_a_stuck_wheel(self):
        self.assertIsNone(self.run_wheels(lambda k: (0, k * 5)))

    def test_says_it_once_and_stops(self):
        spoken, stops, seen = [], [], []
        robot = SimpleNamespace(stop=lambda source: stops.append(source), log=lambda *a: None)
        w = WheelWatch(robot, lambda text, kind: spoken.append(text))
        w.listeners.append(seen.append)
        self.assertTrue(w.report("left", 100.0))
        self.assertFalse(w.report("left", 101.0))
        self.assertEqual(spoken, ["Oops, looks like my wheel is stuck."])
        self.assertEqual((stops, seen), (["auto"], ["left"]))

    def test_encoder_scale(self):
        c = EncoderConfig(wheel_diameter_m=0.1, left_counts_per_rev=100, right_counts_per_rev=200)
        self.assertAlmostEqual(c.metres_per_count()[0], 0.0031416, places=6)


class AdaptiveTest(unittest.TestCase):
    def setUp(self):
        self.a = AdaptiveInterval(VisionConfig())
        self.img = np.full((240, 320, 3), 100, np.uint8)

    def settle(self, n, dets=0):
        for _ in range(n):
            self.a.should_detect(self.img, 99, dets)
            self.a.detected(self.img, dets)

    def test_backs_off_in_a_still_scene(self):
        self.settle(30)
        self.assertEqual(self.a.every, VisionConfig().detect_max_idle)
        self.settle(30, 2)
        self.assertEqual(self.a.every, VisionConfig().detect_max_tracking)
        self.assertFalse(self.a.should_detect(self.img, 2, 2))

    def test_something_new_is_detected_at_once(self):
        self.settle(30)
        changed = self.img.copy()
        changed[60:180, 80:240] = 230
        self.assertTrue(self.a.should_detect(changed, 1, 0))

    def test_losing_a_track_or_turning_is_immediate(self):
        self.settle(30, 2)
        self.assertTrue(self.a.should_detect(self.img, 1, 1))
        self.settle(30, 2)
        self.a.should_detect(self.img, 1, 2, moving=True, turning=True)
        self.assertEqual(self.a.every, VisionConfig().detect_min)


class LocalVisionTest(unittest.TestCase):
    def test_colours(self):
        for bgr, name in (((200, 60, 30), "blue"), ((30, 30, 210), "red"), ((40, 190, 40), "green"), ((30, 220, 230), "yellow"),
                          ((245, 245, 245), "white"), ((15, 15, 15), "black"), ((128, 128, 128), "grey")):
            img = np.zeros((100, 100, 3), np.uint8)
            img[20:80, 20:80] = bgr
            self.assertEqual(dominant_colour(img, (20, 20, 80, 80)), name, name)

    def test_answers_without_the_ai(self):
        items = [{"label": "cup", "colour": "blue", "area": 900}, {"label": "book", "colour": "purple", "area": 4000}]
        self.assertEqual(local_vision_answer("What colour is the mug?", items)["speech"], "The cup looks blue.")
        self.assertIn("blue cup", local_vision_answer("what do you see", items)["speech"])
        self.assertIn("purple book", local_vision_answer("what's this?", items)["speech"])
        self.assertIsNone(local_vision_answer("what colour is the giraffe", items))
        self.assertIsNone(local_vision_answer("why is the sky blue", items))
        self.assertIsNone(local_vision_answer("what do you see", []))


if __name__ == "__main__":
    unittest.main()
