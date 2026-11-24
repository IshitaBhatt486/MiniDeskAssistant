"""
Every tunable for the camera, vision and fusion mapping, in one place.

Pins are NOT here - they stay in robot_config.py. Robot geometry/odometry calibration for the
dead-reckoning stays in dashboard/mapping.py (WHEEL_SPEED_AT_FULL, TRACK_WIDTH) so the old mapper
and the new one agree. Ultrasonic mounting positions stay in dashboard/multisonar.py (MOUNTS).

Explanations of every value: docs/vision.md and docs/fusion.md
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

ENCODER_FILE = Path(__file__).resolve().parent.parent / "data" / "encoders.json"


@dataclass
class CameraConfig:
    # Capture: the ISP scales the sensor image down for free, so ask for the size the detector
    # wants. 320x240 RGB888 (= BGR byte order, exactly what OpenCV/YOLO expect, no conversion).
    width: int = 320
    height: int = 240
    fps: int = 30
    buffer_count: int = 2          # 2 = one being filled, one being read; more only adds latency

    # Field of view. Camera Module 3: 66 x 41 deg, v2 (imx219): 62.2 x 48.8, v1 (ov5647): 53.5 x 41.4.
    # The capture is 4:3; with Module 3 (16:9 sensor) the 4:3 crop keeps the full vertical FOV.
    hfov_deg: float = 62.2
    vfov_deg: float = 48.8

    # Mounting, robot frame (x forward, y left), metres / degrees.
    x: float = 0.05                # ahead of the robot centre
    y: float = 0.0
    height_m: float = 0.09         # lens height above the desk
    pitch_deg: float = 12.0        # tilted down from horizontal (positive = down)

    rotate_180: bool = False       # camera mounted upside down

    @property
    def fx(self):
        return (self.width / 2) / math.tan(math.radians(self.hfov_deg) / 2)

    @property
    def fy(self):
        return (self.height / 2) / math.tan(math.radians(self.vfov_deg) / 2)


@dataclass
class VisionConfig:
    model_name: str = "yolo26n"    # downloaded once from Ultralytics, exported to NCNN by scripts/export-model.sh
    imgsz: int = 320               # 320 is ~4x fewer pixels than 640 -> ~3-4x faster on a Pi 4
    conf: float = 0.10             # detector threshold; ByteTrack (bytetrack.yaml) decides what becomes a track
    classes: list | None = None    # COCO class ids to keep (None = all 80)
    threads: int = 3               # NCNN/OpenMP threads; leaves one Pi 4 core for safety loop + server
    tracker: str = "bytetrack"     # deskbot/vision/bytetrack.yaml
    stream_fps: float = 10.0       # max MJPEG frame rate sent to the dashboard (only while someone watches)
    jpeg_quality: int = 70

    # Detect every N frames, track in between (runtime/ camera process). The detector runs on frame k
    # when >= detect_every frames have passed since the last detection; the frames in between move
    # the boxes with sparse Lucas-Kanade optical flow (~1-2 ms at 320x240 instead of a full inference).
    # If inference is slower than N frame periods, detection simply runs as often as it can.
    detect_every: int = 3          # 3-5: lower = fresher boxes, higher = less CPU
    flow_points: int = 12          # corner points tracked per box
    adaptive_detection: bool = True   # vary the interval (vision/adaptive.py); detect_every is the normal value
    detect_min: int = 2            # while turning
    detect_max_tracking: int = 10  # still scene with objects in view
    detect_max_idle: int = 15      # still scene with nothing in view
    detect_change: float = 6.0     # mean grey-level change (0-255) that triggers a detection at once


@dataclass
class MappingConfig:
    size: int = 80                 # cells per side
    resolution: float = 0.05       # m per cell -> 4 m x 4 m, start pose in the centre
    update_hz: float = 10.0

    # geometric layer (log-odds)
    l_occ: float = 0.85            # sonar hit
    l_free: float = -0.40          # sonar beam passes through
    l_floor: float = -0.60         # IR sees floor / robot footprint
    l_min: float = -4.0
    l_max: float = 4.0
    geo_half_life_s: float = 90.0  # evidence halves every 90 s without a new observation

    # sonar model
    sonar_max_useful: float = 1.2
    sonar_cone_half_deg: float = 7.5
    sonar_rays: int = 5

    # semantic layer (objects from the camera)
    max_detect_range: float = 1.5            # beyond this, camera detections are ignored
    l_hit: float = 1.2                       # existence log-odds added per detection (x score)
    l_miss: float = 0.6                      # removed when an object should be visible but isn't
    sem_half_life_s: float = 45.0            # objects can be moved while unseen -> forget faster than walls
    position_drift: float = 0.0004           # m^2/s position variance growth while unseen (object may move)
    gate_m: float = 0.15                     # association gate added to 2 sigma
    sonar_fuse_deg: float = 10.0             # detections within this bearing use the front sonar range
    prune_logodds: float = -1.0              # drop an object when its evidence falls below this

    # heatmap
    heat_object_weight: float = 1.0          # how strongly semantic objects add to the fused heatmap

    # reflections and transparent barriers (docs/fusion.md section "Reflections and glass")
    l_free_no_echo: float = -0.10            # beam with NO echo: weak free evidence (could be a missed/specular echo)
    jump_confirm_m: float = 0.15             # a reading this much LONGER than the last accepted one...
    jump_confirm_n: int = 2                  # ...is only accepted after this many consecutive agreeing readings
    behind_surface_m: float = 0.15           # camera object this far beyond a sonar surface = seen through glass / reflection
    behind_surface_weight: float = 0.3       # its existence evidence is scaled by this
    camera_seen_s: float = 20.0              # "the camera has looked at this cell" lasts this long
    unexplained_p: float = 0.70              # sonar-occupied cell the camera looked at but found nothing -> "unidentified"

    trail_len: int = 300


@dataclass
class RuntimeConfig:
    """Multi-process runtime (deskbot/runtime/, docs/runtime.md).

    The Pi 4 has 4 cores; each process is pinned to one. Priority (Linux scheduler):
        motor   core 0  SCHED_FIFO 50 (if allowed, else nice -10 / 0)  sleeps between 20 ms safety checks
        sensors core 1  SCHED_FIFO 40 (if allowed, else nice -5 / 0)   sleeps between 50 Hz reads
        camera  core 2  SCHED_OTHER nice 5                              CPU-heavy -> never real-time
        nav     core 3  SCHED_OTHER nice 10                             mapper + behaviour + web server
    Real-time is only used for processes that block between short bursts, and the kernel's RT
    throttling (sched_rt_runtime_us, default 95 %) is left on, so nothing else is starved.
    """
    cores: dict = field(default_factory=lambda: {"motor": 0, "sensors": 1, "camera": 2, "nav": 3})
    rt_priority: dict = field(default_factory=lambda: {"motor": 50, "sensors": 40})
    nice: dict = field(default_factory=lambda: {"motor": -10, "sensors": -5, "camera": 5, "nav": 10})
    sensor_hz: float = 50.0          # sonar + IR publish rate (the safety check runs every 20 ms)
    check_interval: float = 0.02     # motor safety check period during a move
    sensor_stale_s: float = 0.25     # motor stops if the newest sensor sample is older than this
    camera_threads: int = 1          # NCNN threads in the camera process (= its one core)

    # behaviour: face the user when idle
    face_user: bool = True
    user_hold_s: float = 8.0         # after a dashboard command, autonomy waits this long
    face_deadband_deg: float = 8.0   # don't turn for smaller errors
    face_gain: float = 0.7           # fraction of the error corrected per turn (latency -> avoid overshoot)
    face_max_turn_s: float = 0.4
    face_min_turn_s: float = 0.05
    face_search_deg: float = 20.0    # turn toward a remembered (out-of-view) user only beyond this


@dataclass
class NavigationConfig:
    """Obstacle-to-obstacle navigation (deskbot/navigation/, docs/navigation.md)."""
    # robot body
    robot_radius: float = 0.075            # same as the simulator's body radius
    clearance_margin: float = 0.025        # extra gap kept between the body and anything solid
    brake_margin: float = 0.015            # planned stop this far before the motor process's sonar limit

    # planning grid: the 5 cm map is resampled into a window around the route
    fine_res: float = 0.025
    coarse_res: float = 0.05
    fine_max_window_m: float = 2.5         # windows larger than this use coarse_res
    window_margin_m: float = 0.45          # how far the window extends past the start and the target

    # reading the map
    occupied_logodds: float = 0.4          # geometric cell counts as solid above this (p ~ 0.6)
    object_min_logodds: float = 0.3        # camera objects weaker than this are ignored
    object_sigma_k: float = 1.5            # object footprint grows by k x position sigma ...
    object_sigma_max: float = 0.05         # ... up to this much

    # soft costs (only the cost-aware planners use them)
    unknown_cost: float = 1.5              # never-observed floor costs this much extra per metre
    proximity_cost: float = 2.0            # extra cost right next to an obstacle
    proximity_range_m: float = 0.12        # distance over which that extra cost fades out

    # goals around the target
    goal_band_m: float = 0.04              # width of the ring of acceptable stopping places
    max_goals: int = 12                    # goal samples given to the non-grid planners
    arrive_slack_m: float = 0.04           # this close to the ring counts as arrived

    # adaptive selection
    time_budget_ms: float = 150.0          # a planner predicted to exceed this is not chosen
    hard_limit_ms: float = 1500.0          # the last-resort search stops here
    few_obstacles: int = 6                 # at most this many -> visibility graph
    many_obstacles: int = 14               # at least this many -> grid search
    max_visibility_vertices: int = 70
    cluttered_density: float = 0.30        # share of the window the robot cannot occupy
    sparse_density: float = 0.10
    tight_gap_slack_m: float = 0.03        # gap narrower than body width + 2 x this is "tight"
    uncertain_unknown: float = 0.45        # share of the route corridor never observed
    uncertain_sigma_m: float = 0.10        # mean object position uncertainty
    weighted_astar_w: float = 1.8
    default_ms_per_1k: float = 40.0        # first guess of search speed; measured values replace it
    rrt_step_m: float = 0.10
    rrt_goal_bias: float = 0.2
    seed: int = 7                          # sampling planner, so a run can be reproduced

    # continuous driving (used when the robot supports direct wheel commands)
    smooth_driving: bool = True
    corner_radius_m: float = 0.07          # start curving toward the next waypoint this far out
    spin_above_deg: float = 60.0           # turn on the spot only for heading errors above this
    heading_gain: float = 2.5              # rad/s of turn per radian of heading error
    wheel_step: float = 0.08               # largest change of a wheel command per 50 ms tick
    avoid_zone_m: float = 0.10             # steer away when the front sonar is this close to its stop distance

    # driving
    hop_m: float = 0.20                    # re-check the pose and the map after this much driving
    heading_tol_deg: float = 6.0
    waypoint_tol_m: float = 0.035
    max_deviation_m: float = 0.08          # further than this from the route -> replan
    target_moved_m: float = 0.08           # target moved this much -> replan
    max_replans: int = 8
    mission_timeout_s: float = 180.0
    backoff_m: float = 0.05                # reverse this far after a safety stop
    command_settle_s: float = 0.08         # let the motor process pick a command up
    map_settle_s: float = 0.5              # longest wait for the map to catch up after a move
    leg_pause_s: float = 0.6               # pause at the first obstacle
    scan_steps: int = 8                    # look-around when a target is not on the map
    scan_pause_s: float = 0.6
    search_spots: int = 3                  # places to visit when a target isn't found by looking around
    search_step_m: float = 0.35            # how far away those places are
    low_confidence: float = 0.45           # below this the robot checks twice as often and says so


@dataclass
class EncoderConfig:
    """Quadrature wheel encoders on the pins in robot_config.ENCODERS. Scale comes from calibrate_encoders.py."""
    enabled: bool = True
    wheel_diameter_m: float = 0.065
    left_counts_per_rev: float = 20.0
    right_counts_per_rev: float = 20.0
    left_sign: int = 1
    right_sign: int = 1
    calibrated: bool = False       # distance is only trusted after calibration

    def metres_per_count(self):
        return (math.pi * self.wheel_diameter_m / self.left_counts_per_rev,
                math.pi * self.wheel_diameter_m / self.right_counts_per_rev)


def load_encoder_config():
    cfg = EncoderConfig()
    try:
        d = json.loads(ENCODER_FILE.read_text(encoding="utf-8"))
        for key in ("wheel_diameter_m", "left_counts_per_rev", "right_counts_per_rev", "left_sign", "right_sign"):
            setattr(cfg, key, type(getattr(cfg, key))(d[key]))
        cfg.calibrated = True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return cfg


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    mapping: MappingConfig = field(default_factory=MappingConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    navigation: NavigationConfig = field(default_factory=NavigationConfig)
    encoders: EncoderConfig = field(default_factory=load_encoder_config)


# Rough real-world footprint radius (m) per COCO class, used to paint objects into the maps.
OBJECT_RADIUS = {
    "cup": 0.045, "bottle": 0.04, "cell phone": 0.05, "book": 0.10, "laptop": 0.17, "mouse": 0.04,
    "keyboard": 0.15, "remote": 0.04, "scissors": 0.05, "person": 0.25, "chair": 0.25, "tv": 0.25,
    "potted plant": 0.10, "vase": 0.06, "clock": 0.08, "teddy bear": 0.10, "bowl": 0.07,
}
DEFAULT_OBJECT_RADIUS = 0.06


def object_radius(label):
    return OBJECT_RADIUS.get(label, DEFAULT_OBJECT_RADIUS)


# Long, thin things are seen side-on, so their centre is only half their DEPTH behind the front face the camera
# and sonar see; OBJECT_RADIUS is half their length (the footprint). Used only to locate a sighting (24 Nov 2026:
# with the radius a keyboard was placed ~10 cm too far, found in legacy/simplified_code.py).
OBJECT_DEPTH = {"keyboard": 0.05, "tv": 0.05, "remote": 0.02, "scissors": 0.03, "laptop": 0.12}


def object_depth(label):
    return OBJECT_DEPTH.get(label, object_radius(label))
