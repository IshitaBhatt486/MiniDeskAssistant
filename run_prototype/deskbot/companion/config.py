"""
Every tunable of the companion runtime. Explanations: docs/companion.md

Override any value without editing code by creating data/companion.json, for example:

    {"oled": {"driver": "sh1106", "rotate": 2}, "control": {"yaw_kp": 2.0}, "lift": {"on_place": ["reset_map"]}}
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field

from .. import ROOT
from ..config import AppConfig

DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
CONFIG_FILE = DATA_DIR / "companion.json"
CALIBRATION_FILE = DATA_DIR / "calibration.json"
SIM_CALIBRATION_FILE = DATA_DIR / "calibration_sim.json"   # simulation never touches the real robot's numbers
GESTURES_FILE = DATA_DIR / "gestures.json"


@dataclass
class ImuConfig:
    enabled: bool = True
    address: int = 0x68            # 0x69 if AD0 is tied high
    hz: float = 100.0
    madgwick_gain: float = 0.033   # how strongly gravity corrects roll/pitch
    still_gyro: float = 0.04       # rad/s: below this (and still_accel) the robot counts as stationary
    still_accel: float = 0.4       # m/s^2 away from 1 g
    still_hold_s: float = 0.4      # must stay quiet this long
    bias_alpha: float = 0.002      # how fast the gyro bias follows while stationary


@dataclass
class OledConfig:
    enabled: bool = True
    driver: str = "ssd1306"        # ssd1306 | sh1106 (the common 1.3" modules)
    port: int = 1
    address: int = 0x3C
    width: int = 128
    height: int = 64
    rotate: int = 0                # 0-3 quarter turns
    fps: float = 15.0
    gaze_x_px: float = 18.0        # how far the eyes travel when looking fully sideways
    gaze_y_px: float = 9.0
    gaze_smooth: float = 0.35      # 0-1, higher = quicker eyes
    mirror_gaze: bool = True       # screen faces the user: a person on the camera's left is on the screen's right
    blink_min_s: float = 2.5
    blink_max_s: float = 7.0
    replay_min_s: float = 8.0      # the emotion is re-invoked (new random animation) after 8-16 s
    replay_max_s: float = 16.0
    tilt_x_px: float = 13.0        # how far the eyes slide "downhill" at tilt_full_deg of roll
    tilt_y_px: float = 8.0         # ... and of pitch
    tilt_full_deg: float = 30.0
    tilt_sign_x: float = 1.0       # flip if the eyes slide uphill on your build
    tilt_sign_y: float = 1.0
    woozy_start_deg: float = 12.0  # the face starts to look woozy here ...
    woozy_full_deg: float = 28.0   # ... and is fully woozy here


@dataclass
class ControlConfig:
    hz: float = 25.0
    enabled: bool = True
    # heading hold while driving straight: yaw error (rad) -> wheel difference (fraction)
    heading_kp: float = 1.2
    heading_ki: float = 0.3
    heading_kd: float = 0.05
    heading_limit: float = 0.3
    # turn-rate regulation of timed turns: rate error (rad/s) -> speed scale change
    rate_kp: float = 0.15
    rate_ki: float = 0.35
    rate_kd: float = 0.0
    rate_limit_low: float = -0.4
    rate_limit_high: float = 0.8
    # slow down near obstacles
    slow_zone_m: float = 0.25      # starts this far before the stop distance
    min_speed_scale: float = 0.45
    # facing the user: yaw error (rad) -> turn rate (rad/s), cascaded into the rate loop
    yaw_kp: float = 2.2
    yaw_ki: float = 0.1
    yaw_kd: float = 0.08
    max_turn_rate: float = 2.0
    face_deadband_deg: float = 3.0
    face_rate_kp: float = 0.08
    face_rate_ki: float = 0.25
    face_pwm_limit: float = 0.8
    # optional: hold a distance to the user with the front sonar
    keep_distance: bool = False
    distance_m: float = 0.45
    distance_kp: float = 1.2
    distance_ki: float = 0.1
    distance_kd: float = 0.1
    distance_limit: float = 0.35
    distance_deadband_m: float = 0.03
    # a commanded turn that produces almost no rotation
    stall_fraction: float = 0.15
    stall_after_s: float = 0.7


@dataclass
class LiftConfig:
    lift_confirm_s: float = 0.4    # both IR sensors off the desk
    tilt_deg: float = 30.0         # tilted further than a desk allows
    tilt_confirm_s: float = 0.3
    shake_gyro: float = 0.8        # rad/s while the motors are off = being handled
    shake_accel: float = 2.0       # m/s^2 away from 1 g
    shake_confirm_s: float = 0.35
    place_confirm_s: float = 1.0
    place_tilt_deg: float = 15.0
    reset_after_s: float = 1.0     # shorter lifts only resume
    # what to do after being put down, in order. Any of:
    # reset_map, zero_heading, look_around, face_user, greet, save_figures
    on_place: list = field(default_factory=lambda: ["save_figures", "reset_map", "zero_heading", "greet", "look_around"])


@dataclass
class GestureConfig:
    enabled: bool = True
    hz: float = 5.0
    min_score: float = 0.6
    only_with_person: bool = True  # skip the hand model unless YOLO sees a person (saves CPU on the Pi)
    model_url: str = ("https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
                      "gesture_recognizer/float16/latest/gesture_recognizer.task")


@dataclass
class OutputConfig:
    telemetry_hz: float = 5.0
    figure_every_s: float = 180.0  # automatic map figures
    max_auto_figures: int = 100    # per session; manual saves are never limited
    detection_cooldown_s: float = 60.0   # at most one snapshot per object type per minute
    max_detection_snapshots: int = 200


@dataclass
class EmotionConfig:
    idle_sleepy_s: float = 300.0   # nothing has happened for this long
    lonely_s: float = 120.0        # no person seen for this long
    event_hold_s: float = 5.0      # how long a reaction lasts
    near_object_m: float = 0.30    # curious when a sonar reads closer than this...
    near_clear_m: float = 0.36     # ...until it reads farther than this
    near_box_fraction: float = 0.08   # or when a recognised object fills this much of the camera image


@dataclass
class GreetConfig:
    enabled: bool = True
    confirm_s: float = 1.0         # a person must stay in view this long
    absent_s: float = 45.0         # someone returning after this long counts as new
    cooldown_s: float = 30.0       # at least this long between greetings
    min_box_fraction: float = 0.02
    min_score: float = 0.5
    phrases: list = field(default_factory=lambda: ["Hi there!", "Hello! Nice to see you.", "Oh, hello!", "Hey! Good to see you."])


@dataclass
class CompanionConfig:
    imu: ImuConfig = field(default_factory=ImuConfig)
    oled: OledConfig = field(default_factory=OledConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    lift: LiftConfig = field(default_factory=LiftConfig)
    gesture: GestureConfig = field(default_factory=GestureConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    emotion: EmotionConfig = field(default_factory=EmotionConfig)
    greet: GreetConfig = field(default_factory=GreetConfig)


@dataclass
class CompanionAppConfig(AppConfig):
    companion: CompanionConfig = field(default_factory=CompanionConfig)

    def __post_init__(self):
        # body shares the sensor core at normal priority (the real-time sensor loop always wins);
        # gestures share the nav core at the lowest priority and only run a few times a second
        self.runtime.cores.update(body=1, gesture=3)
        self.runtime.nice.update(body=-2, gesture=15)


def _overlay(obj, values, path=""):
    for key, value in values.items():
        name = f"{path}{key}"
        if not dataclasses.is_dataclass(obj) or key not in {f.name for f in dataclasses.fields(obj)}:
            raise ValueError(f"unknown setting {name!r}")
        current = getattr(obj, key)
        if dataclasses.is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object")
            _overlay(current, value, name + ".")
        else:
            setattr(obj, key, value)


def load_config(path=None, warn=print):
    """CompanionAppConfig with data/companion.json applied. A bad file is reported and ignored."""
    cfg = CompanionAppConfig()
    path = path or CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return cfg
    try:
        overlay_cfg = CompanionAppConfig()
        _overlay(overlay_cfg.companion, json.loads(text))
        return overlay_cfg
    except ValueError as exc:
        warn(f"Ignoring {path.name}: {exc}")
        return cfg
