"""
Sensor fusion mapper: ultrasonic + IR + camera detections -> three maps.

    geometric   DecayGrid (grid.py)      where something reflects sound / where the desk ends
    semantic    SemanticMap (semantic.py) WHAT is where: cup, book, phone ... (camera)
    heatmap     fused log-odds            P(object at this cell), stale -> 0.5 (unknown)

Runs in its own thread (inherited from dashboard/mapping.Mapper, 10 Hz). It re-uses the proven
dead-reckoning (wheel_log replay) and the four-sonar mounting geometry from dashboard/multisonar.py.
Same isolation rules as the original mapper: it never touches motors or GPIO, it only reads
robot.latest_reading(), robot.wheel_log and the vision pipeline's published results.

Camera <-> map:
    For each detection, the bottom-centre of its box is where the object stands on the desk.
    Bearing comes from the pixel column; range from intersecting that pixel ray with the desk plane
    (CameraModel.ground_point). If the object is straight ahead (|bearing| <= sonar_fuse_deg) and the
    front ultrasonic sees something at a consistent distance, the sonar range is used instead - sonar
    range is accurate to ~1 cm, the ground-plane estimate degrades with distance squared.
    The frame's capture time is used to look up the robot pose AT THAT TIME (interpolated pose
    history), so a detection that took 80 ms to compute is not smeared by the robot's motion.

Reflections and transparent barriers (glass, acrylic, mirrors):
    * sonar NO-echo readings (max range) add only weak free evidence: the pulse may have bounced away
      off an angled/shiny surface, so a missed echo can't erase an obstacle seen before
    * a reading much LONGER than the previous one (multipath: the echo took a detour) is only
      believed once it repeats (SonarFilter)
    * a camera object far BEHIND the surface the front sonar hears is either seen through glass or a
      reflection: its existence evidence is scaled down
    * cells the sonar says are occupied, that the camera looked at recently and found nothing at, are
      reported as "unrecognised" (wall, glass, or an object YOLO can't name). They stay obstacles in
      the heatmap: sonar evidence is not overruled by the camera's silence.

Full design: docs/fusion.md
"""

from __future__ import annotations

import base64
import bisect
import math
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from multisonar import MAX_DISTANCE, MultiSonarMapper, SONARS  # dashboard/ (on sys.path via deskbot/__init__)

from ..config import AppConfig, object_radius
from ..vision.geometry import CameraModel
from .grid import DecayGrid
from .semantic import Observation, SemanticMap

ROBOT_RADIUS = 0.06       # the robot's own footprint is free space
IR_OFFSET = 0.07          # front/rear IR sensors, ahead/behind the centre


@dataclass
class _Seen:
    bmin: float
    bmax: float
    rng: float


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.uint8).tobytes()).decode()


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class SonarFilter:
    """Multipath rejection for one sonar. A reading SHORTER than the last accepted one is believed at
    once (something came closer: the safe direction). A reading much LONGER is only believed after
    `confirm` consecutive readings agree with each other (an echo that took a detour off an angled or
    shiny surface comes back late, and rarely the same way twice)."""

    def __init__(self, jump_m=0.15, confirm=2):
        self.jump = jump_m
        self.confirm = confirm
        self.accepted = None
        self.pending = []

    def __call__(self, d):
        if d is None:
            return None
        if self.accepted is None or d <= self.accepted + self.jump:
            self.accepted, self.pending = d, []
            return d
        if self.pending and abs(d - self.pending[-1]) > self.jump:
            self.pending = []
        self.pending.append(d)
        if len(self.pending) >= self.confirm:
            self.accepted, self.pending = d, []
            return d
        return None   # not believed yet: skip this reading for mapping (safety uses the raw value)


class FusionMapper(MultiSonarMapper):
    def __init__(self, robot, cfg: AppConfig | None = None, vision=None):
        self.cfg = cfg or AppConfig()
        self.mcfg = self.cfg.mapping
        self.vision = vision
        self.cam = CameraModel(self.cfg.camera)
        self.front = SONARS["front"]
        super().__init__(robot)  # sets up the lock/thread and calls _reset_state()

    # ---------------- state ----------------

    def _reset_state(self):
        super()._reset_state()               # odometry, trail, wheel-log replay state
        self.trail = deque([(0.0, 0.0)], maxlen=self.mcfg.trail_len)
        self.geo = DecayGrid(self.mcfg)
        self.sem = SemanticMap(self.mcfg)
        self.poses = deque(maxlen=400)       # (t, x, y, theta) - ~40 s at 10 Hz
        latest = self.vision.latest() if getattr(self, "vision", None) else None
        self._vision_seq = latest.seq if latest else 0   # don't map frames from before the reset
        self.frames_used = 0
        self.observations = 0
        self.sonar_fused = 0
        mc = self.mcfg
        self.filters = {}
        self.rejected = 0                    # sonar readings held back as possible multipath
        self.behind_surface = 0              # camera detections behind a sonar surface (glass / mirror)
        self.cam_T = np.full((mc.size, mc.size), -np.inf)   # when the camera last looked at each cell
        self._snap = None                    # (key, payload) cache

    def reset(self):
        super().reset()
        det = getattr(getattr(self.vision, "detector", None), "reset", None)
        if det:
            det()  # new map -> new track IDs

    # ---------------- pose history ----------------

    def pose_at(self, t):
        """Interpolated (x, y, theta) at monotonic time t (clamped to the known history)."""
        if not self.poses:
            return self.odom.x, self.odom.y, self.odom.theta
        times = [p[0] for p in self.poses]
        i = bisect.bisect_left(times, t)
        if i <= 0:
            return self.poses[0][1:]
        if i >= len(self.poses):
            return self.poses[-1][1:]
        t0, x0, y0, a0 = self.poses[i - 1]
        t1, x1, y1, a1 = self.poses[i]
        f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        return x0 + f * (x1 - x0), y0 + f * (y1 - y0), a0 + f * _wrap(a1 - a0)

    @staticmethod
    def _to_world(pose, dx, dy):
        x, y, th = pose
        c, s = math.cos(th), math.sin(th)
        return x + dx * c - dy * s, y + dx * s + dy * c

    @staticmethod
    def _to_robot(pose, wx, wy):
        x, y, th = pose
        dx, dy = wx - x, wy - y
        c, s = math.cos(th), math.sin(th)
        return dx * c + dy * s, -dx * s + dy * c

    # ---------------- one update (called by Mapper.step under self._lock) ----------------

    def _integrate(self, reading):
        now = reading["t"]
        o = self.odom
        self.poses.append((now, o.x, o.y, o.theta))
        g = self.geo

        g.floor(o.x, o.y, now, radius=ROBOT_RADIUS)

        for k, (dx, dy, dtheta, d) in enumerate(self.sonar_sources(reading)):
            if d is None:
                continue
            no_echo = d >= MAX_DISTANCE - 0.01
            if not no_echo:
                f = self.filters.setdefault(k, SonarFilter(self.mcfg.jump_confirm_m, self.mcfg.jump_confirm_n))
                d = f(d)
                if d is None:
                    self.rejected += 1
                    continue
            ox, oy = o.transform(dx, dy)
            g.sonar(ox, oy, o.theta + dtheta, d, now, free_delta=self.mcfg.l_free_no_echo if no_echo else None)

        for key, offset in (("front_floor", IR_OFFSET), ("back_floor", -IR_OFFSET)):
            value = reading.get(key)
            if value is None:
                continue
            x, y = o.point(offset)
            if value:
                g.floor(x, y, now)
            else:
                g.mark_edge(x, y)

        if self.vision is not None:
            for res in self.vision.results_since(self._vision_seq):
                self._vision_seq = res.seq
                self._integrate_frame(res, reading)

        last = self.trail[-1]
        if math.hypot(o.x - last[0], o.y - last[1]) >= 0.02:
            self.trail.append((o.x, o.y))
        self.updates += 1
        self._update_times.append(time.monotonic())

    def _integrate_frame(self, res, reading):
        cfg, mc = self.cfg.camera, self.mcfg
        pose = self.pose_at(res.t_capture)
        distances = reading.get("distances") or {}
        front_d = distances.get("front", reading.get("distance"))
        obs, seen = [], []

        for det in res.detections:
            x1, y1, x2, y2 = det.box
            u = (x1 + x2) / 2
            bearing = self.cam.bearing(u)
            seen_rng = None
            truncated = y2 >= cfg.height - 2           # base cut off -> ground range is unreliable
            gp = None if truncated else self.cam.ground_point(u, y2)
            r_ground = None if gp is None else math.hypot(gp[0] - cfg.x, gp[1] - cfg.y)

            point, var, source = None, None, "ground"
            weight = 1.0
            # 1) sonar range when the object is straight ahead and the ranges agree
            if (front_d is not None and front_d < mc.sonar_max_useful
                    and abs(math.degrees(bearing)) <= mc.sonar_fuse_deg):
                r_sonar = front_d + (self.front["x"] - cfg.x)   # sonar range measured from the camera
                if r_ground is None or abs(r_sonar - r_ground) < max(0.08, 0.4 * r_ground):
                    point = (cfg.x + r_sonar * math.cos(bearing), cfg.y + r_sonar * math.sin(bearing))
                    var = 0.02 ** 2 + (r_sonar * 0.03) ** 2
                    source = "sonar"
                    seen_rng = r_sonar
                    self.sonar_fused += 1
            # 2) otherwise the ground-plane estimate, uncertainty growing with distance^2
            if point is None and gp is not None:
                point = gp
                var = (0.02 + 0.10 * r_ground ** 2) ** 2
                seen_rng = r_ground
                # straight ahead, but well BEHIND the surface the sonar hears: seen through glass, or a
                # reflection in it. Keep it, with much less weight.
                if (front_d is not None and front_d < mc.sonar_max_useful
                        and abs(math.degrees(bearing)) <= mc.sonar_fuse_deg
                        and r_ground > front_d + (self.front["x"] - cfg.x) + mc.behind_surface_m):
                    weight = mc.behind_surface_weight
                    source = "behind surface"
                    self.behind_surface += 1
            if seen_rng is not None and seen_rng > mc.max_detect_range:
                continue
            if seen_rng is not None:
                seen.append(_Seen(self.cam.bearing(x2), self.cam.bearing(x1), seen_rng))

            if point is None:
                obs.append(Observation(det.label, det.score, None, None, 1.0, det.track_id))
                continue
            # the box bottom is the object's FRONT face; its centre is ~one radius further away
            rad = object_radius(det.label)
            px, py = point[0] + rad * math.cos(bearing), point[1] + rad * math.sin(bearing)
            wx, wy = self._to_world(pose, px, py)
            obs.append(Observation(det.label, det.score * weight, wx, wy, var, det.track_id, source))

        def visible(lm):
            rx, ry = self._to_robot(pose, lm.x, lm.y)
            dx, dy = rx - cfg.x, ry - cfg.y
            rng = math.hypot(dx, dy)
            if not (0.10 < rng < mc.max_detect_range):
                return False
            # the object's base (front face) must be inside the image
            rad = object_radius(lm.label)
            fx, fy = rx - rad * dx / rng, ry - rad * dy / rng
            if not self.cam.in_view(fx, fy, margin_px=10):
                return False
            b = math.atan2(dy, dx)
            for s in seen:  # hidden behind something nearer that the camera is looking at
                if s.bmin - 0.03 <= b <= s.bmax + 0.03 and s.rng < rng - 0.08:
                    return False
            return True

        self.sem.update(res.t_capture, obs, visible)
        self._mark_viewed(pose, res.t_capture, front_d)
        self.frames_used += 1
        self.observations += len(obs)

    def _mark_viewed(self, pose, t, front_d):
        """Remember which desk cells were inside the camera's view in this frame (up to the detection
        range, and not past the surface straight ahead that the front sonar hears)."""
        cfg, mc = self.cfg.camera, self.mcfg
        X, Y = self.geo.cell_centres()
        x, y, th = pose
        c, s = math.cos(th), math.sin(th)
        cx, cy = x + cfg.x * c - cfg.y * s, y + cfg.x * s + cfg.y * c
        dx, dy = X - cx, Y - cy
        fwd = dx * c + dy * s
        lat = -dx * s + dy * c
        rng = np.hypot(fwd, lat)
        ang = np.abs(np.arctan2(lat, fwd))
        near = cfg.height_m / math.tan(math.radians(cfg.pitch_deg + cfg.vfov_deg / 2))   # closest visible desk
        mask = (fwd > 0) & (ang < self.cam.half_hfov()) & (rng > near) & (rng < mc.max_detect_range)
        if front_d is not None and front_d < mc.sonar_max_useful:
            ahead = ang < math.radians(mc.sonar_cone_half_deg)
            mask &= ~(ahead & (rng > front_d + (self.front["x"] - cfg.x) + self.geo.res))
        self.cam_T[mask] = t

    def unrecognised(self, now, p_geo, sem_labels):
        """Flat indices of cells the sonar says are occupied, the camera looked at recently, and no
        recognised object explains: walls, glass/acrylic, or objects YOLO can't name."""
        mc = self.mcfg
        looked = (now - self.cam_T) < mc.camera_seen_s
        explained = sem_labels > 0
        # grow the objects by one cell: sonar hits land on their front face, just outside the disc
        grown = explained.copy()
        grown[1:] |= explained[:-1]
        grown[:-1] |= explained[1:]
        grown[:, 1:] |= explained[:, :-1]
        grown[:, :-1] |= explained[:, 1:]
        return np.flatnonzero((p_geo > mc.unexplained_p) & looked & ~grown)

    # ---------------- layers ----------------

    def semantic_layer(self, now):
        """(signed log-odds contribution, label index grid, label names) from the object map."""
        n, res = self.geo.n, self.geo.res
        contrib = np.zeros((n, n), np.float32)
        label_idx = np.zeros((n, n), np.uint8)          # 0 = none, k = labels[k-1]
        labels = []
        X, Y = self.geo.cell_centres()
        for lm in self.sem.objects.values():
            e = self.sem.existence(lm, now)
            sigma = math.sqrt(self.sem.variance(lm, now))
            rad = object_radius(lm.label)
            reach = rad + 2.5 * sigma + res
            c0 = max(0, int((lm.x - reach) / res) + n // 2)
            c1 = min(n, int((lm.x + reach) / res) + n // 2 + 1)
            r0 = max(0, int((lm.y - reach) / res) + n // 2)
            r1 = min(n, int((lm.y + reach) / res) + n // 2 + 1)
            if c0 >= c1 or r0 >= r1:
                continue
            d = np.hypot(X[r0:r1, c0:c1] - lm.x, Y[r0:r1, c0:c1] - lm.y)
            w = np.where(d <= rad, 1.0, np.exp(-((d - rad) ** 2) / (2 * max(sigma, res) ** 2)))
            val = (e * w).astype(np.float32)
            sub = contrib[r0:r1, c0:c1]
            stronger = np.abs(val) > np.abs(sub)
            sub[stronger] = val[stronger]
            if lm.label not in labels:
                labels.append(lm.label)
            li = label_idx[r0:r1, c0:c1]
            li[stronger & (val > 0.3)] = labels.index(lm.label) + 1
        return contrib, label_idx, labels

    # ---------------- dashboard ----------------

    def snapshot(self, since=0, epoch=None):
        # Several dashboard tabs poll this; recompute only when the map actually changed (or every
        # second, so ages and decay still move on an idle map).
        key = (self.epoch, self.updates, int(time.monotonic()))
        cached = self._snap
        if cached is not None and cached[0] == key:
            return cached[1]
        payload = self._snapshot()
        self._snap = (key, payload)
        return payload

    def _snapshot(self):
        with self._lock:
            now = time.monotonic()
            g = self.geo
            L_geo = g.logodds(now)
            sem, sem_labels, labels = self.semantic_layer(now)
            fused = np.clip(L_geo + self.mcfg.heat_object_weight * sem, self.mcfg.l_min, self.mcfg.l_max)
            p_geo = 1 / (1 + np.exp(-L_geo))
            p_heat = 1 / (1 + np.exp(-fused))
            p_sem = 1 / (1 + np.exp(-sem))
            conf = np.abs(2 * p_heat - 1)
            observed = g.seen | (sem_labels > 0)
            times = self._update_times
            rate = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
            age = g.age(now)
            seen_age = age[np.isfinite(age)]
            return {
                "epoch": self.epoch,
                "size": g.n,
                "resolution": g.res,
                "row0": "bottom",
                "pose": {"x": self.odom.x, "y": self.odom.y, "theta": self.odom.theta},
                "trail": [[round(x, 3), round(y, 3)] for x, y in self.trail],
                # uint8 layers, row-major, row 0 = bottom of the map; 128 ~ p = 0.5 (unknown)
                "geo": _b64(np.rint(p_geo * 255)),
                "heat": _b64(np.rint(p_heat * 255)),
                "sem_label": _b64(sem_labels),
                "sem_p": _b64(np.rint(p_sem * 255)),
                "edges": np.flatnonzero(g.edge).tolist(),
                "unrecognised": self.unrecognised(now, p_geo, sem_labels).tolist() if self.vision is not None else [],
                "labels": labels,
                "objects": self.sem.describe(now),
                "camera": {"x": self.cfg.camera.x, "y": self.cfg.camera.y, "hfov": self.cfg.camera.hfov_deg,
                           "range": self.mcfg.max_detect_range},
                "stats": {
                    "updates": self.updates,
                    "rate_hz": round(rate, 1),
                    "frames": self.frames_used,
                    "observations": self.observations,
                    "sonar_fused": self.sonar_fused,
                    "multipath_rejected": self.rejected,
                    "behind_surface": self.behind_surface,
                    "objects": len(self.sem.objects),
                    "observed_m2": round(float(observed.sum()) * g.res ** 2, 2),
                    "confident_m2": round(float((conf > 0.6).sum()) * g.res ** 2, 2),
                    "mean_conf": round(float(conf[observed].mean()) if observed.any() else 0.0, 3),
                    "median_age_s": round(float(np.median(seen_age)), 1) if seen_age.size else None,
                    "geo_half_life_s": self.mcfg.geo_half_life_s,
                    "sem_half_life_s": self.mcfg.sem_half_life_s,
                },
                "vision": self.vision is not None,
                "uptime": now - self.started,
            }
