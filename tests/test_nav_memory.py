"""Home, no-go zones, cost-saving routing, musical motifs and the tilt face (18 Nov 2026)."""

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant.brain import local_command, needs_image
from deskbot.assistant.motifs import MOTIFS, synth
from deskbot.config import NavigationConfig
from deskbot.navigation.costmap import Costmap, Target
from deskbot.navigation.memory import NavMemory
from deskbot.navigation.planners import route_ok
from desk_bench.scenes import add_object, blank
from deskbot.navigation.selector import plan_growing
from tests.test_navigation import FakeNavigator, FakeRobot

SQUARE = [[-0.1, -0.4], [0.1, -0.4], [0.1, 0.4], [-0.1, 0.4]]


class MemoryTest(unittest.TestCase):
    def path(self):
        return Path(tempfile.mkdtemp()) / "nav.json"

    def test_restart_is_not_trusted_until_home_realigns_everything(self):
        p = self.path()
        m = NavMemory(p)
        m.mark_home((1.0, 0.0, 0.0))
        m.add_zone([[1.5, 0.0], [1.7, 0.0], [1.7, 0.2]])
        m2 = NavMemory(p)
        self.assertFalse(m2.aligned)
        self.assertIsNone(m2.layers())                    # never enforce a zone that may be in the wrong place
        with self.assertRaises(ValueError):
            m2.add_zone(SQUARE)
        self.assertTrue(m2.mark_home((0.0, 0.0, math.pi / 2)))   # new origin, rotated by 90 degrees
        x, y = m2.zones[0]["points"][0]
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 0.5)
        self.assertTrue(m2.aligned)

    def test_new_map_switches_the_memory_off(self):
        m = NavMemory()
        m.add_zone(SQUARE)
        m.sync(0)
        m.sync(1)
        self.assertFalse(m.aligned)
        m.accept()
        self.assertEqual(len(m.layers()["nogo"]), 1)

    def test_bad_zones_are_rejected(self):
        m = NavMemory()
        for bad in ([[0, 0], [1, 1]], [[0, 0], [9, 0], [9, 9]], [[0, 0], [0.001, 0], [0, 0.001]], "x"):
            with self.assertRaises(ValueError):
                m.add_zone(bad)


class ZonePlanningTest(unittest.TestCase):
    def test_route_goes_around_a_no_go_zone(self):
        cfg = NavigationConfig()
        v = blank()
        t = add_object(v, 0.7, 0.0, 0.05, "cup")
        target = Target("cup", t.x, t.y, t.radius, t.id, t.label)
        start = (-0.6, 0.0)
        zones = {"nogo": [SQUARE], "avoid": [], "corridor": []}
        make = lambda m: Costmap(v, cfg, 0.2, [start, (t.x, t.y)], margin=m, zones=zones)   # noqa: E731
        route = plan_growing(make, start, 0.0, target)
        self.assertTrue(route.ok)
        self.assertTrue(route_ok(route.cm, route.path))
        for (ax, ay), (bx, by) in zip(route.path, route.path[1:]):
            for f in np.linspace(0, 1, 60):
                x, y = ax + (bx - ax) * f, ay + (by - ay) * f
                self.assertFalse(abs(x) < 0.1 + cfg.robot_radius and abs(y) < 0.4, (x, y))


class HomeTest(unittest.TestCase):
    def test_goes_home_and_restores_heading(self):
        robot = FakeRobot((0.1, 0.1, 0.4))
        nav = FakeNavigator(robot, blank())
        nav.mark_home()
        robot.pose[:] = [0.7, -0.4, 2.0]
        self.assertIsNone(nav.go("home"))
        self.assertLess(math.hypot(robot.pose[0] - 0.1, robot.pose[1] - 0.1), 0.06)
        err = (robot.pose[2] - 0.4 + math.pi) % (2 * math.pi) - math.pi
        self.assertLess(abs(err), math.radians(8))

    def test_home_not_set_is_explained(self):
        nav = FakeNavigator(FakeRobot((0.0, 0.0, 0.0)), blank())
        self.assertEqual(nav.go("home"), "home is not set")


class CostTest(unittest.TestCase):
    def test_plain_commands_stay_local(self):
        for text, action in (("turn left", "turn_left"), ("Please go from the cup to the bottle.", "navigate"),
                             ("go home", "navigate"), ("this is home", "set_home"), ("stop", "stop")):
            self.assertEqual(local_command(text)["commands"][0]["action"], action, text)

    def test_conversation_still_goes_to_the_ai(self):
        for text in ("what's left on my desk?", "how far can you go", "tell me a joke and then spin",
                     "who is on the right", "good question", "I like the book"):
            self.assertIsNone(local_command(text), text)

    def test_images_only_when_eyes_are_needed(self):
        self.assertTrue(needs_image("What colour is this mug?"))
        self.assertTrue(needs_image("read this label"))
        self.assertFalse(needs_image("what's the weather in Delhi"))
        self.assertFalse(needs_image("tell me a joke"))


class SoundAndFaceTest(unittest.TestCase):
    def test_motifs_are_distinct_short_and_in_range(self):
        waves = {n: synth(n) for n in MOTIFS}
        self.assertGreaterEqual(len(waves), 6)
        for name, x in waves.items():
            self.assertLess(len(x) / 22050, 1.2, name)
            self.assertLessEqual(float(np.abs(x).max()), 1.0, name)
        self.assertEqual(len({tuple(v) for v in MOTIFS.values() for v in [tuple(v)]}), len(MOTIFS))

    def test_tilt_slides_eyes_and_makes_the_face_woozy(self):
        from deskbot.companion.config import OledConfig
        from deskbot.companion.eyes import FacePlayer

        level, tilted = FacePlayer(OledConfig()), FacePlayer(OledConfig())
        level.invoke("neutral", 0.0)
        tilted.invoke("neutral", 0.0)
        tilted.frames = level.frames
        p = fx = None
        for i in range(60):
            t = i / 15
            base, _ = level.pose(t)
            p, fx = tilted.pose(t, roll=math.radians(35))
        self.assertGreater(tilted.tx, 10)
        self.assertGreater(tilted.woozy, 0.9)
        self.assertEqual(fx, "dizzy")
        self.assertGreater(p["lid"], base["lid"])

    def test_being_picked_up_starts_with_a_gasp(self):
        from deskbot.companion.config import OledConfig
        from deskbot.companion.eyes import FacePlayer

        for _ in range(10):
            f = FacePlayer(OledConfig())
            f.invoke("neutral", 0.0)
            f.invoke("scared", 1.0)
            self.assertEqual(f.name, "gasp")


if __name__ == "__main__":
    unittest.main()
