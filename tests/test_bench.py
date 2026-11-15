"""Benchmark maths: AP / mAP, tracking metrics, lighting conditions."""

import unittest

import numpy as np

import deskbot  # noqa: F401
from desk_bench import lighting, metrics
from deskbot.vision.detector import Detection


class TestDetectionMetrics(unittest.TestCase):
    def test_perfect_predictions_score_one(self):
        gts = [[("cup", [0, 0, 10, 10]), ("book", [20, 20, 40, 40])]]
        preds = [[("cup", 0.9, [0, 0, 10, 10]), ("book", 0.8, [20, 20, 40, 40])]]
        m = metrics.evaluate(preds, gts, ["cup", "book", "laptop"])
        self.assertAlmostEqual(m["map50"], 1.0)
        self.assertAlmostEqual(m["map"], 1.0)
        self.assertEqual((m["precision"], m["recall"]), (1.0, 1.0))
        self.assertNotIn("laptop", m["per_class"])     # no ground truth -> not averaged

    def test_false_positive_ranked_first_lowers_ap(self):
        gts = [[("cup", [0, 0, 10, 10])]]
        preds = [[("cup", 0.9, [50, 50, 60, 60]), ("cup", 0.5, [0, 0, 10, 10])]]
        m = metrics.evaluate(preds, gts, ["cup"])
        # precision at recall 1 is 1/2 -> AP = 0.5 over the 101 points
        self.assertAlmostEqual(m["map50"], 0.5, places=2)

    def test_loose_box_counts_at_50_not_at_95(self):
        gts = [[("cup", [0, 0, 10, 10])]]
        preds = [[("cup", 0.9, [0, 0, 10, 13])]]        # IoU ~0.77
        m = metrics.evaluate(preds, gts, ["cup"])
        self.assertAlmostEqual(m["map50"], 1.0)
        self.assertLess(m["map"], 1.0)

    def test_iou(self):
        self.assertAlmostEqual(metrics.iou([0, 0, 2, 2], [1, 1, 3, 3]), 1 / 7)


class TestTrackingMetrics(unittest.TestCase):
    def test_id_switch_and_gaps(self):
        frames = [[Detection("cup", 0.9, (0, 0, 10, 10), 1)],
                  [Detection("cup", 0.9, (1, 0, 11, 10), 1)],
                  [],
                  [Detection("cup", 0.9, (2, 0, 12, 10), 2)],
                  [Detection("cup", 0.9, (2, 0, 12, 10), 3), Detection("book", 0.9, (0, 0, 99, 99), 9)]]
        m = metrics.tracking_metrics(frames, "cup", reference=frames)
        self.assertEqual(m["found"], 0.8)
        self.assertEqual(m["ids"], 3)
        self.assertEqual(m["id_switches"], 1)           # 2 -> 3 (1 -> 2 spans a gap)
        self.assertEqual(m["longest"], 0.4)
        self.assertAlmostEqual(m["agreement"], 1.0)


class TestLighting(unittest.TestCase):
    def test_conditions_are_deterministic_and_plausible(self):
        rng = np.random.default_rng(0)
        img = (rng.random((60, 80, 3)) * 200 + 30).astype(np.uint8)
        for name in lighting.CONDITIONS:
            a = lighting.apply(name, img, seed=5)
            b = lighting.apply(name, img, seed=5)
            self.assertEqual(a.shape, img.shape)
            self.assertEqual(a.dtype, np.uint8)
            self.assertTrue(np.array_equal(a, b), name)
        self.assertLess(lighting.apply("dark", img).mean(), img.mean())
        self.assertGreater(lighting.apply("bright", img).mean(), img.mean())
        warm = lighting.apply("warm", img).astype(float)
        self.assertGreater(warm[..., 2].mean() - warm[..., 0].mean(), img[..., 2].mean() - img[..., 0].mean())
        self.assertTrue(np.array_equal(lighting.apply("normal", img), img))


if __name__ == "__main__":
    unittest.main()
