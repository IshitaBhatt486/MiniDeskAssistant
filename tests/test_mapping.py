"""Geometry, decaying grid, semantic map, lap fallback - pure logic, no hardware."""

import math
import unittest

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.config import CameraConfig, MappingConfig
from deskbot.mapping.grid import DecayGrid
from deskbot.mapping.semantic import Observation, SemanticMap
from deskbot.vision.geometry import CameraModel
from deskbot.vision.lap_compat import lapjv


class TestGeometry(unittest.TestCase):
    def setUp(self):
        self.cam = CameraModel(CameraConfig())

    def test_ground_round_trip(self):
        for x, y in [(0.3, 0.0), (0.5, 0.15), (0.25, -0.1), (0.9, 0.3)]:
            u, v = self.cam.project(x, y, 0.0)
            gx, gy = self.cam.ground_point(u, v)
            self.assertAlmostEqual(gx, x, places=6)
            self.assertAlmostEqual(gy, y, places=6)

    def test_bearing_sign(self):
        cfg = CameraConfig()
        self.assertGreater(self.cam.bearing(0), 0)            # left edge of the image = left of the robot
        self.assertLess(self.cam.bearing(cfg.width), 0)
        self.assertAlmostEqual(self.cam.bearing(cfg.width / 2), 0.0)
        self.assertAlmostEqual(math.degrees(self.cam.bearing(0)), cfg.hfov_deg / 2, places=6)

    def test_above_horizon_has_no_ground_point(self):
        self.assertIsNone(self.cam.ground_point(160, 0))

    def test_in_view(self):
        self.assertTrue(self.cam.in_view(0.5, 0.0))
        self.assertFalse(self.cam.in_view(-0.5, 0.0))         # behind
        self.assertFalse(self.cam.in_view(0.5, 0.8))          # far outside the field of view


class TestDecayGrid(unittest.TestCase):
    def setUp(self):
        self.cfg = MappingConfig()
        self.g = DecayGrid(self.cfg)

    def cell(self, x, y):
        return self.g.cells([x], [y])[0]

    def test_sonar_hit_and_free(self):
        self.g.sonar(0.0, 0.0, 0.0, 0.5, now=0.0)
        L = self.g.logodds(0.0).ravel()
        self.assertGreater(L[self.cell(0.5, 0.0)], 0)         # hit
        self.assertLess(L[self.cell(0.25, 0.0)], 0)           # beam passed through
        self.assertEqual(L[self.cell(0.25, 0.3)], 0)          # outside the cone: untouched

    def test_each_cell_updated_once_per_reading(self):
        self.g.sonar(0.0, 0.0, 0.0, 0.5, now=0.0)
        near = self.g.logodds(0.0).ravel()[self.cell(0.05, 0.0)]
        self.assertAlmostEqual(near, self.cfg.l_free, places=5)  # 5 rays overlap here, counted once

    def test_no_echo_is_all_free(self):
        self.g.sonar(0.0, 0.0, 0.0, 2.0, now=0.0)
        L = self.g.logodds(0.0)
        self.assertFalse((L > 0).any())
        self.assertLess(L.ravel()[self.cell(1.1, 0.0)], 0)

    def test_half_life(self):
        self.g.sonar(0.0, 0.0, 0.0, 0.5, now=0.0)
        i = self.cell(0.5, 0.0)
        v0 = self.g.logodds(0.0).ravel()[i]
        v1 = self.g.logodds(self.cfg.geo_half_life_s).ravel()[i]
        self.assertAlmostEqual(v1, v0 / 2, places=4)

    def test_update_folds_in_decay(self):
        i = self.cell(0.5, 0.0)
        self.g.add(np.array([i]), 2.0, now=0.0)
        self.g.add(np.array([i]), 1.0, now=self.cfg.geo_half_life_s)
        self.assertAlmostEqual(self.g.L.ravel()[i], 2.0, places=4)  # 2 halved + 1

    def test_clamp_and_edges(self):
        i = self.cell(0.1, 0.1)
        for _ in range(20):
            self.g.add(np.array([i]), 1.0, now=0.0)
        self.assertLessEqual(self.g.L.ravel()[i], self.cfg.l_max)
        self.g.mark_edge(0.2, 0.2)
        self.assertTrue(self.g.edge.ravel()[self.cell(0.2, 0.2)])


class TestSemanticMap(unittest.TestCase):
    def setUp(self):
        self.cfg = MappingConfig()
        self.m = SemanticMap(self.cfg)

    def obs(self, x=0.5, y=0.1, tid=1, label="cup", score=0.9):
        return Observation(label, score, x, y, 0.02 ** 2, tid)

    def test_repeated_sightings_fuse_into_one_object(self):
        for k in range(10):
            self.m.update(k * 0.1, [self.obs(0.5 + 0.01 * (k % 2), 0.1, tid=1)], lambda lm: True)
        self.assertEqual(len(self.m.objects), 1)
        lm = next(iter(self.m.objects.values()))
        self.assertAlmostEqual(lm.x, 0.505, delta=0.01)
        self.assertGreater(self.m.probability(self.m.existence(lm, 1.0)), 0.95)

    def test_association_without_track_id(self):
        self.m.update(0.0, [self.obs(tid=None)], lambda lm: True)
        self.m.update(0.1, [self.obs(0.52, 0.11, tid=None)], lambda lm: True)
        self.assertEqual(len(self.m.objects), 1)

    def test_different_labels_are_different_objects(self):
        self.m.update(0.0, [self.obs(tid=None), self.obs(0.52, 0.1, tid=None, label="bottle")], lambda lm: True)
        self.assertEqual(len(self.m.objects), 2)

    def test_misses_remove_a_moved_object(self):
        self.m.update(0.0, [self.obs()], lambda lm: True)
        for k in range(1, 6):
            self.m.update(k * 0.1, [], lambda lm: True)   # in view, not detected
        self.assertEqual(len(self.m.objects), 0)

    def test_out_of_view_is_not_a_miss(self):
        self.m.update(0.0, [self.obs()], lambda lm: True)
        for k in range(1, 20):
            self.m.update(k * 0.1, [], lambda lm: False)
        self.assertEqual(len(self.m.objects), 1)

    def test_stale_object_fades_to_unknown(self):
        self.m.update(0.0, [self.obs()], lambda lm: True)
        lm = next(iter(self.m.objects.values()))
        e0 = self.m.existence(lm, 0.0)
        hl = self.cfg.sem_half_life_s
        self.assertAlmostEqual(self.m.existence(lm, hl), e0 / 2, places=6)
        self.assertLess(abs(self.m.probability(self.m.existence(lm, 5 * hl)) - 0.5), 0.05)
        self.assertGreater(self.m.variance(lm, 60.0), lm.var)  # position gets less certain too

    def test_unlocalised_sighting_refreshes_tracked_object(self):
        self.m.update(0.0, [self.obs(tid=7)], lambda lm: True)
        lm = next(iter(self.m.objects.values()))
        x0 = lm.x
        self.m.update(10.0, [Observation("cup", 0.9, None, None, 1.0, 7)], lambda lm: True)
        self.assertEqual(lm.t_seen, 10.0)
        self.assertEqual(lm.x, x0)


class TestLapFallback(unittest.TestCase):
    def brute(self, cost, limit):
        """Exhaustive optimum with 'leave unmatched costs limit/2' semantics."""
        import itertools
        n, m = cost.shape
        best = (math.inf, None)
        cols = list(range(m)) + [None] * n
        for perm in set(itertools.permutations(cols, n)):
            used = [c for c in perm if c is not None]
            total = sum(cost[i, c] if c is not None else limit / 2 for i, c in enumerate(perm))
            total += (m - len(used)) * limit / 2
            if total < best[0] - 1e-9:
                best = (total, perm)
        return best

    def test_matches_brute_force(self):
        rng = np.random.default_rng(0)
        for _ in range(30):
            n, m = rng.integers(1, 4), rng.integers(1, 4)
            cost = rng.random((n, m))
            limit = 0.6
            _, x, y = lapjv(cost, extend_cost=True, cost_limit=limit)
            total = sum(cost[i, x[i]] for i in range(n) if x[i] >= 0) + ((x < 0).sum() + (y < 0).sum()) * limit / 2
            self.assertAlmostEqual(total, self.brute(cost, limit)[0], places=9)
            for i in range(n):
                if x[i] >= 0:
                    self.assertEqual(y[x[i]], i)

    def test_two_value_return(self):
        x, y = lapjv(np.array([[0.1, 0.9]]), extend_cost=True, cost_limit=0.5, return_cost=False)
        self.assertEqual(list(x), [0])
        self.assertEqual(list(y), [0, -1])


if __name__ == "__main__":
    unittest.main()
