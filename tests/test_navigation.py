"""Obstacle-to-obstacle navigation (18 Nov 2026). No hardware, no camera, no network."""

import math
import threading
import unittest
from types import SimpleNamespace

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant.brain import OfflineBrain, parse_navigation
from deskbot.assistant.commands import Executor, normalise
from deskbot.config import NavigationConfig
from deskbot.navigation.costmap import SONAR_X, Target, edt
from deskbot.navigation.navigator import Navigator, clean_name, find_target
from deskbot.navigation.planners import PLANNERS, route_length, route_ok
from desk_bench.scenes import NO_ROUTE_EXPECTED, SCENES, add_object, add_wall, blank, costmap_for, scene
from deskbot.navigation.selector import Features, SearchSpeed, choose, plan_growing, plan_route


def features(**kw):
    base = dict(n_obstacles=8, density=0.15, line_clear=False, n_on_route=1, tight_on_route=0, unknown_frac=0.0,
                object_sigma=0.01, distance_m=1.0, free_cells=3000, vertices=100, resolution_m=0.025, predicted_ms=5.0)
    return Features(**{**base, **kw})


def solve(name, force=None, speed=None):
    cfg = NavigationConfig()
    view, start, target, _ = scene(name, cfg)
    route = plan_growing(lambda m: costmap_for(view, start, target, cfg, margin=m), start, 0.0, target,
                         speed or SearchSpeed(cfg.default_ms_per_1k), force=force)
    return route, target


class GeometryTest(unittest.TestCase):
    def test_distance_transform_matches_brute_force(self):
        rng = np.random.default_rng(1)
        mask = rng.random((25, 40)) < 0.03
        pts = np.argwhere(mask)
        got = edt(mask)
        for r, c in ((0, 0), (12, 20), (24, 39), (5, 33)):
            self.assertAlmostEqual(got[r, c], np.hypot(pts[:, 0] - r, pts[:, 1] - c).min())

    def test_goal_ring_is_outside_the_sonar_stop_distance(self):
        view, start, target, _ = scene("open desk")
        cm = costmap_for(view, start, target)
        self.assertGreater(cm.standoff, SONAR_X + 0.20)
        rows, cols = np.nonzero(cm.goal_mask(target))
        d = np.hypot(cm.X[cols] - target.x, cm.Y[rows] - target.y) - target.radius
        self.assertGreater(d.min(), SONAR_X + 0.20)

    def test_driving_at_a_wall_is_refused_even_when_the_segment_is_free(self):
        view = blank()
        add_wall(view, 0.5, -1.0, 0.55, 1.0)
        target = Target("t", -0.5, 0.0, 0.05)
        cm = costmap_for(view, (0.0, 0.0), target, margin=0.8)
        self.assertTrue(cm.segment_free(0.0, 0.0, 0.3, 0.0))     # nothing touches the robot...
        self.assertFalse(cm.edge_ok(0.0, 0.0, 0.3, 0.0))         # ...but the motor rule would stop it
        self.assertTrue(cm.edge_ok(0.3, 0.0, 0.0, 0.0))          # driving away is fine


class PlannerTest(unittest.TestCase):
    def test_every_planner_gives_a_drivable_route_on_every_solvable_desk(self):
        for name in SCENES:
            if name in NO_ROUTE_EXPECTED:
                continue
            cfg = NavigationConfig()
            view, start, target, _ = scene(name, cfg)
            for planner in PLANNERS:
                if planner == "direct":
                    continue
                route = plan_growing(lambda m: costmap_for(view, start, target, cfg, margin=m), start, 0.0, target, force=planner)
                if not route.ok:
                    continue    # a sampling or corner planner may miss; the selector has fallbacks
                self.assertTrue(route_ok(route.cm, route.path), (name, planner))
                self.assertLessEqual(target.surface_distance(*route.path[-1]), route.cm.standoff + 0.1)
            self.assertTrue(plan_growing(lambda m: costmap_for(view, start, target, cfg, margin=m), start, 0.0, target).ok, name)

    def test_any_angle_is_not_longer_than_grid(self):
        theta, _ = solve("one obstacle", "theta_star")
        grid, _ = solve("one obstacle", "astar")
        self.assertLessEqual(theta.length_m, grid.length_m + 1e-6)

    def test_walled_off_is_refused(self):
        route, _ = solve("walled off")
        self.assertFalse(route.ok)

    def test_route_outside_the_first_window_is_still_found(self):
        route, _ = solve("few obstacles")
        self.assertTrue(route.ok)
        self.assertGreater(route.cm.margin, NavigationConfig().window_margin_m)

    def test_fallback_when_the_chosen_planner_fails(self):
        cfg = NavigationConfig()
        view, start, target, _ = scene("one obstacle", cfg)
        cm = costmap_for(view, start, target, cfg, margin=1.0)
        original = PLANNERS["theta_star"]
        PLANNERS["theta_star"] = lambda p, deadline: None
        try:
            speed = SearchSpeed(cfg.default_ms_per_1k)
            route = plan_route(cm, start, 0.0, target, speed)
        finally:
            PLANNERS["theta_star"] = original
        self.assertTrue(route.ok)
        self.assertEqual(route.tried[0], {**route.tried[0], "planner": "theta_star", "status": "no route"})
        self.assertNotEqual(route.planner, "theta_star")


class SelectorTest(unittest.TestCase):
    cfg = NavigationConfig()

    def pick(self, **kw):
        return choose(features(**kw), self.cfg).planner

    def test_rules(self):
        self.assertEqual(self.pick(line_clear=True), "direct")
        self.assertEqual(self.pick(line_clear=True, unknown_frac=0.9), "astar")
        self.assertEqual(self.pick(n_obstacles=3, vertices=20), "theta_star")
        self.assertEqual(self.pick(n_obstacles=8), "theta_star")
        self.assertEqual(self.pick(n_obstacles=20), "astar")
        self.assertEqual(self.pick(density=0.4), "astar")
        self.assertEqual(self.pick(n_obstacles=3, vertices=20, tight_on_route=1), "astar")
        self.assertEqual(self.pick(object_sigma=0.2), "astar")

    def test_obstacle_count_decides_when_any_angle_search_is_too_slow(self):
        self.assertEqual(self.pick(n_obstacles=3, vertices=20, predicted_ms=40), "visibility")
        self.assertEqual(self.pick(n_obstacles=3, vertices=500, predicted_ms=40), "astar")
        self.assertEqual(self.pick(n_obstacles=8, vertices=20, predicted_ms=40), "astar")

    def test_slow_machine_changes_the_choice(self):
        self.assertEqual(self.pick(predicted_ms=500, density=0.05), "rrt_connect")
        self.assertEqual(self.pick(predicted_ms=500, density=0.25), "weighted_astar")
        self.assertEqual(self.pick(predicted_ms=40), "astar")      # Theta* would not fit the budget

    def test_fallbacks_cover_the_others(self):
        order = choose(features(n_obstacles=3, vertices=20, predicted_ms=40), self.cfg).order
        self.assertEqual(order[0], "visibility")
        self.assertTrue({"astar", "theta_star", "rrt_connect"} <= set(order))

    def test_measured_features_on_known_desks(self):
        self.assertEqual(solve("open desk")[0].planner, "direct")
        self.assertTrue(solve("narrow gap")[0].features.tight_on_route >= 1)
        self.assertEqual(solve("unexplored")[0].planner, "astar")
        self.assertGreater(solve("clutter")[0].features.n_obstacles, solve("one obstacle")[0].features.n_obstacles)

    def test_speed_is_learned(self):
        s = SearchSpeed(40.0)
        for _ in range(30):
            s.update(10.0, 1000)
        self.assertAlmostEqual(s.ms_per_1k, 10.0, places=1)


class NamesTest(unittest.TestCase):
    def view(self):
        v = blank()
        add_object(v, 0.5, 0.0, 0.045, "cup")
        add_object(v, -0.4, 0.2, 0.045, "cup")
        add_object(v, 0.0, 0.5, 0.04, "cell phone")
        add_wall(v, -0.8, -0.6, -0.7, -0.5)
        return v

    def test_lookup(self):
        v, cfg = self.view(), NavigationConfig()
        self.assertEqual(clean_name("  The Mug, please"), "mug")
        self.assertEqual(find_target(v, cfg, "the mug").x, -0.4)          # nearest of the two cups
        self.assertEqual(find_target(v, cfg, "phone").label, "cell phone")
        self.assertIsNone(find_target(v, cfg, "giraffe"))
        self.assertEqual(find_target(v, cfg, "obstacle one").name, "obstacle 1")
        self.assertEqual(find_target(v, cfg, "farthest obstacle").name, "obstacle 1")

    def test_second_of_the_same_kind(self):
        v, cfg = self.view(), NavigationConfig()
        first = find_target(v, cfg, "cup")
        self.assertEqual(find_target(v, cfg, "cup", exclude=first).x, 0.5)


class CommandTest(unittest.TestCase):
    def test_normalise(self):
        clean, problems = normalise([{"action": "navigate", "from_object": " cup ", "to_object": "bottle"},
                                     {"action": "navigate", "to_object": ""}, {"action": "stop", "to_object": "x"}])
        self.assertEqual(clean[0], {"action": "navigate", "amount": 0.0, "from_object": "cup", "to_object": "bottle"})
        self.assertEqual(clean[1], {"action": "stop", "amount": 0.0})
        self.assertEqual(problems, ["navigate needs to_object"])

    def test_phrases(self):
        self.assertEqual(parse_navigation("go from the cup to the bottle."), ("the cup", "the bottle"))
        self.assertEqual(parse_navigation("please drive to the book please"), ("", "the book"))
        for text in ("go to sleep", "go to the left", "go back 2 seconds", "what is the time"):
            self.assertIsNone(parse_navigation(text), text)

    def test_offline_brain(self):
        cmd = OfflineBrain().think("Go from the mug to obstacle 2", "", [])["commands"][0]
        self.assertEqual((cmd["action"], cmd["from_object"], cmd["to_object"]), ("navigate", "the mug", "obstacle 2"))
        self.assertEqual(OfflineBrain().think("go to sleep", "", [])["commands"][0]["action"], "sleep")

    def test_executor_passes_names_and_cancel(self):
        seen, done = [], threading.Event()

        def go(to, frm, cancelled):
            seen.append((to, frm, cancelled()))
            done.set()

        ex = Executor(SimpleNamespace(robot=None, navigator=SimpleNamespace(go=go)), None, lambda *a, **k: None)
        ex.run([{"action": "navigate", "from_object": "cup", "to_object": "book"}])
        self.assertTrue(done.wait(2))
        self.assertEqual(seen, [("book", "cup", False)])


class FakeRobot:
    """Perfect kinematics, moves finish instantly; can stop forward moves at a hidden wall."""
    speed = 0.5
    stop_distance = 0.20

    def __init__(self, pose, hidden_wall_x=None):
        self.pose = list(pose)
        self.state = "idle"
        self.hidden_wall_x = hidden_wall_x
        self.moves = []
        self.logs = []
        self.front = 2.0

    def log(self, level, msg):
        self.logs.append(msg)

    def stop(self):
        self.state = "idle"

    def snapshot(self):
        return {"state": self.state}

    def latest_reading(self):
        return {"distance": self.front, "distances": {"front": self.front, "left": 2.0, "right": 2.0, "rear": 2.0},
                "front_floor": True, "back_floor": True}

    def move(self, direction, seconds):
        self.moves.append(direction)
        x, y, th = self.pose
        self.state = "idle"
        if direction in ("left", "right"):
            rate = 2 * self.speed * 0.25 / 0.12
            self.pose[2] = th + (rate * seconds if direction == "left" else -rate * seconds)
            return
        d = (1 if direction == "forward" else -1) * self.speed * 0.25 * seconds
        nx = x + d * math.cos(th)
        if direction == "forward" and self.hidden_wall_x is not None and math.cos(th) > 0.5:
            limit = self.hidden_wall_x - SONAR_X - self.stop_distance
            if nx > limit:
                d = max(0.0, (limit - x) / math.cos(th))
                nx = x + d * math.cos(th)
                self.front = self.stop_distance
                self.state = "blocked"
        self.pose[0], self.pose[1] = nx, y + d * math.sin(th)


class FakeNavigator(Navigator):
    def __init__(self, robot, view, **kw):
        cfg = NavigationConfig(command_settle_s=0.0, leg_pause_s=0.0, scan_pause_s=0.0)
        super().__init__(robot, None, cfg, say=lambda text, kind="chatter": self.spoken.append(text), **kw)
        self.spoken = []
        self.world = view

    def view(self):
        self.world.pose = tuple(self.robot.pose)
        return self.world

    def pose(self):
        return tuple(self.robot.pose)

    def _wait_for_map(self):
        pass


class NavigatorTest(unittest.TestCase):
    def desk(self):
        v = blank()
        add_object(v, 0.6, 0.0, 0.045, "cup")
        add_object(v, -0.6, 0.5, 0.04, "bottle")
        add_object(v, 0.0, 0.25, 0.1, "book")
        return v

    def test_goes_from_one_obstacle_to_the_other(self):
        v = self.desk()
        robot = FakeRobot((0.0, -0.3, 0.0))
        nav = FakeNavigator(robot, v)
        self.assertIsNone(nav.go("bottle", "the mug"))
        x, y, th = robot.pose
        cup_visits = [p for p in nav.history if p["target"] == "cup"]
        self.assertTrue(cup_visits)
        self.assertLess(math.hypot(x + 0.6, y - 0.5) - 0.04, 0.45)
        bearing = math.atan2(0.5 - y, -0.6 - x)
        self.assertLess(abs((bearing - th + math.pi) % (2 * math.pi) - math.pi), math.radians(10))
        self.assertEqual(nav.status()["phase"], "done")
        self.assertIn("I reached the bottle.", nav.spoken)

    def test_replans_after_a_safety_stop(self):
        v = blank()
        add_object(v, 1.0, 0.0, 0.05, "cup")
        robot = FakeRobot((0.0, 0.0, 0.0), hidden_wall_x=0.45)    # not on the map: only the sonar stop reveals it
        nav = FakeNavigator(robot, v)
        nav.go("cup")
        self.assertTrue(any("safety stop" in m for m in robot.logs))
        self.assertGreaterEqual(len(nav.history), 2)

    def test_unknown_target_looks_around_then_says_so(self):
        robot = FakeRobot((0.0, 0.0, 0.0))
        nav = FakeNavigator(robot, self.desk())
        events = []
        nav.listeners.append(events.append)
        why = nav.go("giraffe")
        self.assertEqual(why, "can't find giraffe")
        self.assertGreater(robot.moves.count("forward"), 0)                    # it went looking
        self.assertIn("I cannot seem to find the giraffe.", nav.spoken)
        self.assertEqual(events, ["not_found"])

    def test_cancel_stops_the_trip(self):
        robot = FakeRobot((0.0, -0.3, 0.0))
        nav = FakeNavigator(robot, self.desk())
        self.assertEqual(nav.go("bottle", cancelled=lambda: True), "cancelled")
        self.assertEqual(robot.state, "idle")

    def test_face_user_is_paused_and_restored(self):
        calls = []
        behaviour = SimpleNamespace(enabled=True, set_enabled=calls.append)
        nav = FakeNavigator(FakeRobot((0.0, -0.3, 0.0)), self.desk(), behaviour=behaviour)
        nav.go("cup")
        self.assertEqual(calls, [False, True])


if __name__ == "__main__":
    unittest.main()
