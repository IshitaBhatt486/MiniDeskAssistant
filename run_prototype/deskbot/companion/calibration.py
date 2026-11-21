"""
The complete calibration. Choosing "calibrate" runs ALL of this, in order, with no sub-menu:

     1 preflight    sensors alive, on the desk, not moving
     2 i2c          MPU-6050 and OLED answer on the bus
     3 imu          4 s at rest: gyro bias, accelerometer scale, mounting tilt
     4 sonars       noise and dropouts of all four
     5 edge sensors both see the desk steadily
     6 camera       exposure and sharpness; lens field of view if a 9x6 checkerboard is shown
     7 turning      4 timed spins measured by the gyro: turn rate per PWM, start-up lag, gyro sign
     8 dead zone    smallest PWM that really turns the robot
     9 driving      4 short drives: speed, start-up lag, left/right wheel balance
    10 verify       two 90 degree turns using the new numbers, measured by the gyro

Every move goes through the motor process, so all the safety rules stay on, and the robot ends about where
it started. Results go to data/calibration.json (data/calibration_sim.json in simulation; used automatically from then on), the robot_shell settings
file, and a report + figure in outputs/. A step that can't run is reported and the others continue;
motion steps stop as soon as a safety rule stops a move.
"""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime

import numpy as np

from .. import ROOT
from .config import OUTPUTS_DIR
from .control import motor_status
from .imu import G, calibration_file, load_calibration
from .outputs import INK_2, SERIES, _figure, new_session_dir, style_axes
from .shared import fresh_imu, nav_bump

BOARD = (9, 6)
TURN_TIMES = (0.5, 1.2)
DRIVE_TIMES = (0.4, 1.0)
DRIVE_CLEARANCE_M = 0.18   # room needed ahead AND behind, beyond the safety stop distance


class Abort(Exception):
    pass


class MotionBlocked(Exception):
    pass


def apply_calibration(cal, cfg=None):
    """Use a calibration in this process: odometry, turn planning and the camera model."""
    import mapping                       # dashboard/mapping.py

    from ..runtime import behaviour

    d = cal.get("drive") or {}
    if d.get("wheel_speed_at_full"):
        mapping.WHEEL_SPEED_AT_FULL = behaviour.WHEEL_SPEED_AT_FULL = float(d["wheel_speed_at_full"])
    if d.get("turn_rate_per_pwm"):
        track = 2 * mapping.WHEEL_SPEED_AT_FULL / float(d["turn_rate_per_pwm"])
        mapping.TRACK_WIDTH = behaviour.TRACK_WIDTH = track
    c = cal.get("camera") or {}
    if cfg is not None and c.get("hfov_deg"):
        cfg.camera.hfov_deg, cfg.camera.vfov_deg = float(c["hfov_deg"]), float(c["vfov_deg"])


def fit_line(times, amounts):
    """amount = rate * (t - lag), least squares (numpy)."""
    slope, intercept = np.polyfit(np.asarray(times, float), np.asarray(amounts, float), 1)
    if slope <= 0:
        raise ValueError("the robot did not move further in the longer run")
    return float(slope), float(max(-0.3, min(0.6, -intercept / slope)))


def level_matrix(mean_accel):
    """Rotation that makes the measured gravity point along +z: the shortest-arc rotation (Rodrigues), the same matrix
    scipy's Rotation.align_vectors gave for one vector pair (numpy only since 20 Nov 2026)."""
    v = np.asarray(mean_accel, float)
    v = v / np.linalg.norm(v)
    z = np.array([0.0, 0.0, 1.0])
    axis, c = np.cross(v, z), float(np.dot(v, z))
    s = float(np.linalg.norm(axis))
    if s < 1e-12:                                     # already up, or exactly upside down: 180 deg about x
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    k = axis / s
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * kx + (1 - c) * (kx @ kx)


class Calibration:
    def __init__(self, robot, shared, cfg, sim=False, folder=None, log=print, ask=None, has_camera=True):
        self.robot, self.s, self.cfg, self.sim = robot, shared, cfg, sim
        self.log = log
        self.ask = ask                   # fn(question) -> number or None (terminal only)
        self.has_camera = has_camera
        self.folder = folder or (new_session_dir("calibration") / "calibration")
        self.cancel = threading.Event()
        self.data = load_calibration(sim)
        self.results = []
        self.plots = {}
        self.current = None
        self.running = False
        self.motion_ok = True

    STEPS = (("preflight", "Preflight", False), ("i2c", "I2C devices", False), ("imu", "IMU at rest", False),
             ("sonars", "Ultrasonic sensors", False), ("edges", "Edge sensors", False), ("camera", "Camera", False),
             ("turning", "Turn rate", True), ("deadzone", "Motor dead zone", True), ("driving", "Driving", True),
             ("verify", "Verification", True))

    # -- helpers --

    def _check(self):
        if self.cancel.is_set():
            raise Abort("cancelled")

    def _sleep(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._check()
            time.sleep(0.01)

    def _imu_rows(self, seconds, fields):
        rows, last, end = [], -1, time.monotonic() + seconds
        while time.monotonic() < end:
            self._check()
            if self.s.imu.version != last:
                last = self.s.imu.version
                v = fresh_imu(self.s, time.monotonic())
                if v:
                    rows.append([v[f] for f in fields])
            time.sleep(0.003)
        return np.array(rows)

    def _wait_stopped(self, timeout):
        end = time.monotonic() + timeout
        time.sleep(0.06)
        while time.monotonic() < end:
            self._check()
            m = motor_status(self.robot)
            if m["state"] == "blocked":
                raise MotionBlocked(self.robot.last_stop_reason or "a safety rule stopped the move")
            if m["state"] != "moving":
                return
            time.sleep(0.01)
        self.robot.stop(source="auto")
        raise MotionBlocked("the move did not finish")

    def _timed(self, direction, seconds):
        """Run one move and return (gyro angle in rad, seconds) including the coast after it stops."""
        before = fresh_imu(self.s, time.monotonic())
        self.robot.move(direction, seconds, source="auto")
        self._wait_stopped(seconds + 2.0)
        self._sleep(0.35)
        after = fresh_imu(self.s, time.monotonic())
        # the filter's heading has already integrated every gyro sample at the full IMU rate
        return None if before is None or after is None else after["yaw"] - before["yaw"]

    def _sonar(self, name, seconds=0.5):
        vals, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            d = self.robot.latest_reading().get("distances") or {}
            if d.get(name) is not None:
                vals.append(d[name])
            time.sleep(0.02)
        return float(np.median(vals)) if vals else None

    def _sim_pose(self):
        p = self.s.sim.pose.read()
        return p["x"], p["y"]

    def _save_data(self):
        self.data["date"] = datetime.now().isoformat(timespec="seconds")
        path = calibration_file(self.sim)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(path)
        nav_bump(self.s.imu_ctl, "reload_seq")

    # -- steps: each returns (status, message, values) --

    def step_preflight(self):
        r = None
        for _ in range(100):
            r = self.robot.latest_reading()
            if r.get("t") is not None:
                break
            self._sleep(0.05)
        if r is None or r.get("t") is None:
            self.motion_ok = False
            return "fail", "No sensor data, so nothing that moves will run.", {}
        if not (r["front_floor"] and r["back_floor"]):
            self.motion_ok = False
            return "fail", "Both edge sensors must see the desk. Put the robot in the middle of the desk.", {}
        return "ok", "Sensors are live and the robot is on the desk.", {}

    def step_i2c(self):
        if self.sim:
            return "skip", "Simulation has no I2C bus.", {}
        from smbus2 import SMBus

        wanted = {"MPU-6050": self.cfg.companion.imu.address, "OLED": self.cfg.companion.oled.address}
        found = {}
        with SMBus(self.cfg.companion.oled.port) as bus:
            for name, addr in wanted.items():
                try:
                    bus.read_byte(addr)
                    found[name] = True
                except OSError:
                    found[name] = False
        missing = [n for n, ok in found.items() if not ok]
        return ("warn", f"Not found: {', '.join(missing)}. Check wiring and `i2cdetect -y 1`.", found) if missing \
            else ("ok", "MPU-6050 and OLED both answer.", found)

    def step_imu(self):
        if fresh_imu(self.s, time.monotonic()) is None:
            self._sleep(1.0)
            if fresh_imu(self.s, time.monotonic()) is None:
                return "skip", "No IMU data. Motion steps will ask for or skip what needs it.", {}
        self.log("Keep the robot still for 4 seconds...")
        a = self._imu_rows(4.0, ["rax", "ray", "raz", "rgx", "rgy", "rgz"])
        if len(a) < 50:
            return "fail", f"Only {len(a)} IMU samples arrived.", {}
        acc, gyr = a[:, :3], a[:, 3:]
        noise = float(gyr.std(axis=0).max())
        if noise > 0.05:
            return "fail", "The robot moved during the measurement. Keep it still and run calibration again.", {"gyro_noise": noise}
        mean = acc.mean(axis=0)
        norm = float(np.linalg.norm(mean))
        imu = {"gyro_bias": gyr.mean(axis=0).tolist(), "accel_scale": G / norm, "level_matrix": level_matrix(mean).tolist(),
               "yaw_sign": (self.data.get("imu") or {}).get("yaw_sign", 1.0), "gyro_noise": noise}
        self.data["imu"] = imu
        self._save_data()
        self.plots["rest"] = gyr
        tilt = math.degrees(math.acos(max(-1, min(1, mean[2] / norm))))
        self._sleep(0.3)
        status = "ok" if norm > 8.5 and norm < 11.0 else "warn"
        return status, f"Gyro bias removed, mounted {tilt:.1f}° off level, gravity read as {norm:.2f} m/s².", {"tilt_deg": round(tilt, 2)}

    def step_sonars(self):
        samples = {k: [] for k in ("front", "left", "right", "rear")}
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            self._check()
            d = self.robot.latest_reading().get("distances") or {}
            for k in samples:
                if d.get(k) is not None:
                    samples[k].append(d[k])
            time.sleep(0.02)
        values, bad = {}, []
        for k, v in samples.items():
            if not v:
                bad.append(f"{k}: no data")
                continue
            a = np.array(v)
            near = a[a < 1.95]
            values[k] = {"median_m": round(float(np.median(a)), 3), "noise_cm": round(float(near.std() * 100), 2) if near.size else None,
                         "no_echo_pct": round(100 * float((a >= 1.95).mean()), 1)}
            if near.size > 5 and near.std() > 0.03:
                bad.append(f"{k}: noisy ({near.std() * 100:.1f} cm)")
            if np.median(a) < 0.03:
                bad.append(f"{k}: blocked or miswired")
        self.data["sonars"] = values
        return ("warn", "; ".join(bad), values) if bad else ("ok", "All four read steadily.", values)

    def step_edges(self):
        ff, bf, n = 0, 0, 100
        for _ in range(n):
            self._check()
            r = self.robot.latest_reading()
            ff += bool(r["front_floor"])
            bf += bool(r["back_floor"])
            time.sleep(0.01)
        values = {"front_pct": ff, "rear_pct": bf}
        return ("ok", "Both see the desk steadily.", values) if ff == n and bf == n \
            else ("warn", f"Unsteady: front {ff} %, rear {bf} % of readings saw the desk.", values)

    def step_camera(self):
        import cv2

        if not self.has_camera:
            return "skip", "Started without a camera.", {}
        first = None
        for _ in range(100):
            first = self.s.frames.read()
            if first is not None:
                break
            self._sleep(0.1)
        if first is None:
            return "warn", "No camera frame arrived within 10 s.", {}
        self.log(f"Camera: hold a {BOARD[0]}x{BOARD[1]} checkerboard in view now if you want the lens measured (optional).")
        grids, seen, last, brightness, sharpness = [], 0, None, [], []
        end = time.monotonic() + 6.0
        size = first[2].shape[1::-1]
        while time.monotonic() < end:
            self._check()
            f = self.s.frames.read()
            if f is None or f[0] == last:
                time.sleep(0.05)
                continue
            last = f[0]
            gray = cv2.cvtColor(f[2], cv2.COLOR_BGR2GRAY)
            brightness.append(float(gray.mean()))
            sharpness.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            ok, corners = cv2.findChessboardCorners(gray, BOARD, cv2.CALIB_CB_FAST_CHECK)
            if ok:
                seen += 1
                grids.append(cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                                              (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.01)))
                if len(grids) < 12:
                    end = max(end, time.monotonic() + 2.0)       # keep going while the board is being shown
        values = {"brightness": round(float(np.mean(brightness)), 1) if brightness else None,
                  "sharpness": round(float(np.median(sharpness)), 1) if sharpness else None, "board_views": seen}
        notes = []
        if brightness and not 40 <= values["brightness"] <= 215:
            notes.append("the image is too dark or too bright")
        if len(grids) >= 6:
            obj = np.zeros((BOARD[0] * BOARD[1], 3), np.float32)
            obj[:, :2] = np.mgrid[0:BOARD[0], 0:BOARD[1]].T.reshape(-1, 2)
            err, k, _, _, _ = cv2.calibrateCamera([obj] * len(grids), grids, size, None, None)
            hfov = 2 * math.degrees(math.atan(size[0] / (2 * k[0, 0])))
            vfov = 2 * math.degrees(math.atan(size[1] / (2 * k[1, 1])))
            self.data["camera"] = {"hfov_deg": round(hfov, 2), "vfov_deg": round(vfov, 2), "rms_px": round(float(err), 3)}
            values.update(self.data["camera"])
        msg = f"Brightness {values['brightness']}, sharpness {values['sharpness']}"
        msg += f", lens measured: {values['hfov_deg']}° wide." if "hfov_deg" in values else ", no checkerboard shown (lens values unchanged)."
        return ("warn", "; ".join(notes) + ". " + msg, values) if notes else ("ok", msg, values)

    def _need_motion(self):
        if not self.motion_ok:
            raise MotionBlocked("skipped because an earlier step failed")

    def step_turning(self):
        self._need_motion()
        speed = self.robot.speed
        samples, signs = [], []
        for seconds in TURN_TIMES:
            for direction in ("left", "right"):
                angle = self._timed(direction, seconds)
                if angle is None:
                    return "skip", "Needs the IMU.", {}
                signs.append(angle if direction == "left" else -angle)
                samples.append((direction, seconds, abs(angle)))
        sign = 1.0 if sum(signs) >= 0 else -1.0
        if sign < 0:
            imu = self.data.setdefault("imu", {})
            imu["yaw_sign"] = -imu.get("yaw_sign", 1.0)
        t = [s[1] for s in samples]
        a = [s[2] for s in samples]
        rate, lag = fit_line(t, a)
        d = self.data.setdefault("drive", {})
        d.update(turn_rate_per_pwm=rate / speed, turn_lag_s=lag, calibrated_at_pwm=speed,
                 turn_deg_s=math.degrees(rate))
        self.plots["turn"] = (t, a, rate, lag)
        self._save_data()
        return "ok", f"{math.degrees(rate):.0f}°/s at speed {speed:g}, {lag * 1000:.0f} ms start-up lag" \
            + (" (gyro axis was reversed; corrected)" if sign < 0 else "") + ".", {"deg_per_s": round(math.degrees(rate), 1)}

    def step_deadzone(self):
        self._need_motion()
        d = self.data.get("drive") or {}
        k = d.get("turn_rate_per_pwm")
        if not k or fresh_imu(self.s, time.monotonic()) is None:
            return "skip", "Needs the turn-rate step and the IMU.", {}
        found = {}
        for name, sign in (("left", 1), ("right", -1)):
            for pwm in np.arange(0.1, 0.85, 0.05):
                headings = []
                end = time.monotonic() + 0.3
                while time.monotonic() < end:
                    self._check()
                    self.robot.drive(-sign * pwm, sign * pwm, 0.2)
                    imu = fresh_imu(self.s, time.monotonic())
                    if imu:
                        headings.append((imu["t"], imu["yaw"]))
                    time.sleep(0.02)
                if motor_status(self.robot)["state"] == "blocked":
                    raise MotionBlocked(self.robot.last_stop_reason or "blocked")
                settled = headings[len(headings) // 2:]    # ignore the spin-up half of the window
                span = settled[-1][0] - settled[0][0] if len(settled) > 1 else 0.0
                rate = abs(settled[-1][1] - settled[0][1]) / span if span > 0 else 0.0
                if rate > 0.35:
                    found[name] = max(0.0, float(pwm) - rate / k)      # where the line through this point meets zero
                    break
            self.robot.drive(0.0, 0.0)
            self._sleep(0.3)
        if len(found) < 2:
            return "warn", "It never started turning within the tested power range.", found
        d["min_turn_pwm"] = round(max(found.values()), 3)
        self._save_data()
        return "ok", f"Wheels start turning at about {d['min_turn_pwm'] * 100:.0f} % power.", found

    def _distance(self, direction, before, seconds):
        """Metres moved, and how it was measured."""
        if self.sim:
            x, y = self._sim_pose()
            return math.hypot(x - before["pose"][0], y - before["pose"][1]), "simulator"
        name = "front" if direction == "forward" else "rear"
        now = self._sonar(name)
        if before[name] is not None and now is not None and 0.25 < before[name] < 1.6 and before[name] - now > 0.005:
            return before[name] - now, f"{name} sonar"
        if self.ask:
            cm = self.ask(f"How many cm did it drive {direction} in the {seconds:g} s run?")
            if cm:
                return float(cm) / 100, "measured by hand"
        return None, None

    def _face_clear_line(self):
        """Turn until there is room to drive both ahead and behind. False if no direction has room."""
        need = self.robot.stop_distance + DRIVE_CLEARANCE_M
        per_pwm = (self.data.get("drive") or {}).get("turn_rate_per_pwm")
        for attempt in range(6):
            front, rear = self._sonar("front"), self._sonar("rear")
            if front is not None and rear is not None and front > need and rear > need:
                return True
            if not per_pwm:
                return False
            self.log(f"Not enough room to drive here (front {front * 100:.0f} cm, rear {rear * 100:.0f} cm): turning to find some.")
            self._timed("left", round(math.radians(60) / (per_pwm * self.robot.speed), 3))
        return False

    def step_driving(self):
        self._need_motion()
        speed = self.robot.speed
        if not self._face_clear_line():
            return "warn", f"No direction has {DRIVE_CLEARANCE_M * 100:.0f} cm of room past the stop distance, so speed was not measured.", {}
        pts = {"forward": [], "backward": []}
        drift = []
        method = set()
        for seconds in DRIVE_TIMES:
            for direction in ("forward", "backward"):
                before = {"front": self._sonar("front"), "rear": self._sonar("rear")}
                if self.sim:
                    before["pose"] = self._sim_pose()
                angle = self._timed(direction, seconds)
                metres, how = self._distance(direction, before, seconds)
                if metres:
                    pts[direction].append((seconds, metres))
                    method.add(how)
                if angle is not None:
                    drift.append(angle / seconds)
        d = self.data.setdefault("drive", {})
        all_pts = pts["forward"] + pts["backward"]
        values = {}
        note = ""
        if len({p[0] for p in all_pts}) >= 2:
            t, m = zip(*all_pts)
            rate, lag = fit_line(t, m)
            d.update(wheel_speed_at_full=rate / speed, drive_lag_s=lag, forward_m_s=rate)
            self.plots["drive"] = (t, m, rate, lag)
            values = {"cm_per_s": round(rate * 100, 1), "lag_ms": round(lag * 1000)}
            note = f"{rate * 100:.1f} cm/s at speed {speed:g} (measured with {', '.join(sorted(method))})"
        else:
            note = "Speed not measured: put a box 30-100 cm in front of and behind the robot, or run from the terminal to type distances"
        if drift and d.get("wheel_speed_at_full") and d.get("turn_rate_per_pwm"):
            w = float(np.mean(drift[::2]))          # forward runs: + = veers left = right wheel is stronger
            epsilon = max(-0.2, min(0.2, w / (speed * d["turn_rate_per_pwm"])))
            d.update(left_gain=round(1 + epsilon, 3), right_gain=round(1 - epsilon, 3))
            values["wheel_balance_pct"] = round(epsilon * 100, 1)
            note += f"; wheel balance {epsilon * 100:+.1f} %"
        self._save_data()
        return ("ok" if "cm_per_s" in values else "warn"), note + ".", values

    def step_verify(self):
        self._need_motion()
        d = self.data.get("drive") or {}
        if not d.get("turn_rate_per_pwm"):
            return "skip", "Needs the turn-rate step.", {}
        rate = d["turn_rate_per_pwm"] * self.robot.speed
        seconds = math.pi / 2 / rate + d.get("turn_lag_s", 0.0)
        errors = {}
        for direction in ("left", "right"):
            angle = self._timed(direction, round(seconds, 3))
            errors[direction] = round(abs(math.degrees(abs(angle))) - 90, 1)
        worst = max(abs(v) for v in errors.values())
        d["verify_error_deg"] = worst
        self._save_data()
        return ("ok" if worst <= 10 else "warn"), f"A 90° turn came out within {worst:.1f}°.", errors

    # -- run --

    def run(self):
        self.running = True
        started = time.time()
        try:
            for i, (key, title, moves) in enumerate(self.STEPS, 1):
                self.current = title
                self.log(f"[{i}/{len(self.STEPS)}] {title}")
                try:
                    self._check()
                    status, msg, values = getattr(self, f"step_{key}")()
                except Abort:
                    self.results.append(self._result(key, title, "skip", "Cancelled.", {}))
                    self.robot.stop(source="auto")
                    break
                except MotionBlocked as exc:
                    status, msg, values = "fail" if self.motion_ok else "skip", str(exc).capitalize() + ".", {}
                    self.motion_ok = False
                    self.robot.stop(source="auto")
                except Exception as exc:
                    status, msg, values = "fail", f"{type(exc).__name__}: {exc}", {}
                    if moves:
                        self.motion_ok = False
                        self.robot.stop(source="auto")
                self.results.append(self._result(key, title, status, msg, values))
                self.log(f"      {status.upper()}: {msg}")
            self.data["last_run"] = {"seconds": round(time.time() - started), "steps": {r["key"]: r["status"] for r in self.results}}
            self._save_data()
            self._export_shell()
            self._report()
        finally:
            self.robot.stop(source="auto")
            self.current = None
            self.running = False
        return self.results

    @staticmethod
    def _result(key, title, status, msg, values):
        return {"key": key, "title": title, "status": status, "message": msg, "values": values}

    def _export_shell(self):
        """robot_shell.py gets the same numbers, in its own units."""
        d = self.data.get("drive") or {}
        pwm = d.get("calibrated_at_pwm")
        if not pwm:
            return
        path = ROOT / ("robot_shell_settings_sim.json" if self.sim else "robot_shell_settings.json")
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        cal = settings.get("calibration") or {}
        if d.get("forward_m_s"):
            for k in ("forward", "backward"):
                cal[k] = {"pwm": pwm, "rate": round(d["forward_m_s"] * 100, 2), "lag": round(d.get("drive_lag_s", 0.0), 3)}
        if d.get("turn_deg_s"):
            for k in ("left", "right"):
                cal[k] = {"pwm": pwm, "rate": round(d["turn_deg_s"], 1), "lag": round(d.get("turn_lag_s", 0.0), 3)}
        cal["date"] = time.strftime("%Y-%m-%d")
        settings["calibration"] = cal
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def _report(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "calibration.json").write_text(json.dumps({"results": self.results, "calibration": self.data}, indent=2), encoding="utf-8")
        lines = ["# Calibration report", "", f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "", "| Step | Result | Details |", "| --- | --- | --- |"]
        lines += [f"| {r['title']} | {r['status'].upper()} | {r['message']} |" for r in self.results]
        (self.folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            self._plot()
        except Exception as exc:
            self.log(f"Could not draw the calibration figure: {exc}")

    def _plot(self):
        panels = [k for k in ("rest", "turn", "drive") if k in self.plots]
        if not panels:
            return
        fig, axes = _figure(4 * len(panels), 3.2, 1, len(panels))
        for ax, key in zip(axes[0], panels):
            if key == "rest":
                style_axes(ax, "Gyro at rest", "sample", "rad/s")
                for i, name in enumerate("xyz"):
                    ax.plot(self.plots[key][:, i], color=SERIES[i], lw=1.0, label=name)
                ax.legend(fontsize=7, frameon=False, labelcolor=INK_2, ncols=3)
                continue
            t, y, rate, lag = self.plots[key]
            scale = math.degrees(1) if key == "turn" else 100
            style_axes(ax, "Turn angle vs time" if key == "turn" else "Distance vs time", "motor-on time (s)", "degrees" if key == "turn" else "cm")
            ax.scatter(t, np.array(y) * scale, s=28, color=SERIES[0], edgecolors="#fcfcfb", linewidths=1.2, label="measured", zorder=3)
            xs = np.array([min(t), max(t)])
            ax.plot(xs, rate * (xs - lag) * scale, color=SERIES[1], lw=1.5, label="fit")
            ax.legend(fontsize=7, frameon=False, labelcolor=INK_2)
        fig.savefig(self.folder / "calibration.png", facecolor="#fcfcfb")

    def status(self):
        return {"running": self.running, "current": self.current, "results": self.results,
                "total": len(self.STEPS), "report": self._relative_report()}

    def _relative_report(self):
        if self.running or not (self.folder / "report.md").exists():
            return None
        return (self.folder / "report.md").resolve().relative_to(OUTPUTS_DIR.resolve()).as_posix()
