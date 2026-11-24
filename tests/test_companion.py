"""Companion runtime: wheel commands, IMU filter, PID loops, lift, gestures, eyes, outputs, calibration maths, CLI."""

import json
import math
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import deskbot  # noqa: F401  (puts dashboard/ on sys.path)
from deskbot.companion import animations as anim
from deskbot.companion import cli, config, gestures, outputs
from deskbot.companion.calibration import fit_line, level_matrix
from deskbot.companion.config import CompanionAppConfig, ImuConfig, LiftConfig, OledConfig, load_config
from deskbot.companion.control import ClosedLoopFaceUser, MotionTrim
from deskbot.companion.emotion import EmotionEngine
from deskbot.companion.eyes import FacePlayer, draw_face
from deskbot.companion.imu import G, ImuFilter, tilt_rad
from deskbot.companion.lift import ImuLiftDetector
from deskbot.companion.shared import GESTURES, CompanionShared
from deskbot.config import AppConfig
from deskbot.runtime.procs import MotorLoop, wheel_direction
from deskbot.runtime.shared import DRIVE, MOVE, STATES, WakeSignal
from deskbot.vision.detector import Detection


def imu_sample(shared, now=None, yaw=0.0, gz=0.0, roll=0.0, pitch=0.0, gyro_norm=0.0, accel_err=0.0, still=1.0):
    shared.imu.write(t=time.monotonic() if now is None else now, ok=1.0, yaw=yaw, gz=gz, roll=roll, pitch=pitch,
                     gyro_norm=gyro_norm, accel_err=accel_err, still=still)


def sensors(shared, front=1.0, rear=1.0, ff=True, bf=True):
    shared.sensors.write(t=time.monotonic(), tp=time.perf_counter(), front=front, left=1.0, right=1.0, rear=rear,
                         front_floor=float(ff), back_floor=float(bf), read_ms=0.1)


class FakeRobot:
    speed = 0.5
    stop_distance = 0.2
    last_user_command = -1e9
    last_stop_reason = None

    def __init__(self, shared):
        self.s = shared
        self.sent, self.stops, self.logs = [], [], []

    def motor_state(self):
        return self.s.motor.read()

    def latest_reading(self):
        v = self.s.sensors.read()
        return {"distances": {k: v[k] for k in ("front", "left", "right", "rear")},
                "front_floor": v["front_floor"] > 0.5, "back_floor": v["back_floor"] > 0.5, "t": v["t"]}

    def drive(self, left, right, duration=0.25, source="auto"):
        self.sent.append((left, right))

    def stop(self, source="user"):
        self.stops.append(source)

    def log(self, level, msg):
        self.logs.append((level, msg))

    def busy(self):
        return False


def motor(shared, state="moving", direction=0, seq=1, drive=0.0, left=0.5, right=0.5, safety_stops=0.0):
    shared.motor.write(t=time.monotonic(), state=STATES.index(state), direction=direction, cmd_seq=seq, drive=drive,
                       left=left, right=right, safety_stops=safety_stops)


class FakeHw:
    def __init__(self):
        self.calls = []

    def drive(self, left, right):
        self.calls.append((left, right))

    def stop(self):
        self.calls.append((0.0, 0.0))

    def tick(self):
        pass


class TestWakeSignal(unittest.TestCase):
    def test_set_is_idempotent_and_never_blocks(self):
        w = WakeSignal()
        self.assertFalse(w.wait(0.001))
        w.set()
        w.set()                      # no sleeper, already signalled: must return at once
        self.assertTrue(w.wait(0.01))
        self.assertFalse(w.wait(0.001))
        w.set()
        w.clear()
        self.assertFalse(w.wait(0.001))


class TestDriveCommand(unittest.TestCase):
    def setUp(self):
        self.s = CompanionShared()
        self.s.settings.write(speed=0.5, stop_distance=0.2, side_stop_distance=0.08)
        self.hw = FakeHw()
        self.loop = MotorLoop(self.s, AppConfig().runtime, self.hw)
        sensors(self.s)

    def cmd(self, kind, left=0.0, right=0.0, duration=0.25, direction=0):
        self.s.command.write(t=time.monotonic(), tp=time.perf_counter(), kind=kind, direction=direction,
                             duration=duration, source=1, left=left, right=right)

    def test_direction_decides_which_safety_rule_applies(self):
        self.assertEqual(wheel_direction(0.4, 0.5), "forward")
        self.assertEqual(wheel_direction(-0.4, -0.5), "backward")
        self.assertEqual(wheel_direction(-0.3, 0.3), "left")
        self.assertEqual(wheel_direction(0.3, -0.1), "right")
        self.assertIsNone(wheel_direction(0.0, 0.0))

    def test_drive_sets_wheels_and_updates_in_place(self):
        self.cmd(DRIVE, -0.3, 0.3)
        self.loop.step()
        self.assertEqual(self.hw.calls[-1], (-0.3, 0.3))
        self.cmd(DRIVE, -0.2, 0.2)
        self.loop.step()
        self.assertEqual(self.hw.calls[-1], (-0.2, 0.2))
        self.assertEqual(self.loop.stats["moves"], 1)
        self.assertEqual(self.loop.stats["preempted"], 0)
        self.assertEqual(self.s.motor.read()["drive"], 1.0)

    def test_deadman_stops_when_commands_end(self):
        self.cmd(DRIVE, 0.3, 0.3, duration=0.01)
        self.loop.step()
        time.sleep(0.03)
        sensors(self.s)
        self.loop.step()
        self.assertEqual(self.hw.calls[-1], (0.0, 0.0))

    def test_safety_rules_still_stop_a_drive(self):
        self.cmd(DRIVE, 0.3, 0.3)
        self.loop.step()
        sensors(self.s, front=0.1)
        self.loop.step()
        self.assertEqual(self.loop.state, "blocked")
        self.assertEqual(self.hw.calls[-1], (0.0, 0.0))

    def test_timed_moves_use_fresh_trims_and_ignore_stale_ones(self):
        self.s.control.write(t=time.monotonic(), left=0.8, right=1.2)
        self.cmd(MOVE, duration=1.0)
        self.loop.step()
        self.assertEqual(self.hw.calls[-1], (0.4, 0.6))
        self.s.control.write(t=time.monotonic() - 5, left=0.8, right=1.2)
        sensors(self.s)
        self.loop.step()
        self.assertEqual(self.hw.calls[-1], (0.5, 0.5))


class TestImuFilter(unittest.TestCase):
    def run_filter(self, f, gyro, seconds, hz=100, motors=True, acc=(0, 0, G)):
        out, t = None, f.t or 0.0
        for _ in range(int(seconds * hz)):
            t += 1 / hz
            out = f.update(np.array(acc, float), np.array(gyro, float), t, motors)
        return out

    def test_yaw_integrates_left_turns_positive_and_is_continuous(self):
        f = ImuFilter(ImuConfig(), {})
        o = self.run_filter(f, (0, 0, 1.0), 8)    # past +pi: must not wrap
        self.assertAlmostEqual(o["yaw"], 8.0, delta=0.1)

    def test_calibration_removes_bias_and_can_flip_the_axis(self):
        f = ImuFilter(ImuConfig(), {"imu": {"gyro_bias": [0, 0, 0.2], "yaw_sign": -1}})
        o = self.run_filter(f, (0, 0, 1.2), 1)
        self.assertAlmostEqual(o["yaw"], -1.0, delta=0.03)

    def test_still_robot_freezes_yaw_and_learns_the_bias(self):
        f = ImuFilter(ImuConfig(bias_alpha=0.02), {})
        o = self.run_filter(f, (0, 0, 0.02), 10, motors=False)
        self.assertEqual(o["still"], 1.0)
        self.assertLess(abs(o["yaw"]), 0.02)
        self.assertAlmostEqual(f.gyro_bias[2], 0.02, delta=0.005)

    def test_tilt_from_gravity(self):
        a = math.radians(30)
        f = ImuFilter(ImuConfig(madgwick_gain=0.5), {})
        o = self.run_filter(f, (0, 0, 0), 12, acc=(G * math.sin(a), 0, G * math.cos(a)))
        self.assertAlmostEqual(math.degrees(tilt_rad(o)), 30, delta=3)


class TestControl(unittest.TestCase):
    def setUp(self):
        self.s = CompanionShared()
        self.robot = FakeRobot(self.s)
        self.cfg = CompanionAppConfig()
        sensors(self.s)
        self.trim = MotionTrim(self.robot, self.cfg)

    def control(self):
        c = self.s.control.read()
        return c["left"], c["right"]

    def test_drifting_right_speeds_up_the_right_wheel(self):
        motor(self.s, direction=0)
        imu_sample(self.s, yaw=0.0)
        self.trim.step(time.monotonic(), 0.04)
        imu_sample(self.s, yaw=-0.1)
        self.trim.step(time.monotonic(), 0.04)
        left, right = self.control()
        self.assertGreater(right, left)

    def test_correction_is_mirrored_when_reversing(self):
        motor(self.s, direction=1)
        imu_sample(self.s, yaw=0.0)
        self.trim.step(time.monotonic(), 0.04)
        imu_sample(self.s, yaw=-0.1)
        self.trim.step(time.monotonic(), 0.04)
        left, right = self.control()
        self.assertGreater(left, right)

    def test_slows_down_near_an_obstacle(self):
        motor(self.s, direction=0)
        sensors(self.s, front=0.25)
        self.trim.step(time.monotonic(), 0.04)
        left, right = self.control()
        self.assertLess(max(left, right), 0.6)

    def test_slow_turn_gets_more_power(self):
        motor(self.s, direction=2)
        imu_sample(self.s, gz=0.5)
        self.trim.step(time.monotonic(), 0.04)
        imu_sample(self.s, gz=0.5)
        self.trim.step(time.monotonic(), 0.04)
        self.assertGreater(self.control()[0], 1.0)

    def test_stalled_turn_stops_the_robot(self):
        called = []
        self.trim.on_stall = lambda: called.append(1)
        motor(self.s, direction=2)
        now = time.monotonic()
        for i in range(30):
            t = now + i * 0.05
            imu_sample(self.s, now=t, gz=0.0)
            self.trim.step(t, 0.05)
        self.assertEqual(self.robot.stops, ["auto"])
        self.assertEqual(called, [1])

    def test_paused_controller_applies_no_correction(self):
        self.trim.paused = True
        motor(self.s, direction=0)
        self.trim.step(time.monotonic(), 0.04)
        self.assertEqual(self.control(), (1.0, 1.0))


class FakeVision:
    def __init__(self):
        self.res = None

    def latest(self):
        return self.res


class TestFaceUserLoop(unittest.TestCase):
    def test_turns_to_the_person_and_settles(self):
        s = CompanionShared()
        robot = FakeRobot(s)
        cfg = CompanionAppConfig()
        vision = FakeVision()
        f = ClosedLoopFaceUser(robot, vision, None, cfg)
        motor(s, state="idle", drive=0.0, left=0.0, right=0.0)
        yaw = 0.0
        person_world = math.radians(25)            # the person stays still; the view changes as the robot turns
        for i in range(120):
            t = time.monotonic()
            bearing = person_world - yaw
            u = 160 - f.cam.fx * math.tan(bearing)
            vision.res = SimpleNamespace(seq=i, t_capture=t, detections=[Detection("person", 0.9, (u - 20, 20, u + 20, 200), 1)])
            s.imu.write(t=t, ok=1.0, yaw=yaw, gz=0.0)
            robot.sent.clear()
            f.step(t)
            if robot.sent:
                left, right = robot.sent[-1]
                yaw += (right - left) / 2 * 4.17 * 0.05
        self.assertAlmostEqual(math.degrees(yaw), 25, delta=cfg.companion.control.face_deadband_deg + 1.5)
        self.assertEqual(f.state, "facing user")
        self.assertLess(abs(f.gaze[0]), 0.2)      # the person ended up near the middle of the image


class FakeMapper:
    def __init__(self):
        self.paused = False
        self.resets = self.reanchors = 0

    def reset(self):
        self.resets += 1

    def reanchor_heading(self):
        self.reanchors += 1


class FakeAlerts:
    def warn(self, *a, **k):
        pass

    def resolve(self, *a):
        pass


class FakeExecutor:
    def __init__(self):
        self.runs, self.cancels = [], 0

    def run(self, commands, source=""):
        self.runs.append(commands)
        return commands, []

    def cancel(self):
        self.cancels += 1


class TestLift(unittest.TestCase):
    def setUp(self):
        self.s = CompanionShared()
        self.robot = FakeRobot(self.s)
        self.mapper = FakeMapper()
        self.ex = FakeExecutor()
        ImuLiftDetector.cfg = LiftConfig(on_place=["save_figures", "reset_map", "zero_heading", "look_around"])
        self.lift = ImuLiftDetector(self.robot, self.mapper, FakeAlerts(), lambda *a: None, self.ex)
        self.order = []
        self.lift.actions = {"save_figures": lambda: self.order.append(self.mapper.resets)}
        motor(self.s, state="idle", left=0.0, right=0.0)
        sensors(self.s)

    def feed(self, seconds, start, **imu):
        t = start
        while t < start + seconds:
            imu_sample(self.s, now=time.monotonic(), **imu)
            self.lift.step(t)
            t += 0.05
        return t

    def test_ir_alone_detects_a_lift_without_imu(self):
        self.s.imu.write(ok=0.0)
        sensors(self.s, ff=False, bf=False)
        for i in range(12):
            self.lift.step(100 + i * 0.05)
        self.assertTrue(self.lift.lifted)
        self.assertTrue(self.mapper.paused)
        self.assertEqual(self.ex.cancels, 1)

    def test_tilt_detects_a_lift_while_ir_still_sees_the_desk(self):
        self.feed(0.5, 100, roll=math.radians(40))
        self.assertTrue(self.lift.lifted)
        self.assertIn("tilted", self.lift.trigger)

    def test_a_bump_on_the_desk_is_not_a_lift(self):
        self.feed(1.0, 100, gyro_norm=2.0, accel_err=4.0)       # both IR sensors still see the desk
        self.assertFalse(self.lift.lifted)

    def test_a_short_lift_resumes_instead_of_resetting(self):
        # 24 Nov 2026: time in the air ends at touch-down, not after the 1 s put-down confirmation; before, every
        # lift counted as >= 1 s (= reset_after_s), so even a blip reset the map (legacy/simplified_code.py)
        t = self.feed(0.5, 100, roll=math.radians(40))          # lifted at ~100.3
        self.assertTrue(self.lift.lifted)
        self.feed(1.3, t)                                        # put straight back down
        self.assertFalse(self.lift.lifted)
        self.assertEqual(self.mapper.resets, 0)
        self.assertEqual(self.order, [])                         # no on_place actions

    def test_put_down_runs_the_configured_actions_in_order(self):
        t = self.feed(0.5, 100, roll=math.radians(40))
        self.feed(1.3, t + 2)
        self.assertFalse(self.lift.lifted)
        self.assertFalse(self.mapper.paused)
        self.assertEqual(self.order, [0])                       # figures saved BEFORE the reset
        self.assertEqual(self.mapper.resets, 1)
        self.assertEqual(self.mapper.reanchors, 1)
        self.assertEqual(self.s.imu_ctl.read()["zero_seq"], 1)
        self.assertEqual(self.ex.runs, [[{"action": "look_around", "amount": 0}]])

    def test_not_placed_until_still_and_level(self):
        t = self.feed(0.5, 100, roll=math.radians(40))
        self.feed(2.0, t, gyro_norm=1.0)
        self.assertTrue(self.lift.lifted)


class TestGestures(unittest.TestCase):
    def setUp(self):
        self.s = CompanionShared()
        self.ex = FakeExecutor()
        self.robot = FakeRobot(self.s)
        self.app = SimpleNamespace(lift=SimpleNamespace(lifted=False), presence=None, executor=self.ex, robot=self.robot,
                                   outputs=SimpleNamespace(save_all=lambda r: self.saved.append(r)))
        self.saved = []
        self.c = gestures.GestureController(self.s, config.GestureConfig(), self.app, mapping=gestures.clean_mapping({}))

    def show(self, name, score=0.9):
        self.s.gesture.write(t=time.monotonic(), gesture=GESTURES.index(name), score=score, seq=1, backend=2)

    def hold(self, name, seconds, start=100.0):
        t = start
        while t <= start + seconds:
            self.show(name)
            self.c.step(t)
            t += 0.05
        return t

    def test_runs_after_the_hold_time_and_only_once(self):
        self.hold("Thumb_Up", 0.5)
        self.assertEqual(self.ex.runs, [])
        self.hold("Thumb_Up", 1.0, 100.55)
        self.assertEqual(self.ex.runs, [[{"action": "dance", "amount": 0.0}]])

    def test_open_palm_stops_at_once(self):
        self.hold("Open_Palm", 0.3)
        self.assertEqual(self.robot.stops, ["user"])
        self.assertEqual(self.ex.cancels, 1)

    def test_low_confidence_is_ignored(self):
        for i in range(40):
            self.show("Victory", 0.3)
            self.c.step(100 + i * 0.05)
        self.assertEqual(self.ex.runs, [])

    def test_mapping_is_configurable_and_validated(self):
        m = gestures.clean_mapping({"Victory": {"action": "save_figures", "hold_s": 99}})
        self.assertEqual(m["Victory"]["action"], "save_figures")
        self.assertEqual(m["Victory"]["hold_s"], 5.0)
        self.c.mapping = m
        self.hold("Victory", 5.2)
        self.assertEqual(self.saved, ["gesture"])
        with self.assertRaises(ValueError):
            gestures.clean_mapping({"Wave": {}})
        with self.assertRaises(ValueError):
            gestures.clean_mapping({"Victory": {"action": "explode"}})

    def test_nothing_happens_while_lifted(self):
        self.app.lift.lifted = True
        self.hold("Thumb_Up", 1.0)
        self.assertEqual(self.ex.runs, [])

    def test_mapping_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.json"
            saved = gestures.save_mapping({"Thumb_Up": {"action": "spin", "amount": 2}}, p)
            self.assertEqual(gestures.load_mapping(p), saved)
            p.write_text("{broken", encoding="utf-8")
            self.assertEqual(gestures.load_mapping(p, warn=lambda m: None)["Thumb_Up"]["action"], "dance")


class TestEyes(unittest.TestCase):
    def test_every_emotion_has_five_valid_animations(self):
        import pytweening

        self.assertEqual(set(anim.ANIMATIONS), set(anim.EMOTIONS))
        for emotion, items in anim.ANIMATIONS.items():
            self.assertEqual(len(items), 5, emotion)
            self.assertEqual(len({name for name, _ in items}), 5, emotion)
            for name, frames in items:
                times = [k.ms for k in frames]
                self.assertEqual(times, sorted(set(times)), name)
                self.assertEqual(times[0], 0, name)
                for k in frames:
                    self.assertTrue(callable(getattr(pytweening, k.ease)), name)
                    self.assertLessEqual(set(k.pose), set(anim.DEFAULT_POSE), name)

    def test_invoke_picks_randomly_without_immediate_repeats(self):
        p = FacePlayer(OledConfig(), random.Random(1))
        seen, last = set(), None
        for i in range(40):
            p.invoke("happy", float(i))
            self.assertNotEqual(p.name, last)
            last = p.name
            seen.add(p.name)
        self.assertEqual(len(seen), 5)

    def test_eyes_look_toward_the_user_through_the_screen(self):
        p = FacePlayer(OledConfig(gaze_smooth=1.0, blink_min_s=99, blink_max_s=100))
        p.invoke("neutral", 0.0)
        left_of_image, _ = p.pose(10.0, gaze_x=-1.0)
        self.assertGreater(left_of_image["dx"], 10)       # mirrored: camera-left is screen-right

    def test_blinks_happen_occasionally(self):
        p = FacePlayer(OledConfig(blink_min_s=1, blink_max_s=1, replay_min_s=99, replay_max_s=99))
        p.invoke("neutral", 0.0)
        opens = [p.pose(i * 0.02)[0]["open"] for i in range(100)]
        self.assertLess(min(opens), 0.3)
        self.assertGreater(sum(o > 0.95 for o in opens), 80)

    def test_every_pose_draws(self):
        from PIL import Image, ImageDraw

        for emotion in anim.EMOTIONS:
            p = FacePlayer(OledConfig())
            p.invoke(emotion, 0.0)
            im = Image.new("1", (128, 64))
            pose, fx = p.pose(0.2)
            draw_face(ImageDraw.Draw(im), pose, fx or "spark", now=0.2)
            self.assertIsNotNone(im.getbbox(), emotion)


class TestEmotion(unittest.TestCase):
    def setUp(self):
        self.s = CompanionShared()
        self.robot = FakeRobot(self.s)
        motor(self.s, state="idle", left=0.0, right=0.0)
        self.app = SimpleNamespace(robot=self.robot, lift=SimpleNamespace(lifted=False), presence=None, behaviour=None,
                                   assistant=SimpleNamespace(status=lambda: {"log": self.log}))
        self.log = []
        self.e = EmotionEngine(self.s, config.EmotionConfig(), self.app)

    def test_priorities(self):
        now = time.monotonic()
        self.e.step(now)
        self.assertEqual(self.e.emotion, "neutral")
        self.e.react("excited", 5, now=now)
        self.e.step(now)
        self.assertEqual(self.e.emotion, "excited")
        self.app.lift.lifted = True
        self.e.step(now)
        self.assertEqual(self.e.emotion, "scared")
        self.assertEqual(anim.EMOTIONS[int(self.s.face.read()["emotion"])], "scared")

    def test_safety_stop_annoys_and_assistant_mood_shows(self):
        now = time.monotonic()
        self.e.step(now)
        motor(self.s, state="blocked", left=0.0, right=0.0, safety_stops=1.0)
        self.e.step(now)
        self.assertEqual(self.e.emotion, "annoyed")
        self.log.append({"id": 1, "mood": "curious"})
        self.e.step(now + 10)
        self.assertEqual(self.e.emotion, "curious")


class TestOutputsAndConfig(unittest.TestCase):
    def test_download_cannot_leave_the_outputs_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.png").write_bytes(b"x")
            (root / "a.exe").write_bytes(b"x")
            original = outputs.OUTPUTS_DIR
            outputs.OUTPUTS_DIR = root
            try:
                self.assertIsNotNone(outputs.resolve_download("a.png"))
                self.assertIsNone(outputs.resolve_download("a.exe"))
                self.assertIsNone(outputs.resolve_download("../secrets.env"))
                self.assertIsNone(outputs.resolve_download("missing.png"))
            finally:
                outputs.OUTPUTS_DIR = original

    def test_map_figures_draw(self):
        import base64

        n = 10
        layer = base64.b64encode(bytes([128]) * (n * n)).decode()
        snap = {"size": n, "resolution": 0.05, "trail": [[0, 0], [0.1, 0]], "pose": {"x": 0.1, "y": 0, "theta": 0}, "geo": layer,
                "heat": layer, "edges": [3], "objects": [{"label": "cup", "x": 0.1, "y": 0.1}]}
        fig, axes = outputs._figure(9, 3, 1, 3)
        outputs.draw_geometric(axes[0][0], snap)
        outputs.draw_semantic(axes[0][1], snap)
        outputs.draw_heatmap(fig, axes[0][2], snap)
        with tempfile.TemporaryDirectory() as d:
            fig.savefig(Path(d) / "x.png")
            self.assertGreater((Path(d) / "x.png").stat().st_size, 1000)

    def test_config_file_overrides_and_rejects_typos(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"oled": {"driver": "sh1106"}, "control": {"yaw_kp": 3.0}}), encoding="utf-8")
            c = load_config(p).companion
            self.assertEqual((c.oled.driver, c.control.yaw_kp), ("sh1106", 3.0))
            p.write_text(json.dumps({"oled": {"drivr": "x"}}), encoding="utf-8")
            warnings = []
            self.assertEqual(load_config(p, warnings.append).companion.oled.driver, "ssd1306")
            self.assertEqual(len(warnings), 1)


class TestCalibrationMaths(unittest.TestCase):
    def test_fit_separates_rate_and_lag(self):
        t = [0.5, 0.5, 1.2, 1.2]
        rate, lag = fit_line(t, [2.0 * (x - 0.1) for x in t])
        self.assertAlmostEqual(rate, 2.0)
        self.assertAlmostEqual(lag, 0.1)
        with self.assertRaises(ValueError):
            fit_line([0.5, 1.2], [1.0, 0.5])

    def test_level_matrix_maps_gravity_to_up(self):
        g = np.array([0.8, -0.4, 9.7])
        up = level_matrix(g) @ (g / np.linalg.norm(g))
        np.testing.assert_allclose(up, [0, 0, 1], atol=1e-6)


class TestEntryPoint(unittest.TestCase):
    def test_every_listed_tool_exists(self):
        for script, _ in cli.PY_TOOLS.values():
            self.assertTrue((deskbot.ROOT / script).exists(), script)
        for script, _ in cli.SH_TOOLS.values():
            self.assertTrue((deskbot.ROOT / script).exists(), script)

    def test_commands_parse(self):
        p = cli.build_parser()
        self.assertTrue(p.parse_args(["start", "--sim", "--lan"]).sim)
        self.assertEqual(p.parse_args(["gestures", "set", "Victory", "spin", "--amount", "2"]).target, "spin")

    def test_preview_writes_sheet_and_gifs(self):
        with tempfile.TemporaryDirectory() as d:
            cli.render_preview(Path(d))
            self.assertTrue((Path(d) / "all_animations.png").exists())
            self.assertEqual(len(list(Path(d).glob("*.gif"))), len(anim.EMOTIONS))


if __name__ == "__main__":
    unittest.main()
