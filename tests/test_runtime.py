"""Multi-process runtime: shared memory, command arbitration, safety, optical flow, behaviour, reflections."""

import math
import time
import unittest

import numpy as np

import deskbot  # noqa: F401  (puts dashboard/ on sys.path)
from deskbot.config import AppConfig, MappingConfig
from deskbot.runtime import sched
from deskbot.runtime.procs import MotorLoop, decode_result, encode_result
from deskbot.runtime.safety import SafetyRules
from deskbot.runtime.shared import CTX, MOVE, STOP, Shared
from deskbot.runtime.shm import FrameRing, Ring, SeqBlock
from deskbot.vision.detector import Detection


def _child_write(block):
    block.write(a=1.5, b=2.5)


class TestSharedMemory(unittest.TestCase):
    def test_seqblock_starts_empty_and_round_trips(self):
        b = SeqBlock(["a", "b"])
        self.assertTrue(math.isnan(b.read()["a"]))
        b.write(a=1.0, b=None)
        self.assertEqual(b.read()["a"], 1.0)
        self.assertTrue(math.isnan(b.read()["b"]))
        self.assertEqual(b.version, 1)

    def test_seqblock_is_shared_with_a_spawned_process(self):
        b = SeqBlock(["a", "b"])
        p = CTX.Process(target=_child_write, args=(b,))
        p.start()
        p.join(30)
        self.assertEqual(p.exitcode, 0)
        self.assertEqual(b.read(), {"a": 1.5, "b": 2.5})

    def test_ring_keeps_newest_rows_in_order(self):
        r = Ring(4, 2)
        self.assertEqual(len(r.rows()), 0)
        for i in range(7):
            r.append((i, -i))
        self.assertEqual(r.rows()[:, 0].tolist(), [3, 4, 5, 6])

    def test_frame_ring(self):
        f = FrameRing(4, 5)
        self.assertIsNone(f.read())
        for seq in (1, 2, 3, 4):
            f.write(seq, seq * 0.1, np.full((4, 5, 3), seq, np.uint8))
        seq, t, img = f.read()
        self.assertEqual((seq, int(img[0, 0, 0])), (4, 4))
        self.assertEqual(int(f.read(3)[2][0, 0, 0]), 3)
        self.assertEqual(f.read(1)[0], 4)        # overwritten -> newest instead

    def test_detection_rows_round_trip(self):
        dets = [Detection("cup", 0.8, (1, 2, 30, 40), 7), Detection("person", 0.5, (5, 6, 7, 8), None)]
        h = decode_result(encode_result(12, 1.0, 1.05, 30.0, dets, True, 30.0, 10.0, 0.0))
        self.assertEqual([d.label for d in h["detections"]], ["cup", "person"])
        self.assertEqual(h["detections"][0].track_id, 7)
        self.assertIsNone(h["detections"][1].track_id)
        self.assertEqual(int(h["seq"]), 12)


class FakeMotors:
    def __init__(self):
        self.calls = []

    def drive(self, l, r):
        self.calls.append((l, r))

    def stop(self):
        self.calls.append((0, 0))

    def tick(self):
        pass


def _sample(shared, front=1.0, floor=True, age=0.0):
    shared.sensors.write(t=time.monotonic() - age, tp=time.perf_counter() - age, front=front, left=1.0, right=1.0,
                         rear=1.0, front_floor=float(floor), back_floor=1.0, read_ms=0.1)


def _command(shared, kind, direction=0, duration=1.0):
    shared.command.write(t=time.monotonic(), tp=time.perf_counter(), kind=kind, direction=direction, duration=duration, source=0)


class TestMotorLoop(unittest.TestCase):
    def setUp(self):
        self.s = Shared()
        self.s.settings.write(speed=0.5, stop_distance=0.2, side_stop_distance=0.08)
        self.hw = FakeMotors()
        self.loop = MotorLoop(self.s, AppConfig().runtime, self.hw)
        _sample(self.s)

    def state(self):
        return self.s.motor.read()

    def test_newest_command_wins(self):
        _command(self.s, MOVE, 0)        # forward ...
        _command(self.s, MOVE, 2)        # ... replaced by left before the motor process even looked
        self.loop.step()
        self.assertEqual(self.loop.active["direction"], "left")
        self.assertEqual(self.hw.calls[-1], (-0.5, 0.5))
        _command(self.s, MOVE, 3)        # a new command preempts the running move immediately
        self.loop.step()
        self.assertEqual(self.loop.active["direction"], "right")
        self.assertEqual(self.state()["preempted"], 1)
        _command(self.s, STOP)
        self.loop.step()
        self.assertIsNone(self.loop.active)
        self.assertEqual(self.hw.calls[-1], (0, 0))
        self.assertEqual(self.state()["user_stops"], 1)

    def test_obstacle_stops_forward(self):
        _command(self.s, MOVE, 0)
        self.loop.step()
        _sample(self.s, front=0.1)
        self.loop.step()
        self.assertEqual(self.loop.state, "blocked")
        self.assertEqual(self.state()["stop_obstacle"], 1)

    def test_stale_sensors_stop_the_motors(self):
        _sample(self.s, age=1.0)
        _command(self.s, MOVE, 0)
        self.loop.step()
        self.assertEqual(self.loop.state, "blocked")
        self.assertEqual(self.state()["stop_stale_sensors"], 1)
        self.assertNotIn((0.5, 0.5), self.hw.calls)

    def test_move_completes(self):
        _command(self.s, MOVE, 1, duration=0.05)
        self.loop.step()
        time.sleep(0.07)
        _sample(self.s)
        self.loop.step()
        self.assertEqual(self.loop.state, "idle")
        self.assertEqual(self.state()["completed"], 1)
        log = self.s.wheel_log.rows()
        self.assertEqual(log[-1, 1:].tolist(), [0.0, 0.0])

    def test_safety_rules_are_the_proven_ones(self):
        rules = SafetyRules(0.2, 0.08)
        ok = {"distance": 1, "distances": {"front": 1, "left": 1, "right": 1, "rear": 1}, "front_floor": True, "back_floor": True}
        self.assertIsNone(rules.check("forward", ok))
        self.assertEqual(rules.check("forward", {**ok, "front_floor": False})[0], "front_edge")
        self.assertEqual(rules.check("backward", {**ok, "distances": {**ok["distances"], "rear": 0.1}})[0], "rear_obstacle")
        self.assertEqual(rules.check("left", {**ok, "distances": {**ok["distances"], "left": 0.05}})[0], "side_obstacle")


class TestScheduling(unittest.TestCase):
    def test_apply_reports_what_it_did(self):
        info = sched.apply("camera", AppConfig().runtime)
        self.assertEqual(info["role"], "camera")
        self.assertIn(info["policy"], ("other", "fifo", "rr"))
        if hasattr(__import__("os"), "sched_getaffinity"):
            self.assertEqual(len(__import__("os").sched_getaffinity(0)), 1)


class TestFlow(unittest.TestCase):
    def test_box_follows_the_image(self):
        from deskbot.vision.flow import FlowTracker

        rng = np.random.default_rng(0)
        base = (rng.random((240, 320)) * 255).astype(np.uint8)
        import cv2
        base = cv2.GaussianBlur(base, (5, 5), 0)
        img0 = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
        img1 = np.roll(np.roll(img0, 5, axis=1), 3, axis=0)
        ft = FlowTracker(12)
        ft.reset(img0, [Detection("cup", 0.9, (100, 80, 160, 140), 4)])
        out = ft.update(img1)
        self.assertEqual(len(out), 1)
        x1, y1, x2, y2 = out[0].box
        self.assertAlmostEqual(x1, 105, delta=1.0)
        self.assertAlmostEqual(y1, 83, delta=1.0)
        self.assertEqual(out[0].track_id, 4)
        self.assertLess(out[0].score, 0.9)

    def test_lost_box_is_held(self):
        from deskbot.vision.flow import FlowTracker

        flat = np.full((240, 320, 3), 128, np.uint8)
        ft = FlowTracker(12)
        ft.reset(flat, [Detection("cup", 0.9, (100, 80, 160, 140), 4)])
        out = ft.update(np.zeros_like(flat))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].box, (100, 80, 160, 140))


class TestFaceUser(unittest.TestCase):
    def test_plan_turn(self):
        from deskbot.runtime.behaviour import plan_turn, turn_rate

        rcfg = AppConfig().runtime
        self.assertIsNone(plan_turn(math.radians(5), 0.5, rcfg))
        d, s = plan_turn(math.radians(30), 0.5, rcfg)
        self.assertEqual(d, "left")
        self.assertAlmostEqual(s, rcfg.face_gain * math.radians(30) / turn_rate(0.5), places=2)
        d, s = plan_turn(math.radians(-170), 0.5, rcfg)
        self.assertEqual((d, s), ("right", rcfg.face_max_turn_s))

    def test_pick_user_takes_the_nearest(self):
        from deskbot.runtime.behaviour import pick_user

        dets = [Detection("person", 0.9, (0, 0, 10, 10), 1), Detection("person", 0.6, (0, 0, 50, 80), 2),
                Detection("cup", 0.9, (0, 0, 200, 200), 3)]
        self.assertEqual(pick_user(dets).track_id, 2)
        self.assertIsNone(pick_user(dets[2:]))


class TestReflections(unittest.TestCase):
    def test_multipath_jump_needs_confirmation(self):
        from deskbot.mapping.fusion import SonarFilter

        f = SonarFilter(0.15, 2)
        self.assertEqual(f(0.40), 0.40)
        self.assertIsNone(f(1.10))        # sudden long echo: not believed yet
        self.assertEqual(f(0.41), 0.41)   # back to normal: the long one was multipath
        self.assertIsNone(f(1.10))
        self.assertEqual(f(1.12), 1.12)   # repeated -> the obstacle really moved away
        self.assertEqual(f(0.20), 0.20)   # closer is always believed at once

    def test_no_echo_is_weak_free_evidence(self):
        from deskbot.mapping.grid import DecayGrid

        cfg = MappingConfig()
        g1, g2 = DecayGrid(cfg), DecayGrid(cfg)
        g1.sonar(0, 0, 0, 2.0, 1.0)
        g2.sonar(0, 0, 0, 2.0, 1.0, free_delta=cfg.l_free_no_echo)
        i = g1.cells([0.5], [0.0])[0]
        self.assertLess(g1.L.ravel()[i], g2.L.ravel()[i])
        self.assertAlmostEqual(float(g2.L.ravel()[i]), cfg.l_free_no_echo, places=5)


class TestMultiProcessSim(unittest.TestCase):
    """The real processes on the simulated robot: a move goes through the motor process and the shared
    simulated world moves; the sensor process keeps publishing."""

    def test_move_through_processes(self):
        from deskbot.robot import RUNTIME_SIM_OBJECTS
        from deskbot.runtime.app import start_children, stop_children, wait_ready
        from deskbot.runtime.hardware import SimMirrorHardware
        from deskbot.runtime.proxy import RobotProxy

        cfg = AppConfig()
        shared = Shared(sim=True)
        shared.sim.publish_objects(RUNTIME_SIM_OBJECTS)
        procs = start_children(shared, cfg, True, "none")
        robot = RobotProxy(shared, cfg.runtime, SimMirrorHardware(shared.sim))
        try:
            self.assertTrue(all(wait_ready(shared, procs, ["motor", "sensors"], 60).values()))
            end = time.monotonic() + 10
            while robot.latest_reading()["t"] is None and time.monotonic() < end:
                time.sleep(0.05)
            x0 = robot.snapshot()["sim"]["x"]
            robot.move("forward", 0.6)
            time.sleep(1.2)
            snap = robot.snapshot()
            self.assertEqual(snap["state"], "idle")
            self.assertAlmostEqual(snap["sim"]["x"] - x0, 0.6 * 0.125, delta=0.03)
            self.assertEqual(snap["stats"]["completed"], 1)
            self.assertGreaterEqual(len(robot.wheel_log), 2)
            self.assertLess(shared.motor.read()["cmd_latency_p50"], 50)
        finally:
            robot.close()
            stop_children(shared, procs)
        for p in procs.values():
            self.assertFalse(p.is_alive())


if __name__ == "__main__":
    unittest.main()
