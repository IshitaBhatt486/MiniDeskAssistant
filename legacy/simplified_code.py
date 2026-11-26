"""
simplified_code.py - one-file robot control: typed CLI + web dashboard (21 Nov 2026).

    python3 legacy/simplified_code.py               # on the Pi (real motors and sensors)
    python3 legacy/simplified_code.py --sim         # laptop: simulated robot on a simulated desk
    python3 legacy/simplified_code.py --port 8080 --no-camera --no-edge
    python3 legacy/simplified_code.py --basic       # only motors, sensors, sensor map, obstacle stops (fastest)
    python3 legacy/simplified_code.py --slam        # SLAM on: sonar scan matching corrects the pose
    python3 legacy/simplified_code.py --ignore-obstacles   # sonars never stop a move ('obstacles on' undoes it)
    python3 legacy/simplified_code.py --oled-driver sh1106 --oled-rotate 2   # 1.3" screen, mounted upside down

Type commands at the "robot>" prompt (also accepted by the dashboard):
    forward [s]   f      drive forward  (default 1 s)
    back [s]      b      drive backward (default 1 s)
    forward 30cm         drive a distance (also 'back 20 cm', 'forward 0.5m', '150mm'): measured by the
                         calibrated wheel encoders, or timed (approximate) without a calibration
    left [s]      l      turn left on the spot  (default 90 deg: measured by the gyro, or timed without one)
                         'left 45deg' / 'right 30°' turn by an angle
    right [s]     r      turn right on the spot (default 90 deg)
    spin [s] [left|right]  spin on the spot (default one full turn, to the left)
    turn <deg>           turn by an angle: + = left, - = right (e.g. 'turn 45', 'turn -120')
    stop          x      stop now
    speed <0.1-1>        motor speed
    status               sensors, pose, current move
    encoders             wheel encoder counts, distance per wheel, calibration
    calibrate [cm]       automatic encoder calibration: drives forward ~25 cm by itself, then
                         calibrate moved <distance>   tell it how far it really went (24cm, 240mm, 0.24m)
    calibrate spin       optional: spins ~1 turn by itself, then
                         calibrate turned <angle>     how far it turned (340, 1 turn) -> turning/heading
    calibrate hand [diameter] [turns]   by hand instead (robot lifted): then 'calibrate next' per wheel
    calibrate cancel | calibrate status
                         Saved to encoders.json and loaded on every start; run it again to redo.
    sim turn left|right [turns]  (simulation only) turn a wheel "by hand" during 'calibrate hand'
    imu                  heading, turn rate, tilt, temperature, gyro bias
    imu zero             set the heading shown to 0
    imu calibrate        robot still on a flat desk: measures the gyro bias and saves "level" (imu.json)
    sim lift [on|off] | sim bump   (simulation only) tilt the robot 35 deg / give it a knock
    touch                touch pad state and counts
    sim touch [hold]     (simulation only) tap / hold the touch pad
    lift [on|off]        lift detection: state / turn it on or off (on by default)
    motors [reverse|normal] [left|right]   a motor wired backwards: flip its direction in software (saved in
                         motors.json). 'forward' goes backwards -> 'motors reverse'; 'forward' spins -> one side
    slam [on|off]        SLAM: sonar scan matching corrects the wheel/gyro pose against the map (off by default)
    invert [on|off]      camera picture rotated 180 deg (ON by default: camera mounted upside down; --no-invert)
    obstacles [ignore|on]  sonar obstacle stops: state / ignore them / watch again (desk edges, lift, tilt and
                         bumps still stop it; also --ignore-obstacles and the dashboard's Obstacles button)
    see                  what the camera recognises, where (also 'look', 'what do you see')
    detect [on|off]      object detection status / switch it
    photo                save the camera picture to photos/ (also the dashboard's Take photo button)
    ask <text>    hey    talk to the robot: "ask what can you see?", "hey turn left and take a photo"
                         (Groq AI first, Claude as fallback, offline rules for plain commands; also the
                         dashboard's Assistant card with a microphone button)
    assistant            which AI brains are ready, where the API keys came from
    map reset            clear the obstacle map (and the objects on it)
    objects              what the camera has recognised and placed on the map, and where it is now
    where is <thing>     e.g. 'where is the cup' (also 'where's my phone')
    objects clear        forget them
    go to <thing>        e.g. 'go to the cup': looks around if needed, faces it, drives up to it (stops ~20 cm
                         in front, at the sonar's safety distance); 'stop' or any command cancels
    find <thing>         look around until it is seen, then face it (no driving)
    go home              drive back to where the map started (0, 0)
    remind me <when> <what>   e.g. 'remind me in 20 minutes to drink water', 'remind me at 5pm to call mom'
    todo <task>          add a task, with or without a time: 'todo buy milk by friday'
    tasks                the open tasks;  done <#n or words>  finish one;  undone <#n>  reopen it
    tasks remove <#n or words> | tasks clear done
    face me              turn to face you once (also 'look at me');  face me on / off  keep facing you
    greet on | off       say hello when someone new shows up (on by default);  people  shows both
    sim person <deg> | off   (simulation only) put a person at that angle (+ = left), 60 cm away
    gestures             hand gestures from the LAPTOP's camera (dashboard Gestures card): what each one does
    gesture map <Name> <action>   e.g. 'gesture map Thumb_Up forward 10cm' (actions: see 'gestures')
    rps                  play rock paper scissors (first to two): show ✊ ✋ ✌ to the laptop camera, or say /
                         type rock, paper, scissors;  rps stop
    weather [city]       the weather (Open-Meteo, free);  weather home <city>  sets the city used when none is said
    joke                 a joke (said out loud);  wiki <topic>  a two-sentence Wikipedia summary
    convert 10 usd to inr   currency conversion (daily rates)
    idea <text>          save an idea (also "remember this idea: ...");  ideas | ideas search <words> | ideas forget <#n>
    phone                Bluetooth: is your phone near?  phone devices | phone use <name or address> | phone forget
    sim phone near|far|away   (simulation only) move the simulated phone
    focus [minutes]      a focus session (default 25 min): nudges when you look away or pick up your phone,
                         then a break;  focus  how it's going;  focus stop
    oled [eyes|status|off]   what the OLED shows (default eyes: they react to what the robot does)
    oled <text>          show text for 6 s (also 'oled say <text>') (\n = new line);  oled ip  shows the dashboard address
    dance [song]         play a random song (or that one) and dance to its beat in pre-coded routines;  dance stop
    songs                the songs it can dance to (built in, plus music files you put in songs/)
    sounds [on|off]      sound effects (played by the dashboard browser);  sound <name>  plays one
    help / quit

Safety: every move is checked 50 times a second. It does not start, and it stops, when
    forward  - front sonar <= 20 cm or the front IR sees no floor
    back     - rear sonar  <= 20 cm or the rear IR sees no floor
    turns    - left/right sonar <= 8 cm or either IR sees no floor
A sensor that cannot be read blocks the moves that need it (fail safe).
The sonars are pinged one at a time (never together, so they cannot hear each other's echoes) and each
reports the median of its last 3 readings, so a single stray echo does not stop a move.
Wheel encoders (GPIO 5/6 left, 20/16 right): a wheel told to turn whose encoder does not move for
0.8 s stops the move ("wheel stuck"). Once calibrated, the pose comes from the encoders instead of
from motor timing.
IMU (MPU-6050 at 0x68 on I2C bus 1, shared with the OLED; read with smbus2): its gyro gives the heading of the
pose and ends turns at the asked angle. It also stops a move when the robot is tilted more than 20 deg (lifted,
tipping off the desk) or bumps into something while driving (a jolt over 0.6 g). Without an IMU everything
still works as before (timed turns, heading from the encoders).
Lift detection: picked up (both IR lose the desk, tilted > 30 deg, or swung by hand) -> motors stop, no moves,
map and pose frozen. Put down (both IR see the desk, level and still, for 1 s) after more than 1 s -> it is
somewhere new: fresh map, pose back to (0, 0). ('sim lift' in simulation.)
Object detection: YOLO26n (NCNN) on the camera, ~3 times a second, boxes drawn on the dashboard video; the eyes
look at what it sees. Needs numpy + OpenCV + ncnn: on the Pi the script restarts itself with ~/deskbot/.venv/bin/python
when the Python it was started with lacks them.
Touch pad (TTP223, I/O on GPIO 7 = physical pin 26, VCC 3.3 V): touching it while the robot moves STOPS the move;
a short tap is a pat (happy eyes); holding it 2 s shows the dashboard address on the OLED.
Assistant: GROQ_API_KEY / ANTHROPIC_API_KEY from secrets.env (next to this file, ~/deskbot/ or run_prototype/).
Replies go on the OLED (text + face) and are spoken by the browser that has the dashboard open (the laptop is
the speaker for now). The microphone needs the https dashboard (https://<pi-address>:8443, self-signed).

Dashboard: http://<pi-address>:8080  - camera, obstacle map, sensors, buttons, OLED mirror.
OLED: 128x64 SSD1306 on I2C bus 1 at 0x3C (luma.oled + Pillow). At start it shows the dashboard address.
Pins: run_prototype/robot_config.py (a copy of the same numbers is built in, so this file also
runs on its own).  Design notes: docs/simplified-code.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------- PINS (same as robot_config.py) ----------------

LEFT_MOTOR = {"forward": 22, "backward": 23, "enable": 13}
RIGHT_MOTOR = {"forward": 27, "backward": 17, "enable": 12}
SONARS = {
    "right": {"trigger": 24, "echo": 25},
    "rear": {"trigger": 4, "echo": 18},
    "left": {"trigger": 21, "echo": 9},
    "front": {"trigger": 10, "echo": 11},
}
IR_FRONT, IR_BACK = 19, 26
ENCODERS = {"left_a": 5, "left_b": 6, "right_a": 20, "right_b": 16}
TOUCH_PIN = 7               # TTP223 touch pad I/O (the "top" pad of robot_config.TOUCH), physical pin 26

try:  # prefer the shared pin file, so a wiring change there is picked up here too
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "run_prototype"))
    import robot_config as _cfg

    LEFT_MOTOR, RIGHT_MOTOR, SONARS = _cfg.LEFT_MOTOR, _cfg.RIGHT_MOTOR, _cfg.SONARS
    IR_FRONT, IR_BACK = _cfg.IR_FRONT, _cfg.IR_BACK
    ENCODERS = getattr(_cfg, "ENCODERS", ENCODERS)
    TOUCH_PIN = getattr(_cfg, "TOUCH", {}).get("top", TOUCH_PIN)
except Exception as exc:  # missing or invalid file: keep the built-in copy
    print(f"[pins] robot_config.py not used ({exc}); using built-in pin numbers")

# ---------------- SETTINGS ----------------

STOP_DISTANCE = 0.20        # m, front (forward) and rear (backward)
SIDE_STOP_DISTANCE = 0.08   # m, left/right while turning
START_MARGIN = 0.03         # m, extra clearance needed to START a move (stops start/stop chatter)
SONAR_MAX = 2.0             # m, HC-SR04 reading clamp
SPEED_OF_SOUND = 343.0      # m/s at ~20 C
FLOOR_VALUE = 0             # IR output LOW = floor detected
STATUS_SHARE_S = 0.1        # the OLED (10/s) and every dashboard tab share one status snapshot this fresh
LOOP_HZ = 50
BOOT_ID = f"{time.time():.3f}"   # changes on every start: the dashboard reconnects its video when it sees a new one
MAX_DURATION = 30.0         # s, longest single move

# Dead reckoning (same rough calibration as dashboard/mapping.py)
WHEEL_SPEED_AT_FULL = 0.25  # m/s of a wheel at 100 % PWM
TRACK_WIDTH = 0.12          # m between the wheels

# Wheel encoders (quadrature, gpiozero RotaryEncoder). Distance needs a calibration, made with the
# 'calibrate' command (or the dashboard); without one the encoders still detect a stuck wheel.
ENCODER_FILES = [Path(__file__).resolve().with_name("encoders.json"),          # next to this script
                 Path(__file__).resolve().parents[1] / "run_prototype" / "data" / "encoders.json"]
STUCK_MIN_COMMAND = 0.2     # weaker motor commands may legitimately not turn a wheel
STUCK_MIN_COUNTS = 2        # encoder counts that prove a wheel is turning
STUCK_AFTER_S = 0.8         # told to turn, encoder still for this long -> stuck
MAX_STEP_M = 0.1            # an encoder jump bigger than this in one 20 ms tick is a glitch, ignored
SIM_ENCODER = {"wheel_diameter_m": 0.065, "left_counts_per_rev": 360.0, "right_counts_per_rev": 360.0,
               "left_sign": 1, "right_sign": 1, "file": "simulated (built in)"}
SIM_CALIBRATION_FILE = Path(__file__).resolve().with_name("encoders_sim.json")  # never mixed with the real one
DEFAULT_WHEEL_DIAMETER = 0.065   # m, suggested by 'calibrate' when there is no earlier calibration
SIDES = ("left", "right")
AUTO_CAL_TARGET_CM = 25     # automatic calibration drives about this far (timed from the speed estimate)
MIN_CAL_COUNTS = 5          # fewer counts than this on a wheel = encoder not working, calibration refused
CAL_SETTLE_S = 0.3          # wait after the calibration move stops before reading the final counts
SIM_TRACK_WIDTH = TRACK_WIDTH   # the simulated robot's true wheel spacing (its "ruler" for 'calibrate spin')

# OLED screen (I2C bus 1: SDA GPIO 2, SCL GPIO 3)
OLED_WIDTH, OLED_HEIGHT = 128, 64
OLED_SLEEPY_AFTER_S = 90.0
OLED_RETRY_S = 2.0          # while the screen is not answering, try to reconnect this often  # no commands or events this long -> sleepy eyes

# IMU: MPU-6050 (or an MPU-6500/9250) on I2C bus 1, same pins as the OLED. Mounted any way up: "level" is
# the direction gravity is measured in while the robot stands on the desk (saved by 'imu calibrate').
GRAVITY = 9.80665
IMU_ADDRESS = 0x68          # 0x69 if the board's AD0 pin is pulled high
IMU_HZ = 100
IMU_RETRY_S = 2.0           # sensor not answering -> try again this often
IMU_FILE = Path(__file__).resolve().with_name("imu.json")
SIM_IMU_FILE = Path(__file__).resolve().with_name("imu_sim.json")
IMU_CAL_S = 1.0             # keep still this long at start-up / 'imu calibrate' (gyro bias)
IMU_CAL_GYRO_SPREAD = 0.06  # rad/s: more spread than this during the bias window = it was moving, try again
IMU_CAL_ACCEL_SPREAD = 0.6  # m/s^2, same for the accelerometer
IMU_STILL_GYRO = 0.03       # rad/s and ...
IMU_STILL_ACCEL = 0.3       # ... m/s^2: quieter than this, motors off, for IMU_STILL_HOLD_S = standing still:
IMU_STILL_HOLD_S = 0.5      #     the gyro bias is updated and the heading frozen (stops slow drift)
IMU_BIAS_ALPHA = 0.01       # per sample while still (time constant ~1 s at 100 Hz)
IMU_TILT_STOP_DEG = 20.0    # tilted more than this (lifted, tipping) -> no moves
IMU_BUMP_MS2 = 0.6 * GRAVITY   # jolt (accel minus its slow average) this big while driving -> stop
IMU_BUMP_IGNORE_S = 0.3     # ... but not in the first 0.3 s of a move (the motors starting jolt it)
IMU_TURN_LEAD_DEG = 3.0     # end a gyro turn this early: the robot coasts the rest
# Drive by distance (24 Nov 2026): 'forward 30cm' ends when the calibrated encoders have rolled that far
DRIVE_LEAD_M = 0.005        # end this early: the robot coasts the rest (measure on the robot and tune)
DRIVE_MIN_M, DRIVE_MAX_M = 0.01, 3.0

# Lift detection (from run_prototype deskbot/presence/lift.py + companion/lift.py, same numbers).
# Lifted when one of these holds for its confirm time: both IR sensors see no desk / tilted past LIFT_TILT_DEG /
# motors off but being swung or shaken while at least one IR has lost the desk.
LIFT_CONFIRM_S = 0.4        # both IR sensors off the desk this long
LIFT_TILT_DEG = 30.0        # tilted further than a desk allows ...
LIFT_TILT_CONFIRM_S = 0.3   # ... this long
LIFT_SHAKE_GYRO = 0.8       # rad/s with the motors off = being handled
LIFT_SHAKE_ACCEL = 2.0      # m/s^2 away from 1 g
LIFT_SHAKE_CONFIRM_S = 0.35
PLACE_CONFIRM_S = 1.0       # put down: both IR see the desk (and the IMU is level and still) this long
PLACE_TILT_DEG = 15.0
LIFT_RESET_AFTER_S = 1.0    # up at least this long = somewhere new -> fresh map; shorter = just resume
LIFT_STUCK_WARN_S = 120.0   # "lifted" this long with both IR dark: maybe the IR sensors are unplugged

# Object detection: YOLO26n exported to NCNN (run_prototype/models/yolo26n_ncnn_model), same pre/post-processing
# as run_prototype deskbot/vision/ncnn_detector.py, without the ByteTrack tracker. Needs numpy, OpenCV and ncnn:
# on the Pi that is the project venv (~/deskbot/.venv/bin/python), not the system python3.
_HERE = Path(__file__).resolve().parent
DETECT_MODEL_DIRS = [_HERE / "models" / "yolo26n_ncnn_model",
                     _HERE.parent / "run_prototype" / "models" / "yolo26n_ncnn_model",
                     Path.home() / "deskbot" / "models" / "yolo26n_ncnn_model"]
DETECT_CONF = 0.35          # run_prototype uses 0.10 because ByteTrack filters after it; with no tracker, 0.35
DETECT_IOU = 0.5            # class-aware NMS overlap (Ultralytics' default)
DETECT_IMGSZ = 320          # used when the model folder has no metadata.yaml
DETECT_THREADS = 2          # NCNN threads: leaves 2 Pi 4 cores for the control loop, sonars, IMU, camera, server
DETECT_PERIOD_S = 0.3       # at most ~3 detections a second (the Pi 4 needs ~0.15-0.25 s per frame)
DETECT_STALE_S = 1.5        # detections older than this are not shown or used
CAMERA_HFOV_DEG = 62.2      # horizontal field of view: Pi camera v2 (v3: 66, typical USB webcam: ~60)
CAMERA_VFOV_DEG = 48.8      # vertical field of view (v2; v3: 41)
CAMERA_X_M = 0.05           # camera mounting (run_prototype CameraConfig): ahead of the robot centre,
CAMERA_HEIGHT_M = 0.09      #   lens height above the desk,
CAMERA_PITCH_DEG = 12.0     #   tilted down from horizontal

# Objects on the map (24 Nov 2026, run_prototype mapping/semantic.py + fusion.py, same numbers)
OBJ_SONAR_DEG = 10.0        # a detection this close to straight ahead takes its range from the front sonar
OBJ_SONAR_MAX_M = 1.2       # ... if the sonar reads less than this
OBJ_BEHIND_SURFACE_M = 0.15 # camera range this far beyond the sonar's surface: a reflection / seen through glass
OBJ_MAX_RANGE_M = 1.5       # ground-plane ranges beyond this are too uncertain to place
OBJ_L_HIT, OBJ_L_MISS = 1.2, 0.6     # existence log-odds per detection (x score) / per miss while in view
OBJ_L_MAX, OBJ_L_MIN = 4.0, -4.0
OBJ_HALF_LIFE_S = 45.0      # existence fades: things get moved while the robot looks elsewhere
OBJ_DRIFT = 0.0004          # m^2/s position variance growth while unseen
OBJ_GATE_M = 0.15           # a sighting this close (+ 2 sigma) to a landmark with the same label is that landmark
OBJ_PRUNE_LOGODDS = -1.0    # forget a landmark below this
OBJ_SHOW_P = 0.6            # shown / answered only when at least this sure
OBJ_TURN_SKIP_DPS = 30.0    # no updates while turning faster than this (blur, and the pose lags the picture)
OBJ_AFTER_TURN_S = 0.3      # ... nor from pictures taken less than this after a turn (they may be mid-turn)
OBJ_SKIP = ("person", "dining table", "bed", "couch")   # not standing on the desk: the ground range is meaningless
OBJ_RADIUS = {"cup": 0.045, "bottle": 0.04, "cell phone": 0.05, "book": 0.10, "laptop": 0.17, "mouse": 0.04,
              "keyboard": 0.15, "remote": 0.04, "scissors": 0.05, "chair": 0.25, "tv": 0.25, "potted plant": 0.10,
              "vase": 0.06, "clock": 0.08, "teddy bear": 0.10, "bowl": 0.07}
OBJ_DEFAULT_RADIUS = 0.06

# Go to an object (24 Nov 2026)
NAV_SCAN_DEG = 40           # look around in steps this big (< the 62 deg field of view, so nothing is skipped)
NAV_SCAN_STEPS = 10         # ... at most this many (one full turn)
NAV_LOOK_S = 1.0            # stand still this long after each step so the camera adds a few frames
NAV_SETTLE_S = 0.3          # after each move, before looking
NAV_FACE_DEG = 8.0          # turn to face the target when it is further off than this
NAV_LEG_M = 0.25            # drive at most this far before looking again
NAV_STANDOFF_M = 0.22       # stop with the object this far in front of the front sonar (its stop distance is 0.20)
NAV_ARRIVE_M = 0.03         # close enough
NAV_MAX_LEGS = 14
# Long, thin things: the camera/sonar see their long side, so the centre is only half their DEPTH further away
# (OBJ_RADIUS is half their length, used for the size drawn on the map).
OBJ_DEPTH = {"keyboard": 0.05, "tv": 0.05, "remote": 0.02, "scissors": 0.03, "laptop": 0.12}
# The project venv: has OpenCV + ncnn (and, via system site packages, everything the system python3 has).
# Started with a Python that lacks them, the script restarts itself with this one (see use_project_venv()).
VENV_PYTHONS = [Path.home() / "deskbot" / ".venv" / "bin" / "python",
                _HERE.parent / "run_prototype" / ".venv" / "bin" / "python"]
PHOTO_DIR = _HERE / "photos"  # 'photo' / the dashboard button save here
ERRORS_FILE = _HERE / "errors.log"
# Bluetooth phone presence (24 Nov 2026, run_prototype presence/ble.py numbers)
PHONE_FILE = _HERE / "phone.json"           # which phone to listen for
MOTORS_FILE = _HERE / "motors.json"         # {"left": bool, "right": bool}: motor wired backwards ('motors reverse')
# Gestures (laptop camera, recognised in the browser) + rock paper scissors (24 Nov 2026)
GESTURES_FILE = _HERE / "gestures.json"     # what each gesture does
# Web APIs + ideas (24 Nov 2026)
APIS_FILE = _HERE / "apis.json"             # the home city for the weather
API_TIMEOUT_S = 6.0
IDEAS_FILE = _HERE / "ideas.json"
IDEAS_MAX, IDEAS_MAX_TEXT, IDEAS_WAIT_S = 500, 500, 60.0   # "remember this idea" alone: the next minute's words are it
RPS_MOVE_S = 6.0            # a round: the count-down is said (~2.5 s), then this long in all to show a move
RPS_NEXT_S = 3.0            # pause after a result before the next count-down
RPS_WIN = 2                 # first to two
BLE_TX_1M, BLE_PATH_N = -59.0, 2.2          # RSSI at 1 m, indoor path-loss exponent (for the rough distance)
BLE_EMA = 0.3                               # weight of a new RSSI sample in the smoothed value
BLE_NEAR_RSSI, BLE_AWAY_RSSI = -67.0, -85.0  # near at or above / away below (hysteresis in between)
BLE_NEAR_HOLD_S, BLE_AWAY_HOLD_S = 2.0, 10.0
BLE_AWAY_TIMEOUT_S = 25.0                   # not heard for this long = away
BLE_RETRY_S = 20.0                          # Bluetooth adapter error: try again after this   # full tracebacks of anything that failed (the dashboard shows one line)

# Assistant (24 Nov 2026, from run_prototype pro/groq_brain.py + assistant/): Groq first, Claude as fallback,
# offline rules for plain commands. Keys: GROQ_API_KEY / ANTHROPIC_API_KEY in the environment or secrets.env.
SECRETS_FILES = [_HERE / "secrets.env", Path.home() / "deskbot" / "secrets.env",
                 _HERE.parent / "run_prototype" / "secrets.env"]
GROQ_URL = "https://api.groq.com/openai/v1"
AI_GROQ_MODEL = "openai/gpt-oss-120b"       # run_prototype's default; "openai/gpt-oss-20b" is faster
AI_STT_MODEL = "whisper-large-v3-turbo"     # Groq speech to text (the dashboard microphone)
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
AI_CLAUDE_MODEL = "claude-opus-5-5"         # --claude-model claude-haiku-5-5 is what run_prototype uses (cheaper)
AI_TIMEOUT_S = 25.0         # per HTTP request
AI_HISTORY = 6              # earlier AI exchanges sent along as context
AI_RECENT = 8               # exchanges shown on the dashboard
AI_MAX_COMMANDS = 6         # robot commands per reply
AI_MAX_DRIVE_S = 3.0        # longest forward/back the AI may ask for (about 36 cm at speed 0.5)
AI_MAX_DRIVE_M = 0.5        # ... or by distance
AI_COMMANDS = ("forward", "back", "left", "right", "turn", "spin", "stop", "photo", "remind", "todo", "done",
               "focus", "face", "rps", "dance")
AI_MOODS = ("happy", "sad", "angry", "scared", "focused", "sleepy", "normal")   # = the OLED faces
# Faces + focus timer (24 Nov 2026, run_prototype hub/focus.py)
MODEL_DIRS = [Path.home() / "deskbot" / "models", _HERE.parent / "run_prototype" / "models", _HERE / "models"]
YUNET_NAME = "face_detection_yunet_2023mar.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/" + YUNET_NAME
FACE_HZ = 4.0               # face detection at most this often, and only while a feature asks for it
FOCUS_FILE = _HERE / "focus.json"
FOCUS_DEFAULT_MIN, FOCUS_BREAK_MIN, FOCUS_LONG_BREAK_MIN = 25, 5, 15   # long break after every 4th session
FOCUS_HZ = 2.0
FOCUS_YAW_TOL, FOCUS_PITCH_TOL = 0.35, 0.22   # head turned / tipped further than this from "looking at work"
FOCUS_BASELINE_S = 4.0      # the first seconds with a face in view = looking at the work
FOCUS_GRACE_S, FOCUS_REPEAT_S, FOCUS_PHONE_S, FOCUS_RESET_S = 20.0, 45.0, 10.0, 3.0
FOCUS_NO_FACE_AWAY_N = 3    # a person but no face this many checks in a row = turned right round
FOCUS_MIN_FACE = 0.008      # faces smaller than this share of the picture (further than ~1 m) are someone else
FOCUS_GOOD = 0.8            # a session this focused gets a "great session"
FOCUS_KEEP = 30             # sessions kept in focus.json
# Face me + greeter (24 Nov 2026)
PEOPLE_HZ = 4.0             # how often 'keep facing me' and the greeter look
FACE_USER_OK_DEG = 5.0      # 'face me': already facing you when closer than this
FACE_USER_KEEP_DEG = 10.0   # 'face me on': re-aim when you are further off than this ...
FACE_USER_CONFIRM_S = 0.6   # ... for this long (not detector flicker)
FACE_USER_QUIET_S = 2.0     # ... and nobody has given a command for this long (it never fights you)
GREET_CONFIRM_S, GREET_ABSENT_S, GREET_COOLDOWN_S = 1.0, 45.0, 30.0   # run_prototype GreeterConfig
GREET_MIN_BOX, GREET_MIN_SCORE = 0.02, 0.5   # a person box this big (share of the picture) and sure counts
USER_MEMORY_S = 1.0         # a detector that misses the user for a frame or two: use where they were last seen

# Tasks and reminders (24 Nov 2026, run_prototype buddy/)
TASKS_FILE = _HERE / "tasks.json"
TASKS_MAX, TASKS_MAX_TITLE, TASKS_KEEP_DONE_DAYS = 200, 120, 14
TASKS_SOON_MIN = 15         # "heads up" this long before a deadline (if the task was added before that)
TASKS_OVERDUE_MIN = 60      # "still open" this long after it
TASKS_CHECK_S = 5.0
TLS_DIR = _HERE / "tls"     # self-signed certificate for the https dashboard (the browser microphone needs it)
HTTPS_PORT = 8443
COCO_NAMES = ("person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign "
              "parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella "
              "handbag tie suitcase frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard "
              "surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl banana apple sandwich orange "
              "broccoli carrot hot_dog pizza donut cake chair couch potted_plant bed dining_table toilet tv laptop "
              "mouse remote keyboard cell_phone microwave oven toaster sink refrigerator book clock vase scissors "
              "teddy_bear hair_drier toothbrush")
COCO_NAMES = [n.replace("_", " ") for n in COCO_NAMES.split()]   # fallback when metadata.yaml has no names

# Touch pad (TTP223, default jumpers: output HIGH while touched). Read by the control loop at 50 Hz.
TOUCH_HOLD_S = 2.0          # held this long -> the OLED shows the dashboard address

# Sonar mounting: angle (rad, CCW from robot forward) and distance from the robot centre (m)
SONAR_MOUNT = {"front": (0.0, 0.06), "left": (math.pi / 2, 0.05),
               "right": (-math.pi / 2, 0.05), "rear": (math.pi, 0.06)}

# Occupancy map
MAP_SIZE_M = 4.0
CELL_M = 0.05
# Noise filter (24 Nov 2026, run_prototype runtime/sensor_filter.py numbers)
FILTER_WINDOW = 25          # readings looked at for flicker (~2 s of sonar, 0.5 s of IR)
FILTER_JUMP_M = 0.30        # a sonar "bounce": jumped more than this and straight back ...
FILTER_BOUNCES = 4          # ... this many times in the window = flickering
FILTER_TO_EDGE, FILTER_TO_FLOOR = 2, 5   # IR ticks before "no floor" / "floor again" is believed
FILTER_IR_FLIPS = 6         # an IR that changes this often in the window is flickering
# Sensor fusion map
IR_MOUNT_M = 0.08           # the IR edge sensors look at the desk this far ahead / behind the robot centre
FOOTPRINT_M = 0.06          # cells this close to where the robot drove are surely free
FUSION_DECAY_S, FUSION_DECAY = 2.0, 0.97   # every 2 s evidence fades by 3 % (stale obstacles vanish in ~2 min)
TRAIL_N = 400               # robot positions kept for the trail
MAP_N = int(MAP_SIZE_M / CELL_M)   # 80 x 80 cells, robot starts in the middle
HIT, MISS, CLAMP = 3, 1, 12        # log-odds style counters


def log(msg):
    print(f"\n[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_calibration(d, source):
    """A validated calibration dict from the JSON data `d`, or None."""
    try:
        cal = {"wheel_diameter_m": float(d["wheel_diameter_m"]),
               "left_counts_per_rev": float(d["left_counts_per_rev"]),
               "right_counts_per_rev": float(d["right_counts_per_rev"]),
               "left_sign": 1 if int(d.get("left_sign", 1)) >= 0 else -1,
               "right_sign": 1 if int(d.get("right_sign", 1)) >= 0 else -1,
               "revolutions": d.get("revolutions"), "calibrated_at": d.get("calibrated_at"),
               "method": d.get("method"), "measured_m": d.get("measured_m"), "measured_deg": d.get("measured_deg"),
               "counts": d.get("counts"), "track_width_m": None, "file": str(source)}
        tw = d.get("track_width_m")
        if tw is not None and 0.04 <= float(tw) <= 0.5:       # out of range -> ignored, built-in value used
            cal["track_width_m"] = float(tw)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    ok = all(math.isfinite(cal[k]) and cal[k] > 0
             for k in ("wheel_diameter_m", "left_counts_per_rev", "right_counts_per_rev"))
    return cal if ok else None


def load_encoder_calibration(files=None):
    """The first valid calibration file in `files` (default ENCODER_FILES), or None."""
    for f in ENCODER_FILES if files is None else files:
        try:
            cal = parse_calibration(json.loads(f.read_text(encoding="utf-8")), f)
        except (OSError, ValueError):
            continue
        if cal:
            return cal
    return None


def parse_distance(args):
    """Metres from command words like ['30cm'], ['30', 'cm'], ['0.5m'], ['150mm'], or None if there is no
    distance (a bare number means seconds). Raises ValueError when out of range."""
    units = {"cm": 0.01, "mm": 0.001, "m": 1.0, "centimetres": 0.01, "centimeters": 0.01, "metres": 1.0,
             "meters": 1.0, "metre": 1.0, "meter": 1.0, "millimetres": 0.001, "millimeters": 0.001}
    for i, a in enumerate(args):
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]*)", a)
        if not m:
            continue
        unit = m.group(2) or (args[i + 1] if i + 1 < len(args) else "")
        if unit in units:
            d = float(m.group(1)) * units[unit]
            if not DRIVE_MIN_M <= d <= DRIVE_MAX_M:
                raise ValueError(f"distance must be {DRIVE_MIN_M * 100:.0f} cm to {DRIVE_MAX_M:.0f} m")
            return d
    return None


def sleep_until(deadline, stop):
    """Sleep until `deadline` (time.monotonic()). Short waits use time.sleep: since Python 3.11 it has ~1 ms
    resolution on Windows too, where Event.wait rounds up to 15.6 ms steps (a 20 ms tick became 31 ms, so the
    control loop ran at 33 Hz in simulation). Long waits use the stop Event so shutting down stays instant."""
    delay = deadline - time.monotonic()
    if delay <= 0:
        return
    if delay > 0.05:
        stop.wait(delay - 0.02)
        delay = deadline - time.monotonic()
    if delay > 0 and not stop.is_set():
        time.sleep(delay)


def metres_per_count(cal):
    """(left, right) metres of wheel travel per encoder count."""
    return (math.pi * cal["wheel_diameter_m"] / cal["left_counts_per_rev"],
            math.pi * cal["wheel_diameter_m"] / cal["right_counts_per_rev"])


# =====================================================================
# Hardware
# =====================================================================

class SonarScanner:
    """Pings the HC-SR04 sonars ONE AT A TIME from one background thread.

    gpiozero's DistanceSensor gives every sensor its own thread; a lock stops two pinging at the same instant,
    but each fires the moment the previous echo ends, while that ping is still bouncing around, so it hears it. Measured on the robot (23 Nov 2026): the right sonar, normally 200 cm, read 16.3 cm (the
    front sonar's obstacle) 11 times in 4 s, and the rear one dropped to 18 cm 70 times. Each false reading
    stopped the running move. Here each ping has the air to itself: trigger, time the echo pulse with the pin
    factory's edge timestamps (lgpio alerts on the Pi, microsecond resolution), wait for the echoes to die down,
    then the next sensor. Each sensor reports the median of its last 3 readings, so one stray echo is ignored.
    """

    ECHO_TIMEOUT = 0.07     # s: no complete echo pulse by then (rising edge never came = no echo / wiring)
    GAP = 0.015             # s of silence after each ping so its echoes fade before the next sensor fires
    WINDOW = 3              # readings kept per sensor for the median
    STALE = 1.0             # s: readings older than this do not count

    def __init__(self, sonars):
        from gpiozero import Device

        self.factory = Device.pin_factory
        if self.factory is None:      # normally already set: the motors are created first
            self.factory = Device.pin_factory = Device._default_pin_factory()
        self.pins, self.errors, self._callbacks = {}, {}, []
        self.history = {name: [] for name in sonars}
        self.no_echo = {name: 0 for name in sonars}
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._active = self._rise = self._fall = None
        for name, p in sonars.items():
            trig = echo = None
            try:
                trig = self.factory.pin(p["trigger"])
                trig.function, trig.state = "output", False
                echo = self.factory.pin(p["echo"])
                echo.function, echo.pull = "input", "down"
                echo.edges, echo.bounce = "both", None
                cb = (lambda ticks, state, n=name: self._edge(n, ticks, state))
                self._callbacks.append(cb)     # gpiozero only keeps a weak reference to when_changed
                echo.when_changed = cb
                self.pins[name] = (trig, echo)
            except Exception as exc:
                for pin in (trig, echo):
                    try:
                        pin and pin.close()
                    except Exception:
                        pass
                self.errors[name] = f"{type(exc).__name__}: {exc}"
                log(f"[sensor] {name} sonar unavailable: {self.errors[name]}")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sonars")
        self._thread.start()

    def _edge(self, name, ticks, state):
        if name != self._active:
            return
        if state:
            self._rise = ticks
        elif self._rise is not None:
            self._fall = ticks
            self._done.set()

    def ping(self, name):
        """One measurement in metres (SONAR_MAX = nothing in range), or None (no echo at all)."""
        trig, _ = self.pins[name]
        self._rise = self._fall = None
        self._done.clear()
        self._active = name
        trig.state = True
        time.sleep(0.00001)            # >= 10 us trigger pulse (Python makes it ~50-100 us, which is fine)
        trig.state = False
        got = self._done.wait(self.ECHO_TIMEOUT)
        self._active = None
        if not got:
            return SONAR_MAX if self._rise is not None else None   # echo still high = nothing in range
        dt = self.factory.ticks_diff(self._fall, self._rise)
        return max(0.0, min(SONAR_MAX, dt * SPEED_OF_SOUND / 2))

    def _run(self):
        while not self._stop.is_set():
            if not self.pins:
                self._stop.wait(1.0)
                continue
            for name in self.pins:
                if self._stop.is_set():
                    return
                try:
                    d = self.ping(name)
                except Exception as exc:
                    d = None
                    self.errors[name] = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    h = self.history[name]
                    h.append((d, time.monotonic()))
                    del h[:-self.WINDOW]
                    self.no_echo[name] = self.no_echo[name] + 1 if d is None else 0
                self._stop.wait(self.GAP)

    def value(self, name):
        """Median of the recent readings, metres; None when the sensor has no usable recent reading."""
        now = time.monotonic()
        with self._lock:
            recent = [d for d, t in self.history.get(name, []) if now - t <= self.STALE]
        valid = sorted(d for d in recent if d is not None)
        if len(valid) >= 2:
            return valid[1] if len(valid) == 3 else valid[0]    # 3 -> median, 2 -> the closer (cautious)
        if len(valid) == 1 and len(recent) == 1:
            return valid[0]                                     # only one reading so far (start-up)
        return None

    def reason(self, name):
        if name in self.errors:
            return self.errors[name]
        if self.no_echo.get(name, 0) >= 2:
            p = SONARS[name]
            return f"no echo - check its wiring (TRIG GPIO {p['trigger']}, ECHO GPIO {p['echo']}, 5 V, GND)"
        return ""

    def close(self):
        self._stop.set()
        self._thread.join(timeout=0.5)
        for trig, echo in self.pins.values():
            for pin in (echo, trig):
                try:
                    if pin is echo:
                        pin.when_changed = None
                    pin.close()
                except Exception:
                    pass


def load_motor_reversal(path=MOTORS_FILE):
    """{"left": bool, "right": bool} from motors.json (missing/bad file = both normal)."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"left": bool(d.get("left")), "right": bool(d.get("right"))}
    except (OSError, ValueError, AttributeError):
        return {"left": False, "right": False}


def save_motor_reversal(rev, path=MOTORS_FILE):
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(rev), encoding="utf-8")
    os.replace(tmp, path)


class RealHardware:
    """gpiozero devices. Each sensor is opened on its own so one bad part does not stop the rest."""

    mode = "robot"

    def __init__(self, use_encoders=True, use_imu=True, imu_address=IMU_ADDRESS, touch_pin=TOUCH_PIN):
        from gpiozero import DigitalInputDevice, Motor  # raises off the Pi

        self.reversed = load_motor_reversal()   # a motor wired backwards: its sign is flipped in drive()
        self.left = Motor(**LEFT_MOTOR)
        try:
            self.right = Motor(**RIGHT_MOTOR)
        except Exception:
            self.left.close()
            raise
        self.irs = {}
        self.ir_errors = {}                  # name -> why the IR could not be opened
        self._ir_pins = {"front": IR_FRONT, "rear": IR_BACK}
        self._ir_class = DigitalInputDevice
        self._ir_retry_at = 0.0
        try:
            self.scanner = SonarScanner(SONARS)
        except Exception as exc:
            self.scanner = None
            log(f"[sensor] sonars unavailable: {type(exc).__name__}: {exc}")
        for name in self._ir_pins:
            self._open_ir(name)
        self.calibration = load_encoder_calibration()
        self.calibration_path = ENCODER_FILES[0]     # where 'calibrate' saves
        self.encoder_devs, self.encoder_error = None, "disabled (--no-encoders)"
        if use_encoders:
            self._open_encoders()
        # never raises: a missing sensor is reported in its status and looked for again every 2 s
        self.imu = Imu(Mpu6050(1, imu_address), IMU_FILE) if use_imu else None
        self.touch_pin, self.touch_dev, self.touch_error = touch_pin, None, "disabled (--no-touch)"
        if touch_pin is not None:
            try:      # pull-down: an unplugged pad reads "not touched", never a phantom touch
                self.touch_dev = DigitalInputDevice(touch_pin, pull_up=False)
                self.touch_error = ""
            except Exception as exc:
                self.touch_error = f"GPIO {touch_pin}: {type(exc).__name__}: {exc}"
                if "busy" in str(exc).lower():
                    self.touch_error += " - pin in use (SPI on? sudo raspi-config nonint do_spi 1; or another script)"
                log(f"[sensor] touch pad unavailable: {self.touch_error}")

    def touched(self):
        """True while the pad is touched, False when not, None when it cannot be read."""
        if self.touch_dev is None:
            return None
        try:
            return bool(self.touch_dev.value)
        except Exception as exc:
            self.touch_error = f"read failed: {type(exc).__name__}: {exc}"
            return None

    def _open_encoders(self):
        from gpiozero import RotaryEncoder

        opened = []
        try:
            for side in ("left", "right"):
                opened.append(RotaryEncoder(ENCODERS[f"{side}_a"], ENCODERS[f"{side}_b"], max_steps=0))
            self.encoder_devs, self.encoder_error = tuple(opened), ""
        except Exception as exc:
            for dev in opened:
                dev.close()
            self.encoder_error = f"{type(exc).__name__}: {exc}"
            log(f"[sensor] wheel encoders unavailable: {self.encoder_error}")

    def encoders(self):
        """(left, right) counts, positive = wheel turning forward, or None."""
        if self.encoder_devs is None:
            return None
        cal = self.calibration or {}
        return (self.encoder_devs[0].steps * cal.get("left_sign", 1),
                self.encoder_devs[1].steps * cal.get("right_sign", 1))

    def raw_encoders(self):
        """(left, right) counts exactly as the encoders give them (no sign correction), or None."""
        if self.encoder_devs is None:
            return None
        return self.encoder_devs[0].steps, self.encoder_devs[1].steps

    def _open_ir(self, name):
        pin = self._ir_pins[name]
        try:
            self.irs[name] = self._ir_class(pin)
            if name in self.ir_errors:
                log(f"[sensor] {name} IR (GPIO {pin}) now available")
            self.ir_errors.pop(name, None)
        except Exception as exc:
            msg = f"GPIO {pin}: {type(exc).__name__}: {exc}"
            if "busy" in str(exc).lower():
                msg += " - another program holds the pin (sudo systemctl stop deskbot?)"
            if self.ir_errors.get(name) != msg:
                log(f"[sensor] {name} IR unavailable: {msg}")
            self.ir_errors[name] = msg

    def drive(self, left, right):
        """left/right: -1..1, + = the robot's forward. A side marked reversed (motors.json) gets the opposite
        sign here, at the very last step, so everything above (directions, safety checks, odometry) stays right."""
        if self.reversed["left"]:
            left = -left
        if self.reversed["right"]:
            right = -right
        for motor, v in ((self.left, left), (self.right, right)):
            if v > 0:
                motor.forward(min(v, 1.0))
            elif v < 0:
                motor.backward(min(-v, 1.0))
            else:
                motor.stop()

    def read(self, pose=None):
        """{"sonar": {name: metres|None}, "floor": {name: True|False|None}}"""
        if self.ir_errors and time.monotonic() >= self._ir_retry_at:  # retry a failed IR every 2 s
            self._ir_retry_at = time.monotonic() + 2.0
            for name in list(self.ir_errors):
                self._open_ir(name)
        floor = {}
        for name in ("front", "rear"):
            dev = self.irs.get(name)
            try:
                floor[name] = None if dev is None else dev.value == FLOOR_VALUE
            except Exception as exc:
                self.ir_errors[name] = f"read failed: {type(exc).__name__}: {exc}"
                floor[name] = None
        sonar = {name: self.scanner.value(name) if self.scanner else None for name in SONARS}
        return {"sonar": sonar, "floor": floor}

    def sonar_reason(self, name):
        """Why a sonar is unreadable ('' if unknown)."""
        return self.scanner.reason(name) if self.scanner else "the sonar scanner could not start"

    def close(self):
        if self.imu:
            self.imu.close()
        if self.scanner:
            self.scanner.close()
        for dev in [self.left, self.right, *self.irs.values(), *(self.encoder_devs or ()), self.touch_dev]:
            if dev is None:
                continue
            try:
                dev.close()
            except Exception:
                pass


class SimHardware:
    """A 1.6 x 1.2 m desk (robot starts in the middle) with a few boxes on it."""

    mode = "simulation"
    DESK = (-0.8, -0.6, 0.8, 0.6)                       # x1, y1, x2, y2 (m)
    # (COCO label, box x1, y1, x2, y2 in m, height m): sonar obstacles, and what SimDetector "sees"
    OBJECTS = [("book", (0.35, -0.15, 0.5, 0.1), 0.05), ("teddy bear", (-0.5, 0.25, -0.3, 0.4), 0.15),
               ("keyboard", (0.0, -0.55, 0.3, -0.45), 0.03), ("cup", (0.26, 0.31, 0.34, 0.39), 0.10),
               ("bottle", (-0.44, -0.29, -0.36, -0.21), 0.20)]
    BOXES = [o[1] for o in OBJECTS]

    def __init__(self, use_imu=True):
        self.reversed = {"left": False, "right": False}   # simulated motors are wired right: kept, never applied
        self.motors = (0.0, 0.0)
        self.calibration = load_encoder_calibration([SIM_CALIBRATION_FILE]) or dict(SIM_ENCODER)
        self.calibration_path = SIM_CALIBRATION_FILE
        self.encoder_error = ""
        self._wheel_m = [0.0, 0.0]         # distance each wheel has rolled
        self._t = time.monotonic()
        self.imu_source = SimImuSource(self)
        self.imu = Imu(self.imu_source, SIM_IMU_FILE) if use_imu else None
        self.touch_pin, self.touch_error = "simulated", ""
        self.touch_until = 0.0             # 'sim touch' presses the pad until this time

    def touched(self):
        return time.monotonic() < self.touch_until

    def _roll(self):
        now = time.monotonic()
        dt, self._t = now - self._t, now
        for i in (0, 1):
            self._wheel_m[i] += self.motors[i] * WHEEL_SPEED_AT_FULL * dt

    def drive(self, left, right):
        self._roll()
        self.motors = (left, right)

    def encoders(self):
        self._roll()
        ml, mr = metres_per_count(SIM_ENCODER)        # the simulated encoders' true resolution
        return int(self._wheel_m[0] / ml), int(self._wheel_m[1] / mr)

    raw_encoders = encoders

    def wheel_truth(self):
        """Metres each wheel has really rolled: what a ruler would measure (simulation only)."""
        self._roll()
        return tuple(self._wheel_m)

    def turn_by_hand(self, side, turns):
        """'sim turn left 10': roll one wheel as if turned by hand (for calibrate)."""
        self._roll()
        self._wheel_m[SIDES.index(side)] += turns * math.pi * SIM_ENCODER["wheel_diameter_m"]

    def _ray(self, x, y, ang):
        step = 0.01
        for i in range(int(SONAR_MAX / step)):
            px, py = x + i * step * math.cos(ang), y + i * step * math.sin(ang)
            for x1, y1, x2, y2 in self.BOXES:
                if x1 <= px <= x2 and y1 <= py <= y2:
                    return i * step
        return SONAR_MAX

    def _on_desk(self, x, y):
        x1, y1, x2, y2 = self.DESK
        return x1 <= x <= x2 and y1 <= y <= y2

    def read(self, pose):
        x, y, th = pose
        sonar = {}
        for name, (ang, off) in SONAR_MOUNT.items():
            a = th + ang
            d = self._ray(x + off * math.cos(a), y + off * math.sin(a), a)
            sonar[name] = max(0.02, min(SONAR_MAX, d + random.gauss(0, 0.005)))
        floor = {name: self._on_desk(x + s * 0.08 * math.cos(th), y + s * 0.08 * math.sin(th))
                 and not self.imu_source.lifted                    # 'sim lift': nothing under either IR
                 for name, s in (("front", 1), ("rear", -1))}
        return {"sonar": sonar, "floor": floor}

    def close(self):
        if self.imu:
            self.imu.close()


# =====================================================================
# IMU (MPU-6050): heading from the gyro, tilt and bumps from the accelerometer
# =====================================================================

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    return math.sqrt(_dot(a, a))


def _mean(vs):
    return tuple(sum(v[i] for v in vs) / len(vs) for i in range(3))


def _spread(vs):
    """Largest max-min over the three axes."""
    return max(max(v[i] for v in vs) - min(v[i] for v in vs) for i in range(3))


class Mpu6050:
    """The MPU-6050 registers over smbus2 (the OLED's luma.oled already needs smbus2; no Adafruit/Blinka).
    Accel +-4 g, gyro +-500 deg/s, ~44 Hz low-pass, 100 samples/s. MPU-6500/9250 boards use the same registers."""

    NAMES = {0x68: "MPU-6050", 0x70: "MPU-6500", 0x71: "MPU-9250", 0x73: "MPU-9255"}

    def __init__(self, bus=1, address=IMU_ADDRESS):
        self.bus_no, self.address = bus, address
        self.name, self.bus, self._mpu6500 = "MPU-6050", None, False

    def open(self):
        from smbus2 import SMBus

        bus = SMBus(self.bus_no)
        try:
            who = bus.read_byte_data(self.address, 0x75)          # WHO_AM_I
            bus.write_byte_data(self.address, 0x6B, 0x80)          # PWR_MGMT_1: reset
            time.sleep(0.1)
            bus.write_byte_data(self.address, 0x6B, 0x01)          # wake up, clock from the gyro PLL
            time.sleep(0.05)
            bus.write_byte_data(self.address, 0x1A, 0x03)          # CONFIG: digital low-pass ~44 Hz
            bus.write_byte_data(self.address, 0x19, 9)             # SMPLRT_DIV: 1 kHz / (1 + 9) = 100 Hz
            bus.write_byte_data(self.address, 0x1B, 0x08)          # GYRO_CONFIG: +-500 deg/s (65.5 LSB per deg/s)
            bus.write_byte_data(self.address, 0x1C, 0x08)          # ACCEL_CONFIG: +-4 g (8192 LSB per g)
        except Exception:
            bus.close()
            raise
        self.bus = bus
        self._mpu6500 = who in (0x70, 0x71, 0x73)
        self.name = self.NAMES.get(who, f"MPU-6050 compatible (WHO_AM_I {who:#04x})")
        return self.name

    def read(self):
        """(accel m/s^2, gyro rad/s, temperature C) in the sensor's own axes."""
        b = self.bus.read_i2c_block_data(self.address, 0x3B, 14)   # ACCEL_XOUT_H .. GYRO_ZOUT_L in one go
        v = [(b[i] << 8 | b[i + 1]) - (65536 if b[i] & 0x80 else 0) for i in range(0, 14, 2)]
        acc = tuple(x / 8192.0 * GRAVITY for x in v[0:3])
        gyr = tuple(math.radians(x / 65.5) for x in v[4:7])
        temp = v[3] / 333.87 + 21.0 if self._mpu6500 else v[3] / 340.0 + 36.53
        return acc, gyr, temp

    def close(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
            self.bus = None


class SimImuSource:
    """What an IMU on the simulated robot would measure: turn rate from the wheels, gravity, a constant gyro bias
    (so the bias calibration has work to do) and noise. 'sim lift' tilts it 35 deg, 'sim bump' knocks it."""

    name = "simulated IMU"
    BIAS = (0.004, -0.003, 0.006)       # rad/s

    def __init__(self, sim):
        self.sim = sim
        self.lifted = False
        self.bump_until = 0.0

    def open(self):
        return self.name

    def read(self):
        left, right = self.sim.motors
        wz = (right - left) * WHEEL_SPEED_AT_FULL / SIM_TRACK_WIDTH
        tilt = math.radians(35) if self.lifted else 0.0
        acc = [GRAVITY * math.sin(tilt), 0.0, GRAVITY * math.cos(tilt)]
        if time.monotonic() < self.bump_until:
            acc[0] -= 0.9 * GRAVITY                      # a knock from the front
        n = random.gauss
        return (tuple(a + n(0, 0.03) for a in acc),
                (self.BIAS[0] + n(0, 0.002), self.BIAS[1] + n(0, 0.002), wz + self.BIAS[2] + n(0, 0.002)),
                30.0)

    def close(self):
        pass


class Imu:
    """Reads an IMU source 100 times a second in its own thread and keeps what the robot needs:

        yaw     heading in rad, CCW (left) positive like the pose, NOT wrapped (the robot uses differences)
        tilt    angle between "up" now and "up" when standing level, rad
        shock   biggest jolt since the robot last asked (accel minus its slow average), m/s^2
        still   standing still: the gyro bias is re-estimated and the heading frozen

    Any mounting works: "up" is the direction the accelerometer feels gravity in while the robot stands level
    (saved in imu.json by 'imu calibrate', else taken at start-up), and the turn rate is the gyro vector along it.
    """

    def __init__(self, source, cal_file):
        self.source, self.cal_file = source, cal_file
        self.name = source.name
        self.status = "starting"
        self.message = ""                    # result of the last 'imu calibrate'
        self.lock = threading.Lock()
        self.yaw = self.rate = self.tilt = 0.0
        self.gyro_norm = self.accel_err = 0.0   # how hard it is being turned / shaken (lift detection)
        self.yaw_offset = 0.0               # 'imu zero': only the heading SHOWN changes, yaw stays continuous
        self.temp = self.acc = None
        self.still = False
        self.motors_on = False               # set by the robot every tick: no "still" while the motors run
        self.bias = (0.0, 0.0, 0.0)
        self.up, self.up_from = None, "start-up"
        self.g_ref = GRAVITY                 # what this accelerometer reads for 1 g (scale error included)
        self.calibrated = False
        self.samples = self.errors = 0
        self.last_sample = 0.0
        self._acc_lp = None
        self._shock_peak = 0.0
        self._t = self._still_since = None
        self._cal = None                     # running bias/level measurement
        try:
            d = json.loads(cal_file.read_text(encoding="utf-8"))
            up = tuple(float(x) for x in d["up"])
            if len(up) == 3 and 0.5 < _norm(up) < 1.5:
                self.up = tuple(x / _norm(up) for x in up)
                self.up_from = f"{cal_file.name} ({d.get('calibrated_at', '?')})"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="imu")
        self._thread.start()

    # ----- sensor thread -----
    def _why(self, exc):
        addr = getattr(self.source, "address", IMU_ADDRESS)
        if isinstance(exc, ImportError):
            return "unavailable: smbus2 not installed (pip install smbus2)"
        if isinstance(exc, FileNotFoundError):
            return "unavailable: I2C bus 1 is off (sudo raspi-config nonint do_i2c 0, then reboot)"
        if isinstance(exc, OSError):
            return (f"not answering at {addr:#04x} - loose wire? (VCC 3.3 V, GND, SDA GPIO 2, SCL GPIO 3; "
                    f"check with: i2cdetect -y 1)")
        return f"unavailable ({type(exc).__name__}: {exc})"

    def _run(self):
        period = 1.0 / IMU_HZ
        opened = False
        while not self._stop.is_set():
            if not opened:
                try:
                    self.name = self.source.open()
                    opened = True
                except Exception as exc:
                    msg = self._why(exc)
                    if msg != self.status:
                        log(f"[imu] {msg}. Retrying every {IMU_RETRY_S:g} s; everything else works without it.")
                    self.status = msg
                    self._stop.wait(IMU_RETRY_S)
                    continue
                with self.lock:
                    self._start_cal(save=False)
                log(f"[imu] {self.name} found - keep the robot still for {IMU_CAL_S:g} s (gyro bias)")
            t0 = time.monotonic()
            try:
                acc, gyr, temp = self.source.read()
                if _norm(acc) < 2.0:          # a sensor that lost power and reset reads all zeros
                    raise OSError("accelerometer reads ~0 g (the sensor reset or lost power?)")
            except Exception as exc:
                self.errors += 1
                log(f"[imu] lost the sensor ({type(exc).__name__}: {exc}) - reconnecting every {IMU_RETRY_S:g} s")
                with self.lock:
                    self.status = f"error: {exc} - reconnecting"
                    self.calibrated, self._cal = False, None
                self.source.close()
                opened = False
                self._stop.wait(IMU_RETRY_S)
                continue
            self._update(t0, acc, gyr, temp)
            sleep_until(t0 + period, self._stop)

    def _start_cal(self, save):
        self._cal = {"until": time.monotonic() + IMU_CAL_S, "acc": [], "gyr": [], "save": save, "tries": 0}
        self.status = "measuring the gyro bias - keep the robot still"

    def _collect(self, now, acc, gyr):
        c = self._cal
        c["acc"].append(acc)
        c["gyr"].append(gyr)
        if now < c["until"] or len(c["gyr"]) < 10:
            return
        moving = (_spread(c["gyr"]) > IMU_CAL_GYRO_SPREAD or _spread(c["acc"]) > IMU_CAL_ACCEL_SPREAD
                  or self.motors_on)
        if moving and c["tries"] < 4:        # try for up to 5 s to catch a still moment
            c.update(until=now + IMU_CAL_S, acc=[], gyr=[], tries=c["tries"] + 1)
            self.status = "measuring the gyro bias - the robot is moving, keep it still"
            return
        self._cal = None
        a = _mean(c["acc"])
        if moving and c["save"]:             # never save a "level" measured while moving: keep the old one
            self.calibrated = self.up is not None
            self.status = f"{self.name} ok" if self.calibrated else self.status
            self.message = "IMU calibration failed: the robot kept moving for 5 s. Nothing was changed."
            log(f"[imu] {self.message}")
            return
        self.bias, self.g_ref = _mean(c["gyr"]), _norm(a)
        if c["save"] or self.up is None:
            self.up = tuple(x / self.g_ref for x in a)
            self.up_from = "start-up (assumed level)"
        self._acc_lp, self._still_since, self.calibrated = a, None, True
        note = " - it moved while measuring, so the heading may drift until it stands still" if moving else ""
        self.status = f"{self.name} ok{note}"
        if c["save"]:
            data = {"up": [round(x, 5) for x in self.up], "gyro_bias": [round(x, 6) for x in self.bias],
                    "sensor": self.name, "calibrated_at": time.strftime("%Y-%m-%d %H:%M")}
            try:
                self.cal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                self.up_from = f"{self.cal_file.name} ({data['calibrated_at']})"
                where = f"saved to {self.cal_file}"
            except OSError as exc:
                where = f"could NOT save to {self.cal_file} ({exc}) - used until this program exits"
            self.message = (f"IMU calibrated{note}: gyro bias "
                            f"{', '.join(f'{math.degrees(b):+.2f}' for b in self.bias)} deg/s, level {where}")
        else:
            self.message = ""
        log(f"[imu] ready{note}: gyro bias {', '.join(f'{math.degrees(b):+.2f}' for b in self.bias)} deg/s, "
            f"level from {self.up_from}")

    def _update(self, now, acc, gyr, temp):
        with self.lock:
            dt = 0.0 if self._t is None else min(0.1, now - self._t)
            self._t, self.acc, self.temp = now, acc, temp
            self.samples += 1
            self.last_sample = now
            if self._cal is not None:
                self._collect(now, acc, gyr)
                return
            if not self.calibrated:
                return
            g = tuple(x - b for x, b in zip(gyr, self.bias))
            lp = self._acc_lp
            self._acc_lp = lp = tuple(p + 0.1 * (a - p) for a, p in zip(acc, lp))   # ~1.7 Hz low-pass
            self._shock_peak = max(self._shock_peak, _norm(tuple(a - p for a, p in zip(acc, lp))))
            n = _norm(lp)
            self.tilt = math.acos(max(-1.0, min(1.0, _dot(lp, self.up) / n))) if n > 1e-6 else 0.0
            rate = _dot(g, self.up)
            self.gyro_norm, self.accel_err = _norm(g), abs(_norm(acc) - self.g_ref)
            quiet = (self.gyro_norm < IMU_STILL_GYRO and self.accel_err < IMU_STILL_ACCEL
                     and not self.motors_on)
            if not quiet:
                self._still_since = None
            elif self._still_since is None:
                self._still_since = now
            self.still = quiet and now - self._still_since >= IMU_STILL_HOLD_S
            if self.still:                    # the gyro should read 0 now, so what it reads is bias
                self.bias = tuple(b + IMU_BIAS_ALPHA * (x - b) for b, x in zip(self.bias, gyr))
                rate = 0.0
            self.rate = rate
            self.yaw += rate * dt

    # ----- for the robot -----
    def ok(self):
        """Usable now: bias measured, not re-measuring (the heading pauses then), and a fresh sample."""
        return self.calibrated and self._cal is None and time.monotonic() - self.last_sample < 0.3

    def snapshot(self):
        """For the control loop, once per tick (takes the shock peak), or None while not usable."""
        with self.lock:
            if not self.ok():
                return None
            peak, self._shock_peak = self._shock_peak, 0.0
            return {"yaw": self.yaw, "tilt": self.tilt, "shock": peak, "rate": self.rate, "still": self.still,
                    "gyro_norm": self.gyro_norm, "accel_err": self.accel_err}

    def info(self):
        with self.lock:
            ok = self.ok()
            return {"status": self.status, "sensor": self.name, "ok": ok, "calibrating": self._cal is not None,
                    "heading_deg": math.degrees(math.atan2(math.sin(self.yaw - self.yaw_offset),
                                                          math.cos(self.yaw - self.yaw_offset))),
                    "rate_dps": math.degrees(self.rate), "tilt_deg": math.degrees(self.tilt), "still": self.still,
                    "temp_c": self.temp, "accel_g": _norm(self.acc) / GRAVITY if self.acc else None,
                    "bias_dps": [math.degrees(b) for b in self.bias], "level_from": self.up_from,
                    "samples": self.samples, "errors": self.errors, "message": self.message}

    def zero(self):
        with self.lock:
            self.yaw_offset = self.yaw

    def calibrate(self):
        with self.lock:
            if self._cal is not None:
                return "The IMU is already measuring - keep the robot still"
            if not self.ok():
                return f"IMU not available: {self.status}"
            self._start_cal(save=True)
            self.message = ""
        return (f"IMU calibration: keep the robot STILL on a flat desk for {IMU_CAL_S:g} s... "
                f"('imu' shows the result; this position is saved as level)")

    def close(self):
        self._stop.set()
        self._thread.join(timeout=0.5)
        self.source.close()


# =====================================================================
# Camera (latest JPEG only)
# =====================================================================

def rotate180(img):
    """Upside down (= flipped both ways), as a new contiguous array. cv2.flip is ~0.3 ms for 640x480 on a Pi 4."""
    try:
        import cv2

        return cv2.flip(img, -1)
    except ImportError:
        import numpy as np

        return np.ascontiguousarray(img[::-1, ::-1])


class Camera:
    def __init__(self, enabled=True, invert=True):
        self.invert = bool(invert)            # rotate 180 deg at the source (camera mounted upside down): the
        self.jpeg = None                      # dashboard, photos, detection and object bearings all see it upright
        self.frame, self.frame_id = None, 0   # latest raw BGR frame, for the object detector
        self.viewers = 0                     # open /stream.mjpg connections: JPEGs are only made while > 0 ...
        self.want_until = 0.0                # ... or shortly after a /snapshot.jpg
        self.encoded = 0                     # JPEGs made (for the docs/benchmark)
        self._vlock = threading.Lock()
        self.overlay = None                   # fn(bgr) -> bgr with boxes drawn, set by the Detector
        self.status = "off"
        self._stop = threading.Event()
        if enabled:
            threading.Thread(target=self._run, daemon=True, name="camera").start()

    def _open(self):
        errors = []
        try:
            from picamera2 import Picamera2

            if not Picamera2.global_camera_info():
                raise RuntimeError("no Pi camera detected")
            cam = Picamera2()
            cam.configure(cam.create_video_configuration(main={"size": (640, 480), "format": "RGB888"}))
            cam.start()
            return "Pi camera", lambda: cam.capture_array("main")[:, :, :3], lambda: (cam.stop(), cam.close())
        except Exception as exc:
            errors.append(f"picamera2: {exc}")
        try:
            import cv2

            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(0)
            if not cap.isOpened():
                raise RuntimeError("no webcam at index 0")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            def read():
                ok, img = cap.read()
                if not ok:
                    raise RuntimeError("webcam read failed")
                return img
            return "USB webcam", read, cap.release
        except Exception as exc:
            errors.append(f"opencv: {exc}")
        raise RuntimeError("; ".join(errors))

    @staticmethod
    def _encoder():
        try:
            import cv2

            return lambda bgr: cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
        except Exception:
            import io

            from PIL import Image  # fallback when OpenCV is not installed

            def enc(bgr):
                buf = io.BytesIO()
                Image.fromarray(bgr[:, :, ::-1]).save(buf, "JPEG", quality=70)
                return buf.getvalue()
            return enc

    def _run(self):
        failures = 0
        while not self._stop.is_set():
            try:
                name, read, close = self._open()
                encode = self._encoder()
            except Exception as exc:
                self.status = f"unavailable ({exc})"
                log(f"[camera] {self.status} - dashboard runs without video")
                return
            self.status = name
            log(f"[camera] {name} streaming")
            try:
                while not self._stop.is_set():
                    img = read()
                    if self.invert:
                        img = rotate180(img)
                    self.frame, self.frame_id = img, self.frame_id + 1
                    if self.viewers <= 0 and time.monotonic() >= self.want_until:
                        time.sleep(0.08)       # nobody is watching: the detector only needs the raw frame
                        continue
                    ov = self.overlay
                    if ov is not None:
                        try:
                            img = ov(img)
                        except Exception as exc:     # a drawing bug must not stop the video
                            self.overlay = None
                            log(f"[camera] box overlay disabled: {exc}")
                    self.jpeg = encode(img)
                    self.encoded += 1
                    failures = 0
                    time.sleep(0.08)           # ~12 fps is plenty for the dashboard
            except Exception as exc:
                failures += 1
                self.status = f"error: {exc}"
                log(f"[camera] {exc} - retrying")
            finally:
                try:
                    close()
                except Exception:
                    pass
            if failures >= 3:
                self.status = "stopped after 3 failures"
                log("[camera] giving up after 3 failures")
                return
            self._stop.wait(2.0)

    def watch(self, delta):
        with self._vlock:
            self.viewers += delta

    def snapshot(self, timeout=1.0):
        """A fresh JPEG for /snapshot.jpg: asks the camera thread to encode for a few seconds, waits for one."""
        old = self.jpeg if time.monotonic() < self.want_until else None
        self.want_until = time.monotonic() + 3.0
        t_end = time.monotonic() + timeout
        while time.monotonic() < t_end and (self.jpeg is None or self.jpeg is old) and self.frame is not None:
            time.sleep(0.02)
        return self.jpeg

    def save_photo(self, folder=PHOTO_DIR):
        """Save the newest raw frame (no detection boxes) as a JPEG. Returns its Path; raises if none."""
        img = self.frame
        if img is None:
            raise RuntimeError(f"no camera picture ({self.status})")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = folder / f"photo-{stamp}.jpg"
        n = 2
        while path.exists():                       # two photos in the same second
            path = folder / f"photo-{stamp}-{n}.jpg"
            n += 1
        try:
            import cv2

            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise RuntimeError("JPEG encoding failed")
            path.write_bytes(buf.tobytes())
        except ImportError:
            from PIL import Image

            Image.fromarray(img[:, :, ::-1]).save(path, "JPEG", quality=92)
        return path

    def close(self):
        self._stop.set()


# =====================================================================
# Object detection (YOLO26n on NCNN) - its own thread, on the camera's latest frame
# =====================================================================

def find_model(path=None):
    """The NCNN model folder (holding model.ncnn.param/.bin): `path`, else the first of DETECT_MODEL_DIRS."""
    for p in ([Path(path)] if path else DETECT_MODEL_DIRS):
        if p.is_dir() and any(p.glob("*.param")):
            return p
    return None


def read_model_metadata(folder):
    """(imgsz, class names) from the export's metadata.yaml, parsed without PyYAML. None where missing."""
    try:
        text = (folder / "metadata.yaml").read_text(encoding="utf-8")
    except OSError:
        return None, None
    m = re.search(r"^imgsz:\s*\n\s*-\s*(\d+)|^imgsz:\s*\[?\s*(\d+)", text, re.M)
    imgsz = int(m.group(1) or m.group(2)) if m else None
    block = re.search(r"^names:\s*\n((?:[ \t]+\d+:.*\n?)+)", text, re.M)
    names = None
    if block:
        found = dict(re.findall(r"^\s+(\d+):\s*['\"]?(.*?)['\"]?\s*$", block.group(1), re.M))
        names = [found[str(i)] for i in range(len(found))] if found else None
    return imgsz, names


def letterbox(image, size):
    """(CHW float32 RGB 0..1 of size x size, scale, (pad_x, pad_y)): resize keeping the shape, grey padding,
    image centred. Same arithmetic as Ultralytics' LetterBox (and run_prototype's ncnn_detector.py)."""
    import cv2
    import numpy as np

    h, w = image.shape[:2]
    r = min(size / h, size / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    dw, dh = (size - nw) / 2, (size - nh) / 2
    if (w, h) != (nw, nh):
        image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    image = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    chw = np.ascontiguousarray(image[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32) / 255.0
    return chw, r, (left, top)


def nms(boxes, scores, iou):
    """Indices kept by greedy non-maximum suppression, highest score first."""
    import numpy as np

    order = scores.argsort()[::-1]
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        rest = order[1:]
        w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = w * h
        order = rest[inter / (areas[i] + areas[rest] - inter + 1e-9) <= iou]
    return np.asarray(keep, dtype=int)


def decode(out, conf, iou=DETECT_IOU, max_det=100):
    """Network output (84, N) or (1, 84, N): cx, cy, w, h + 80 class scores per anchor (the NCNN export has no
    NMS-free head) -> (boxes xyxy, scores, classes) in letterboxed pixels. Also takes end2end output (K, 6)."""
    import numpy as np

    out = np.asarray(out, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    if out.ndim == 2 and out.shape[1] == 6 and out.shape[0] != 6:       # end2end: already final boxes
        out = out[out[:, 4] > conf][:max_det]
        return out[:, :4], out[:, 4], out[:, 5].astype(int)
    pred = out.T
    best = pred[:, 4:].argmax(1)
    score = pred[np.arange(len(best)), 4 + best]
    keep = score > conf
    xywh, score, best = pred[keep, :4], score[keep], best[keep]
    if not len(score):
        return np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, int)
    boxes = np.concatenate([xywh[:, :2] - xywh[:, 2:] / 2, xywh[:, :2] + xywh[:, 2:] / 2], 1)
    keep = nms(boxes + best[:, None] * 7680.0, score, iou)[:max_det]    # class offset = class-aware NMS
    return boxes[keep], score[keep], best[keep]


class Detector:
    """Runs YOLO26n on the camera's newest frame, at most every DETECT_PERIOD_S, in its own thread.

    detections: [{"label", "score", "box": [x1, y1, x2, y2] (frame pixels), "bearing_deg" (+ = left, like the
    pose), "size": box area / frame area}], newest first by score. The camera thread draws them on the stream.
    """

    def __init__(self, camera, model=None, enabled=True, threads=DETECT_THREADS):
        self.camera, self.threads = camera, threads
        self.enabled = enabled
        self.status, self.model = "off", None
        self.detections, self.det_time, self.frame_size = [], 0.0, None
        self.ms = self.fps = None
        self.runs = 0
        self._model_arg = model
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if camera is None:
            self.status = "off (no camera)"
            return
        if not enabled:
            self.status = "off (--no-detect)"
            return
        threading.Thread(target=self._run, daemon=True, name="detector").start()

    def _load(self):
        folder = find_model(self._model_arg)
        if folder is None:
            where = self._model_arg or ", ".join(str(p) for p in DETECT_MODEL_DIRS)
            raise RuntimeError(f"no NCNN model found (looked in {where}; export one with "
                               f"run_prototype/scripts/export-model.sh, or pass --model <folder>)")
        # NCNN uses OpenMP: cap its threads BEFORE importing it, so the control loop keeps its cores
        os.environ.setdefault("OMP_NUM_THREADS", str(self.threads))
        import cv2
        import ncnn
        import numpy  # noqa: F401  (needed by the helpers)

        cv2.setNumThreads(1)
        param = next(folder.glob("*.param"))
        net = ncnn.Net()
        net.opt.use_vulkan_compute = False
        net.opt.num_threads = self.threads
        net.load_param(str(param))
        net.load_model(str(param.with_suffix(".bin")))
        imgsz, names = read_model_metadata(folder)
        self.imgsz, self.names = imgsz or DETECT_IMGSZ, names or list(COCO_NAMES)
        self._net, self._mat = net, ncnn.Mat
        self._in, self._out = net.input_names()[0], sorted(net.output_names())[0]
        self.model = folder.name
        return folder

    def detect(self, image):
        """One frame (BGR numpy) -> list of detection dicts (see the class docstring)."""
        import numpy as np

        chw, r, (px, py) = letterbox(image, self.imgsz)
        with self._net.create_extractor() as ex:           # extractors are single-use
            ex.input(self._in, self._mat(chw))
            out = np.array(ex.extract(self._out)[1])
        boxes, scores, cls = decode(out, DETECT_CONF)
        h, w = image.shape[:2]
        dets = []
        for b, s, c in zip(boxes, scores, cls):
            x1, y1, x2, y2 = ((b - np.array([px, py, px, py], np.float32)) / r).tolist()
            x1, x2 = max(0.0, x1), min(float(w), x2)
            y1, y2 = max(0.0, y1), min(float(h), y2)
            c = int(c)
            dets.append({"label": self.names[c] if 0 <= c < len(self.names) else str(c), "score": float(s),
                         "box": [round(x1), round(y1), round(x2), round(y2)],
                         "bearing_deg": pixel_bearing((x1 + x2) / 2, w),
                         "size": (x2 - x1) * (y2 - y1) / (w * h)})
        return sorted(dets, key=lambda d: -d["score"])

    def _run(self):
        try:
            folder = self._load()
        except Exception as exc:
            name = type(exc).__name__
            hint = (" - start with the project venv: ~/deskbot/.venv/bin/python " + Path(__file__).name
                    if isinstance(exc, ImportError) else "")
            self.status = f"unavailable ({name}: {exc}){hint}"
            log(f"[detect] {self.status}. Everything else runs without it.")
            return
        log(f"[detect] {self.model} loaded from {folder} ({self.imgsz} px, {self.threads} threads)")
        self.status = "waiting for the camera"
        self.camera.overlay = self.draw
        last_id, errors = -1, 0
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame, fid = self.camera.frame, self.camera.frame_id
            if not self.enabled or frame is None or fid == last_id:
                self._stop.wait(0.05)
                continue
            last_id = fid
            try:
                dets = self.detect(frame)
                errors = 0
            except Exception as exc:
                errors += 1
                log(f"[detect] error: {type(exc).__name__}: {exc}")
                if errors >= 5:
                    self.status = f"stopped after 5 errors ({exc})"
                    self.camera.overlay = None
                    return
                self._stop.wait(1.0)
                continue
            dt = time.monotonic() - t0
            with self._lock:
                self.detections, self.det_time = dets, time.monotonic()
                self.frame_size = frame.shape[1], frame.shape[0]
                self.ms = dt * 1000
                self.fps = 1 / max(dt, DETECT_PERIOD_S)
                self.runs += 1
            self.status = f"{self.model}: {self.ms:.0f} ms per frame"
            self._stop.wait(max(0.0, DETECT_PERIOD_S - dt))

    def current(self):
        """The latest detections, or [] when they are stale or detection is off."""
        with self._lock:
            if not self.enabled or time.monotonic() - self.det_time > DETECT_STALE_S:
                return []
            return list(self.detections)

    def draw(self, img):
        """Camera thread: boxes + labels on a copy of the frame (boxes may lag the video by one detection)."""
        dets = self.current()
        if not dets:
            return img
        import cv2

        img = img.copy()
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 255), 2)
            txt = f"{d['label']} {d['score'] * 100:.0f}%"
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ty = max(th + 4, y1)
            cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 4, ty), (0, 200, 255), -1)
            cv2.putText(img, txt, (x1 + 2, ty - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        return img

    def info(self):
        return {"status": self.status, "enabled": self.enabled, "model": self.model, "ms": self.ms,
                "fps": self.fps, "runs": self.runs, "detections": self.current()}

    def close(self):
        self._stop.set()
        if self.camera is not None:
            self.camera.overlay = None


# =====================================================================
# Objects on the map (24 Nov 2026): what the camera recognises, placed and remembered on the obstacle map
# =====================================================================
#
# Ported from run_prototype deskbot/vision/geometry.py (pinhole camera over a flat desk), mapping/fusion.py
# (sonar or ground-plane range) and mapping/semantic.py (one landmark per object: Kalman position, log-odds
# existence that fades), without ByteTrack IDs (association is by label + distance only).

def pixel_bearing(u, w):
    """Horizontal angle (deg, + = left like the pose) of pixel column u in a w-pixel-wide picture. Exact pinhole
    model: angle = atan(offset / focal length). The linear "share of the field of view" it replaces was right at
    the centre and the very edge but up to ~1.3 deg off in between (1.2 deg at 20 deg)."""
    fx = (w / 2) / math.tan(math.radians(CAMERA_HFOV_DEG) / 2)
    return -math.degrees(math.atan((u - w / 2) / fx))


def camera_ground_point(u, v, w, h):
    """Robot-frame (x forward, y left) where pixel (u, v) of a w x h frame meets the desk, or None if that pixel
    looks at or above the horizon. Camera CAMERA_X_M ahead of the centre, CAMERA_HEIGHT_M up, tilted down
    CAMERA_PITCH_DEG (run_prototype CameraModel.ground_point)."""
    fx = (w / 2) / math.tan(math.radians(CAMERA_HFOV_DEG) / 2)
    fy = (h / 2) / math.tan(math.radians(CAMERA_VFOV_DEG) / 2)
    a, b = (u - w / 2) / fx, (v - h / 2) / fy
    p = math.radians(CAMERA_PITCH_DEG)
    sp, cp = math.sin(p), math.cos(p)
    dx, dy, dz = cp - b * sp, -a, -sp - b * cp
    if dz >= -1e-3:
        return None
    t = CAMERA_HEIGHT_M / -dz
    return CAMERA_X_M + dx * t, dy * t


def camera_project(x, y, z, w, h):
    """Pixel (u, v) of a robot-frame point (z up from the desk), or None if it is behind the camera."""
    fx = (w / 2) / math.tan(math.radians(CAMERA_HFOV_DEG) / 2)
    fy = (h / 2) / math.tan(math.radians(CAMERA_VFOV_DEG) / 2)
    p = math.radians(CAMERA_PITCH_DEG)
    sp, cp = math.sin(p), math.cos(p)
    px, py, pz = x - CAMERA_X_M, y, z - CAMERA_HEIGHT_M
    zc = px * cp - pz * sp
    if zc <= 1e-3:
        return None
    return w / 2 + fx * -py / zc, h / 2 + fy * (-px * sp - pz * cp) / zc


def object_radius(label):
    return OBJ_RADIUS.get(label, OBJ_DEFAULT_RADIUS)


def locate_detection(d, frame_size, sonar_front):
    """Robot-frame (x, y, variance m^2, source) of the CENTRE of a detected object, or None.

    Range: the front sonar when the object is within OBJ_SONAR_DEG of straight ahead and the two estimates agree
    (or there is no ground estimate), else where the bottom-centre of its box meets the desk (variance grows with
    distance^2). The measured point is a surface, so the object's radius is added along the bearing."""
    w, h = frame_size
    x1, y1, x2, y2 = d["box"]
    if x1 <= 2 or x2 >= w - 2:      # partly outside the picture: the box centre (= its direction) is wrong
        return None
    u, v = (x1 + x2) / 2, y2
    ground = None if y2 >= h - 2 else camera_ground_point(u, v, w, h)   # box cut off at the bottom: too close
    bearing = math.radians(d["bearing_deg"])
    r_ground = None if ground is None else math.hypot(ground[0] - CAMERA_X_M, ground[1])
    point = None
    if (sonar_front is not None and sonar_front < OBJ_SONAR_MAX_M and abs(d["bearing_deg"]) <= OBJ_SONAR_DEG):
        r_sonar = sonar_front + (SONAR_MOUNT["front"][1] - CAMERA_X_M)
        if r_ground is None or abs(r_sonar - r_ground) < max(0.08, 0.4 * r_ground):
            point = (CAMERA_X_M + r_sonar * math.cos(bearing), r_sonar * math.sin(bearing),
                     0.02 ** 2 + (r_sonar * 0.03) ** 2, "sonar")
        elif r_ground > r_sonar + OBJ_BEHIND_SURFACE_M:
            return None              # far behind what the sonar hears: a reflection or seen through glass
    if point is None:
        if ground is None or r_ground > OBJ_MAX_RANGE_M:
            return None
        point = (ground[0], ground[1], (0.02 + 0.10 * r_ground ** 2) ** 2, "camera")
    rad = OBJ_DEPTH.get(d["label"], object_radius(d["label"]))
    return point[0] + rad * math.cos(bearing), point[1] + rad * math.sin(bearing), point[2], point[3]


class ObjectMap:
    """One landmark per physical object. Every new detection frame: each sighting is matched to the nearest
    landmark with the same label inside the gate (else a new one), its position is Kalman-updated and its
    existence log-odds go up by OBJ_L_HIT x score. A landmark that should be in view but is not detected loses
    OBJ_L_MISS. Existence fades with a half-life (things get moved while the robot looks elsewhere) and the
    position variance grows while unseen. Faded landmarks are dropped."""

    def __init__(self):
        self.lock = threading.Lock()
        self.objects = {}
        self._next = 1
        self.frames = 0
        self.k = math.log(2.0) / OBJ_HALF_LIFE_S

    def reset(self):
        with self.lock:
            self.objects.clear()

    def _existence(self, o, now):
        return o["L"] * math.exp(-self.k * max(0.0, now - o["t_update"]))

    def _var(self, o, now):
        return o["var"] + OBJ_DRIFT * max(0.0, now - o["t_seen"])

    def update(self, now, pose, dets, frame_size, sonar_front):
        """One processed camera frame (the robot not turning). dets: the detector's detection dicts."""
        x0, y0, th = pose
        c, s = math.cos(th), math.sin(th)
        obs = []
        # seen, but cut off at the left/right edge: not placed (its direction is wrong), yet it is still there,
        # so a landmark with that label is not counted as missed
        clipped = {d["label"] for d in dets if d["box"][0] <= 2 or d["box"][2] >= frame_size[0] - 2}
        for d in dets:
            if d["label"] in OBJ_SKIP:
                continue
            loc = locate_detection(d, frame_size, sonar_front)
            if loc is not None:
                rx, ry, var, source = loc
                obs.append((d, x0 + c * rx - s * ry, y0 + s * rx + c * ry, var, source))
        with self.lock:
            self.frames += 1
            matched = set()
            for d, wx, wy, var, source in sorted(obs, key=lambda o: -o[0]["score"]):
                best, best_dist = None, None
                for o in self.objects.values():
                    if o["id"] in matched or d["label"] not in o["votes"]:
                        continue
                    dist = math.hypot(wx - o["x"], wy - o["y"])
                    if dist < OBJ_GATE_M + 2 * math.sqrt(self._var(o, now) + var) and (best is None or dist < best_dist):
                        best, best_dist = o, dist
                if best is None:
                    best = {"id": self._next, "x": wx, "y": wy, "var": var, "L": 0.0, "t_update": now, "t_seen": now,
                            "votes": {}, "hits": 0, "misses": 0, "source": source}
                    self.objects[best["id"]] = best
                    self._next += 1
                matched.add(best["id"])
                pv = self._var(best, now)
                k = pv / (pv + var)
                best["x"] += k * (wx - best["x"])
                best["y"] += k * (wy - best["y"])
                best["var"] = (1 - k) * pv
                best["L"] = min(OBJ_L_MAX, self._existence(best, now) + OBJ_L_HIT * d["score"])
                best["t_update"] = best["t_seen"] = now
                best["votes"][d["label"]] = best["votes"].get(d["label"], 0.0) + d["score"]
                best["hits"] += 1
                best["source"] = source
            for o in list(self.objects.values()):          # should be in view, but the detector missed it
                if (o["id"] in matched or max(o["votes"], key=o["votes"].get) in clipped
                        or not self._in_view(o, pose, sonar_front)):
                    continue
                o["L"] = max(OBJ_L_MIN, self._existence(o, now) - OBJ_L_MISS)
                o["t_update"] = now
                o["misses"] += 1
            for o in list(self.objects.values()):
                if self._existence(o, now) < OBJ_PRUNE_LOGODDS or now - o["t_update"] > 6 * OBJ_HALF_LIFE_S:
                    del self.objects[o["id"]]

    @staticmethod
    def _in_view(o, pose, sonar_front):
        """Should the camera see this landmark now? Inside the field of view (5 deg margin), 12 cm-1 m away, and
        not hidden behind something the front sonar hears closer."""
        x0, y0, th = pose
        dx, dy = o["x"] - x0, o["y"] - y0
        dist = math.hypot(dx, dy)
        bearing = math.degrees(math.atan2(dy, dx) - th)
        bearing = (bearing + 180) % 360 - 180
        if not 0.12 <= dist <= 1.0 or abs(bearing) > CAMERA_HFOV_DEG / 2 - 5:
            return False
        # the sonar hears something clearly in front of the object's own near surface -> hidden behind that
        near = dist - object_radius(max(o["votes"], key=o["votes"].get)) - SONAR_MOUNT["front"][1]
        return not (abs(bearing) < 15 and sonar_front is not None and sonar_front < near - 0.10)

    def describe(self, pose=None, now=None, min_p=OBJ_SHOW_P):
        """Landmarks believed to be there (probability >= min_p), most certain first. With a pose, each also gets
        its distance and direction from the robot now (bearing_deg + = left)."""
        now = time.monotonic() if now is None else now
        out = []
        with self.lock:
            for o in self.objects.values():
                p = 1.0 / (1.0 + math.exp(-self._existence(o, now)))
                if p < min_p:
                    continue
                label = max(o["votes"], key=o["votes"].get)
                e = {"id": o["id"], "label": label, "x": round(o["x"], 3), "y": round(o["y"], 3),
                     "sigma": round(math.sqrt(self._var(o, now)), 3), "radius": object_radius(label),
                     "p": round(p, 2), "age_s": round(now - o["t_seen"], 1), "hits": o["hits"],
                     "misses": o["misses"], "source": o["source"]}
                if pose is not None:
                    dx, dy = o["x"] - pose[0], o["y"] - pose[1]
                    e["dist_m"] = round(math.hypot(dx, dy), 3)
                    e["bearing_deg"] = round((math.degrees(math.atan2(dy, dx) - pose[2]) + 180) % 360 - 180, 1)
                out.append(e)
        return sorted(out, key=lambda e: -e["p"])

    def find(self, label, pose):
        """The most certain remembered object whose label contains `label` ('phone' finds 'cell phone'), or None."""
        label = label.strip().lower()
        hits = [o for o in self.describe(pose) if label and (label in o["label"] or o["label"] in label)]
        return hits[0] if hits else None


def where_words(o):
    """'34 cm away, 20 deg to the left (seen 3 s ago)'"""
    b = o["bearing_deg"]
    way = "straight ahead" if abs(b) < 8 else "behind me" if abs(b) > 150 else \
        f"{abs(b):.0f} deg to the {'left' if b > 0 else 'right'}"
    age = "seen just now" if o["age_s"] < 2 else f"seen {o['age_s']:.0f} s ago"
    return f"{o['dist_m'] * 100:.0f} cm away, {way} ({age}, {o['p'] * 100:.0f} % sure)"


class SimDetector:
    """--sim: 'detects' the labelled objects on the simulated desk (SimHardware.OBJECTS) with the same camera
    geometry, ~3 times a second, so the object map (and go-to) can be tried on the laptop. Same interface as
    Detector. A small random miss rate and position noise make the fusion do real work."""

    def __init__(self, robot, enabled=True):
        self.robot, self.enabled = robot, enabled
        self.status, self.model = "simulated objects", "simulated"
        self.detections, self.det_time, self.frame_size = [], 0.0, (640, 480)
        self.ms, self.fps, self.runs = 1.0, 1 / DETECT_PERIOD_S, 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="detector").start()

    def _see(self):
        r, hw = self.robot, self.robot.hw
        x0, y0, th = r.pose
        w, h = self.frame_size
        c, s = math.cos(th), math.sin(th)
        dets = []
        for label, (bx1, by1, bx2, by2), height in hw.OBJECTS:
            cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
            rx, ry = c * (cx - x0) + s * (cy - y0), -s * (cx - x0) + c * (cy - y0)    # robot frame
            dist = math.hypot(rx, ry)
            rad = max(bx2 - bx1, by2 - by1) / 2
            if dist < 0.06 or random.random() < 0.1:
                continue
            ang = math.atan2(ry, rx)
            # hidden behind another object (the simulator's own sonar ray, from the camera)
            cam_x, cam_y = x0 + CAMERA_X_M * c, y0 + CAMERA_X_M * s
            if hw._ray(cam_x, cam_y, th + ang) < dist - rad - CAMERA_X_M - 0.03:
                continue
            near = (rx - rad * math.cos(ang), ry - rad * math.sin(ang))   # the point facing the camera
            pts = [camera_project(near[0] - rad * math.sin(ang) * k, near[1] + rad * math.cos(ang) * k, z, w, h)
                   for k in (-1, 1) for z in (0.0, height)]
            if any(p is None for p in pts):
                continue
            us, vs = [p[0] for p in pts], [p[1] for p in pts]
            x1, x2, y1, y2 = max(0, min(us)), min(w, max(us)), max(0, min(vs)), min(h, max(vs))
            if x2 - x1 < 4 or y2 - y1 < 4 or x1 >= w or x2 <= 0:
                continue
            y2 += random.gauss(0, 2)
            dets.append({"label": label, "score": round(random.uniform(0.6, 0.9), 2),
                         "box": [round(x1), round(y1), round(x2), round(min(h, y2))],
                         "bearing_deg": pixel_bearing((x1 + x2) / 2, w),
                         "size": (x2 - x1) * (y2 - y1) / (w * h)})
        return sorted(dets, key=lambda d: -d["score"])

    def _run(self):
        log("[detect] simulation: seeing the simulated desk's objects")
        while not self._stop.wait(DETECT_PERIOD_S):
            if not self.enabled:
                continue
            try:
                dets = self._see()
            except Exception as exc:
                log(f"[detect] simulated detection failed: {exc}")
                continue
            with self._lock:
                self.detections, self.det_time = dets, time.monotonic()
                self.runs += 1

    current = Detector.current
    info = Detector.info

    def close(self):
        self._stop.set()


def describe_detections(dets, sonar_front=None):
    """'cup (82 %, ahead, ~34 cm by the front sonar), person (64 %, 20 deg left)'"""
    parts = []
    for d in dets:
        b = d["bearing_deg"]
        where = "ahead" if abs(b) < 8 else f"{abs(b):.0f} deg {'left' if b > 0 else 'right'}"
        if abs(b) < 10 and sonar_front is not None and sonar_front < SONAR_MAX * 0.95:
            where += f", ~{sonar_front * 100:.0f} cm by the front sonar"
        parts.append(f"{d['label']} ({d['score'] * 100:.0f} %, {where})")
    return ", ".join(parts)


# =====================================================================
# Obstacle map
# =====================================================================

class ObstacleMap:
    """Rough occupancy grid from the four sonars and the dead-reckoned pose."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        from collections import deque
        with self.lock:
            self.grid = [[0] * MAP_N for _ in range(MAP_N)]
            self._rows = None
            self.edges = set()               # cells where an IR sensor saw the desk end
            self.trail = deque(maxlen=TRAIL_N)
            self._decay_t = time.monotonic()

    @staticmethod
    def cell(x, y):
        return int(x / CELL_M + MAP_N / 2), int(y / CELL_M + MAP_N / 2)

    def _add(self, i, j, delta):
        if 0 <= i < MAP_N and 0 <= j < MAP_N:
            self.grid[j][i] = max(-CLAMP, min(CLAMP, self.grid[j][i] + delta))

    def update(self, pose, sonar, floor=None):
        """Sonar beams (free along the beam, occupied at the echo), the IR edge sensors (desk edge marks), the
        robot's own footprint (surely free), its trail, and slow fading of all evidence."""
        x, y, th = pose
        with self.lock:
            self._rows = None
            now = time.monotonic()
            if now - self._decay_t >= FUSION_DECAY_S:           # stale evidence fades (things get moved)
                self._decay_t = now
                self.grid = [[int(v * FUSION_DECAY) for v in row] for row in self.grid]
            if not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) >= 0.02:
                self.trail.append((round(x, 3), round(y, 3)))
            ci, cj = self.cell(x, y)
            rr = max(1, int(FOOTPRINT_M / CELL_M))
            for j in range(cj - rr, cj + rr + 1):                # where the robot is, there is desk and nothing else
                for i in range(ci - rr, ci + rr + 1):
                    if (i - ci) ** 2 + (j - cj) ** 2 <= rr * rr:
                        self._add(i, j, -MISS)
            for name, sign in (("front", 1), ("rear", -1)):
                v = (floor or {}).get(name)
                if v is None:
                    continue
                c = self.cell(x + sign * IR_MOUNT_M * math.cos(th), y + sign * IR_MOUNT_M * math.sin(th))
                if v:
                    self.edges.discard(c)                       # desk seen here: not an edge after all
                else:
                    self.edges.add(c)
            for name, d in sonar.items():
                if d is None:
                    continue
                ang, off = SONAR_MOUNT[name]
                a = th + ang
                sx, sy = x + off * math.cos(a), y + off * math.sin(a)
                hit = d < SONAR_MAX * 0.95
                free_len = min(d, SONAR_MAX) - (CELL_M if hit else 0)
                steps = max(0, int(free_len / (CELL_M / 2)))
                seen = set()
                for k in range(steps):                     # free space along the beam
                    c = self.cell(sx + k * CELL_M / 2 * math.cos(a), sy + k * CELL_M / 2 * math.sin(a))
                    if c not in seen:
                        seen.add(c)
                        self._add(*c, -MISS)
                if hit:                                    # obstacle at the end of the beam
                    self._add(*self.cell(sx + d * math.cos(a), sy + d * math.sin(a)), HIT)

    def rows(self):
        """One string per row: '#' obstacle, '.' free, ' ' unknown. Rebuilt only after the map changed
        (it changes 5 times a second; every dashboard tab asks about every 0.7 s)."""
        with self.lock:
            if self._rows is None:
                rows = [list("#" if v > 2 else "." if v < -1 else " " for v in row) for row in self.grid]
                for i, j in self.edges:
                    if 0 <= i < MAP_N and 0 <= j < MAP_N:
                        rows[j][i] = "!"
                self._rows = ["".join(r) for r in rows]
            return self._rows

    def fused(self, objects):
        with self.lock:
            return fused_cells(self.grid, list(self.edges), objects, self.cell), list(self.trail)


# =====================================================================
# SLAM (25 Nov 2026): sonar scan matching corrects the drift of the wheel/gyro pose against the map
# =====================================================================
SLAM_COLLECT_S = 0.1        # sample the sonar echoes this often
SLAM_MATCH_S = 0.5          # try a correction this often
SLAM_WINDOW_S = 2.0         # echo points from the last 2 s form the "scan"
SLAM_XY_M, SLAM_XY_STEP_M = 0.04, 0.01            # search +-4 cm in x and y, 1 cm steps
SLAM_TH_DEG = (-3.0, -1.5, 0.0, 1.5, 3.0)          # and these heading changes
SLAM_MATURE = 3             # a reference cell counts as an established obstacle after this many older echoes
SLAM_REF_MAX = 30           # evidence cap per reference cell
SLAM_MIN_POINTS = 6         # fewer echo points than this: nothing to match
SLAM_MIN_GAIN = 2           # the best shift must put this many MORE points on obstacles than no shift ...
SLAM_MIN_GAIN_FRAC = 0.15   # ... and at least this share of all the points more
SLAM_MIN_MATCH = 0.3        # ... and at least this share of the points on obstacles
SLAM_GAIN = 0.5             # apply half the found correction each time (smooth, robust to one bad match)


class Slam:
    """Correlative scan matching on the sonar occupancy map, in its own (low-priority) thread.

    The control loop keeps dead-reckoning the pose from the encoders + gyro (50 Hz) and painting the map with it.
    This thread samples the sonar echo points (world x, y) every 0.1 s and, every 0.5 s, takes the last 2 s of them
    as a scan. It tries every shift of +-4 cm (1 cm steps) and heading change of +-3 deg (about the robot), and
    scores each by how many points land on ESTABLISHED obstacle cells of its own reference grid. Points enter that grid
    only when they leave the 2 s window (at their corrected position), so a scan is matched against OLDER evidence
    and the echoes just seen cannot vote for themselves (matching against the live map would always say "no shift"). If the best beats "no shift" by SLAM_MIN_GAIN
    points and puts at least 30 % of the points on obstacles, half of it is applied to the robot's pose (and to the
    buffered points). Ties go to the smallest correction. It also keeps the uncorrected ("odometry only") path for
    comparison. Cost: 405 candidates x <= ~80 points, ~10-30 ms on a Pi 4 twice a second, outside the control loop.
    Limits: four sonars see little, so it can only correct near known obstacles; on an empty desk it does nothing."""

    def __init__(self, robot, enabled=False):
        from collections import deque
        self.robot, self.enabled = robot, bool(enabled)
        self.lock = threading.Lock()
        self.points = deque(maxlen=400)          # (t, x, y) echo points in world coordinates
        self.ref = [[0] * MAP_N for _ in range(MAP_N)]   # older echoes per cell: what scans are matched against
        self.raw_trail = deque(maxlen=TRAIL_N)   # the path as wheels + gyro alone would have it
        self._raw = self._last = None
        self.steps = self.corrections = 0
        self.match = None
        self.last = None                         # last applied correction (dx m, dy m, dth rad)
        self.total = [0.0, 0.0, 0.0]
        self.ms = None
        self.status = "on" if self.enabled else "off"
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="slam").start()

    def set(self, on):
        with self.lock:
            self.enabled = bool(on)
            self._clear()
            self.status = "on - collecting echoes" if on else "off"

    def reset(self):
        """Fresh map / pose (map reset, put down somewhere new): forget the scan and the comparison path."""
        with self.lock:
            self._clear()

    def _clear(self):
        self.points.clear()
        self.ref = [[0] * MAP_N for _ in range(MAP_N)]
        self.raw_trail.clear()
        self._raw = self._last = None
        self.total = [0.0, 0.0, 0.0]
        self.last, self.match = None, None

    def _run(self):
        next_match = time.monotonic() + SLAM_MATCH_S
        while not self._stop.wait(SLAM_COLLECT_S):
            if not self.enabled:
                continue
            try:
                self._collect()
                if time.monotonic() >= next_match:
                    next_match = time.monotonic() + SLAM_MATCH_S
                    self._match()
            except Exception as exc:              # never let a SLAM bug take anything else down
                self.status = f"error: {type(exc).__name__}: {exc}"
                _save_traceback("slam", exc)

    def _collect(self):
        r = self.robot
        with r.lock:
            pose, sonar = r.pose, dict(r.readings.get("sonar") or {})
            paused = r.lift["lifted"] or bool(r.cal and r.cal.get("mode") == "hand")
            turning = bool(r.move and r.move["dir"] not in ("forward", "backward"))
        if paused:
            return
        x, y, th = pose
        now = time.monotonic()
        with self.lock:
            if self._last is None:
                self._raw = self._last = pose
            else:                                 # move the raw pose by the odometry step since last time
                lx, ly, lth = self._last
                dxw, dyw = x - lx, y - ly
                c, s = math.cos(-lth), math.sin(-lth)
                fx, fy = c * dxw - s * dyw, s * dxw + c * dyw          # step in the robot's frame
                rx, ry, rth = self._raw
                rth2 = rth + math.atan2(math.sin(th - lth), math.cos(th - lth))
                self._raw = (rx + math.cos(rth) * fx - math.sin(rth) * fy,
                             ry + math.sin(rth) * fx + math.cos(rth) * fy, rth2)
                self._last = pose
            rx, ry, _ = self._raw
            if not self.raw_trail or math.hypot(rx - self.raw_trail[-1][0], ry - self.raw_trail[-1][1]) >= 0.02:
                self.raw_trail.append((round(rx, 3), round(ry, 3)))
            for name, d in sonar.items():
                # while turning, a sonar reading (one ping per sensor every ~0.3 s) is older than the heading it
                # would be placed with: at 90 deg/s that smears echoes by up to 10 cm, so they are skipped
                if d is None or d >= SONAR_MAX * 0.95 or turning:
                    continue
                ang, off = SONAR_MOUNT[name]
                a = th + ang
                self.points.append((now, x + (off + d) * math.cos(a), y + (off + d) * math.sin(a)))
            half = MAP_N / 2
            while self.points and now - self.points[0][0] > SLAM_WINDOW_S:
                _, px, py = self.points.popleft()          # leaves the scan window: becomes reference evidence
                i, j = int(px / CELL_M + half), int(py / CELL_M + half)
                if 0 <= i < MAP_N and 0 <= j < MAP_N:
                    self.ref[j][i] = min(SLAM_REF_MAX, self.ref[j][i] + 1)

    def _match(self):
        t0 = time.perf_counter()
        r = self.robot
        with self.lock:
            pts = [(px, py) for _, px, py in self.points]
        if len(pts) < SLAM_MIN_POINTS:
            self.status = f"on - waiting for echoes ({len(pts)} points)"
            return
        grid = self.ref
        with r.lock:
            x0, y0, th0 = r.pose
        half, steps = MAP_N / 2, int(round(SLAM_XY_M / SLAM_XY_STEP_M))
        shifts = [k * SLAM_XY_STEP_M for k in range(-steps, steps + 1)]
        best = None                               # (score, -size, dx, dy, dth)
        base = 0
        for dth_deg in SLAM_TH_DEG:
            dth = math.radians(dth_deg)
            c, s = math.cos(dth), math.sin(dth)
            rot = [(x0 + c * (px - x0) - s * (py - y0), y0 + s * (px - x0) + c * (py - y0)) for px, py in pts]
            for dx in shifts:
                for dy in shifts:
                    score = 0
                    for px, py in rot:
                        i, j = int((px + dx) / CELL_M + half), int((py + dy) / CELL_M + half)
                        if 0 <= i < MAP_N and 0 <= j < MAP_N and grid[j][i] >= SLAM_MATURE:
                            score += 1
                    size = abs(dx) + abs(dy) + abs(dth) * 0.1
                    cand = (score, -size, dx, dy, dth)
                    if best is None or cand[:2] > best[:2]:
                        best = cand
                    if dx == 0 and dy == 0 and dth_deg == 0:
                        base = score
        score, _, dx, dy, dth = best
        self.steps += 1
        self.match = score / len(pts)
        self.ms = (time.perf_counter() - t0) * 1000
        if score < base + max(SLAM_MIN_GAIN, SLAM_MIN_GAIN_FRAC * len(pts)) or self.match < SLAM_MIN_MATCH or (dx == 0 and dy == 0 and dth == 0):
            self.status = f"on - pose agrees with the map ({self.match * 100:.0f} % of {len(pts)} echoes on obstacles)"
            return
        gx, gy, gth = dx * SLAM_GAIN, dy * SLAM_GAIN, dth * SLAM_GAIN
        with r.lock:                              # the control loop keeps integrating from the corrected pose
            x, y, th = r.pose
            c, s = math.cos(gth), math.sin(gth)   # rotate about where the robot was when matching started
            r.pose = (x0 + c * (x - x0) - s * (y - y0) + gx, y0 + s * (x - x0) + c * (y - y0) + gy,
                      math.atan2(math.sin(th + gth), math.cos(th + gth)))
        with self.lock:
            c, s = math.cos(gth), math.sin(gth)
            self.points = type(self.points)(((t, x0 + c * (px - x0) - s * (py - y0) + gx,
                                              y0 + s * (px - x0) + c * (py - y0) + gy) for t, px, py in self.points),
                                            maxlen=self.points.maxlen)
            if self._last is not None:            # the correction is not odometry: keep it out of the raw path
                lx, ly, lth = self._last
                self._last = (x0 + c * (lx - x0) - s * (ly - y0) + gx, y0 + s * (lx - x0) + c * (ly - y0) + gy,
                              lth + gth)
        self.corrections += 1
        self.last = (gx, gy, gth)
        self.total = [self.total[0] + gx, self.total[1] + gy, self.total[2] + gth]
        self.status = (f"on - corrected {math.hypot(gx, gy) * 100:.1f} cm, {math.degrees(gth):+.1f} deg "
                       f"({self.match * 100:.0f} % of {len(pts)} echoes on obstacles)")

    def info(self):
        with self.lock:
            raw = self._raw
            drift = None
            if raw is not None:
                x, y, th = self.robot.pose
                drift = math.hypot(x - raw[0], y - raw[1])
            return {"enabled": self.enabled, "status": self.status, "points": len(self.points),
                    "match": self.match, "corrections": self.corrections, "steps": self.steps, "ms": self.ms,
                    "last": None if self.last is None else {"dx_cm": self.last[0] * 100, "dy_cm": self.last[1] * 100,
                                                            "dth_deg": math.degrees(self.last[2])},
                    "total": {"dx_cm": self.total[0] * 100, "dy_cm": self.total[1] * 100,
                              "dth_deg": math.degrees(self.total[2])},
                    "drift_cm": None if drift is None else drift * 100}

    def trail(self):
        with self.lock:
            return list(self.raw_trail) if self.enabled else []

    def line(self):
        i = self.info()
        if not i["enabled"]:
            return "SLAM is off ('slam on' to correct the pose with the sonar map)"
        return (f"SLAM: {i['status']} | {i['corrections']} corrections in {i['steps']} matches"
                + (f", total {math.hypot(i['total']['dx_cm'], i['total']['dy_cm']):.1f} cm / "
                   f"{i['total']['dth_deg']:+.1f} deg" if i["corrections"] else "")
                + (f", {i['ms']:.0f} ms per match" if i["ms"] is not None else ""))

    def close(self):
        self._stop.set()


# =====================================================================
# Noise filter (24 Nov 2026, from run_prototype runtime/sensor_filter.py): cleans readings before safety uses them
# =====================================================================

class _SonarFilter:
    """One sonar. The scanner already reports the median of 3 pings; this catches a sonar that keeps jumping
    > 30 cm and straight back (a loose wire, a bad echo path): it then reports the CLOSEST recent reading,
    which can only make the robot more careful. Only NEW readings count (the scanner updates ~12 times a second,
    the control loop asks 50 times)."""

    def __init__(self):
        from collections import deque
        self.window = deque(maxlen=FILTER_WINDOW)
        self.last = None
        self.clean = 0
        self.fault = False

    def _bounces(self):
        v = list(self.window)
        return sum(1 for a, b, c in zip(v, v[1:], v[2:])
                   if abs(b - a) > FILTER_JUMP_M and abs(c - b) > FILTER_JUMP_M and (b - a) * (c - b) < 0)

    def update(self, value):
        if value is None:                    # no reading: passes through, the safety rules treat it as unsafe
            return None
        if value != self.last:
            self.last = value
            self.window.append(value)
            bad = self._bounces() >= FILTER_BOUNCES
            self.clean = 0 if bad else self.clean + 1
            if bad:
                self.fault = True
            elif self.clean >= FILTER_WINDOW:
                self.fault = False
        return min(self.window) if self.fault else value


class _FloorFilter:
    """One IR edge sensor: debounce with hysteresis. "No floor" is believed after FILTER_TO_EDGE ticks (40 ms),
    "floor again" only after FILTER_TO_FLOOR (100 ms), so the careful answer wins quickly and a noisy edge does
    not chatter. A sensor that flips FILTER_IR_FLIPS times in the window reads "no floor" until clean again."""

    def __init__(self):
        from collections import deque
        self.state, self.count, self.last_raw = None, 0, None
        self.changes = deque(maxlen=FILTER_WINDOW)
        self.clean, self.fault = 0, False

    def update(self, raw):
        if raw is None:
            return None
        raw = bool(raw)
        self.changes.append(self.last_raw is not None and raw != self.last_raw)
        self.last_raw = raw
        if self.state is None:
            self.state = raw
        if raw == self.state:
            self.count = 0
        else:
            self.count += 1
            if self.count >= (FILTER_TO_FLOOR if raw else FILTER_TO_EDGE):
                self.state, self.count = raw, 0
        bad = sum(self.changes) >= FILTER_IR_FLIPS
        self.clean = 0 if bad else self.clean + 1
        if bad:
            self.fault = True
        elif self.clean >= FILTER_WINDOW:
            self.fault = False
        return False if self.fault else self.state


class SensorFilter:
    def __init__(self):
        self.sonar = {name: _SonarFilter() for name in SONARS}
        self.floor = {name: _FloorFilter() for name in ("front", "rear")}

    def update(self, r):
        """A hw.read() result -> the same shape, cleaned."""
        out = dict(r)
        out["raw_sonar"], out["raw_floor"] = r.get("sonar", {}), r.get("floor", {})
        out["sonar"] = {n: self.sonar[n].update(v) if n in self.sonar else v for n, v in r.get("sonar", {}).items()}
        out["floor"] = {n: self.floor[n].update(v) if n in self.floor else v for n, v in r.get("floor", {}).items()}
        return out

    def faults(self):
        return ([f"{n} sonar" for n, f in self.sonar.items() if f.fault] +
                [f"{n} IR" for n, f in self.floor.items() if f.fault])


# =====================================================================
# Sensor fusion map (24 Nov 2026): sonar + IR edges + where the robot drove + camera objects, fading with time
# =====================================================================

def fused_cells(grid, edges, objects, cell_of):
    """The confidence heatmap as one string of MAP_N*MAP_N characters, row by row (j = 0 is y min):
    '-' unknown, '0'..'9' probability that the cell is occupied (0 = surely free, 9 = surely occupied, from the
    sonar log-odds), 'E' desk edge (IR), 'O' a camera object (its radius, when the camera is at least 60 % sure)."""
    out = []
    for row in grid:
        out.append("".join("-" if v == 0 else str(min(9, max(0, round(9 / (1 + math.exp(-v / 3)))))) for v in row))
    cells = [list(r) for r in out]
    for o in objects:
        ci, cj = cell_of(o["x"], o["y"])
        rr = max(1, int(round(o["radius"] / CELL_M)))
        for j in range(cj - rr, cj + rr + 1):
            for i in range(ci - rr, ci + rr + 1):
                if 0 <= i < MAP_N and 0 <= j < MAP_N and (i - ci) ** 2 + (j - cj) ** 2 <= rr * rr:
                    cells[j][i] = "O"
    for i, j in edges:
        if 0 <= i < MAP_N and 0 <= j < MAP_N:
            cells[j][i] = "E"
    return "".join("".join(r) for r in cells)


# =====================================================================
# Robot: control loop, safety, commands
# =====================================================================

DIRECTIONS = {  # (left, right) motor sign
    "forward": (1, 1), "backward": (-1, -1), "left": (-1, 1), "right": (1, -1),
}


class Robot:
    def __init__(self, hw, check_edges=True):
        self.hw = hw
        self.check_edges = check_edges
        self.ignore_obstacles = False        # 'obstacles ignore' / --ignore-obstacles: sonars never stop a move
        self.basic = False                   # --basic: only motors, sensors, map and obstacle stops were started
        self.slam = None                     # set by main() (Slam: sonar scan matching corrects the pose)
        self.speed = 0.5
        self.pose = (0.0, 0.0, 0.0)
        self.move = None                     # {"dir", "until", "label"}
        self.applied = (0.0, 0.0)
        self.readings = {"sonar": {}, "floor": {}}
        self.blocked = ""
        self.events = []
        self.map = ObstacleMap()
        self.filter = SensorFilter()         # noise filter: every reading passes it before safety sees it
        self.objects = ObjectMap()           # what the camera recognised, placed on the map
        self._obj_runs = -1
        self._turned_at = -1e9               # last time the robot was turning (object updates wait after it)
        # wheel encoders
        self.enc_counts = None               # latest (left, right)
        self.enc_start = None                # counts at start-up / map reset, for "distance per wheel"
        self._enc_last = None
        self.wheel_working = [False, False]  # an encoder that never moved proves nothing (unplugged?)
        self._stuck_base = [None, None]
        self._stuck_since = [None, None]
        self.stuck_wheel = None
        self.odometry = "motor timing"
        self.cal = None                      # running calibration session (see calibrate())
        self.cal_message = ""                # result of the last calibration, for the dashboard
        self.oled = None                     # set by main() once the screen thread exists
        self.imu = getattr(hw, "imu", None)  # None: --no-imu
        self.detector = None                 # set by main() (object detection on the camera)
        self.camera = None                   # set by main(), for 'photo'
        self.assistant = None                # set by main() (ask / hey)
        self.nav = Navigator(self)           # 'go to the cup'
        self.tasks = None                    # set by main() (TaskList)
        self.focus = None                    # set by main() (FocusTimer)
        self.people = None                   # set by main() (People: face me + greeter)
        self.phone = None                    # set by main() (PhonePresence)
        self.gestures = None                 # set by main() (Gestures)
        self.rps = None                      # set by main() (RockPaperScissors)
        self.apis = None                     # set by main() (WebApis)
        self.ideas = None                    # set by main() (Ideas)
        self.sounds = None                   # set by main() (Sounds: effects played by the dashboard browser)
        self.dance = None                    # set by main() (Dance)
        self.last_user_cmd = -1e9            # time of the last command from a person ('keep facing me' waits)
        self.user_cmds = 0                   # commands typed/clicked by a person: an AI command plan stops on one
        self.ticks = self.late_ticks = 0     # control loop ticks / times it fell a whole tick behind
        self._status_cache = (0.0, None)     # (time, dict): one snapshot shared by the OLED and dashboard tabs
        self._imu_yaw = None                 # IMU yaw at the previous tick (heading change per tick)
        self.touch = {"touched": None, "presses": 0, "pats": 0, "holds": 0, "last": ""}
        self._touch_down = None              # press time while the pad is held
        self._touch_used = False             # this press already did something (stopped a move / hold)
        self.lift = {"enabled": True, "lifted": False, "since": None, "reason": "", "lifts": 0, "resets": 0,
                     "last": "", "stuck_warned": False}
        self._lift_timers = {}
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="control")
        self._thread.start()

    # ---------- events ----------
    def event(self, msg):
        log(msg)
        with self.lock:
            self.events = (self.events + [f"{time.strftime('%H:%M:%S')} {msg}"])[-12:]

    # ---------- safety ----------
    def why_unsafe(self, direction, r, margin=0.0, sonar_optional=False):
        """Why `direction` is unsafe now ('' if safe). sonar_optional: a sonar that gives no reading does
        not block (used only by the supervised calibration moves; a sonar that SEES an obstacle still does)."""
        sonar, floor = r["sonar"], r["floor"]
        if self.lift["lifted"]:
            return f"robot is lifted ({self.lift['reason']}) - put it down on the desk"
        imu = r.get("imu")                   # None = no usable IMU: nothing to check (it is optional)
        if imu and math.degrees(imu["tilt"]) > IMU_TILT_STOP_DEG:
            return f"robot tilted {math.degrees(imu['tilt']):.0f} deg (lifted or tipping?) - put it down flat"

        def need_floor(*names):
            if not self.check_edges:
                return ""
            for n in names:
                if floor.get(n) is None:
                    why = getattr(self.hw, "ir_errors", {}).get(n)
                    return f"{n} IR unreadable{f' ({why})' if why else ''} - use --no-edge to ignore"
                if not floor[n]:
                    return f"{n} edge detected"
            return ""

        def need_clear(name, limit):
            if self.ignore_obstacles:        # the user turned obstacle stops off; edges, lift, tilt, bump still stop
                return ""
            d = sonar.get(name)
            if d is None:
                if sonar_optional:
                    return ""
                why = self.hw.sonar_reason(name) if hasattr(self.hw, "sonar_reason") else ""
                return f"{name} sonar unreadable{f' ({why})' if why else ''}"
            if d <= limit + margin:
                return f"{name} obstacle at {d * 100:.0f} cm"
            return ""

        if direction == "forward":
            return need_floor("front") or need_clear("front", STOP_DISTANCE)
        if direction == "backward":
            return need_floor("rear") or need_clear("rear", STOP_DISTANCE)
        return (need_floor("front", "rear") or need_clear("left", SIDE_STOP_DISTANCE)
                or need_clear("right", SIDE_STOP_DISTANCE))

    # ---------- control loop ----------
    def _set_motors(self, left, right):
        if (left, right) != self.applied:
            try:
                self.hw.drive(left, right)
                self.applied = (left, right)
            except Exception as exc:
                self.move = None
                self.applied = (0.0, 0.0)
                self.event(f"Motor error: {exc} - move cancelled")
                try:
                    self.hw.drive(0, 0)
                except Exception:
                    pass

    def _read_encoders(self):
        try:
            c = self.hw.encoders()
            return None if c is None else (int(c[0]), int(c[1]))
        except Exception:
            return None

    def _which_stuck(self, now, counts):
        """None, "left", "right" or "both" - a wheel told to turn whose encoder has not moved.
        Uses self.applied: what the motors were driven with during the tick that just ended."""
        if counts is None:
            return None
        if self._enc_last is not None:
            for i in (0, 1):
                self.wheel_working[i] = self.wheel_working[i] or counts[i] != self._enc_last[i]
        stuck = []
        for i, cmd in enumerate(self.applied):
            if abs(cmd) < STUCK_MIN_COMMAND:
                self._stuck_since[i] = None
            elif self._stuck_since[i] is None or abs(counts[i] - self._stuck_base[i]) >= STUCK_MIN_COUNTS:
                self._stuck_since[i], self._stuck_base[i] = now, counts[i]
            elif self.wheel_working[i] and now - self._stuck_since[i] >= STUCK_AFTER_S:
                stuck.append(("left", "right")[i])
        return "both" if len(stuck) == 2 else (stuck[0] if stuck else None)

    def _odometry(self, dt, counts, dyaw=None):
        """Advance self.pose: distance from the encoders when calibrated, else from what the motors were told;
        heading change from the gyro (`dyaw`) when the IMU works, else from the same source as the distance.
        The gyro is better for heading: a wheel that slips or skids still counts, the gyro does not care."""
        x, y, th = self.pose
        cal = getattr(self.hw, "calibration", None)
        gyro = " + gyro" if dyaw is not None else ""
        if counts is not None and self._enc_last is not None and cal:
            ml, mr = metres_per_count(cal)
            dl = (counts[0] - self._enc_last[0]) * ml
            dr = (counts[1] - self._enc_last[1]) * mr
            if abs(dl) <= MAX_STEP_M and abs(dr) <= MAX_STEP_M:
                d, dth = (dl + dr) / 2, (dr - dl) / (cal.get("track_width_m") or TRACK_WIDTH)
            else:                              # encoder glitch: no distance this tick
                d, dth = 0.0, 0.0
            dth = dyaw if dyaw is not None else dth
            mid = th + dth / 2
            x, y, th = x + d * math.cos(mid), y + d * math.sin(mid), th + dth
            self.odometry = "encoders" + gyro
        else:
            vl, vr = (m * WHEEL_SPEED_AT_FULL for m in self.applied)
            v, w = (vl + vr) / 2, (vr - vl) / TRACK_WIDTH
            th += dyaw if dyaw is not None else w * dt
            x, y = x + v * math.cos(th) * dt, y + v * math.sin(th) * dt
            self.odometry = "motor timing" + gyro
        self.pose = (x, y, math.atan2(math.sin(th), math.cos(th)))

    def _read_touch(self, now):
        """Touch pad, once per tick (50 Hz polling is its debounce):
            press while a move runs  -> stop it (a hand on the head = stop)
            press + release < 2 s    -> a pat (happy eyes)
            held 2 s                 -> the OLED shows the dashboard address"""
        f = getattr(self.hw, "touched", None)
        try:
            t = f() if f else None
        except Exception:
            t = None
        tc = self.touch
        tc["touched"] = t
        if t and self._touch_down is None:
            self._touch_down, self._touch_used = now, False
            tc["presses"] += 1
            if self.move:
                self.move = None
                self._touch_used = True
                self.blocked = "stopped by the touch pad"
                self.event("STOPPED: touch pad pressed")
        elif t and not self._touch_used and now - self._touch_down >= TOUCH_HOLD_S:
            self._touch_used = True
            tc["holds"] += 1
            tc["last"] = "hold"
            self.event("Touch pad held - showing the dashboard address")
            if self.oled is not None:
                self.oled.say(f"Dashboard\nhttp://{local_ip()}:{self.oled.port}", 8)
        elif not t and self._touch_down is not None:
            if not self._touch_used:
                tc["pats"] += 1
                tc["last"] = "pat"
                self.event("Touch pad: pat")
            self._touch_down = None

    # ---------- lift detection (picked up -> stop + map paused; put down somewhere new -> fresh map) ----------
    def _held(self, name, cond, now, need):
        """True once `cond` has been true continuously for `need` seconds."""
        if not cond:
            self._lift_timers.pop(name, None)
            return False
        return now - self._lift_timers.setdefault(name, now) >= need

    def _check_lift(self, now, r):
        lf = self.lift
        if not lf["enabled"] or (self.cal and self.cal["mode"] == "hand"):   # hand calibration: lifted on purpose
            self._lift_timers.clear()
            return
        ff, bf = r["floor"].get("front"), r["floor"].get("rear")
        ir = ff is not None and bf is not None and self.check_edges         # --no-edge: IR may be unplugged
        imu = r.get("imu")
        if not lf["lifted"]:
            motors_off = self.applied == (0.0, 0.0)
            # all three timers are updated every tick (no short-circuit), so each one's hold time is real
            by_ir = self._held("ir", ir and not ff and not bf, now, LIFT_CONFIRM_S)
            by_tilt = self._held("tilt", bool(imu) and math.degrees(imu["tilt"]) > LIFT_TILT_DEG,
                                 now, LIFT_TILT_CONFIRM_S)
            shaken = bool(imu) and motors_off and (imu["gyro_norm"] > LIFT_SHAKE_GYRO
                                                   or imu["accel_err"] > LIFT_SHAKE_ACCEL)
            by_hand = self._held("shake", shaken and ir and not (ff and bf), now, LIFT_SHAKE_CONFIRM_S)
            reason = ("both edge sensors lost the desk" if by_ir else
                      f"tilted {math.degrees(imu['tilt']):.0f} deg" if by_tilt else
                      "moved by hand" if by_hand else "")
            if reason:
                self._lifted(now, reason)
            return
        settled = imu is None or (math.degrees(imu["tilt"]) < PLACE_TILT_DEG and imu["gyro_norm"] < 0.15
                                  and imu["accel_err"] < 0.8)
        on_desk = (ff and bf) if ir else imu is not None       # no IR: the IMU being level and still is all we have
        if self._held("place", bool(on_desk) and settled, now, PLACE_CONFIRM_S):
            self._placed(now)
        elif (ir and not ff and not bf and not lf["stuck_warned"]
              and now - lf["since"] > LIFT_STUCK_WARN_S):
            lf["stuck_warned"] = True
            self.event("Both edge sensors have seen no desk for 2 minutes - am I lifted, or are the IR sensors "
                       f"unplugged? (front GPIO {IR_FRONT}, rear GPIO {IR_BACK})")

    def _lifted(self, now, reason):
        lf = self.lift
        lf.update(lifted=True, since=now, reason=reason, stuck_warned=False, last="lifted")
        lf["lifts"] += 1
        lf["left_at"] = min(self._lift_timers.values(), default=now)   # when the lift condition began
        self._lift_timers.clear()
        self.move = None
        self.blocked = f"lifted ({reason})"
        self.event(f"Picked up ({reason}): motors stopped, map paused")

    def _placed(self, now):
        lf = self.lift
        # time in the air = until it touched down, not until the 1 s "put down" confirmation ended (measuring to
        # `now` would make every lift >= PLACE_CONFIRM_S, so even a blip would wipe the map)
        up_for = self._lift_timers.get("place", now) - lf.get("left_at", lf["since"])   # left the desk -> touched down
        lf.update(lifted=False, since=None, reason="")
        self._lift_timers.clear()
        if self.blocked.startswith("lifted"):
            self.blocked = ""
        if up_for < LIFT_RESET_AFTER_S:
            lf["last"] = "resumed"
            self.event("Back on the desk (short lift): map resumed")
            return
        lf["resets"] += 1
        lf["last"] = "new spot"
        self.map.reset()
        self.objects.reset()
        self.pose = (0.0, 0.0, 0.0)
        if self.slam is not None:
            self.slam.reset()
        self.enc_start = self.enc_counts
        self.event(f"Put down after {up_for:.1f} s: new spot - fresh map, pose (0, 0)")
        if self.oled is not None:
            self.oled.say("New spot!", 2.5)

    def lift_line(self):
        lf = self.lift
        if not lf["enabled"]:
            return "lift detection: off"
        state = f"LIFTED ({lf['reason']})" if lf["lifted"] else "on the desk"
        uses = [n for n, ok in (("IR", self.check_edges), ("IMU", bool(self.readings.get("imu")))) if ok]
        return (f"lift: {state} | {lf['lifts']} lifts, {lf['resets']} fresh maps"
                f" | uses {' + '.join(uses) or 'nothing (no IR checks, no IMU)'}")

    def _read_imu(self):
        """IMU snapshot for this tick (None if unusable) and the heading change since the last tick."""
        if self.imu is None:
            return None, None
        self.imu.motors_on = self.applied != (0.0, 0.0)
        s = self.imu.snapshot()
        dyaw = None
        if s is not None and self._imu_yaw is not None:
            dyaw = s["yaw"] - self._imu_yaw
        self._imu_yaw = None if s is None else s["yaw"]
        return s, dyaw

    def _loop(self):
        """The control thread. If a tick raises, the motors are stopped, the error is noted on the dashboard and
        the loop starts again: the safety checks never silently disappear."""
        while not self._stop.is_set():
            try:
                self._loop_inner()
                return
            except Exception as exc:
                with self.lock:
                    self.move = None
                try:
                    self.hw.drive(0, 0)
                except Exception:
                    pass
                HEALTH.note("control loop", f"error, motors stopped, restarted ({type(exc).__name__}: {exc})")
                _save_traceback("control loop", exc)
                self._stop.wait(0.2)

    def _loop_inner(self):
        period = 1.0 / LOOP_HZ
        last = time.monotonic()
        last_map = 0.0
        next_tick = last
        while not self._stop.is_set():
            now = time.monotonic()
            self.ticks += 1
            dt, last = now - last, now
            try:
                r = self.hw.read(self.pose)
            except Exception as exc:
                r = {"sonar": {}, "floor": {}}
                self.blocked = f"sensor read failed: {exc}"
            r = self.filter.update(r)
            counts = self._read_encoders()
            with self.lock:
                imu, dyaw = self._read_imu()
                r["imu"] = imu
                self.readings = r
                if self.enc_start is None and counts is not None:
                    self.enc_start = counts
                stuck = self._which_stuck(now, counts)
                self._check_lift(now, r)
                # odometry for the tick that just ended, before the motors change. Frozen during a hand
                # calibration (wheels turned by hand) and while lifted (being carried is not driving).
                if not (self.cal and self.cal["mode"] == "hand") and not self.lift["lifted"]:
                    self._odometry(dt, counts, dyaw)
                self.enc_counts, self._enc_last = counts, counts
                self._read_touch(now)
                mv = self.move
                if mv and stuck:
                    self.move = mv = None
                    self.stuck_wheel = stuck
                    self.blocked = f"{stuck} wheel stuck (motor on, encoder not turning)"
                    self.event(f"STOPPED: {self.blocked}")
                if (mv and imu and mv["dir"] in ("forward", "backward") and imu["shock"] >= IMU_BUMP_MS2
                        and now - mv.get("t0", 0.0) >= IMU_BUMP_IGNORE_S):
                    self.move = mv = None
                    self.blocked = f"bump detected ({imu['shock'] / GRAVITY:.1f} g jolt) - hit something?"
                    self.event(f"STOPPED: {self.blocked}")
                if mv and mv.get("yaw0") is not None:      # a turn measured by the gyro
                    if imu is None:                         # the IMU dropped out: finish it on time instead
                        mv["yaw0"] = None
                        mv["until"] = min(mv["until"], mv["t0"] + mv["timed_s"])
                        self.event("IMU lost during the turn - finishing it on time")
                    elif abs(imu["yaw"] - mv["yaw0"]) >= mv["turn_rad"] - math.radians(IMU_TURN_LEAD_DEG):
                        turned = math.degrees(abs(imu["yaw"] - mv["yaw0"]))
                        self.move = mv = None
                        self.event(f"Turn done: {turned:.0f} deg (gyro)")
                if mv and mv.get("enc0") is not None:     # a drive measured by the encoders
                    cal = getattr(self.hw, "calibration", None)
                    if counts is None or not cal:            # encoders lost: finish it on time instead
                        mv["enc0"] = None
                        mv["until"] = min(mv["until"], mv["t0"] + mv["timed_s"])
                        self.event("Encoders lost during the drive - finishing it on time")
                    else:
                        ml, mr = metres_per_count(cal)
                        # the wheel that rolled further: a dead or slipping encoder can't make it overshoot
                        rolled = max(abs(counts[0] - mv["enc0"][0]) * ml, abs(counts[1] - mv["enc0"][1]) * mr)
                        if rolled >= mv["dist_m"] - DRIVE_LEAD_M:
                            self.move = mv = None
                            self.event(f"Drive done: {rolled * 100:.1f} cm (encoders)")
                if mv and now >= mv["until"]:
                    if mv.get("enc0") is not None:
                        self.event(f"Drive stopped by its time limit - the encoders did not count "
                                   f"{mv['dist_m'] * 100:.0f} cm (wheel slipping or encoder unplugged?)")
                    self.move = mv = None
                    self.event("Move done")
                if mv:
                    why = self.why_unsafe(mv["dir"], r, sonar_optional=mv.get("sonar_optional", False))
                    if why:
                        self.move = mv = None
                        self.blocked = why
                        self.event(f"STOPPED: {why}")
                if mv:
                    sl, sr = DIRECTIONS[mv["dir"]]
                    self._set_motors(sl * self.speed, sr * self.speed)
                else:
                    self._set_motors(0.0, 0.0)
                c = self.cal                  # automatic calibration: its move has ended -> read the counts
                if c and c["phase"] == "driving" and self.move is None:
                    if c["settle"] is None:
                        c["settle"] = now + CAL_SETTLE_S
                    elif now >= c["settle"]:
                        raw = self._raw_counts()
                        if raw is not None:
                            self._calibration_drive_done(raw)
            if now - last_map >= 0.2 and not self.lift["lifted"]:   # carried around: would paint nonsense
                last_map = now
                try:
                    self.map.update(self.pose, r["sonar"], r.get("floor"))
                except Exception as exc:
                    log(f"[map] update failed: {exc}")
                try:
                    self._update_objects(now, r)
                except Exception as exc:
                    log(f"[objects] update failed: {type(exc).__name__}: {exc}")
            # fixed schedule (no drift); after a stall it restarts the schedule instead of bursting to catch up
            next_tick += period
            if next_tick < time.monotonic() - period:
                next_tick = time.monotonic()
                self.late_ticks += 1
            sleep_until(next_tick, self._stop)

    def announce(self, text, mood="happy", sound=None):
        """Something the robot says on its own (a reminder): Activity log, OLED text + face, the assistant
        chat (so a dashboard with 'Speak replies' ticked reads it out) and a sound effect (the mood's, or `sound`)."""
        self.event(f"Says: {text}")
        if self.sounds is not None:
            self.sounds.play(sound) if sound else self.sounds.mood(mood)
        if self.oled is not None:
            self.oled.mood(mood, 6.0)
            self.oled.say(text, 10.0)
        if self.assistant is not None:
            self.assistant.announce(text, mood)

    def _update_objects(self, now, r):
        """Each NEW detection frame -> the object map, unless the robot is turning (motion blur, and the pose
        would not match the moment the picture was taken)."""
        det = self.detector
        if det is None or not det.enabled or det.frame_size is None or det.runs == self._obj_runs:
            return
        self._obj_runs = det.runs
        mv, imu = self.move, r.get("imu")
        if (mv and mv["dir"] in ("left", "right")) or (imu and abs(math.degrees(imu["rate"])) > OBJ_TURN_SKIP_DPS):
            self._turned_at = now
            return
        if det.det_time < self._turned_at + OBJ_AFTER_TURN_S:   # the picture was taken during the turn
            return
        self.objects.update(now, self.pose, det.current(), det.frame_size, r["sonar"].get("front"))

    # ---------- commands ----------
    def turn_time(self, degrees):
        w = 2 * self.speed * WHEEL_SPEED_AT_FULL / TRACK_WIDTH   # rad/s turning on the spot
        return math.radians(degrees) / w

    def start(self, direction, seconds, label, turn_deg=None, dist_m=None):
        """Start a move. turn_deg (left/right only): turn by that angle instead of for `seconds`: measured by
        the gyro when the IMU works (with twice the estimated time as a backstop), else timed.
        dist_m (forward/backward only): drive that far, measured by the calibrated encoders (twice the
        estimated time as a backstop), else timed from the motor model."""
        with self.lock:
            if self.cal:
                return "Not moving: encoder calibration in progress ('calibrate cancel' to stop it)"
            why = self.why_unsafe(direction, self.readings, START_MARGIN)
            if why:
                self.blocked = why
                return f"Not moving: {why}"
            now = time.monotonic()
            mv = {"dir": direction, "label": label, "t0": now}
            imu = self.readings.get("imu")
            how = ""
            if turn_deg:
                timed = min(MAX_DURATION, self.turn_time(turn_deg))
                if imu:
                    seconds = timed * 2 + 0.5
                    mv.update(turn_rad=math.radians(turn_deg), yaw0=imu["yaw"], timed_s=timed)
                    how = f"{turn_deg:.0f} deg, measured by the gyro"
                else:
                    seconds = timed
                    how = f"~{turn_deg:.0f} deg, timed (no IMU)"
            if dist_m:
                timed = min(MAX_DURATION, dist_m / max(0.01, self.speed * WHEEL_SPEED_AT_FULL))
                if getattr(self.hw, "calibration", None) and self.enc_counts is not None:
                    seconds = timed * 2 + 0.5
                    mv.update(dist_m=dist_m, enc0=self.enc_counts, timed_s=timed)
                    how = f"{dist_m * 100:.0f} cm, measured by the encoders"
                else:
                    seconds = timed
                    why = "encoders not calibrated - 'calibrate'" if self.enc_counts is not None else "no encoders"
                    how = f"~{dist_m * 100:.0f} cm, timed ({why})"
            seconds = max(0.05, min(MAX_DURATION, seconds))
            mv["until"] = now + seconds
            self.blocked = ""
            self.stuck_wheel = None
            self._stuck_since = [None, None]
            self.move = mv
        return f"{label} {how}" if how else f"{label} for {seconds:.1f} s"

    def stop(self):
        with self.lock:
            self.move = None
            self._set_motors(0.0, 0.0)
        return "Stopped"

    def status(self, max_age=0.0):
        """Everything the dashboard/OLED/assistant show. max_age > 0: a snapshot up to that old may be returned
        (shared, do NOT modify it). Only the robot's own fields are read under the control loop's lock; the
        parts with their own locks (IMU, detector, tasks, assistant ...) are built after releasing it."""
        t, cached = self._status_cache
        now = time.monotonic()
        if max_age and cached is not None and now - t < max_age:
            return cached
        with self.lock:
            r = self.readings
            x, y, th = self.pose
            mv = self.move
            core = {
                "mode": self.hw.mode, "speed": self.speed,
                "pose": {"x": x, "y": y, "theta": th},
                "sonar": r["sonar"], "floor": r["floor"], "edges_checked": self.check_edges,
                "obstacles_ignored": self.ignore_obstacles, "basic": self.basic,
                "move": None if mv is None else {"label": mv["label"], "dir": mv["dir"],
                                                 "left_s": max(0.0, mv["until"] - time.monotonic())},
                "blocked": self.blocked, "events": list(self.events),
                "encoders": self.encoder_status(),
                "loop": {"hz": LOOP_HZ, "ticks": self.ticks, "late": self.late_ticks},
                "lift": {k: v for k, v in self.lift.items() if k != "stuck_warned"} | {
                    "up_s": time.monotonic() - self.lift["since"] if self.lift["lifted"] else None},
                "touch": dict(self.touch, pin=getattr(self.hw, "touch_pin", None),
                              error=getattr(self.hw, "touch_error", "not supported")),
                "limits": {"front": STOP_DISTANCE, "rear": STOP_DISTANCE,
                           "left": SIDE_STOP_DISTANCE, "right": SIDE_STOP_DISTANCE,
                           "tilt_deg": IMU_TILT_STOP_DEG, "bump_g": IMU_BUMP_MS2 / GRAVITY},
            }
        core.update({
            "calibration": self.calibration_status(),          # takes the (re-entrant) lock briefly itself
            "imu": self.imu.info() if self.imu else None,
            "assistant": self.assistant.info() if self.assistant else None,
            "nav": self.nav.info(),
            "tasks": self.tasks.describe() if self.tasks else None,
            "focus": self.focus.info() if self.focus else None,
            "people": self.people.info() if self.people else None,
            "phone": self.phone.info() if self.phone else None,
            "gestures": self.gestures.info() if self.gestures else None,
            "rps": self.rps.info() if self.rps else None,
            "apis": self.apis.info() if self.apis else None,
            "ideas": self.ideas.info() if self.ideas else None,
            "sounds": self.sounds.info() if self.sounds else None,
            "accounts": accounts_info(self),
            "vision": self.detector.info() if self.detector else None,
            "slam": self.slam.info() if self.slam else None,
        })
        self._status_cache = (now, core)
        return core

    def touch_line(self):
        t, err = self.touch, getattr(self.hw, "touch_error", "not supported")
        if t["touched"] is None:
            return f"touch: unavailable ({err or 'no reading'})"
        pin = getattr(self.hw, "touch_pin", "?")
        where = f"GPIO {pin}" if isinstance(pin, int) else pin
        return (f"touch ({where}): {'TOUCHED' if t['touched'] else 'not touched'}"
                f" | {t['pats']} pats, {t['holds']} holds, {t['presses']} presses")

    def imu_line(self):
        if self.imu is None:
            return "imu: off (--no-imu)"
        i = self.imu.info()
        if not i["ok"]:
            return f"imu: {i['status']}"
        return (f"imu: heading {i['heading_deg']:.0f} deg, turning {i['rate_dps']:+.0f} deg/s, "
                f"tilt {i['tilt_deg']:.0f} deg, {'still' if i['still'] else 'moving'}"
                + (f", {i['temp_c']:.0f} C" if i["temp_c"] is not None else ""))

    def encoder_status(self):
        cal = getattr(self.hw, "calibration", None)
        c, c0 = self.enc_counts, self.enc_start
        dist = None
        if cal and c is not None and c0 is not None:
            ml, mr = metres_per_count(cal)
            dist = [(c[0] - c0[0]) * ml, (c[1] - c0[1]) * mr]
        return {"counts": list(c) if c is not None else None, "distance_m": dist,
                "working": list(self.wheel_working), "calibrated": bool(cal),
                "calibration_file": cal["file"] if cal else None,
                "error": getattr(self.hw, "encoder_error", "not supported"),
                "odometry": self.odometry, "stuck": self.stuck_wheel}

    def encoder_line(self):
        e = self.encoder_status()
        if e["counts"] is None:
            return f"encoders: unavailable ({e['error'] or 'no data yet'})"
        c, w = e["counts"], e["working"]
        txt = (f"encoders: L {c[0]} R {c[1]} counts"
               f" (seen turning: L {'yes' if w[0] else 'not yet'}, R {'yes' if w[1] else 'not yet'})")
        if e["distance_m"]:
            txt += f", rolled L {e['distance_m'][0]:.2f} m R {e['distance_m'][1]:.2f} m"
        txt += f" | pose from {e['odometry']}"
        if not e["calibrated"]:
            txt += " | not calibrated: type 'calibrate'"
        return txt

    # ---------- encoder calibration (the 'calibrate' command and the dashboard wizard) ----------
    #
    #   auto (default)  the robot drives forward ~25 cm by itself, then you measure how far it really went:
    #                   calibrate [auto] [target cm]  ->  calibrate moved <distance>
    #   spin (optional) the robot spins ~one turn, you say how far it turned -> track width for the heading:
    #                   calibrate spin  ->  calibrate turned <degrees | turns>
    #   hand            robot lifted, turn each wheel N times by hand:
    #                   calibrate hand [diameter] [turns]  ->  calibrate next  ->  calibrate next
    #
    # self.cal holds the running session: {"mode": "auto"|"spin"|"hand", "phase": ..., "start": raw counts, ...}

    def _raw_counts(self):
        try:
            c = self.hw.raw_encoders()
            return None if c is None else (int(c[0]), int(c[1]))
        except Exception:
            return None

    def _sim_truth(self):
        """Simulation only: metres each wheel really rolled (what a ruler would show), else None."""
        f = getattr(self.hw, "wheel_truth", None)
        return f() if f else None

    def calibration_summary(self):
        cal = getattr(self.hw, "calibration", None)
        if not cal:
            return "Encoders not calibrated - type 'calibrate' (or use the dashboard) to calibrate them"
        when = f" on {cal['calibrated_at']}" if cal.get("calibrated_at") else ""
        ml, mr = metres_per_count(cal)
        track = (f", track width {cal['track_width_m'] * 100:.1f} cm" if cal.get("track_width_m")
                 else ", turning not calibrated ('calibrate spin')")
        return (f"Encoder calibration{when} ({cal.get('method') or 'hand'}) from {cal['file']}: "
                f"L {ml * 1000:.3f} / R {mr * 1000:.3f} mm per count{track}  ('calibrate' to redo)")

    def calibration_status(self):
        with self.lock:
            cal = getattr(self.hw, "calibration", None)
            saved = None
            if cal:
                saved = {k: cal.get(k) for k in (
                    "file", "calibrated_at", "method", "wheel_diameter_m", "left_counts_per_rev",
                    "right_counts_per_rev", "left_sign", "right_sign", "revolutions", "track_width_m",
                    "measured_m", "measured_deg")}
                saved["mm_per_count"] = [m * 1000 for m in metres_per_count(cal)]
            active = None
            c, raw = self.cal, self._raw_counts()
            if c:
                active = {"mode": c["mode"], "phase": c["phase"], "stopped": c.get("stopped", ""),
                          "delta": None if raw is None else [raw[0] - c["start"][0], raw[1] - c["start"][1]]}
                if c["mode"] == "hand":
                    i = c["step"]
                    active.update(side=SIDES[i], step=i + 1, revolutions=c["revolutions"],
                                  diameter_m=c["diameter_m"], results=dict(c["results"]),
                                  turned=None if raw is None else raw[i] - c["start"][i])
                else:
                    active.update(target_m=c.get("target_m"), gyro_deg=c.get("gyro_deg"))
                    truth = self._sim_truth()
                    if truth and c.get("truth0"):
                        dl, dr = truth[0] - c["truth0"][0], truth[1] - c["truth0"][1]
                        active["sim_moved_cm"] = round((dl + dr) / 2 * 100, 1)
                        active["sim_turned_deg"] = round(math.degrees((dr - dl) / SIM_TRACK_WIDTH))
            return {"active": active, "saved": saved, "last": self.cal_message,
                    "available": raw is not None,
                    "error": getattr(self.hw, "encoder_error", "not supported")}

    @staticmethod
    def _parse_amount(args, units, default_unit):
        """'24cm' / '24 cm' / '0.24 m' / '1 turn' -> value in the base unit, or None."""
        m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([a-z°]*)\s*", " ".join(args))
        if not m:
            return None
        unit = m.group(2) or default_unit
        if unit not in units:
            return None
        v = float(m.group(1)) * units[unit]
        return v if math.isfinite(v) and v > 0 else None

    def calibrate(self, args):
        words = [a for a in args if not re.fullmatch(r"[0-9.]+", a)]
        sub = words[0] if words else "auto"
        rest = args[args.index(sub) + 1:] if sub in args else args
        with self.lock:
            if sub in ("cancel", "abort", "stop"):
                if not self.cal:
                    return "No calibration is running"
                self.cal = None
                self.move = None
                self._set_motors(0.0, 0.0)
                self.cal_message = "Calibration cancelled - the previous calibration is still used"
                self.event("Calibration cancelled")
                return self.cal_message
            if sub == "status":
                c = self.cal
                return self.calibration_summary() + (f"\n  in progress: {c['mode']} - {c['phase']}" if c else "")
            if self.cal and sub in ("auto", "start", "again", "redo", "hand", "manual", "spin"):
                return "A calibration is already running - finish it or 'calibrate cancel'"
            if sub in ("auto", "start", "again", "redo"):
                return self._auto_start(args)
            if sub in ("moved", "distance", "measured"):
                return self._auto_finish(rest)
            if sub in ("spin", "turn", "rotate"):
                return self._spin_start()
            if sub in ("turned", "angle"):
                return self._spin_finish(rest)
            if sub in ("hand", "manual"):
                return self._hand_start(rest)
            if sub in ("next", "done", "ok"):
                return self._hand_next()
        return ("Use: calibrate [cm]  ->  calibrate moved <distance>   (automatic, default)\n"
                "     calibrate spin  ->  calibrate turned <degrees>   (optional, turning)\n"
                "     calibrate hand [diameter] [turns]  ->  calibrate next  (wheels turned by hand)\n"
                "     calibrate cancel  |  calibrate status")

    # ----- automatic: drive, then the user measures -----
    def _drive_for_calibration(self, mode, direction, seconds, label, **extra):
        raw = self._raw_counts()
        if raw is None:
            return f"Encoders not available ({getattr(self.hw, 'encoder_error', '') or 'no data'})"
        why = self.why_unsafe(direction, self.readings, START_MARGIN, sonar_optional=True)
        if why:
            self.blocked = why
            return f"Not moving: {why} - clear the way and try again"
        self.blocked = ""
        self.stuck_wheel = None
        self._stuck_since = [None, None]
        imu = self.readings.get("imu")
        self.cal = {"mode": mode, "phase": "driving", "start": raw, "settle": None,
                    "truth0": self._sim_truth(), "yaw0": imu["yaw"] if imu else None, **extra}
        self.move = {"dir": direction, "until": time.monotonic() + seconds, "label": label,
                     "sonar_optional": True, "t0": time.monotonic()}
        self.cal_message = ""
        self.event(f"{label} started")
        return None

    def _auto_start(self, args):
        nums = [float(a) for a in args if re.fullmatch(r"[0-9]*\.?[0-9]+", a)]
        target_cm = nums[0] if nums else AUTO_CAL_TARGET_CM
        if not 5 <= target_cm <= 100:
            return "Drive distance must be 5-100 cm (e.g. 'calibrate 30')"
        front = self.readings["sonar"].get("front")
        if front is not None:          # leave the stop distance + 2 cm free, so safety does not cut it short
            room_cm = (front - STOP_DISTANCE) * 100 - 2
            if room_cm < 8:
                return (f"Not enough room: the front sonar sees {front * 100:.0f} cm, and the drive needs at least "
                        f"{STOP_DISTANCE * 100 + 10:.0f} cm clear in front. Turn the robot toward open desk and retry.")
            if room_cm < target_cm:
                target_cm = room_cm
        speed_mps = self.speed * WHEEL_SPEED_AT_FULL          # rough guess, only used to pick the time
        seconds = max(0.5, min(8.0, target_cm / 100 / speed_mps))
        err = self._drive_for_calibration("auto", "forward", seconds, "Calibration drive", target_m=target_cm / 100)
        if err:
            return err
        blind = "" if front is not None else (
            "\nNote: the front sonar gives no reading, so only the edge sensor is watching - stay next to it "
            "(Space / 'stop' stops it).")
        return (f"Automatic calibration: driving forward for {seconds:.1f} s (about {target_cm:.0f} cm at speed "
                f"{self.speed:.2f}). Mark where the robot started now if you haven't.\n"
                f"When it stops, measure how far it moved and type e.g. 'calibrate moved 24cm'.  "
                f"('calibrate cancel' to abort){blind}")

    def _calibration_drive_done(self, raw):
        """Called by the control loop once the calibration move has ended and the robot has settled."""
        c = self.cal
        c["end"], c["phase"] = raw, ("measure" if c["mode"] == "auto" else "angle")
        c["stopped"] = self.blocked
        dl, dr = raw[0] - c["start"][0], raw[1] - c["start"][1]
        if abs(dl) < MIN_CAL_COUNTS or abs(dr) < MIN_CAL_COUNTS:
            bad = [s for s, d in zip(SIDES, (dl, dr)) if abs(d) < MIN_CAL_COUNTS]
            pins = ", ".join(f"{s} GPIO {ENCODERS[f'{s}_a']}/{ENCODERS[f'{s}_b']}" for s in bad)
            self.cal = None
            reason = (f"it was stopped: {c['stopped']}" if c["stopped"]
                      else f"the {' and '.join(bad)} encoder barely counted ({dl}, {dr}) - check {pins}")
            self.cal_message = f"Calibration failed: {reason}. Nothing was changed."
            self.event(self.cal_message)
            return
        what = "how far it moved ('calibrate moved 24cm')" if c["mode"] == "auto" else \
            "how far it turned ('calibrate turned 340' or 'calibrate turned 1 turn')"
        imu = self.readings.get("imu")
        if c["mode"] == "spin" and imu and c.get("yaw0") is not None:
            c["gyro_deg"] = round(math.degrees(abs(imu["yaw"] - c["yaw0"])), 1)
            what += f", or 'calibrate turned gyro' to use the gyro's {c['gyro_deg']:.0f} deg"
        note = f" (stopped early: {c['stopped']})" if c["stopped"] else ""
        self.event(f"Calibration move done{note}: counts L {dl}, R {dr} - now tell me {what}")

    def _auto_finish(self, args):
        c = self.cal
        if not c or c["mode"] != "auto":
            return "No automatic calibration is waiting for a distance - type 'calibrate' to start one"
        if c["phase"] != "measure":
            return "Still driving - wait until it stops, then measure"
        dist = self._parse_amount(args, {"mm": 0.001, "cm": 0.01, "m": 1.0}, "cm")
        if dist is None:
            return "Give the distance it moved, e.g. 'calibrate moved 24cm' (a bare number means cm)"
        if not 0.02 <= dist <= 2.0:
            return "That distance looks wrong (must be 2-200 cm). Measure again, or 'calibrate cancel'"
        dl, dr = c["end"][0] - c["start"][0], c["end"][1] - c["start"][1]
        old = getattr(self.hw, "calibration", None) or {}
        diameter = old.get("wheel_diameter_m") or DEFAULT_WHEEL_DIAMETER
        # each wheel rolled `dist` (a straight drive), so metres per count = dist / counts. Stored as counts per
        # revolution of the (assumed) wheel diameter, the format run_prototype also reads.
        data = {"method": "auto", "wheel_diameter_m": diameter,
                "left_counts_per_rev": round(abs(dl) * math.pi * diameter / dist, 3), "left_sign": 1 if dl > 0 else -1,
                "right_counts_per_rev": round(abs(dr) * math.pi * diameter / dist, 3), "right_sign": 1 if dr > 0 else -1,
                "measured_m": round(dist, 4), "counts": [dl, dr]}
        warn = ""
        if abs(abs(dl) - abs(dr)) > 0.15 * max(abs(dl), abs(dr)):
            warn = ("\nNote: the wheels counted more than 15 % apart, so the robot probably curved. Distance is "
                    "still right on average; if one encoder misses counts, check it.")
        where = self._write_calibration(data)
        self.cal = None
        ml, mr = metres_per_count(self.hw.calibration)
        self.cal_message = (f"Calibrated from a {dist * 100:.1f} cm drive: L {ml * 1000:.3f} / R {mr * 1000:.3f} mm "
                            f"per count. {where}{warn}\nOptional: 'calibrate spin' to also calibrate turning.")
        self.event("Encoders calibrated (automatic)")
        return self.cal_message

    # ----- optional: spin, then the user says how far it turned -----
    def _spin_start(self):
        if not getattr(self.hw, "calibration", None):
            return "Calibrate the distance first ('calibrate'), then 'calibrate spin'"
        err = self._drive_for_calibration("spin", "left", self.turn_time(360), "Calibration spin")
        if err:
            return err
        return ("Turning calibration: spinning LEFT about one full turn. Note which way the front points now.\n"
                "When it stops, type how far it turned, e.g. 'calibrate turned 340' (degrees) or "
                "'calibrate turned 1 turn'.  ('calibrate cancel' to abort)")

    def _spin_finish(self, args):
        c = self.cal
        if not c or c["mode"] != "spin":
            return "No spin calibration is waiting for an angle - type 'calibrate spin' to start one"
        if c["phase"] != "angle":
            return "Still spinning - wait until it stops"
        if args[:1] in (["gyro"], ["imu"]):
            if not c.get("gyro_deg"):
                return "The gyro did not measure this spin (no IMU) - measure it and give the angle"
            args = [str(c["gyro_deg"])]
        deg = self._parse_amount(args, {"deg": 1, "degrees": 1, "°": 1, "turn": 360, "turns": 360,
                                        "rev": 360, "revs": 360}, "deg")
        if deg is None:
            return "Give the angle it turned, e.g. 'calibrate turned 340' or 'calibrate turned 1 turn'"
        if not 30 <= deg <= 1080:
            return "That angle looks wrong (must be 30-1080 degrees). Try again, or 'calibrate cancel'"
        cal = self.hw.calibration
        ml, mr = metres_per_count(cal)
        sl, sr = cal.get("left_sign", 1), cal.get("right_sign", 1)
        dl = (c["end"][0] - c["start"][0]) * sl * ml        # left wheel goes back on a left spin (negative)
        dr = (c["end"][1] - c["start"][1]) * sr * mr
        track = (dr - dl) / math.radians(deg)
        if not 0.04 <= track <= 0.5:
            self.cal = None
            self.cal_message = (f"Turning calibration failed: that gives a track width of {track * 100:.1f} cm, "
                                f"which can't be right (wheels L {dl:+.3f} m, R {dr:+.3f} m). Nothing was changed.")
            self.event(self.cal_message)
            return self.cal_message
        data = self._calibration_file_data(cal)
        data.update(track_width_m=round(track, 4), measured_deg=round(deg, 1))
        where = self._write_calibration(data, keep_date=True)
        self.cal = None
        self.cal_message = (f"Turning calibrated: {deg:.0f} deg spin -> track width {track * 100:.1f} cm "
                            f"(was {TRACK_WIDTH * 100:.0f} cm built in). {where}")
        self.event("Turning calibrated")
        return self.cal_message

    # ----- by hand: robot lifted, turn each wheel a known number of turns -----
    def _hand_start(self, args):
        nums = [float(a) for a in args if re.fullmatch(r"[0-9]*\.?[0-9]+", a)]
        raw = self._raw_counts()
        if raw is None:
            return f"Encoders not available ({getattr(self.hw, 'encoder_error', '') or 'no data'})"
        old = getattr(self.hw, "calibration", None)
        diameter = nums[0] if nums else (old["wheel_diameter_m"] if old else DEFAULT_WHEEL_DIAMETER)
        if diameter > 1:              # "calibrate hand 65" means millimetres
            diameter /= 1000
        turns = nums[1] if len(nums) > 1 else 10.0
        if not 0.01 <= diameter <= 0.5:
            return "Wheel diameter must be 10-500 mm (e.g. 'calibrate hand 65')"
        if not 1 <= turns <= 100:
            return "Turns must be 1-100"
        self.move = None
        self._set_motors(0.0, 0.0)
        self.cal = {"mode": "hand", "phase": "turning", "diameter_m": diameter, "revolutions": turns,
                    "step": 0, "start": raw, "results": {}}
        self.cal_message = ""
        self.event(f"Hand calibration started ({diameter * 1000:.0f} mm wheel, {turns:g} turns)")
        hint = "  (simulation: type 'sim turn left 10')" if self.hw.mode == "simulation" else ""
        return (f"Hand calibration - motors stay off. Lift the robot so the wheels turn freely.\n"
                f"Step 1/2: turn the LEFT wheel FORWARD exactly {turns:g} full turns by hand, "
                f"then type 'calibrate next'.{hint}\n('calibrate cancel' stops and keeps the old calibration)")

    def _hand_next(self):
        c = self.cal
        if not c or c["mode"] != "hand":
            return "No hand calibration is running - type 'calibrate hand' to start one"
        raw = self._raw_counts()
        if raw is None:
            return "The encoders stopped answering - 'calibrate cancel', check the wiring, try again"
        i, side, turns = c["step"], SIDES[c["step"]], c["revolutions"]
        counts = raw[i] - c["start"][i]
        if abs(counts) < MIN_CAL_COUNTS:
            pins = f"GPIO {ENCODERS[f'{side}_a']}/{ENCODERS[f'{side}_b']}"
            return (f"The {side} encoder only moved {counts} counts. Turn the {side} wheel {turns:g} full turns "
                    f"(if you did, check its wiring: {pins}, 3.3 V, GND), then 'calibrate next' again.")
        c["results"][side] = {"counts_per_rev": abs(counts) / turns, "sign": 1 if counts > 0 else -1}
        if i == 0:
            c["step"], c["start"] = 1, raw
            hint = "  (simulation: 'sim turn right 10')" if self.hw.mode == "simulation" else ""
            return (f"Left wheel: {abs(counts) / turns:.1f} counts per turn.\n"
                    f"Step 2/2: turn the RIGHT wheel FORWARD exactly {turns:g} full turns, "
                    f"then type 'calibrate next'.{hint}")
        res = c["results"]
        data = {"method": "hand", "wheel_diameter_m": round(c["diameter_m"], 4),
                "left_counts_per_rev": round(res["left"]["counts_per_rev"], 3), "left_sign": res["left"]["sign"],
                "right_counts_per_rev": round(res["right"]["counts_per_rev"], 3), "right_sign": res["right"]["sign"],
                "revolutions": turns}
        where = self._write_calibration(data)
        self.cal = None
        lc, rc = data["left_counts_per_rev"], data["right_counts_per_rev"]
        warn = ""
        if abs(lc - rc) > 0.15 * max(lc, rc):
            warn = ("\nNote: the wheels differ by more than 15 %. If both encoders are the same model, one wheel "
                    "probably got a different number of turns - run 'calibrate hand' again.")
        self.cal_message = (f"Calibrated by hand: L {lc:.1f} / R {rc:.1f} counts per turn, "
                            f"{data['wheel_diameter_m'] * 1000:.0f} mm wheel. {where}{warn}")
        self.event("Encoders calibrated (by hand)")
        return self.cal_message

    # ----- saving -----
    @staticmethod
    def _calibration_file_data(cal):
        """The JSON-able part of a loaded calibration (drops the 'file' it came from)."""
        return {k: v for k, v in cal.items() if k != "file" and v is not None}

    def _write_calibration(self, data, keep_date=False):
        """Save `data` to the calibration file, apply it at once, and say where it went."""
        if not keep_date or "calibrated_at" not in data:
            data["calibrated_at"] = time.strftime("%Y-%m-%d %H:%M")
        path = getattr(self.hw, "calibration_path", ENCODER_FILES[0])
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            where = f"Saved to {path} - loaded automatically on every start."
        except OSError as exc:
            where = f"Could NOT save to {path} ({exc}) - used until this program exits."
        self.hw.calibration = parse_calibration(data, path)
        self._enc_last = self.enc_start = None     # the sign may have changed: restart the count baselines
        return where

    def execute(self, text, source="user"):
        """A command from anywhere (CLI, dashboard, assistant, gestures). An error in any command becomes a reply
        and a dashboard note; it never ends the program."""
        try:
            return self._execute(text, source)
        except Exception as exc:
            HEALTH.note("command", f"'{str(text)[:40]}' failed ({type(exc).__name__}: {exc})", "warn")
            _save_traceback(f"command {text!r}", exc)
            return f"Sorry, that command hit an error ({type(exc).__name__}: {exc}). It's noted on the dashboard."

    def _execute(self, text, source="user"):
        """Parse one command line (CLI and dashboard share this). Returns a reply string.
        source "assistant": sent by the AI's command plan (does not count as a person's command)."""
        parts = text.strip().lower().split()
        if not parts:
            return ""
        if source == "user":
            self.user_cmds += 1
            self.last_user_cmd = time.monotonic()
        cmd, args = parts[0], parts[1:]
        aliases = {"f": "forward", "fwd": "forward", "b": "back", "backward": "back",
                   "l": "left", "r": "right", "x": "stop", "s": "stop", "q": "quit", "exit": "quit",
                   "?": "help", "h": "help"}
        cmd = aliases.get(cmd, cmd)

        def seconds(default):
            for a in args:
                try:
                    v = float(a)
                except ValueError:
                    continue
                if not math.isfinite(v) or v <= 0:
                    raise ValueError("duration must be a positive number of seconds")
                return v
            return default

        try:
            if cmd in ("forward", "back"):
                d = parse_distance(args)
                way, label = ("forward", "Forward") if cmd == "forward" else ("backward", "Backward")
                return self.start(way, 0, label, dist_m=d) if d else self.start(way, seconds(1.0), label)
            if cmd in ("left", "right"):              # a number = seconds (as before); none = 90 deg
                deg = next((a for a in args if re.fullmatch(r"\d+(\.\d+)?(deg|°|degrees?)", a)), None)
                if deg or "deg" in args or "degrees" in args:
                    v = float(re.match(r"\d+(\.\d+)?", deg or next(a for a in args if a[:1].isdigit())).group())
                    if not 1 <= v <= 1080:
                        return "Angle must be 1-1080 degrees"
                    return self.start(cmd, 0, f"Turn {cmd}", v)
                s = seconds(None)
                return self.start(cmd, s, f"Turn {cmd}") if s else self.start(cmd, 0, f"Turn {cmd}", 90)
            if cmd == "spin":
                way = "right" if "right" in args or "cw" in args else "left"
                s = seconds(None)
                return self.start(way, s, f"Spin {way}") if s else self.start(way, 0, f"Spin {way}", 360)
            if cmd == "turn":
                if not args:
                    return "Use: turn <degrees>   (+ = left, - = right, e.g. 'turn 45', 'turn -90')"
                deg = float(args[0].rstrip("°").removesuffix("deg"))
                if not math.isfinite(deg) or not 1 <= abs(deg) <= 1080:
                    return "Angle must be 1-1080 degrees, + = left, - = right"
                way = "left" if deg > 0 else "right"
                return self.start(way, 0, f"Turn {way}", abs(deg))
            if cmd == "imu":
                if self.imu is None:
                    return "No IMU (started with --no-imu)"
                sub = args[0] if args else ""
                if sub in ("zero", "reset"):
                    self.imu.zero()
                    return "IMU heading set to 0 (the robot's pose heading is unchanged; 'map reset' resets that)"
                if sub in ("calibrate", "cal", "level"):
                    return self.imu.calibrate()
                if sub:
                    return "Use: imu | imu zero | imu calibrate"
                i = self.imu.info()
                return (f"{self.imu_line()}\n  sensor: {i['sensor']} | {i['status']}\n"
                        f"  gyro bias {', '.join(f'{b:+.2f}' for b in i['bias_dps'])} deg/s | level from "
                        f"{i['level_from']} | {i['samples']} samples, {i['errors']} errors"
                        + (f"\n  {i['message']}" if i["message"] else ""))
            if cmd in ("photo", "picture", "snap"):
                if self.camera is None:
                    return "No camera (started with --no-camera or --no-dashboard)"
                try:
                    path = self.camera.save_photo()
                except Exception as exc:
                    return f"Could NOT take a photo: {exc}"
                h, w = self.camera.frame.shape[:2]
                self.event(f"Photo saved: {path.name}")
                if self.sounds is not None:
                    self.sounds.play("shutter")
                return f"Photo saved: {path} ({w}x{h})"
            if cmd in ("see", "look", "what"):        # 'what do you see' arrives as cmd 'what'
                det = self.detector
                if det is None or det.model is None:
                    return f"Object detection is not running: {det.status if det else 'off'}"
                if not det.enabled:
                    return "Object detection is off ('detect on')"
                dets = det.current()
                if not dets:
                    return f"Nothing I recognise right now ({det.status})"
                return "I see: " + describe_detections(dets, self.readings["sonar"].get("front"))
            if cmd == "detect":
                det = self.detector
                if det is None:
                    return "Object detection is off (no camera, or --no-detect)"
                if args[:1] in (["on"], ["off"]):
                    det.enabled = args[0] == "on"
                    return f"Object detection {args[0]}" + ("" if det.model else f" (but: {det.status})")
                i = det.info()
                return (f"detect: {i['status']} | {'on' if i['enabled'] else 'off'}, {i['runs']} frames"
                        + (f", ~{i['fps']:.1f} per s" if i["fps"] else ""))
            if cmd == "touch":
                return self.touch_line()
            if cmd == "lift":
                sub = args[0] if args else ""
                if sub in ("on", "off"):
                    with self.lock:
                        self.lift["enabled"] = sub == "on"
                        self._lift_timers.clear()
                        if sub == "off" and self.lift["lifted"]:
                            self.lift.update(lifted=False, since=None, reason="")
                    return f"Lift detection {sub}"
                return self.lift_line() if not sub else "Use: lift | lift on | lift off"
            if cmd == "sim" and args[:1] == ["touch"]:
                if not hasattr(self.hw, "touch_until"):
                    return "'sim touch' only works with --sim"
                hold = "hold" in args
                self.hw.touch_until = time.monotonic() + (TOUCH_HOLD_S + 0.5 if hold else 0.2)
                return f"Simulated: touch pad {'held' if hold else 'tapped'}"
            if cmd == "sim" and args[:1] in (["lift"], ["bump"]):
                src = getattr(self.hw, "imu_source", None)
                if src is None:
                    return f"'sim {args[0]}' only works with --sim"
                if args[0] == "bump":
                    src.bump_until = time.monotonic() + 0.05
                    return "Simulated: a knock from the front"
                src.lifted = (args[1] != "off") if len(args) > 1 else not src.lifted
                return f"Simulated: robot {'lifted (tilted 35 deg)' if src.lifted else 'put back down flat'}"
            if cmd == "stop":
                if self.dance is not None and self.dance.active():    # also from the AI ("stop dancing")
                    self.dance.stop()
                return self.stop()
            if cmd in ("motors", "motor"):
                rev = getattr(self.hw, "reversed", None)
                if rev is None:
                    return "Motor reversal is not supported here"
                sides = [a for a in args[1:] if a in ("left", "right")] or ["left", "right"]
                if args[:1] in (["reverse"], ["reversed"], ["normal"], ["flip"]):
                    self.stop()
                    for side in sides:
                        rev[side] = (not rev[side]) if args[0] == "flip" else args[0] != "normal"
                    try:
                        save_motor_reversal(rev)
                        saved = f"saved in {MOTORS_FILE.name}"
                    except OSError as exc:
                        saved = f"NOT saved ({exc})"
                    self.event(f"Motors: left {'REVERSED' if rev['left'] else 'normal'}, "
                               f"right {'REVERSED' if rev['right'] else 'normal'} ({saved})")
                    sim = " (simulation: its motors are never miswired, so this changes nothing here)" \
                        if self.hw.mode == "simulation" else ""
                    return (f"Left motor {'reversed' if rev['left'] else 'normal'}, right motor "
                            f"{'reversed' if rev['right'] else 'normal'} - {saved}. Try 'forward 0.3'{sim}")
                return (f"Left motor {'REVERSED' if rev['left'] else 'normal'}, right motor "
                        f"{'REVERSED' if rev['right'] else 'normal'}. If 'forward' drives backwards: 'motors reverse'; "
                        f"if 'forward' spins: 'motors reverse left' (or right)")
            if cmd == "slam":
                if self.slam is None:
                    return "SLAM is not available"
                if args[:1] in (["on"], ["start"]):
                    self.slam.set(True)
                    self.event("SLAM on: the sonar map corrects the pose")
                    return "SLAM on: drive around known obstacles and it corrects wheel/gyro drift against the map"
                if args[:1] in (["off"], ["stop"]):
                    self.slam.set(False)
                    self.event("SLAM off")
                    return "SLAM off: the pose comes from the wheels and gyro only"
                return self.slam.line()
            if cmd in ("invert", "flip") or (cmd == "camera" and args[:1] == ["invert"]):
                cam = self.camera
                if cam is None:
                    return "No camera"
                a = args[1:] if cmd == "camera" else args
                cam.invert = (a[0] == "on") if a[:1] in (["on"], ["off"]) else not cam.invert
                return f"Camera picture {'upside down (inverted)' if cam.invert else 'as the camera sees it'}"
            if cmd == "obstacles":
                if args[:1] in (["ignore"], ["off"]):
                    self.ignore_obstacles = True
                    if "sonar" in self.blocked or "obstacle" in self.blocked:
                        self.blocked = ""
                    self.event("Obstacle stops OFF: the sonars no longer stop moves (edges, lift, tilt, bump still do)")
                    return "Ignoring obstacles: the sonars won't stop moves. Desk edges, lifting, tilt and bumps still stop it."
                if args[:1] in (["on"], ["watch"], ["stop"]):
                    self.ignore_obstacles = False
                    self.event("Obstacle stops ON")
                    return "Watching for obstacles again"
                return ("Obstacles are IGNORED ('obstacles on' to watch again)" if self.ignore_obstacles else
                        f"Obstacle stops are on ({STOP_DISTANCE * 100:.0f} cm front/rear, "
                        f"{SIDE_STOP_DISTANCE * 100:.0f} cm sides). 'obstacles ignore' turns them off")
            if cmd == "speed":
                if not args:
                    return f"Speed is {self.speed:.2f}"
                v = float(args[0])
                if not 0.1 <= v <= 1.0:
                    return "Speed must be between 0.1 and 1.0"
                self.speed = v
                return f"Speed set to {v:.2f}"
            if cmd == "status":
                s = self.status()
                son = ", ".join(f"{k} {'--' if v is None else f'{v * 100:.0f} cm'}" for k, v in s["sonar"].items())
                flo = ", ".join(f"{k} {'?' if v is None else 'floor' if v else 'EDGE'}" for k, v in s["floor"].items())
                p = s["pose"]
                mv = s["move"]["label"] if s["move"] else "idle"
                return (f"[{s['mode']}] {mv} | speed {s['speed']:.2f}\n  sonar: {son}\n  IR: {flo}\n"
                        f"  pose: x {p['x']:.2f} m, y {p['y']:.2f} m, heading {math.degrees(p['theta']):.0f} deg\n"
                        f"  {self.encoder_line()}\n  {self.imu_line()}\n  {self.touch_line()}\n  {self.lift_line()}"
                        + ("\n  OBSTACLES IGNORED: the sonars do not stop moves ('obstacles on')"
                           if s["obstacles_ignored"] else "")
                        + (f"\n  last block: {s['blocked']}" if s["blocked"] else ""))
            if cmd == "encoders":
                e = self.encoder_status()
                return (self.encoder_line()
                        + (f"\n  calibration: {e['calibration_file']}" if e["calibrated"] else "")
                        + (f"\n  STUCK: {e['stuck']} wheel" if e["stuck"] else ""))
            if cmd in ("calibrate", "cal"):
                return self.calibrate(args)
            if cmd == "sim" and args[:1] == ["turn"]:
                if not hasattr(self.hw, "turn_by_hand"):
                    return "'sim turn' only works with --sim"
                side = args[1] if len(args) > 1 else ""
                if side not in SIDES:
                    return "Use: sim turn left|right [turns]"
                turns = float(args[2]) if len(args) > 2 else 10.0
                self.hw.turn_by_hand(side, turns)
                return f"Simulated: {side} wheel turned {turns:g} times by hand"
            if cmd == "oled":
                if self.oled is None:
                    return "No OLED (the dashboard-only or --no-oled mode)"
                return self.oled.command(args, text.strip())
            if (cmd == "face" and args[:1] == ["me"]) or (cmd in ("look", "turn") and args[:2] == ["at", "me"]):
                if self.people is None:
                    return "No camera features (started with --no-camera?)"
                if args[1:2] == ["on"] or args[2:3] == ["on"]:
                    return self.people.set_keep(True)
                if args[1:2] == ["off"] or args[2:3] == ["off"]:
                    return self.people.set_keep(False)
                return self.people.face_once()
            if cmd in ("greet", "greeter") and args[:1] in (["on"], ["off"]):
                if self.people is None:
                    return "No camera features"
                self.people.greet_enabled = args[0] == "on"
                return f"Greeter {args[0]}"
            if cmd == "people":
                return self.people.line() if self.people else "No camera features"
            if cmd == "sim" and args[:1] == ["person"]:
                if self.hw.mode != "simulation":
                    return "'sim person' only works in simulation (--sim)"
                self.hw.OBJECTS = [o for o in self.hw.OBJECTS if o[0] != "person"]
                if args[1:2] == ["off"]:
                    return "Simulated person gone"
                try:
                    deg = float(args[1]) if len(args) > 1 else 0.0
                except ValueError:
                    return "Use: sim person <angle, + = left> | sim person off"
                x, y, th = self.pose
                a = th + math.radians(deg)
                px, py = x + 0.6 * math.cos(a), y + 0.6 * math.sin(a)
                self.hw.OBJECTS = self.hw.OBJECTS + [("person", (px - 0.15, py - 0.15, px + 0.15, py + 0.15), 0.6)]
                return f"Simulated person 60 cm away, {deg:+.0f} deg"
            if cmd in ("weather", "joke", "wiki", "wikipedia", "convert") or (cmd == "look" and args[:1] == ["up"]):
                a = self.apis
                if a is None:
                    return "The web APIs are not available (see the Notes card)"
                rest = text.strip().split(None, 1)[1] if len(text.strip().split()) > 1 else ""
                try:
                    if cmd == "weather":
                        if args[:1] == ["home"]:
                            return a.set_home(rest.split(None, 1)[1] if len(rest.split()) > 1 else "")
                        return a.weather(rest)
                    if cmd == "joke":
                        j = a.joke()
                        self.announce(j, "happy")
                        return j
                    if cmd == "convert":
                        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]{3})\s+(?:to|in|into)\s+([a-zA-Z]{3})", rest.strip())
                        return a.convert(*m.groups()) if m else "Use: convert 10 usd to inr"
                    return a.wikipedia(rest.removeprefix("up ").strip() if cmd == "look" else rest)
                except ApiError as exc:
                    return f"Sorry: {exc}"
            if cmd in ("idea", "ideas"):
                ib = self.ideas
                if ib is None:
                    return "The ideas notebook is not available (see the Notes card)"
                rest = text.strip().split(None, 1)[1] if len(text.strip().split()) > 1 else ""
                if cmd == "idea":
                    return ib.add(rest)
                if args[:1] in (["forget"], ["delete"], ["remove"]):
                    return ib.forget(rest.split(None, 1)[1] if len(rest.split()) > 1 else "")
                if args[:1] == ["search"]:
                    hits = ib.search(rest.split(None, 1)[1] if len(rest.split()) > 1 else "")
                    return "\n".join(f"  #{i['id']} {i['text']}" for i in hits[:15]) or "No matching ideas"
                return ib.lines()
            if cmd in ("gesture", "gestures"):
                g = self.gestures
                if g is None:
                    return "Gestures are not available (see the Notes card)"
                words = text.strip().split()
                if cmd == "gestures" or len(words) < 2:
                    return "Gestures (laptop camera):\n" + "\n".join(
                        f"  {n}: {g.map.get(n) or '(nothing)'}" for n in GESTURE_NAMES) + \
                        f"\n  Allowed actions: {', '.join(a or '(nothing)' for a in GESTURE_ACTIONS)}"
                if words[1].lower() == "map":
                    if len(words) < 3:
                        return "Use: gesture map <Name> <action>"
                    return g.set(words[2], " ".join(words[3:]).lower())
                return g.handle(words[1])
            if cmd in ("dance", "boogie", "songs"):
                d = self.dance
                if d is None:
                    return "Dancing is not available (see the Notes card)"
                if cmd == "songs" or args[:1] in (["list"], ["songs"]):
                    return "Songs:\n" + "\n".join(
                        f"  {s['title']} ({s['bpm']:.0f} bpm, {s['seconds']:.0f} s{', file' if s['kind'] == 'file' else ''})"
                        for s in d.songs()) + "\n  (add .mp3/.ogg/.wav files to songs/ next to this script)"
                if args[:1] in (["stop"], ["off"], ["end"]):
                    return d.stop()
                if args[:1] in (["status"], ["info"]):
                    return d.line()
                want = " ".join(text.strip().split()[1:]).removeprefix("to ").strip()
                return d.start("" if want.lower() in ("", "random") else want)
            if cmd in ("sounds", "sound", "beep", "sfx"):
                sd = self.sounds
                if sd is None:
                    return "Sound effects are not available (see the Notes card)"
                if args[:1] in (["on"], ["off"]):
                    return sd.set(args[0] == "on")
                if args:
                    return sd.play(args[0])
                i = sd.info()
                return (f"Sound effects {'on' if i['on'] else 'off'} (played by the dashboard page, on the laptop)\n"
                        f"  sounds: {', '.join(i['names'])}\n  'sound <name>' plays one, 'sounds on|off'")
            if cmd in ("rps", "rock", "paper", "scissors"):
                g = self.rps
                if g is None:
                    return "Rock paper scissors is not available (see the Notes card)"
                if cmd != "rps":
                    return g.play(cmd)
                if args[:1] in (["stop"], ["end"], ["quit"]):
                    return g.stop()
                if args[:1] and args[0] in RPS_BEATS:
                    return g.play(args[0])
                return g.start()
            if cmd == "phone" or (cmd == "sim" and args[:1] == ["phone"]):
                ph = self.phone
                if ph is None:
                    return "No Bluetooth (started with --no-bluetooth, or it could not start: see the Notes card)"
                if cmd == "sim":
                    if not ph.sim:
                        return "'sim phone' only works in simulation (--sim)"
                    where = args[1] if len(args) > 1 else "near"
                    ph.sim_rssi = {"near": -55.0, "far": -76.0, "away": None, "off": None}.get(where, -55.0)
                    return f"Simulated phone: {where}"
                if args[:1] == ["devices"]:
                    devs = ph.devices()
                    if not devs:
                        return "Nothing heard over Bluetooth yet" + (f" ({ph.error})" if ph.error else "")
                    return "Nearby (strongest first):\n" + "\n".join(
                        f"  {d['rssi']} dBm  {d['address']}  {d['name'] or '(no name)'}{'  <- yours' if d['match'] else ''}"
                        for d in devs[:12])
                if args[:1] == ["use"]:
                    return ph.use(text.strip().split(None, 2)[2] if len(args) > 1 else "")
                if args[:1] == ["forget"]:
                    ph.match = {"address": "", "name": "", "ibeacon": ""}
                    try:
                        ph.file.unlink()
                    except OSError:
                        pass
                    return "Forgot the phone"
                return ph.line()
            if cmd in ("focus", "pomodoro"):
                if self.focus is None:
                    return "No focus timer"
                if args[:1] in (["stop"], ["end"], ["off"], ["cancel"]):
                    return self.focus.stop()
                if args[:1] == ["status"] or (not args and self.focus.mode != "idle"):   # bare 'focus' while running
                    return self.focus.line()
                nums = [float(a.removesuffix("min").removesuffix("m")) for a in args
                        if re.fullmatch(r"\d+(\.\d+)?(min|m)?", a)]
                return self.focus.start(int(nums[0]) if nums else FOCUS_DEFAULT_MIN)
            if cmd in ("remind", "todo", "task", "tasks", "done", "undone", "reopen"):
                if self.tasks is None:
                    return "No task list"
                words = text.strip().split(None, 1)
                rest = words[1] if len(words) > 1 else ""
                if cmd == "remind":
                    rest = re.sub(r"^\s*me\b\s*", "", rest, flags=re.I)
                    t, reply = self.tasks.add(rest)
                    if t is not None and not t["due"]:
                        reply += " (no time given, so it's on the list without a reminder)"
                    return reply
                if cmd in ("todo", "task") or (cmd == "tasks" and args[:1] == ["add"]):
                    return self.tasks.add(re.sub(r"^\s*add\b\s*", "", rest, flags=re.I) if cmd == "tasks" else rest)[1]
                if cmd == "done":
                    return self.tasks.complete(rest) if rest else "Use: done <#number or words>"
                if cmd in ("undone", "reopen"):
                    return self.tasks.complete(rest, done=False) if rest else "Use: undone <#number>"
                if args[:1] in (["remove"], ["delete"]) and len(args) > 1:
                    return self.tasks.remove(rest.split(None, 1)[1])
                if args[:2] == ["clear", "done"]:
                    return self.tasks.clear_done()
                if args:
                    return "Use: tasks | tasks add <task> | tasks remove <#n> | tasks clear done"
                return self.tasks.lines()
            if cmd in ("go", "goto", "find", "come") and args:
                words = [w for w in args if w not in ("to", "the", "my", "a", "an", "back", "please")]
                if cmd == "come" or words == ["home"] or args[:2] == ["back", "home"]:
                    return self.nav.start("home")
                return self.nav.start(" ".join(words), face_only=cmd == "find")
            if cmd == "objects" or (cmd in ("where", "where's", "wheres") and args):
                if args[:1] == ["clear"] and cmd == "objects":
                    self.objects.reset()
                    return "Objects forgotten"
                found = self.objects.describe(self.pose)
                if cmd == "objects":
                    if not found:
                        why = "" if (self.detector and self.detector.model) else \
                            f" (object detection is not running: {self.detector.status if self.detector else 'off'})"
                        return "No objects on the map yet" + why
                    return "Objects on the map:\n" + "\n".join(f"  {o['label']}: {where_words(o)}" for o in found)
                thing = " ".join(w for w in args if w not in ("is", "are", "the", "my", "a", "an")).strip("?")
                o = self.objects.find(thing, self.pose)
                return (f"The {o['label']} is {where_words(o)}" if o else
                        f"I haven't seen a {thing or 'thing'} - look around ('spin') and ask again")
            if cmd == "map" and args[:1] == ["reset"]:
                self.map.reset()
                self.objects.reset()
                with self.lock:
                    self.pose = (0.0, 0.0, 0.0)
                    self.enc_start = self.enc_counts
                if self.slam is not None:
                    self.slam.reset()
                return "Map cleared, pose reset to (0, 0)"
            if cmd in ("ask", "hey", "ai", "heard"):         # 'heard': the dashboard's browser speech-to-text
                if self.assistant is None:
                    return "No assistant"
                words = text.strip().split(None, 1)
                return self.assistant.ask(words[1] if len(words) > 1 else "",
                                          source="voice" if cmd == "heard" else "typed")
            if cmd == "assistant":
                return self.assistant.line() if self.assistant else "No assistant"
            if cmd == "help":
                return "Commands:" + __doc__.split("dashboard):", 1)[1].split("Safety:", 1)[0].rstrip()
            if cmd == "quit":
                return "quit"
        except ValueError as exc:
            return f"Bad value: {exc}"
        return f"Unknown command '{text.strip()}' - type help"

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self.hw.drive(0, 0)
        except Exception:
            pass
        self.hw.close()


# =====================================================================
# OLED screen (I2C, 128 x 64) - eyes that react to the robot, a status page, or text
# =====================================================================

def local_ip():
    """This machine's LAN address (no packet is sent: UDP connect only picks the outgoing interface)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class Oled:
    """Draws the screen ~10 times a second in its own thread; only this thread talks to the display.

    The same image is kept for the dashboard mirror (/oled.png), so it also works in simulation or with no
    screen attached. A display error (loose wire) is logged once and the screen is reopened every 5 s.
    """

    W, H = OLED_WIDTH, OLED_HEIGHT
    MODES = ("eyes", "status", "off")
    #           w   h   dx  dy  lid    lid: + = angry (inner corners down), - = sad (outer corners down)
    FACES = {"normal": (30, 30, 0, 0, 0), "angry": (30, 22, 0, 2, 9), "sad": (28, 24, 0, 4, -9),
             "scared": (24, 38, 0, -2, 0), "focused": (32, 14, 0, -6, 0), "sleepy": (32, 5, 0, 6, 0),
             "happy": (30, 30, 0, 0, 0)}

    def __init__(self, robot, port, enabled=True, driver="ssd1306", address=0x3C, rotate=0):
        self.robot, self.port = robot, port
        self.driver, self.address, self.rotate = driver, address, rotate
        self.mode = "eyes"
        self.device, self.status = None, "off"
        self.image = None                   # latest frame (PIL "1"), for the dashboard
        self.png = b""
        self.frame_no, self._png_no = 0, -1
        self.say_text, self.say_until = "", 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pose = list(self.FACES["normal"])
        self._blink_at = time.monotonic() + 2.0
        self._glance_at, self._glance = time.monotonic() + 4.0, 0.0
        self._react, self._react_until = "", 0.0
        self._seen = {"blocked": "", "events": 0, "cal_last": ""}
        self._last_activity = time.monotonic()
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        except ImportError:
            self.status = "disabled (Pillow not installed: pip install pillow)"
            log(f"[oled] {self.status}")
            return
        if not enabled:
            self.status = "disabled (--no-oled)"
            return
        self.say(f"Dashboard\nhttp://{local_ip()}:{port}", 8)
        threading.Thread(target=self._run, daemon=True, name="oled").start()

    # ----- display -----
    def _open(self):
        if self.robot.hw.mode == "simulation":
            self.status = "simulated (dashboard mirror only)"
            return
        try:
            from luma.core.interface.serial import i2c
            from luma.oled import device as oled

            make = {"ssd1306": oled.ssd1306, "sh1106": oled.sh1106}[self.driver]
            self.device = make(i2c(port=1, address=self.address), width=self.W, height=self.H, rotate=self.rotate)
            was_down = self.status.startswith(("not answering", "unavailable", "error"))
            self.status = f"{self.driver} at {self.address:#04x} on I2C bus 1"
            log(f"[oled] {'screen connected again: ' if was_down else ''}{self.status}")
        except Exception as exc:
            self.device = None
            if type(exc).__name__ == "DeviceNotFoundError" or isinstance(exc, OSError):
                status = (f"not answering on I2C at {self.address:#04x} - loose wire? "
                          f"(VCC, GND, SDA GPIO 2, SCL GPIO 3)")
            else:
                status = f"unavailable ({type(exc).__name__}: {exc})"
            if self.status != status:
                log(f"[oled] screen {status}. Retrying every {OLED_RETRY_S:g} s; the dashboard still shows it.")
            self.status = status

    def _run(self):
        from PIL import Image

        self._open()
        next_open = time.monotonic() + OLED_RETRY_S
        last_bytes = None
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                img = self.render(now)
            except Exception as exc:          # a drawing bug must never kill the robot
                log(f"[oled] draw error: {exc}")
                img = Image.new("1", (self.W, self.H))
            data = img.tobytes()
            if data != last_bytes:
                last_bytes = data
                import io
                with self._lock:
                    self.image = img           # the PNG for the dashboard is made on request (png_bytes)
                    self.frame_no += 1
                if self.device is not None:
                    try:
                        self.device.display(img)
                    except Exception as exc:
                        log(f"[oled] lost the screen ({exc}) - reconnecting every {OLED_RETRY_S:g} s")
                        self.status = f"error: lost the screen ({exc}) - loose wire?"
                        self.device, last_bytes = None, None
            if self.device is None and self.robot.hw.mode != "simulation" and now >= next_open:
                next_open = now + OLED_RETRY_S
                self._open()
                last_bytes = None
            self._stop.wait(0.1)

    def png_bytes(self):
        """The current frame as PNG for the dashboard mirror, encoded only when it changed since the last ask."""
        import io

        with self._lock:
            if self._png_no != self.frame_no and self.image is not None:
                buf = io.BytesIO()
                self.image.save(buf, "PNG")
                self.png, self._png_no = buf.getvalue(), self.frame_no
            return self.png

    def close(self):
        self._stop.set()
        if self.device is not None:
            try:
                self.device.clear()
                self.device.cleanup()
            except Exception:
                pass

    # ----- commands -----
    def say(self, text, seconds=6.0):
        self.say_text = text.replace("\\n", "\n")[:120]
        self.say_until = time.monotonic() + seconds

    def mood(self, face, seconds=4.0):
        """Show this face (one of FACES) for a while, e.g. the assistant's reply mood. Lifted/stuck still win."""
        if face in self.FACES:
            self._react, self._react_until = face, time.monotonic() + seconds

    def _not_on_screen(self):
        """'' when the picture really reaches a screen (or this is the simulation), else why it does not."""
        if self.device is not None or self.robot.hw.mode == "simulation":
            return ""
        return f"\n  ...but NOT on the screen right now: {self.status}. It reconnects by itself."

    def command(self, args, raw_text=""):
        if not args:
            return (f"OLED: {self.status} | mode {self.mode}"
                    + (" | showing text" if time.monotonic() < self.say_until else ""))
        sub = args[0]
        if sub in self.MODES:
            self.mode = sub
            self.say_until = 0.0
            return f"OLED mode: {sub}{self._not_on_screen()}"
        if sub == "ip":
            self.say(f"Dashboard\nhttp://{local_ip()}:{self.port}", 8)
            return f"OLED shows the dashboard address: http://{local_ip()}:{self.port}{self._not_on_screen()}"
        # 'oled hello' and 'oled say hello' both show the text (with its original capitals)
        parts = raw_text.split(None, 2 if sub == "say" else 1)
        text = parts[-1] if len(parts) == (3 if sub == "say" else 2) else ""
        if not text:
            return "Use: oled <text>  |  oled eyes|status|off|ip   (\\n in the text = new line; shown for 6 s)"
        self.say(text)
        return f"OLED shows: {text}{self._not_on_screen()}"

    def info(self):
        return {"status": self.status, "mode": self.mode, "showing_text": time.monotonic() < self.say_until,
                "hardware": self.device is not None}

    # ----- drawing -----
    def render(self, now):
        from PIL import Image, ImageDraw

        img = Image.new("1", (self.W, self.H))
        d = ImageDraw.Draw(img)
        if now < self.say_until:
            self._draw_text(d, self.say_text)
        elif self.mode == "status":
            self._draw_status(d)
        elif self.mode == "eyes":
            self._draw_eyes(d, now)
            f = self.robot.focus.info() if self.robot.focus is not None and self.robot.focus.mode != "idle" else None
            if f:
                txt = f"{'FOCUS' if f['mode'] == 'focus' else 'BREAK'} {f['left_s'] // 60}:{f['left_s'] % 60:02d}"
                font = self._font(10)
                box = d.textbbox((0, 0), txt, font=font)
                d.rectangle((0, self.H - 12, box[2] + 4, self.H), fill=0)
                d.text((2, self.H - 12), txt, font=font, fill=1)
        return img

    @staticmethod
    def _font(size):
        from PIL import ImageFont
        try:
            return ImageFont.load_default(size=size)       # Pillow >= 10.1: scalable
        except TypeError:
            return ImageFont.load_default()

    def _draw_text(self, d, text):
        """Biggest font that fits (same idea as oled_print.py)."""
        import textwrap
        for size in range(28, 7, -2):
            font = self._font(size)
            chars = max(1, int(self.W / (size * 0.55)))
            lines = "\n".join(textwrap.fill(part, chars, break_long_words=False) or " "
                              for part in text.split("\n"))
            box = d.multiline_textbbox((0, 0), lines, font=font, spacing=2)
            if box[2] - box[0] <= self.W - 2 and box[3] - box[1] <= self.H - 2:
                break
        x = (self.W - (box[2] - box[0])) // 2 - box[0]
        y = (self.H - (box[3] - box[1])) // 2 - box[1]
        d.multiline_text((x, y), lines, font=font, fill=1, spacing=2, align="center")

    def _draw_status(self, d):
        s = self.robot.status()
        cm = lambda v: "--" if v is None else f"{v * 100:.0f}"
        so = s["sonar"]
        fl = s["floor"]
        ir = lambda v: "?" if v is None else ("ok" if v else "EDGE")
        e = s["encoders"]
        mv = s["move"]["label"] if s["move"] else "idle"
        im = s.get("imu")
        imu_txt = ("imu off" if im is None else f"imu H{im['heading_deg']:.0f} tilt{im['tilt_deg']:.0f}"
                   if im["ok"] else "imu " + im["status"][:17])
        lines = [f"{local_ip()}:{self.port}",
                 f"{s['mode'][:5]} {mv[:12]} {s['speed']:.2f}",
                 f"F{cm(so.get('front'))} L{cm(so.get('left'))} R{cm(so.get('right'))} B{cm(so.get('rear'))}",
                 f"IR f:{ir(fl.get('front'))} r:{ir(fl.get('rear'))}",
                 ("enc " + (f"{e['counts'][0]}/{e['counts'][1]}" if e["counts"] else "n/a")
                  + (" cal" if e["calibrated"] else " uncal")),
                 (s["blocked"] or imu_txt)[:21]]
        font = self._font(10)
        for i, line in enumerate(lines):
            d.text((0, i * 10 + 1), line, font=font, fill=1)

    def _expression(self, s, now):
        """Which face, and where the eyes look, from the robot's state."""
        cal = s.get("calibration") or {}
        if s["blocked"] != self._seen["blocked"]:
            self._seen["blocked"] = s["blocked"]
            if s["blocked"]:
                b = s["blocked"]
                self._react = ("sad" if "stuck" in b else "scared" if ("edge" in b or "tilted" in b)
                               else "happy" if "touch" in b else "angry")
                self._react_until = now + 3.0
        if (cal.get("last") or "") != self._seen["cal_last"]:
            self._seen["cal_last"] = cal.get("last") or ""
            if self._seen["cal_last"].startswith("Calibrated") or self._seen["cal_last"].startswith("Turning calibrated"):
                self._react, self._react_until = "happy", now + 4.0
            elif "failed" in self._seen["cal_last"]:
                self._react, self._react_until = "sad", now + 4.0
        if len(s["events"]) != self._seen["events"] or s["move"]:
            self._seen["events"] = len(s["events"])
            self._last_activity = now
        mv = s["move"]
        look = {"forward": (0, -4), "backward": (0, 5), "left": (-14, 0), "right": (14, 0)}.get(
            mv.get("dir") if mv else None, None)
        if (s["encoders"] or {}).get("stuck"):
            return "sad", (0, 4)
        lf = s.get("lift") or {}
        if lf.get("lifted"):                                          # picked up: wide eyes, looking down
            self._last_activity = now
            return "scared", (0, 5)
        if lf.get("resets", 0) != self._seen.get("resets", 0):       # put down somewhere new: happy
            self._seen["resets"] = lf.get("resets", 0)
            self._react, self._react_until = "happy", now + 3.0
        tc = s.get("touch") or {}
        if tc.get("pats", 0) != self._seen.get("pats", 0):            # a pat: happy for 3 s
            self._seen["pats"] = tc.get("pats", 0)
            self._react, self._react_until = "happy", now + 3.0
        if tc.get("touched"):                                         # being touched: happy, looking up
            self._last_activity = now
            return "happy", (0, -5)
        im = s.get("imu")
        if im and im["ok"] and im["tilt_deg"] > IMU_TILT_STOP_DEG:   # picked up / tipping: wide eyes, look down
            self._last_activity = now
            return "scared", (0, 5)
        if cal.get("active"):
            return "focused", look or (0, 0)
        if now < self._react_until:
            return self._react, (0, 0)
        if look:
            return "normal", look
        dets = (s.get("vision") or {}).get("detections") or []
        if dets:                                    # look at the biggest thing it recognises
            big = max(dets, key=lambda d: d["size"])
            if big["label"] == "person" and not self._seen.get("person"):
                self._react, self._react_until = "happy", now + 2.0    # someone came into view: happy
            self._seen["person"] = any(d["label"] == "person" for d in dets)
            self._last_activity = now
            return ("happy" if now < self._react_until else "normal",
                    (max(-14.0, min(14.0, -big["bearing_deg"] / (CAMERA_HFOV_DEG / 2) * 14)), 0))
        self._seen["person"] = False
        if now - self._last_activity > OLED_SLEEPY_AFTER_S:
            return "sleepy", (0, 0)
        return "normal", None

    def _draw_eyes(self, d, now):
        face, look = self._expression(self.robot.status(max_age=STATUS_SHARE_S), now)
        if look is None:                                   # idle: glance around now and then
            if now >= self._glance_at:
                self._glance = random.choice((-10, 0, 0, 10))
                self._glance_at = now + random.uniform(2.0, 5.0)
            look = (self._glance, 0)
        target = list(self.FACES[face])
        target[2] += look[0]
        target[3] += look[1]
        if face not in ("sleepy", "focused"):              # blink every 2-6 s for 0.12 s
            if now >= self._blink_at + 0.12:
                self._blink_at = now + random.uniform(2.0, 6.0)
            elif now >= self._blink_at:
                target[1] = 2
        self._pose = [p + (t - p) * 0.45 for p, t in zip(self._pose, target)]   # ease toward the target
        w, h, dx, dy, lid = self._pose
        cy = self.H / 2 + dy
        for side in (-1, 1):                                # -1 = left eye on screen, +1 = right eye
            cx = self.W / 2 + side * 26 + dx
            x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
            if h < 4:
                d.line((x0, cy, x1, cy), fill=1, width=2)
                continue
            d.rounded_rectangle((x0, y0, x1, y1), radius=min(8, h / 2, w / 2), fill=1)
            if abs(lid) > 0.5:                              # slanted eyelid cut
                inner_x, outer_x = (x1, x0) if side < 0 else (x0, x1)
                low_x = inner_x if lid > 0 else outer_x     # angry: inner corner down; sad: outer down
                high_x = outer_x if lid > 0 else inner_x
                d.polygon([(high_x, y0 - 1), (low_x, y0 - 1), (low_x, y0 + abs(lid))], fill=0)
            if face == "happy":                             # ^ ^ : cut away the lower half
                d.ellipse((x0 - 6, cy + h * 0.05, x1 + 6, cy + h * 1.2), fill=0)
        if face == "focused":
            font = self._font(10)
            d.text((self.W / 2, self.H - 6), "calibrating", font=font, fill=1, anchor="ms")


# =====================================================================
# Dashboard (stdlib HTTP server, page embedded below)
# =====================================================================

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Desk Robot</title>
<script>try{const t=localStorage.getItem('robot-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}</script>
<style>
:root{--bg:#f3f4f6;--card:#ffffff;--sub:#f8f9fb;--fg:#17202e;--mut:#667085;--line:#e3e6eb;--acc:#2563eb;--acc-s:#dbe7fe;
--ok:#15803d;--ok-s:#dcfce7;--warn:#b45309;--warn-s:#fef3c7;--bad:#dc2626;--bad-s:#fee2e2;--unk:#98a2b3;--free:#e8edf5;--shadow:0 1px 2px rgba(16,24,40,.05),0 6px 18px -6px rgba(16,24,40,.12);--shadow-h:0 2px 4px rgba(16,24,40,.06),0 14px 32px -10px rgba(16,24,40,.22);--bg2:#e6ebf3}
:root{color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0e1116;--card:#171b22;--sub:#1d222b;--fg:#e7eaee;--mut:#98a2b3;--line:#2a313c;--acc:#6ea8fe;--acc-s:#1c2a44;
--ok:#4ade80;--ok-s:#12301f;--warn:#fbbf24;--warn-s:#3a2c0b;--bad:#f87171;--bad-s:#3b1717;--unk:#5d6675;--free:#202733;--shadow:0 1px 0 rgba(255,255,255,.04) inset,0 10px 28px -12px rgba(0,0,0,.7);--shadow-h:0 1px 0 rgba(255,255,255,.06) inset,0 18px 40px -14px rgba(0,0,0,.85);--bg2:#0a0d12}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0e1116;--card:#171b22;--sub:#1d222b;--fg:#e7eaee;--mut:#98a2b3;--line:#2a313c;--acc:#6ea8fe;--acc-s:#1c2a44;
--ok:#4ade80;--ok-s:#12301f;--warn:#fbbf24;--warn-s:#3a2c0b;--bad:#f87171;--bad-s:#3b1717;--unk:#5d6675;--free:#202733;--shadow:0 1px 0 rgba(255,255,255,.04) inset,0 10px 28px -12px rgba(0,0,0,.7);--shadow-h:0 1px 0 rgba(255,255,255,.06) inset,0 18px 40px -14px rgba(0,0,0,.85);--bg2:#0a0d12}
.themebtn{cursor:pointer;font:inherit;font-size:12px}.themebtn:hover{border-color:var(--acc);color:var(--fg)}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 10% -10%,color-mix(in srgb,var(--acc) 9%,transparent),transparent 60%),linear-gradient(180deg,var(--bg),var(--bg2));background-attachment:fixed;min-height:100vh;color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
button,input{font:inherit;color:inherit}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 16px;
background:color-mix(in srgb,var(--card) 72%,transparent);backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid color-mix(in srgb,var(--line) 70%,transparent);box-shadow:0 4px 20px -12px rgba(0,0,0,.25)}
.top h1{font-size:16px;margin:0 6px 0 0;letter-spacing:-.01em}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:99px;background:var(--card);border:1px solid var(--line);
color:var(--mut);font-size:12px;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--unk)}.dot.on{background:var(--ok)}.dot.off{background:var(--bad)}.dot.sim{background:var(--warn)}
.spacer{flex:1}
.stopbig{border:0;border-radius:10px;background:var(--bad);color:#fff;font-weight:700;padding:9px 18px;cursor:pointer;letter-spacing:.03em}
.stopbig:active{transform:scale(.97)}
kbd{font:11px ui-monospace,monospace;padding:1px 5px;border-radius:4px;border:1px solid currentColor;opacity:.7;margin-left:6px}
/* the warning banner floats at the bottom (25 Nov 2026): appearing/disappearing must not push the cards around */
.banner{position:fixed;z-index:15;left:50%;bottom:16px;transform:translateX(-50%);width:min(900px,calc(100vw - 32px));
  box-shadow:var(--shadow-h);padding:10px 14px;border-radius:10px;background:var(--warn-s);color:var(--warn);border:1px solid color-mix(in srgb,var(--warn) 35%,transparent)}
.banner.bad{background:var(--bad-s);color:var(--bad);border-color:color-mix(in srgb,var(--bad) 35%,transparent)}
.grid{display:grid;gap:16px;align-items:start;grid-auto-flow:row;padding:14px 16px 24px;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));max-width:1500px;margin:0 auto}
.card{background:var(--card);border:1px solid color-mix(in srgb,var(--line) 80%,transparent);border-radius:16px;padding:16px;box-shadow:var(--shadow);min-width:0;transition:box-shadow .2s,transform .2s,opacity .2s;animation:cardin .35s ease both}
.card:hover{box-shadow:var(--shadow-h)}
@keyframes cardin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.card{animation:none;transition:none}}
.card h2{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:650;margin:0 0 12px;color:var(--mut);text-transform:uppercase;letter-spacing:.07em}
.card h2 .r{margin-left:auto;text-transform:none;letter-spacing:0;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
/* text that changes while running gets fixed space, so a card's height (and everything below it) stays put */
#dets{height:26px;overflow:hidden;flex-wrap:nowrap!important}#detst,#phsig,#peoplest{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#photomsg{min-height:1.5em}#slamst{height:2.9em;overflow:hidden}#slamleg{height:1.5em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.objline{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#notelist{max-height:160px;overflow:auto}
.wide{grid-column:span 2}@media (max-width:700px){.wide{grid-column:auto}}
.grip{display:none;cursor:grab;touch-action:none;user-select:none;font-size:15px;line-height:1;color:var(--mut);padding:2px 4px;margin-left:-4px;border-radius:6px}
.grip:hover{background:var(--sub);color:var(--fg)}
.tools{display:none;gap:4px;margin-left:6px}.tbtn{border:1px solid var(--line);background:var(--sub);border-radius:7px;width:24px;height:22px;
  cursor:pointer;font-size:12px;line-height:1;color:var(--mut);display:grid;place-items:center;padding:0}.tbtn:hover{color:var(--fg);border-color:var(--acc)}
.editing .grip,.editing .tools{display:inline-flex}.editing .card{outline:1.5px dashed color-mix(in srgb,var(--acc) 45%,transparent);outline-offset:3px}
.card.dragging{opacity:.55;transform:scale(.985);box-shadow:var(--shadow-h);outline-style:solid}
.hdrbtn{cursor:pointer;font:inherit;font-size:12px}.hdrbtn:hover{border-color:var(--acc);color:var(--fg)}.hdrbtn.on{background:var(--acc);border-color:var(--acc);color:#fff}
.menu{position:fixed;z-index:20;top:56px;right:16px;width:min(300px,calc(100vw - 32px));max-height:70vh;overflow:auto;background:var(--card);
  border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow-h);padding:10px}
.menu label{display:flex;align-items:center;gap:10px;padding:7px 8px;border-radius:8px;cursor:pointer}.menu label:hover{background:var(--sub)}
.menu input{accent-color:var(--acc);width:16px;height:16px}.menu .mfoot{display:flex;gap:8px;margin-top:8px;padding-top:8px;border-top:1px solid var(--line)}
.notes{list-style:none;margin:0;padding:0;display:grid;gap:6px}.notes li{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;border-radius:10px;
  background:var(--sub);border:1px solid var(--line);font-size:13px}.notes b{font-weight:600}.notes .lv{flex:none;width:20px;text-align:center}
.notes li.error{border-color:color-mix(in srgb,var(--bad) 40%,transparent)}.notes li.warn{border-color:color-mix(in srgb,var(--warn) 40%,transparent)}
.presenting [data-card=notes],.presenting #banner,.presenting #notechip,.presenting .err,.presenting .reply.bad,.presenting .hint.t-bad,
.presenting .grip,.presenting .tools{display:none!important}
.presenting .broken,.presenting .brk,.presenting #acctlist .off{display:none!important}
.cam{position:relative;aspect-ratio:4/3;max-height:560px;margin:auto;border-radius:10px;overflow:hidden;background:#05070a;display:grid;place-items:center}
.cam.off{aspect-ratio:auto;min-height:120px}
.cam img{width:100%;height:100%;object-fit:contain;display:block}
.cam .ph{color:#8a94a6;font-size:13px;text-align:center;padding:20px}
.cam .chip{position:absolute;left:10px;top:10px;background:rgba(0,0,0,.55);border-color:transparent;color:#e5e7eb}
.pad{display:grid;grid-template-columns:repeat(3,64px);grid-template-rows:repeat(3,56px);gap:8px;justify-content:center;margin:4px 0 12px}
.pad button{border:1px solid var(--line);border-radius:12px;background:var(--sub);cursor:pointer;font-size:18px;display:grid;place-items:center;line-height:1}
.pad button small{font-size:10px;color:var(--mut);margin-top:2px}
.pad button:hover{border-color:var(--acc);background:var(--acc-s)}.pad button:active{transform:scale(.96)}
.pad .stp{background:var(--bad);border-color:var(--bad);color:#fff;font-size:15px;font-weight:700}
.pad .stp:hover{background:var(--bad);filter:brightness(1.1)}
.row{display:flex;align-items:center;gap:10px;margin:8px 0}.row label{color:var(--mut);font-size:12px;min-width:58px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.seg button{border:0;background:var(--sub);padding:5px 11px;cursor:pointer;font-size:12px}.seg button+button{border-left:1px solid var(--line)}
.seg button.on{background:var(--acc);color:#fff}
input[type=range]{flex:1;accent-color:var(--acc)}
.val{font-variant-numeric:tabular-nums;min-width:38px;text-align:right}
input.txt,input.num{width:100%;padding:9px 11px;border-radius:10px;border:1px solid var(--line);background:var(--sub);outline:none}
input.txt:focus,input.num:focus{border-color:var(--acc)}input.num{width:90px}
.reply{min-height:1.4em;margin-top:8px;white-space:pre-wrap;font-size:13px;color:var(--mut)}.reply.ok{color:var(--ok)}.reply.bad{color:var(--bad)}
.hint{color:var(--mut);font-size:12px}
.chat{max-height:300px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;margin:4px 0 10px}
.msg{padding:7px 11px;border-radius:12px;max-width:85%;white-space:pre-wrap;overflow-wrap:anywhere}
.msg.u{align-self:flex-end;background:var(--acc-s)}.msg.r{align-self:flex-start;background:var(--sub);border:1px solid var(--line)}
.msg small{display:block;color:var(--mut);font-size:11px;margin-top:3px}.msg.think{font-style:italic;color:var(--mut)}
.focus{text-align:center;margin:4px 0 6px}.fclock{font-size:44px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:.02em}
.fclock.brk{color:var(--ok)}.fclock.idle{color:var(--mut)}
.gmap{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;align-items:center;font-size:13px}
.gmap select{font:inherit;padding:4px 8px;border-radius:8px;border:1px solid var(--line);background:var(--sub);color:var(--fg);min-width:0}
.dnow{font-weight:600;margin:2px 0 8px;min-height:1.4em;overflow-wrap:anywhere}
.dtrack{height:6px;border-radius:99px;background:var(--sub);border:1px solid var(--line);overflow:hidden;margin-bottom:10px}
.dtrack div{height:100%;width:0;background:var(--acc);transition:width .3s linear}
.dsel{font:inherit;padding:6px 8px;border-radius:10px;border:1px solid var(--line);background:var(--sub);color:var(--fg);flex:1;min-width:150px}
.sfxchips{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}.sfxchips button{font-size:11px;padding:2px 8px;border-radius:99px}
.rpsscore{display:flex;justify-content:center;align-items:center;gap:22px;margin:4px 0}.rpsscore div{display:grid;text-align:center}
.rpsscore b{font-size:40px;line-height:1.05;font-variant-numeric:tabular-nums}.rpsscore span{font-size:12px;color:var(--mut)}.rpsvs{color:var(--mut)}
.rpsb{font-size:22px;padding:6px 14px}
.acct{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:10px}
.acct div{display:grid;justify-items:center;gap:4px;padding:10px 6px;border-radius:12px;background:var(--sub);border:1px solid var(--line);text-align:center;font-size:12px;position:relative}
.acct i{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;color:#fff;font-style:normal;font-weight:700;font-size:17px;box-shadow:0 4px 12px -4px rgba(0,0,0,.35)}
.acct div.off{opacity:.55}.acct div.off i{filter:grayscale(1)}.acct b{font-weight:600}.acct small{color:var(--mut);line-height:1.2}
.acct div::after{content:"";position:absolute;top:8px;right:8px;width:8px;height:8px;border-radius:50%;background:var(--unk)}.acct div.on::after{background:var(--ok)}
.tasks{list-style:none;margin:0 0 10px;padding:0;display:grid;gap:4px;max-height:260px;overflow-y:auto}
.tasks li{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:9px;background:var(--sub);border:1px solid var(--line)}
.tasks li.hint{background:none;border:0;padding:0}.tasks .tt{flex:1;overflow-wrap:anywhere}.tasks .due{font-size:12px;color:var(--mut);white-space:nowrap}
.tasks .due.late{color:var(--bad);font-weight:600}.tasks input{width:16px;height:16px;accent-color:var(--acc);cursor:pointer}
.tasks .x{border:0;background:none;color:var(--mut);cursor:pointer;font-size:15px;padding:0 4px}.tasks .x:hover{color:var(--bad)}
.chk{display:inline-flex;align-items:center;gap:6px;color:var(--mut);font-size:12px;cursor:pointer}
.sens{display:grid;gap:14px}
svg.bot{width:100%;max-width:270px;display:block;margin:auto}
svg.bot .body{fill:var(--sub);stroke:var(--fg);stroke-width:1.5}svg.bot .wheel{fill:var(--fg)}svg.bot .nose{fill:var(--acc)}
svg.bot .beam{stroke:none;opacity:.85}svg.bot text{font:600 14px system-ui,sans-serif;fill:var(--fg);text-anchor:middle}
.s-ok{fill:var(--ok-s)}.s-warn{fill:var(--warn-s)}.s-bad{fill:var(--bad-s)}.s-unk{fill:var(--line)}
.i-ok{fill:var(--ok)}.i-bad{fill:var(--bad)}.i-unk{fill:var(--unk)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:13px}.kv dt{color:var(--mut)}.kv dd{margin:0;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.t-ok{color:var(--ok)}.t-warn{color:var(--warn)}.t-bad{color:var(--bad)}.t-mut{color:var(--mut)}
.wheels{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.wheel{background:var(--sub);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.wheel .lbl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.wheel .big{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.wheel.stuck{border-color:var(--bad);background:var(--bad-s)}
.calbox{margin-top:12px;padding:12px;border-radius:12px;border:1px dashed var(--line)}
.calbox.need{border-color:color-mix(in srgb,var(--warn) 55%,transparent);background:var(--warn-s)}
.btn{border:1px solid var(--line);background:var(--sub);border-radius:10px;padding:7px 14px;cursor:pointer}
.btn:hover{border-color:var(--acc)}.btn.pri{background:var(--acc);border-color:var(--acc);color:#fff}.btn.pri:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.steps{display:flex;gap:8px;margin:2px 0 10px}.steps span{flex:1;text-align:center;font-size:12px;padding:5px;border-radius:8px;background:var(--sub);color:var(--mut);border:1px solid var(--line)}
.steps span.on{background:var(--acc-s);color:var(--acc);border-color:var(--acc);font-weight:600}.steps span.done{color:var(--ok)}
.counter{font-size:32px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.hide{display:none!important}
.oled{background:#000;border-radius:10px;padding:10px;margin-bottom:10px;display:grid;place-items:center;border:1px solid var(--line)}
.oled img{width:100%;max-width:384px;aspect-ratio:2/1;image-rendering:pixelated;display:block}
.map{width:100%;aspect-ratio:1;display:block;border-radius:10px;background:var(--sub)}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--mut);font-size:12px;margin-top:8px}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.log{list-style:none;margin:0;padding:0;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;max-height:260px;overflow:auto}
.log li{padding:4px 0;border-bottom:1px solid var(--line);color:var(--mut)}.log li b{color:var(--fg);font-weight:500}
.log li.stop b{color:var(--bad)}
.imu{display:grid;grid-template-columns:120px 1fr;gap:14px;align-items:center}
svg.dial{width:120px;height:120px;display:block}svg.dial .ring{fill:var(--sub);stroke:var(--line);stroke-width:2}
svg.dial .tick{stroke:var(--mut);stroke-width:2}svg.dial .arrow{fill:var(--acc);transition:transform .25s linear}
svg.dial .lvl{fill:none;stroke-width:6;stroke-linecap:round}svg.dial text{font:600 10px system-ui,sans-serif;fill:var(--mut);text-anchor:middle}
.lvl.ok{stroke:var(--ok)}.lvl.warn{stroke:var(--warn)}.lvl.bad{stroke:var(--bad)}.lvl.unk{stroke:var(--line)}
</style></head><body>
<header class="top">
  <h1>Desk robot</h1>
  <span class="chip" id="conn"><i class="dot" id="conndot"></i><span id="modetxt">connecting…</span></span>
  <span class="chip" id="movechip">idle</span>
  <span class="spacer"></span>
  <a class="chip hdrbtn hide" id="notechip" href="#notes" onclick="notesOpen=!notesOpen;renderNotes(S&&S.notes);return false" title="Problems the robot noticed: click to show / hide them (hidden in presentation mode)">⚠ <span id="notecount">0</span></a>
  <button class="chip hdrbtn" id="editbtn" onclick="toggleEdit()" title="Move, resize and remove cards">✎ Layout</button>
  <button class="chip hdrbtn" onclick="toggleMenu()" title="Choose which cards are shown">＋ Cards</button>
  <button class="chip hdrbtn" id="presbtn" onclick="togglePresent()" title="Presentation mode: hide every error and warning">▶ Present</button>
  <button class="chip themebtn" id="themebtn" onclick="cycleTheme()" title="Colour theme: auto (follows the system) / light / dark">◐ Auto</button>
  <button class="stopbig" onclick="send('stop')" title="Stop now (Space)">■ STOP<kbd>Space</kbd></button>
</header>
<div id="banner" class="banner hide"></div>
<div class="menu hide" id="cardmenu" role="dialog" aria-label="Cards"><div class="hint" style="padding:2px 8px 6px">Shown cards</div>
  <div id="cardlist"></div><div class="mfoot"><button class="btn" onclick="resetLayout()">Reset layout</button>
  <span class="spacer"></span><button class="btn pri" onclick="toggleMenu()">Done</button></div></div>
<main class="grid" id="grid">
<section class="card wide hide" id="notes" data-card="notes" data-title="Notes"><h2><span class="grip" title="Drag to move">⠿</span>Notes
  <span class="r hint">features that are off or failing · ▶ Present hides this</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button>
  <button class="tbtn" onclick="hideCard(this)" title="Remove this card">✕</button></span></h2><ul class="notes" id="notelist"></ul></section>

<section class="card wide" data-card="camera" data-title="Camera"><h2><span class="grip" title="Drag to move">⠿</span>Camera <span class="r" id="camst"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="cam off" id="camwrap"><img id="cam" alt="" class="hide"><div class="ph" id="camph">Camera starting…</div></div>
  <div class="row" style="flex-wrap:wrap;margin-bottom:0"><span class="hint" id="detst"></span><span id="dets" style="display:flex;gap:6px;flex-wrap:wrap"></span>
    <span class="spacer"></span><button class="btn" style="padding:3px 10px" id="detbtn" onclick="send(this.dataset.cmd)">Detection</button>
    <button class="btn" style="padding:3px 10px" id="invbtn" onclick="send('invert')" title="Rotate the camera picture 180° (for a camera mounted upside down). Also used by detection and photos">⟲ Upside down</button>
    <button class="btn pri" style="padding:3px 12px" id="photobtn" onclick="takePhoto()" title="Save the camera picture on the robot (photos/) and download it">📷 Take photo</button></div>
  <div class="hint" id="photomsg"></div>
  <div class="row" style="flex-wrap:wrap;margin-bottom:0"><button class="btn" style="padding:3px 10px" onclick="send('face me')">🙂 Face me</button>
    <button class="btn" style="padding:3px 10px" id="keepbtn" onclick="send(this.dataset.cmd)">Keep facing me</button>
    <button class="btn" style="padding:3px 10px" id="greetbtn" onclick="send(this.dataset.cmd)">Greeter</button>
    <span class="hint" id="peoplest"></span></div>
</section>

<section class="card wide" data-card="assistant" data-title="Assistant"><h2><span class="grip" title="Drag to move">⠿</span>Assistant <span class="r hint" id="aist"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="chat" id="chat"><div class="hint">Ask me something, or tell me what to do: "what can you see?",
    "turn left and take a photo", "tell me a joke".</div></div>
  <div class="row" style="flex-wrap:wrap;margin-bottom:0">
    <button class="btn pri" id="micbtn" onclick="mic()" title="Talk to the robot (needs the https page)">🎤 Talk</button>
    <input class="txt" id="asktxt" style="flex:1;min-width:180px;width:auto" maxlength="500" autocomplete="off"
      placeholder="Ask or tell me something, then Enter" onkeydown="if(event.key==='Enter'&&this.value.trim()){ask(this.value);this.value=''}">
    <label class="chk"><input type="checkbox" id="speak" onchange="setSpeak(this.checked)"> 🔊 Speak replies here</label>
  </div>
  <div class="hint" id="aimsg"></div>
</section>

<section class="card" data-card="phone" data-title="Phone"><h2><span class="grip" title="Drag to move">⠿</span>Phone <span class="r hint" id="phone-st"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="row" style="margin:0 0 8px"><span class="chip" id="phstate">…</span><span class="hint" id="phsig"></span></div>
  <svg id="phspark" viewBox="0 0 120 30" preserveAspectRatio="none" style="width:100%;height:42px;display:block"></svg>
  <div class="hint" style="margin:8px 0 4px">Nearby Bluetooth devices · pick your phone</div>
  <ul class="notes" id="phdevs" style="max-height:170px;overflow:auto"></ul>
</section>
<section class="card" data-card="gestures" data-title="Gestures"><h2><span class="grip" title="Drag to move">⠿</span>Gestures <span class="r hint" id="gestures-st">laptop camera</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="row" style="margin:0 0 8px;flex-wrap:wrap"><button class="btn pri" id="gbtn" onclick="gestureToggle()">📷 Start laptop camera</button>
    <span class="chip" id="gnow">camera off</span></div>
  <video id="gvid" playsinline muted style="width:100%;max-height:180px;border-radius:12px;background:#05070a;transform:scaleX(-1);display:none"></video>
  <div class="hint" id="gmsg">Hold a gesture for a moment. It runs in this browser; nothing leaves the laptop but the gesture's name.</div>
  <div class="hint" id="glast" style="margin:4px 0 8px"></div>
  <div class="gmap" id="gmap"></div>
</section>
<section class="card" data-card="rps" data-title="Rock paper scissors"><h2><span class="grip" title="Drag to move">⠿</span>Rock paper scissors <span class="r hint" id="rps-st">first to two</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="rpsscore"><div><b id="rpsyou">0</b><span>you</span></div><div class="rpsvs">vs</div><div><b id="rpsme">0</b><span>robot</span></div></div>
  <div class="hint" id="rpsmsg" style="text-align:center;min-height:2.6em;margin:6px 0">Show 🤟 to the laptop camera, or press Play.</div>
  <div class="row" style="justify-content:center;flex-wrap:wrap;margin-bottom:0">
    <button class="btn rpsb" onclick="send('rps rock')" title="Rock">✊</button><button class="btn rpsb" onclick="send('rps paper')" title="Paper">✋</button>
    <button class="btn rpsb" onclick="send('rps scissors')" title="Scissors">✌️</button>
    <button class="btn pri" id="rpsgo" onclick="send(this.dataset.cmd)" data-cmd="rps">Play</button></div>
</section>
<section class="card" data-card="dance" data-title="Dance &amp; sounds"><h2><span class="grip" title="Drag to move">⠿</span>Dance &amp; sounds <span class="r hint" id="dst">laptop speaker</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="dnow" id="dnow">Pick a song, or let me choose one.</div>
  <div class="dtrack"><div id="dbar"></div></div>
  <div class="row" style="flex-wrap:wrap"><select class="dsel" id="dsong" title="Song"><option value="">🎲 Random song</option></select>
    <button class="btn pri" id="dgo" onclick="danceGo()">💃 Dance</button></div>
  <div class="row" style="flex-wrap:wrap;margin-bottom:6px">
    <label class="chk"><input type="checkbox" id="sfxon" onchange="AU.sfxOn=this.checked;auSave();if(this.checked){auCtx();playSfx('blip')}"> 🔔 Sound effects here</label>
    <label class="chk"><input type="checkbox" id="musicon" onchange="AU.musicOn=this.checked;auSave();AU.key=undefined;render()"> 🎵 Music here</label></div>
  <div class="row" style="margin-bottom:6px"><span class="hint">🔈</span><input type="range" id="vol" min="0" max="1" step="0.05" oninput="auVol(+this.value)" aria-label="Volume"><span class="hint">🔊</span></div>
  <div class="sfxchips" id="sfxchips" title="Try a sound (plays here only)"></div>
  <div class="hint" id="dmsg" style="margin-top:6px"></div>
</section>
<section class="card" data-card="apis" data-title="APIs"><h2><span class="grip" title="Drag to move">⠿</span>APIs <span class="r hint" id="apis-st">free · no keys</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <ul class="notes" id="apilist"></ul>
  <div class="row" style="flex-wrap:wrap;margin:10px 0 0"><button class="btn" onclick="send('weather')">☀ Weather</button>
    <button class="btn" onclick="send('joke')">☺ Joke</button>
    <input class="txt" id="wikitxt" style="flex:1;min-width:140px;width:auto" placeholder="Look up on Wikipedia…" onkeydown="if(event.key==='Enter'&&this.value.trim()){send('wiki '+this.value);this.value=''}"></div>
  <div class="row" style="margin:8px 0 0"><input class="txt" id="citytxt" placeholder="Home city for the weather" onkeydown="if(event.key==='Enter'&&this.value.trim()){send('weather home '+this.value);this.value=''}"></div>
</section>
<section class="card" data-card="ideas" data-title="Ideas"><h2><span class="grip" title="Drag to move">⠿</span>Ideas <span class="r hint" id="ideas-st"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="row" style="margin:0 0 8px"><input class="txt" id="ideatxt" style="flex:1;width:auto" placeholder="New idea, then Enter" maxlength="500"
    onkeydown="if(event.key==='Enter'&&this.value.trim()){send('idea '+this.value);this.value=''}"></div>
  <input class="txt" id="ideaq" placeholder="Search…" oninput="renderIdeas(S&&S.ideas,true)" style="margin-bottom:8px">
  <ul class="tasks" id="idealist"></ul><a class="hint" href="/ideas.md" download>⬇ Download as Markdown</a>
</section>
<section class="card" data-card="accounts" data-title="Accounts"><h2><span class="grip" title="Drag to move">⠿</span>Accounts <span class="r hint" id="accounts-st">view only · no secrets shown</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="acct" id="acctlist"></div>
  <div class="hint" style="margin-top:8px">Keys live in secrets.env on the robot. Nothing about a key (not even part of it) is sent to this page.</div>
</section>
<section class="card" data-card="focus" data-title="Focus"><h2><span class="grip" title="Drag to move">⠿</span>Focus <span class="r hint" id="focst"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="focus"><div class="fclock" id="fclock">--:--</div><div class="hint" id="fstate">Put me next to your screen, facing you.</div></div>
  <div class="row" style="flex-wrap:wrap;margin-bottom:0">
    <button class="btn pri" onclick="send('focus 25')">Focus 25 min</button><button class="btn" onclick="send('focus 50')">50 min</button>
    <button class="btn" id="fstop" onclick="send('focus stop')">Stop</button></div>
</section>

<section class="card" data-card="tasks" data-title="Tasks"><h2><span class="grip" title="Drag to move">⠿</span>Tasks <span class="r hint" id="taskst"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <ul class="tasks" id="tasklist"><li class="hint">No open tasks</li></ul>
  <input class="txt" id="tasktxt" maxlength="150" autocomplete="off"
    placeholder="Add: call mom at 6pm · buy milk by friday · in 20 minutes stretch"
    onkeydown="if(event.key==='Enter'&&this.value.trim()){send('todo '+this.value);this.value=''}">
  <div class="hint" id="taskdone" style="margin-top:6px"></div>
</section>

<section class="card" data-card="drive" data-title="Drive"><h2><span class="grip" title="Drag to move">⠿</span>Drive <span class="r hint">arrow keys · Space stops</span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="pad">
    <button onclick="send('spin left')" title="Spin left (full turn)">⟲<small>spin</small></button>
    <button onclick="drive('forward')" title="Forward">▲<small>fwd</small></button>
    <button onclick="send('spin right')" title="Spin right (full turn)">⟳<small>spin</small></button>
    <button onclick="send('left')" title="Turn left ~90°">◀<small>left</small></button>
    <button class="stp" onclick="send('stop')">STOP</button>
    <button onclick="send('right')" title="Turn right ~90°">▶<small>right</small></button>
    <span></span>
    <button onclick="drive('back')" title="Backward">▼<small>back</small></button>
    <span></span>
  </div>
  <div class="row"><label>Speed</label><input type="range" id="speed" min="0.1" max="1" step="0.05"
    oninput="$('speedv').textContent=(+this.value).toFixed(2)" onchange="send('speed '+this.value)"><span class="val" id="speedv">–</span></div>
  <div class="row"><label title="Use when Forward drives backwards: the motors are wired the other way round">Motors</label><div class="seg" id="motseg"><button data-m="normal" onclick="send('motors normal')">Normal</button><button data-m="reverse" onclick="send('motors reverse')" title="Flip both motors (saved on the robot)">Reversed</button></div><span class="hint" id="motst"></span></div>
  <div class="row"><label>Obstacles</label><div class="seg" id="obst"><button data-o="on" class="on" onclick="send('obstacles on')" title="The sonars stop moves near obstacles">Stop for them</button><button data-o="ignore" onclick="send('obstacles ignore')" title="The sonars never stop a move. Desk edges, lifting, tilt and bumps still do">Ignore</button></div></div>
  <div class="row" style="flex-wrap:wrap"><label>Move for</label><div class="seg" id="durs">
    <button data-d="0.3">0.3 s</button><button data-d="1" class="on">1 s</button><button data-d="2">2 s</button><button data-d="4">4 s</button></div>
    <div class="seg" id="dists"><button data-d="5cm">5 cm</button><button data-d="10cm">10 cm</button><button data-d="20cm">20 cm</button><button data-d="30cm">30 cm</button></div></div>
  <input class="txt" id="cmd" placeholder="Command, e.g. forward 2 · spin 3 right · calibrate · help" autocomplete="off"
    onkeydown="if(event.key==='Enter'){send(this.value);this.value=''}">
  <div class="reply" id="reply"></div>
</section>

<section class="card" data-card="sensors" data-title="Sensors"><h2><span class="grip" title="Drag to move">⠿</span>Sensors <span class="r hint" id="limits"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="sens">
  <svg class="bot" viewBox="0 0 240 240" aria-label="Sensor view, front is up">
    <path id="b-front" class="beam s-unk" d="M106 66 L90 30 L150 30 L134 66Z"/>
    <path id="b-rear" class="beam s-unk" d="M106 174 L90 210 L150 210 L134 174Z"/>
    <path id="b-left" class="beam s-unk" d="M74 104 L40 88 L40 152 L74 136Z"/>
    <path id="b-right" class="beam s-unk" d="M166 104 L200 88 L200 152 L166 136Z"/>
    <rect class="body" x="84" y="66" width="72" height="108" rx="16"/>
    <rect class="wheel" x="75" y="98" width="9" height="44" rx="3"/><rect class="wheel" x="156" y="98" width="9" height="44" rx="3"/>
    <path class="nose" d="M120 82 l9 13 h-18z"/>
    <circle id="ir-front" class="i-unk" cx="120" cy="106" r="6"/><circle id="ir-rear" class="i-unk" cx="120" cy="158" r="6"/>
    <text id="t-front" x="120" y="22">–</text><text id="t-rear" x="120" y="228">–</text>
    <text id="t-left" x="22" y="125">–</text><text id="t-right" x="218" y="124">–</text>
  </svg>
  <dl class="kv" id="senskv"></dl>
  </div>
</section>

<section class="card" data-card="imu" data-title="IMU"><h2><span class="grip" title="Drag to move">⠿</span>IMU <span class="r hint" id="imust"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="imu">
    <svg class="dial" viewBox="0 0 120 120" aria-label="Heading (arrow) and tilt (ring colour)">
      <circle class="ring" cx="60" cy="60" r="52"/>
      <circle class="lvl unk" id="imulvl" cx="60" cy="60" r="52" pathLength="100" stroke-dasharray="0 100" transform="rotate(-90 60 60)"/>
      <path class="tick" d="M60 12v8M60 100v8M12 60h8M100 60h8"/>
      <text x="60" y="32">0°</text><text x="31" y="64">90°</text><text x="89" y="64">-90°</text>
      <g id="imuarrow" class="arrow" style="transform-origin:60px 60px"><path d="M60 30 L72 74 L60 66 L48 74Z"/></g>
    </svg>
    <dl class="kv" id="imukv"></dl>
  </div>
  <div class="row" style="flex-wrap:wrap"><button class="btn" onclick="send('imu zero')">Zero heading</button>
    <button class="btn" onclick="send('imu calibrate')" title="Robot standing still on a flat desk: measures the gyro bias and saves this position as level">Calibrate (keep still)</button>
    <button class="btn" onclick="send('turn 90')">Turn 90°</button><button class="btn" onclick="send('turn -90')">Turn −90°</button></div>
  <div class="hint" id="imumsg" style="white-space:pre-wrap"></div>
</section>

<section class="card" data-card="wheel-encoders" data-title="Wheel encoders"><h2><span class="grip" title="Drag to move">⠿</span>Wheel encoders <span class="r" id="odo"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="wheels">
    <div class="wheel" id="wl"><div class="lbl">Left wheel</div><div class="big" id="wlc">–</div><div class="hint" id="wls">–</div></div>
    <div class="wheel" id="wr"><div class="lbl">Right wheel</div><div class="big" id="wrc">–</div><div class="hint" id="wrs">–</div></div>
  </div>
  <div class="hint" id="encerr"></div>

  <div class="calbox" id="calbox">
    <div id="calsaved"></div>
    <div class="row" style="margin-bottom:0;flex-wrap:wrap">
      <button class="btn pri" id="calbtn" onclick="openWiz('auto')">Auto calibrate</button>
      <button class="btn" id="spinbtn" onclick="openWiz('spin')" title="Needs the distance calibration first">Calibrate turning</button>
      <button class="btn" onclick="openWiz('hand')">By hand…</button>
    </div>
    <div class="hint" id="calnote" style="margin-top:8px;white-space:pre-wrap"></div>
  </div>

  <div class="calbox hide" id="wiz-auto">
    <b>Automatic calibration</b>
    <ol class="hint" style="margin:6px 0 10px;padding-left:18px">
      <li>Put the robot on the desk with at least <b id="needcm">45</b> cm clear in front of it.</li>
      <li>Mark where its front edge is now (tape or a pencil line).</li>
      <li>Press <b>Drive</b>. It drives forward about <input class="num" id="autocm" type="number" value="25" min="5" max="100" style="width:64px;padding:3px 6px" oninput="$('needcm').textContent=Math.round(+this.value+20)"> cm by itself and stops.</li>
      <li>Measure how far it really moved and enter it. That is all.</li>
    </ol>
    <div class="row"><button class="btn pri" onclick="startAuto()">Drive</button><button class="btn" onclick="closeWiz()">Cancel</button></div>
  </div>

  <div class="calbox hide" id="wiz-spin">
    <b>Turning calibration</b> <span class="hint">(optional, improves the heading)</span>
    <p class="hint" style="margin:6px 0 10px">The robot spins <b>left</b> about one full turn on the spot. Note where its front
      points before you start; afterwards tell how far it turned. Keep about 10 cm clear on both sides.</p>
    <div class="row"><button class="btn pri" onclick="wiz=null;send('calibrate spin')">Spin</button><button class="btn" onclick="closeWiz()">Cancel</button></div>
  </div>

  <div class="calbox hide" id="calsetup">
    <b>Calibrate by hand</b>
    <p class="hint" style="margin:4px 0 10px">The motors stay off. Lift the robot, then turn each wheel forward by hand,
      a whole number of turns. Needs the wheel diameter.</p>
    <div class="row"><label>Wheel Ø</label><input class="num" id="caldia" type="number" min="10" max="500" step="1"> <span class="hint">mm</span></div>
    <div class="row"><label>Turns</label><input class="num" id="calturns" type="number" min="1" max="100" step="1" value="10"> <span class="hint">per wheel</span></div>
    <div class="row"><button class="btn pri" onclick="startHand()">Start</button><button class="btn" onclick="closeWiz()">Cancel</button></div>
  </div>

  <div class="calbox hide" id="calrun">
    <div class="steps"><span id="st1">1 · Left wheel</span><span id="st2">2 · Right wheel</span></div>
    <div id="calinstr"></div>
    <div class="row" style="align-items:baseline"><span class="counter" id="calcount">0</span><span class="hint" id="calest">counts</span></div>
    <div class="row"><button class="btn pri" id="calnext" onclick="send('calibrate next')">Done</button>
      <button class="btn" onclick="send('calibrate cancel')">Cancel</button></div>
  </div>

  <div class="calbox hide" id="calauto">
    <div class="steps"><span id="sa1">1 · Drive</span><span id="sa2">2 · Measure</span></div>
    <div id="cainstr"></div>
    <div class="row" style="align-items:baseline"><span class="counter" id="cacount">–</span><span class="hint">counts L / R</span></div>
    <div class="row hide" id="carow"><input class="num" id="caval" type="number" step="0.1" min="0"
      onkeydown="if(event.key==='Enter')finishAuto()"> <span class="hint" id="caunit">cm</span>
      <button class="btn pri" onclick="finishAuto()">Save</button></div>
    <div class="row"><button class="btn" onclick="send('calibrate cancel')">Cancel</button></div>
  </div>
</section>

<section class="card" data-card="oled-screen" data-title="OLED screen"><h2><span class="grip" title="Drag to move">⠿</span>OLED screen <span class="r hint" id="oledst"></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <div class="oled"><img id="oledimg" alt="What the OLED shows"></div>
  <div class="row" style="flex-wrap:wrap"><div class="seg" id="oledmodes"><button data-m="eyes">Eyes</button><button data-m="status">Status</button><button data-m="off">Off</button></div>
    <button class="btn" style="padding:5px 11px;font-size:12px" onclick="send('oled ip')">Show address</button></div>
  <input class="txt" id="oledtxt" placeholder="Show text on the screen, then Enter" maxlength="120"
    onkeydown="if(event.key==='Enter'&&this.value.trim()){send('oled say '+this.value);this.value=''}">
</section>

<section class="card" data-card="obstacle-map" data-title="Map (sensor fusion)"><h2><span class="grip" title="Drag to move">⠿</span>Map <span class="r"><span class="seg" id="mapmode"><button data-m="map" class="on">Map</button><button data-m="conf" title="Sensor fusion: how sure the robot is about each cell">Confidence</button></span></span><span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2>
  <canvas class="map" id="map" width="560" height="560"></canvas>
  <div class="legend"><span><i style="background:var(--fg)"></i>obstacle</span><span><i style="background:var(--free)"></i>free</span>
    <span><i style="background:var(--acc)"></i>robot</span><span><i style="background:var(--warn);border-radius:50%"></i>object</span><span><i style="background:var(--bad)"></i>desk edge</span><span>grid 0.5 m</span>
    <button class="btn" style="margin-left:auto;padding:3px 10px" onclick="send('map reset')">Reset map</button></div>
  <div class="row" style="flex-wrap:wrap;margin:8px 0 0"><label title="Simultaneous localisation and mapping: sonar scans are matched against the map to correct wheel and gyro drift">SLAM</label>
    <div class="seg" id="slamseg"><button data-s="off" onclick="send('slam off')">Off</button><button data-s="on" onclick="send('slam on')">On</button></div>
    <span class="hint" id="slamst" style="flex:1;min-width:180px"></span></div>
  <div class="hint" id="slamleg" style="margin-top:4px"></div>
  <div class="hint objline" style="margin-top:6px">Objects: <span id="objlist">none yet</span></div>
</section>

<section class="card" data-card="activity" data-title="Activity"><h2><span class="grip" title="Drag to move">⠿</span>Activity<span class="tools"><button class="tbtn" onclick="toggleWide(this)" title="Wider / narrower">⇔</button><button class="tbtn" onclick="hideCard(this)" title="Remove this card (＋ Cards brings it back)">✕</button></span></h2><ul class="log" id="log"></ul></section>
</main>

<script>
const $=id=>document.getElementById(id);
const THEMES=['auto','light','dark'],THEME_LABEL={auto:'◐ Auto',light:'☀ Light',dark:'☾ Dark'};
function theme(){return document.documentElement.dataset.theme||'auto'}
function setTheme(t){if(t==='auto')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=t;
  try{localStorage.setItem('robot-theme',t)}catch(e){}$('themebtn').textContent=THEME_LABEL[t];drawMap()}
function cycleTheme(){setTheme(THEMES[(THEMES.indexOf(theme())+1)%3])}
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let S=null,pose={x:0,y:0,theta:0},dur=1,wiz=null,failCount=0;

async function send(c){c=(c||'').trim();if(!c)return;
  try{const r=await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c})});
    const j=await r.json();const t=j.reply||j.error||'';
    say(t,!!j.error||/^(Not moving|Bad|Unknown|Use:|Encoders not|The (left|right) encoder|No calibration|Wheel diameter|Turns must|Could NOT|No IMU|IMU not|The IMU|The gyro|Angle must)/.test(t));
    state()}catch(e){say('Robot not reachable',true)}}
function say(t,bad){const m=$('reply');m.textContent=t;m.className='reply'+(t?(bad?' bad':' ok'):'')}
function drive(d){send(d+' '+dur)}
async function takePhoto(){const m=$('photomsg'),b=$('photobtn');b.disabled=true;
  try{const r=await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'photo'})});
    const t=(await r.json()).reply||'';const f=(t.match(/photo-[0-9-]+\.jpg/)||[])[0];
    if(f){m.className='hint t-ok';m.innerHTML=`Saved on the robot: ${esc(f)} · <a href="/photos/${f}" download>download again</a>`;
      const a=document.createElement('a');a.href='/photos/'+f;a.download=f;document.body.appendChild(a);a.click();a.remove()}
    else{m.className='hint t-bad';m.textContent=t||'No reply'}}
  catch(e){m.className='hint t-bad';m.textContent='Robot not reachable'}
  b.disabled=false;state()}
// ----- assistant: chat, browser speech output, microphone -----
let aiSeen=null,aiDrawn='',speakOn=false,rec=null,recTimer=null,srec=null;
try{speakOn=localStorage.getItem('robot-speak')==='1'}catch(e){}
$('speak').checked=speakOn;
function setSpeak(on){speakOn=on;try{localStorage.setItem('robot-speak',on?'1':'0')}catch(e){}
  if(on)speak('Okay, I will talk here.');else if('speechSynthesis' in window)speechSynthesis.cancel()}
function speak(t){if(!speakOn||!('speechSynthesis' in window)||!t)return;
  const u=new SpeechSynthesisUtterance(t);u.pitch=1.6;u.rate=1.05;speechSynthesis.speak(u)}
function aiMsg(t,cls){const m=$('aimsg');m.className='hint'+(cls?' '+cls:'');m.textContent=t}
async function ask(t,cmd){aiMsg('Thinking…');
  try{const r=await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:(cmd||'ask')+' '+t})});
    const j=await r.json(),x=j.reply||j.error||'';aiMsg(x.startsWith('Robot: ')?'':x,j.error||!x.startsWith('Robot: ')?'t-bad':'')}
  catch(e){aiMsg('Robot not reachable','t-bad')}state()}
function micIdle(){const b=$('micbtn');b.textContent='🎤 Talk';b.classList.add('pri')}
function micBusy(t){const b=$('micbtn');b.textContent=t;b.classList.remove('pri')}
async function mic(){
  if(rec&&rec.state==='recording'){rec.stop();return}
  if(srec){srec.stop();return}
  if(!window.isSecureContext){const p=S&&S.https_port;
    if(!p)return aiMsg('The microphone needs the https dashboard, which is off (started with --https-port 0, or openssl is missing). You can type instead.','t-bad');
    const u=`https://${location.hostname}:${p}/`;const m=$('aimsg');m.className='hint t-warn';
    m.innerHTML=`Browsers only allow the microphone on a secure page. Open <a href="${esc(u)}">${esc(u)}</a> and accept the certificate warning once (Advanced → Proceed).`;return}
  const groq=S&&S.assistant&&S.assistant.stt==='groq',SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!groq&&SR){srec=new SR();srec.lang='en-US';srec.interimResults=false;srec.maxAlternatives=1;
    srec.onresult=e=>{const t=e.results[0][0].transcript;if(t){aiMsg('Heard: “'+t+'”');ask(t,'heard')}};
    srec.onerror=e=>aiMsg('Speech recognition: '+e.error+(e.error==='not-allowed'?' (microphone blocked)':''),'t-bad');
    srec.onend=()=>{srec=null;micIdle()};
    try{srec.start()}catch(e){srec=null;return aiMsg('Speech recognition failed: '+e.message,'t-bad')}
    micBusy('■ Listening…');aiMsg('Speak now (this browser does the speech-to-text; click to stop)');return}
  if(!groq)return aiMsg('No speech-to-text here: add GROQ_API_KEY to secrets.env on the robot, or use Chrome/Edge. You can type instead.','t-bad');
  let stream;try{stream=await navigator.mediaDevices.getUserMedia({audio:true})}
  catch(e){return aiMsg('Microphone blocked: '+e.message,'t-bad')}
  const chunks=[];rec=new MediaRecorder(stream);rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
  rec.onstop=async()=>{stream.getTracks().forEach(t=>t.stop());clearTimeout(recTimer);micIdle();
    const blob=new Blob(chunks,{type:(rec.mimeType||'audio/webm')});rec=null;aiMsg('Transcribing…');
    try{const r=await fetch('/api/voice',{method:'POST',headers:{'Content-Type':blob.type},body:blob});const j=await r.json();
      if(j.error)aiMsg(j.error,'t-bad');else{const x=j.reply||'';aiMsg(x.startsWith('Robot: ')?'Heard: “'+j.text+'”':x,x.startsWith('Robot: ')?'':'t-bad')}}
    catch(e){aiMsg('Robot not reachable','t-bad')}state()};
  rec.start();recTimer=setTimeout(()=>{if(rec&&rec.state==='recording')rec.stop()},15000);
  micBusy('■ Stop');aiMsg('Listening… click Stop when you are done (max 15 s)')}
function renderAI(a){if(!a)return;const b=a.brains||{};
  const ks=Object.keys(b).filter(k=>!presenting()||(b[k].key&&!b[k].error));
  $('aist').textContent=!a.enabled?'AI off (offline rules)':ks.map(k=>`${k} ${b[k].key?(b[k].error?'⚠ error':'✓'):'(no key)'}`).join(' · ');
  $('aist').title=Object.keys(b).map(k=>`${k}: ${b[k].model}${b[k].error?' - '+b[k].error:''}`).join('\n');
  const key=a.last_id+'|'+(a.thinking||'');
  if(key!==aiDrawn){aiDrawn=key;const c=$('chat');
    let h=a.recent.map(e=>(e.user?`<div class="msg u">${esc(e.user)}<small>${e.source==='voice'?'🎤 ':''}${esc(e.t)}</small></div>`:'')+
      `<div class="msg r">${esc(e.speech)}${e.commands.length?`<small>doing: ${esc(e.commands.join(', '))}</small>`:''}`+
      `<small>${e.source==='reminder'?'⏰ reminder · '+esc(e.t):esc(e.backend)+' · '+e.ms+' ms'}${e.errors.length?' · '+esc(e.errors.join('; ')):''}</small></div>`).join('');
    if(a.thinking)h+=`<div class="msg u">${esc(a.thinking)}</div><div class="msg r think">thinking…</div>`;
    if(h){c.innerHTML=h;c.scrollTop=c.scrollHeight}}
  if(aiSeen===null)aiSeen=a.last_id;                 // a page that just opened doesn't read out old replies
  else if(a.last_id>aiSeen){a.recent.filter(e=>e.id>aiSeen).forEach(e=>speak(e.speech));aiSeen=a.last_id}}
document.querySelectorAll('#durs button,#dists button').forEach(b=>b.onclick=()=>{dur=b.dataset.d;
  document.querySelectorAll('#durs button,#dists button').forEach(x=>x.classList.toggle('on',x===b))});
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA'].includes(e.target.tagName))return;
  const k={ArrowUp:'forward 0.4',ArrowDown:'back 0.4',ArrowLeft:'left 0.3',ArrowRight:'right 0.3',' ':'stop'}[e.key];
  if(k){e.preventDefault();send(k)}});

function openWiz(w){wiz=w;const sv=S&&S.calibration.saved;
  if(w==='hand')$('caldia').value=Math.round((sv?sv.wheel_diameter_m:0.065)*1000);render()}
function closeWiz(){wiz=null;render()}
function startAuto(){wiz=null;send('calibrate '+(+$('autocm').value||25))}
function startHand(){const d=+$('caldia').value,t=+$('calturns').value;wiz=null;send(`calibrate hand ${d} ${t}`)}
function finishAuto(){const v=$('caval').value.trim();if(!v)return;const a=S&&S.calibration.active;
  send(a&&a.mode==='spin'?'calibrate turned '+v:'calibrate moved '+v+'cm');$('caval').value=''}
function cls(el,c){el.setAttribute('class',c)}
function sonarClass(v,lim){return v===null||v===undefined?'unk':v<=lim?'bad':v<=lim+0.1?'warn':'ok'}

function renderTasks(t){if(!t)return;const key=JSON.stringify(t.open)+t.done.length;if(key===renderTasks.k)return;renderTasks.k=key;
  $('taskst').textContent=t.open.length?`${t.open.length} open`:'';
  $('tasklist').innerHTML=t.open.length?t.open.map(x=>`<li><input type="checkbox" title="Done" onchange="send('done #${x.id}')">`+
    `<span class="tt">${esc(x.title)}</span>${x.when?`<span class="due${x.overdue?' late':''}">${x.overdue?'overdue · ':''}${esc(x.when)}</span>`:''}`+
    `<button class="x" title="Remove" onclick="send('tasks remove #${x.id}')">×</button></li>`).join(''):'<li class="hint">No open tasks</li>';
  $('taskdone').innerHTML=t.done.length?'Done: '+t.done.slice().reverse().map(x=>`<a href="#" onclick="send('undone #${x.id}');return false" title="Reopen">${esc(x.title)}</a>`).join(' · '):(t.error?`<span class="t-bad">${esc(t.error)}</span>`:'')}
function renderFocus(f){if(!f)return;const c=$('fclock'),m=f.mode;
  c.textContent=m==='idle'?'--:--':`${Math.floor(f.left_s/60)}:${String(f.left_s%60).padStart(2,'0')}`;
  c.className='fclock'+(m==='break'?' brk':m==='idle'?' idle':'');
  const word={focused:'focused ✓',away:'looking away',down:'head down',phone:'phone!',absent:'not at the desk',unknown:"can't see you"}[f.state]||'…';
  $('fstate').textContent=m==='focus'?(f.calibrating?'Learning where your work is - look at it…':`Now: ${word} · ${f.focused_pct===null?'—':f.focused_pct+' % focused'} · ${f.distractions} distraction${f.distractions===1?'':'s'}`):
    m==='break'?'Break - stretch, drink some water.':`Today: ${f.today_min} focused min in ${f.today_sessions} session${f.today_sessions===1?'':'s'}`;
  $('focst').textContent=m==='idle'?'':m==='break'?'break':`${f.minutes} min session`;$('fstop').disabled=m==='idle'}
function renderPeople(p){if(!p)return;const k=$('keepbtn'),g=$('greetbtn');
  k.dataset.cmd=p.keep_facing?'face me off':'face me on';k.textContent=p.keep_facing?'Stop facing me':'Keep facing me';k.classList.toggle('pri',p.keep_facing);
  g.dataset.cmd=p.greet?'greet off':'greet on';g.textContent='Greeter: '+(p.greet?'on':'off');
  $('peoplest').textContent=(p.keep_facing?p.state+' · ':'')+`${p.people} ${p.people===1?'person':'people'} in view`+(p.last_greeting?` · last: "${p.last_greeting}"`:'')}
function renderPhone(p){if(!p)return;const st=$('phstate'),cls={near:'t-ok',away:'t-bad',unknown:'t-mut'}[p.state]||'';
  st.className='chip '+cls;st.textContent=p.phone?({near:'📱 you\'re here',away:'📱 away',unknown:'📱 listening…'}[p.state]||p.state):'📱 no phone chosen';
  $('phsig').textContent=p.rssi!==null?`${p.rssi} dBm · ~${p.distance_m} m · heard ${p.seen_s_ago}s ago`:(p.error?'':'not heard yet');
  $('phone-st').textContent=p.error?p.error:p.backend;$('phone-st').classList.toggle('err',!!p.error);
  const h=p.history||[],sv=$('phspark');if(h.length>1){const lo=-100,hi=-40,X=k=>k*120/(h.length-1),Y=v=>30-30*(Math.min(hi,Math.max(lo,v))-lo)/(hi-lo);
    sv.innerHTML=`<line x1="0" x2="120" y1="${Y(-67)}" y2="${Y(-67)}" stroke="var(--ok)" stroke-dasharray="2 2" stroke-width=".6"/>`+
      `<polyline fill="none" stroke="var(--acc)" stroke-width="1.5" points="${h.map((v,k)=>X(k)+','+Y(v)).join(' ')}"/>`}else sv.innerHTML='';
  const key=JSON.stringify(p.devices.map(d=>[d.address,d.rssi,d.match]));if(key===renderPhone.k)return;renderPhone.k=key;
  $('phdevs').innerHTML=p.devices.length?p.devices.map(d=>`<li><span class="lv">${d.match?'✅':'📶'}</span><span style="flex:1;min-width:0">`+
    `<b>${esc(d.name||'(no name)')}</b> <span class="hint">${esc(d.address)} · ${d.rssi} dBm</span></span>`+
    (d.match?'':`<button class="btn" style="padding:2px 9px;font-size:12px" onclick="send('phone use ${esc(d.name||d.address)}')">This is mine</button>`)+'</li>').join('')
    :'<li class="hint" style="border:0;background:none">Nothing heard yet. On a phone: turn Bluetooth on (some phones only advertise while their Bluetooth settings page is open).</li>'}
// ----- gestures from this laptop's camera: MediaPipe GestureRecognizer in the browser -----
const MP='https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';
const GMODEL='https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task';
const GEMOJI={Open_Palm:'✋',Closed_Fist:'✊',Thumb_Up:'👍',Thumb_Down:'👎',Pointing_Up:'☝️',Victory:'✌️',ILoveYou:'🤟'};
const G={on:false,rec:null,stream:null,cur:null,since:0,lastSent:-1e9,lastT:0};
function gmsg(t,bad){const m=$('gmsg');m.textContent=t;m.className='hint'+(bad?' t-bad err':'')}
async function gestureToggle(){if(G.on)return gestureStop();
  if(!window.isSecureContext){const p=S&&S.https_port;const m=$('gmsg');
    if(!p)return gmsg('The camera needs the https dashboard, which is off (--https-port 0, or openssl missing).',true);
    const u=`https://${location.hostname}:${p}/`;m.className='hint t-warn';
    m.innerHTML=`Browsers only allow the camera on a secure page. Open <a href="${esc(u)}">${esc(u)}</a> and accept the certificate warning once.`;return}
  const b=$('gbtn');b.disabled=true;gmsg('Loading the hand model (about 8 MB, only the first time)…');
  try{if(!G.rec){const v=await import(MP+'/vision_bundle.mjs');const fs=await v.FilesetResolver.forVisionTasks(MP+'/wasm');
      const opts=d=>({baseOptions:{modelAssetPath:GMODEL,delegate:d},runningMode:'VIDEO',numHands:1});
      try{G.rec=await v.GestureRecognizer.createFromOptions(fs,opts('GPU'))}
      catch(e){G.rec=await v.GestureRecognizer.createFromOptions(fs,opts('CPU'))}}   // no WebGL: slower, still works
    G.stream=await navigator.mediaDevices.getUserMedia({video:{width:640,height:480,facingMode:'user'},audio:false});
    const vid=$('gvid');vid.srcObject=G.stream;vid.style.display='block';await vid.play();
    G.on=true;b.textContent='■ Stop camera';b.classList.remove('pri');gmsg('Show a gesture and hold it for a moment.');requestAnimationFrame(gloop)}
  catch(e){gmsg('Gestures unavailable: '+(e&&e.message||e)+' (the model needs internet once; allow the camera)',true)}
  b.disabled=false}
function gestureStop(){G.on=false;if(G.stream)G.stream.getTracks().forEach(t=>t.stop());G.stream=null;
  const v=$('gvid');v.srcObject=null;v.style.display='none';const b=$('gbtn');b.textContent='📷 Start laptop camera';b.classList.add('pri');
  $('gnow').textContent='camera off';gmsg('Camera off.')}
function gloop(t){if(!G.on)return;const vid=$('gvid');
  if(t-G.lastT>=100&&vid.readyState>=2){G.lastT=t;
    try{const r=G.rec.recognizeForVideo(vid,performance.now());const c=r.gestures&&r.gestures[0]&&r.gestures[0][0];
      const name=c&&c.score>=0.6&&c.categoryName&&c.categoryName!=='None'?c.categoryName:null;
      $('gnow').textContent=name?`${GEMOJI[name]||''} ${name.replace('_',' ')} ${(c.score*100).toFixed(0)}%`:'no gesture';
      if(name!==G.cur){G.cur=name;G.since=t}
      else if(name&&t-G.since>=700&&t-G.lastSent>=1500){G.lastSent=t;G.since=Infinity;sendGesture(name)}}   // once per hold
    catch(e){gmsg('Gesture error: '+(e&&e.message||e),true)}}
  requestAnimationFrame(gloop)}
async function sendGesture(n){try{const r=await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'gesture '+n})});
  const j=await r.json();$('glast').textContent=`${GEMOJI[n]||''} ${n.replace('_',' ')} → ${j.reply||j.error||''}`}catch(e){$('glast').textContent='Robot not reachable'}state()}
function renderGestures(g){if(!g)return;const key=JSON.stringify(g.map);if(key===renderGestures.k||document.activeElement&&document.activeElement.closest('#gmap'))return;renderGestures.k=key;
  $('gmap').innerHTML=g.names.map(n=>`<span>${GEMOJI[n]||''} ${esc(n.replace('_',' '))}</span><select onchange="send('gesture map ${n} '+this.value)">`+
    g.actions.map(a=>`<option value="${esc(a)}" ${a===g.map[n]?'selected':''}>${esc(a||'(nothing)')}</option>`).join('')+'</select>').join('')}
function renderRps(r){if(!r)return;$('rpsyou').textContent=r.score[0];$('rpsme').textContent=r.score[1];
  $('rpsmsg').textContent=r.state==='waiting'?(r.counting?`Round ${r.round}: show your move! (${Math.ceil(r.left_s)} s)`:r.last||'…'):(r.last||'Show 🤟 to the laptop camera, or press Play.');
  const b=$('rpsgo');b.dataset.cmd=r.state==='waiting'?'rps stop':'rps';b.textContent=r.state==='waiting'?'Stop':(r.state==='done'?'Play again':'Play')}
function ago(t){return t||'—'}
function renderApis(a){if(!a)return;$('citytxt').placeholder=a.home?`Home city: ${a.home} (Enter a new one to change)`:'Home city for the weather';
  $('apilist').innerHTML=a.apis.map(x=>`<li class="${x.ok===false?'warn':''}"><span class="lv">${x.ok===false?'⚠️':x.ok?'✅':'○'}</span>`+
    `<span style="flex:1"><b>${esc(x.name)}</b> <span class="hint">${esc(x.host)}</span><br><span class="hint ${x.ok===false?'err':''}">${x.ok===null?'not used yet':esc(x.msg)}${x.t?' · '+esc(x.t):''}${x.ms?' · '+x.ms+' ms':''} · ${x.calls} calls</span></span></li>`).join('')}
function renderIdeas(d,force){if(!d)return;const q=($('ideaq').value||'').toLowerCase();const key=JSON.stringify(d.recent)+q;if(key===renderIdeas.k&&!force)return;renderIdeas.k=key;
  $('ideas-st').textContent=`${d.count} idea${d.count===1?'':'s'}${d.waiting?' · listening for one…':''}`;
  const items=d.recent.filter(i=>!q||i.text.toLowerCase().includes(q));
  $('idealist').innerHTML=items.length?items.map(i=>`<li><span class="tt">💡 ${esc(i.text)}<br><span class="hint">#${i.id} · ${esc(i.created)}</span></span>`+
    `<button class="x" title="Forget" onclick="send('ideas forget #${i.id}')">×</button></li>`).join(''):'<li class="hint">No ideas yet. Say "remember this idea: …"</li>'}
// ----- sound effects + dance music, synthesized in this browser (Web Audio): the laptop is the speaker -----
const AU={ctx:null,master:null,noise:null,vol:0.6,sfxOn:true,musicOn:true,sfxSeen:null,songs:{},songsAt:0,play:null,key:null,el:null};
let rtt=0;
try{const v=JSON.parse(localStorage.getItem('robot-audio')||'{}');if(typeof v.vol==='number')AU.vol=v.vol;
  if(v.sfx===false)AU.sfxOn=false;if(v.music===false)AU.musicOn=false}catch(e){}
function auSave(){try{localStorage.setItem('robot-audio',JSON.stringify({vol:AU.vol,sfx:AU.sfxOn,music:AU.musicOn}))}catch(e){}}
function auCtx(){if(!AU.ctx){const C=window.AudioContext||window.webkitAudioContext;if(!C)return null;
    AU.ctx=new C();AU.master=AU.ctx.createGain();AU.master.gain.value=AU.vol;AU.master.connect(AU.ctx.destination);
    const n=AU.ctx.createBuffer(1,AU.ctx.sampleRate,AU.ctx.sampleRate),d=n.getChannelData(0);
    for(let i=0;i<d.length;i++)d[i]=Math.random()*2-1;AU.noise=n}
  if(AU.ctx.state==='suspended')AU.ctx.resume().catch(()=>{});return AU.ctx}
['pointerdown','keydown'].forEach(ev=>document.addEventListener(ev,()=>auCtx(),{passive:true}));  // browsers allow sound after a click
function auReady(){return !!(AU.ctx&&AU.ctx.state==='running')}
function auVol(v){AU.vol=v;if(AU.master)AU.master.gain.value=v;if(AU.el)AU.el.volume=Math.min(1,v);auSave()}
function tone(f0,f1,t,dur,type,vol,dest){const c=AU.ctx,o=c.createOscillator(),g=c.createGain();o.type=type||'square';
  o.frequency.setValueAtTime(f0,t);if(f1&&f1!==f0)o.frequency.exponentialRampToValueAtTime(f1,t+dur);
  g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(vol||0.15,t+0.008);g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
  o.connect(g);g.connect(dest||AU.master);o.start(t);o.stop(t+dur+0.02);return o}
function noise(t,dur,hp,vol,dest){const c=AU.ctx,s=c.createBufferSource(),f=c.createBiquadFilter(),g=c.createGain();s.buffer=AU.noise;
  f.type='highpass';f.frequency.value=hp;g.gain.setValueAtTime(vol,t);g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
  s.connect(f);f.connect(g);g.connect(dest||AU.master);s.start(t,Math.random()*0.5);s.stop(t+dur+0.02);return s}
// each effect: tones [from Hz, to Hz, start s, length s, wave, volume] and noise bursts ['n', high-pass Hz, start, length, volume]
const SFX={boot:[[392,392,0,.09],[523,523,.1,.09],[659,659,.2,.09],[1047,1047,.3,.2,'triangle',.2]],
  blip:[[880,1320,0,.06,'square',.06]],happy:[[660,990,0,.09],[880,1320,.11,.12]],sad:[[520,260,0,.45,'triangle',.25]],
  alarm:[[880,880,0,.12],[660,660,.14,.12],[880,880,.28,.12],[660,660,.42,.12]],
  bump:[[160,70,0,.18,'sine',.4],['n',800,0,.06,.15]],landed:[[330,330,0,.08,'triangle',.2],[494,494,.09,.14,'triangle',.2]],
  pat:[[1200,1800,0,.05,'sine',.2],[1500,2200,.07,.06,'sine',.2]],hold:[[700,700,0,.25,'sine',.2]],
  notify:[[988,988,0,.08,'sine',.22],[1319,1319,.09,.14,'sine',.22]],chime:[[1319,1319,0,.5,'sine',.25],[988,988,.25,.7,'sine',.25]],
  shutter:[['n',2000,0,.04,.35],['n',1200,.07,.05,.3]],
  success:[[523,523,0,.08],[659,659,.09,.08],[784,784,.18,.08],[1047,1047,.27,.25,'triangle',.2]],
  tada:[[784,784,0,.1],[1047,1047,.12,.45,'triangle',.25],[1319,1319,.12,.45,'triangle',.18]],
  grumble:[[180,120,0,.25,'sawtooth',.1],[150,100,.25,.25,'sawtooth',.1]],sleepy:[[600,300,0,.6,'sine',.18]]};
function playSfx(name){if(!auCtx()||!auReady())return;const t=AU.ctx.currentTime+0.01;
  for(const e of SFX[name]||[]){if(e[0]==='n')noise(t+e[2],e[3],e[1],e[4]);else tone(e[0],e[1],t+e[2],e[3],e[4]||'square',e[5]||.15)}}
function renderSounds(d){if(!d)return;
  if(AU.sfxSeen===null||d.last_id<AU.sfxSeen)AU.sfxSeen=d.last_id;     // a page that just opened (or a restarted robot): no old sounds
  else if(d.last_id>AU.sfxSeen){if(AU.sfxOn&&d.on)d.recent.filter(e=>e.id>AU.sfxSeen).slice(-3).forEach((e,i)=>setTimeout(()=>playSfx(e.name),i*150));
    AU.sfxSeen=d.last_id}
  const st=$('sfxon');st.title=d.on?'':'Muted on the robot (sounds on)';st.parentElement.style.opacity=d.on?'':'.5'}
const NOTE={C:0,D:2,E:4,F:5,G:7,A:9,B:11};
function nfreq(n){const m=/^([A-G])([#b]?)(\d)$/.exec(n||'');if(!m)return 0;
  return 440*Math.pow(2,(NOTE[m[1]]+(m[2]==='#'?1:m[2]==='b'?-1:0)+12*(+m[3]+1)-69)/12)}
function synthSong(song,offset){const c=AU.ctx,bus=c.createGain(),nodes=[];bus.gain.value=0.9;bus.connect(AU.master);
  const e8=30/song.bpm,t0=c.currentTime+0.03-offset,bars=song.melody.length,at=i=>t0+i*e8,live=t=>t>=c.currentTime;
  const BASS={octave:[1,0,2,0,1,0,2,0],offbeat:[0,1,0,2,0,1,0,2],pump:[1,1,1,1,1,1,1,1]}[song.bass_style]||[1,0,1,0,1,0,1,0];
  for(let r=0;r<(song.repeat||1);r++)for(let b=0;b<bars;b++){const base=(r*bars+b)*8,toks=song.melody[b].split(/\s+/),root=nfreq(song.bass[b]);
    for(let i=0;i<8;i++){const tk=toks[i];if(!tk||tk==='.'||tk==='-')continue;let len=1;while(toks[i+len]==='-')len++;
      const t=at(base+i),f=nfreq(tk);if(!live(t)||!f)continue;
      nodes.push(tone(f,f,t,len*e8*0.92,song.wave||'square',0.1,bus));
      if(r>0)nodes.push(tone(f*2,f*2,t,len*e8*0.6,'triangle',0.035,bus))}       // second time round: a sparkle an octave up
    for(let i=0;i<8;i++){const t=at(base+i);if(!BASS[i]||!live(t)||!root)continue;const f=BASS[i]===2?root*2:root;
      nodes.push(tone(f,f,t,e8*0.8,'triangle',0.22,bus))}
    for(let i=0;i<8;i++){const d=song.drums[i%song.drums.length],t=at(base+i);if(!live(t))continue;
      if(d==='K')nodes.push(tone(150,45,t,.16,'sine',.55,bus));else if(d==='S')nodes.push(noise(t,.12,1500,.22,bus));
      else if(d==='H')nodes.push(noise(t,.04,7000,.08,bus))}}
  return ()=>{try{bus.gain.setTargetAtTime(0,c.currentTime,0.08)}catch(e){}
    setTimeout(()=>{nodes.forEach(n=>{try{n.stop()}catch(e){}});try{bus.disconnect()}catch(e){}},500)}}
function fileSong(song,offset){const a=new Audio('/songs/'+encodeURIComponent(song.file)),t=performance.now();let timer=null,fade=null;
  a.volume=Math.min(1,AU.vol);AU.el=a;
  if(offset<0)timer=setTimeout(()=>a.play().catch(()=>{}),-offset*1000);
  else a.addEventListener('loadedmetadata',()=>{try{a.currentTime=offset+(performance.now()-t)/1000}catch(e){}a.play().catch(()=>{})},{once:true});
  return ()=>{clearTimeout(timer);if(AU.el===a)AU.el=null;let v=a.volume;
    fade=setInterval(()=>{v-=0.08;if(v<=0){clearInterval(fade);a.pause();a.removeAttribute('src')}else a.volume=v},40)}}
async function loadSongs(){AU.songsAt=Date.now();
  try{const j=await (await fetch('/api/songs')).json();AU.songs={};for(const x of j.songs)AU.songs[x.id]=x;
    const sel=$('dsong'),cur=sel.value;
    sel.innerHTML='<option value="">🎲 Random song</option>'+j.songs.map(x=>`<option value="${esc(x.id)}">${esc(x.title)} · ${Math.round(x.bpm)} bpm${x.kind==='file'?' · file':''}</option>`).join('');
    sel.value=cur}catch(e){}}
function danceGo(){auCtx();const d=S&&S.dance;
  if(d&&d.active)send('dance stop');else send('dance '+($('dsong').value||'random'))}
function renderDance(d){if(!d)return;
  const key=d.active?d.run+'|'+d.song:null;let msg='';
  if(key!==AU.key){if(AU.play){AU.play();AU.play=null}AU.key=key;
    if(key&&AU.musicOn){const song=AU.songs[d.song];
      if(!song){AU.key=null;if(Date.now()-AU.songsAt>2000)loadSongs()}            // a new music file: fetch the list, try again
      else if(song.kind==='synth'&&!(auCtx()&&auReady())){AU.key=null}          // sound not allowed yet: wait for a click
      else{const off=d.elapsed_s+rtt/2000;AU.play=song.kind==='file'?fileSong(song,off):synthSong(song,off)}}}
  if(d.active&&AU.musicOn&&!AU.play)msg='Click anywhere on this page to let it play the music.';
  const el=d.elapsed_s==null?0:Math.max(0,d.elapsed_s),pct=d.active&&d.seconds?Math.min(100,el/d.seconds*100):0;
  $('dbar').style.width=pct+'%';
  $('dnow').textContent=d.active?`♪ ${d.title}`:(d.title?`Last: ${d.title} (${d.result})`:'Pick a song, or let me choose one.');
  $('dst').textContent=d.active?`${d.routine||'get ready'} · ${Math.round(el)}/${Math.round(d.seconds)} s`:'laptop speaker';
  const b=$('dgo');b.textContent=d.active?'■ Stop':'💃 Dance';b.classList.toggle('pri',!d.active);
  $('dmsg').textContent=msg||(d.active&&d.skipped?`${d.skipped} step${d.skipped===1?'':'s'} skipped: not safe there (edge or obstacle)`:'')}
$('sfxon').checked=AU.sfxOn;$('musicon').checked=AU.musicOn;$('vol').value=AU.vol;
$('sfxchips').innerHTML=Object.keys(SFX).map(n=>`<button class="btn" onclick="auCtx();playSfx('${n}')">${n}</button>`).join('');
loadSongs();
function renderAccounts(list){if(!list)return;const key=JSON.stringify(list);if(key===renderAccounts.k)return;renderAccounts.k=key;
  $('acctlist').innerHTML=list.map(a=>`<div class="${a.connected?'on':'off'}" title="${esc(a.name)}: ${esc(a.status)} · ${esc(a.for)}">`+
    `<i style="background:${esc(a.colour)}">${esc(a.glyph)}</i><b>${esc(a.name)}</b><small>${esc(a.status)}</small></div>`).join('')}
// presentation mode hides what isn't working (25 Nov 2026): cards get .broken, single readings .brk
const presenting=()=>document.documentElement.classList.contains('presenting');
// a flag that changes only after the new value has held STABLE_MS (the first value counts at once)
const STABLE_MS=5000,STABLE={};
function stable(k,v){const now=Date.now(),e=STABLE[k];
  if(!e){STABLE[k]={v,cand:v,t:now};return v}
  if(v!==e.cand){e.cand=v;e.t=now}else if(v!==e.v&&now-e.t>=STABLE_MS)e.v=v;
  return e.v}
function renderMotors(s){const r=s.motors_reversed||{},both=r.left&&r.right,none=!r.left&&!r.right;
  document.querySelectorAll('#motseg button').forEach(b=>b.classList.toggle('on',b.dataset.m==='reverse'?both:none));
  $('motst').textContent=both||none?'':(r.left?'left':'right')+' motor reversed'}
function renderSlam(s){const sl=s.slam;
  document.querySelectorAll('#slamseg button').forEach(b=>b.classList.toggle('on',(b.dataset.s==='on')===!!(sl&&sl.enabled)));
  $('slamst').textContent=!sl?'not available':!sl.enabled?'off - pose from wheels + gyro':
    sl.status+(sl.corrections?` · ${sl.corrections} corrections, total ${Math.hypot(sl.total.dx_cm,sl.total.dy_cm).toFixed(1)} cm / ${sl.total.dth_deg.toFixed(1)}°`:'');
  $('slamleg').innerHTML=sl&&sl.enabled?'<span style="color:var(--warn)">- - -</span> path from wheels + gyro alone · <span style="color:var(--acc)">───</span> SLAM-corrected path'+(sl.drift_cm!=null?` · ${sl.drift_cm.toFixed(1)} cm apart now`:''):'';
  const ib=$('invbtn');ib.classList.toggle('pri',!!s.camera_inverted);ib.classList.toggle('hide',!s.camera_live)}
function renderBroken(s){const e=s.encoders||{},im=s.imu,o=s.oled,ph=s.phone,acc=s.accounts||[];
  const bad={camera:!s.camera_live,assistant:!s.assistant,phone:!ph||!!ph.error,gestures:!s.gestures,rps:!s.rps,
    dance:!s.dance&&!s.sounds,apis:!s.apis,ideas:!s.ideas,focus:!s.focus,tasks:!s.tasks,imu:!im||!im.ok,
    'wheel-encoders':!e.counts,'oled-screen':!o||/^(disabled|error|off)/.test(o.status||'')||(!o.hardware&&s.mode!=='simulation'),accounts:!acc.some(a=>a.connected)};
  for(const [id,b] of Object.entries(bad)){const c=document.querySelector(`[data-card="${id}"]`);if(c)c.classList.toggle('broken',stable('card:'+id,b))}
  for(const n of ['front','rear','left','right']){const dead=stable('sonar:'+n,s.sonar[n]==null);['b-','t-'].forEach(p=>{const x=$(p+n);if(x)x.classList.toggle('brk',dead)})}
  for(const n of ['front','rear']){const x=$('ir-'+n);if(x)x.classList.toggle('brk',stable('ir:'+n,s.floor[n]==null))}
  const v=s.vision;['detst','dets','detbtn'].forEach(i=>{const x=$(i);if(x)x.classList.toggle('brk',!v||!v.model)})}
const RENDERERS=[s=>renderMotors(s),s=>renderSlam(s),s=>renderSounds(s.sounds),s=>renderDance(s.dance),s=>renderApis(s.apis),s=>renderIdeas(s.ideas),s=>renderAccounts(s.accounts),s=>renderGestures(s.gestures),s=>renderRps(s.rps),s=>renderPhone(s.phone),s=>renderAI(s.assistant),s=>renderTasks(s.tasks),s=>renderFocus(s.focus),s=>renderPeople(s.people),s=>renderNotes(s.notes)];
function render(){const s=S;if(!s)return;
  for(const f of RENDERERS){try{f(s)}catch(e){console.warn('card render failed',e)}}
  try{renderCore(s)}catch(e){console.warn('render failed',e)}
  try{renderBroken(s)}catch(e){console.warn('broken marks failed',e)}}   // after renderCore: it resets the sonar/IR classes
function renderCore(s){
  $('conndot').className='dot '+(s.mode==='simulation'?'sim':'on');$('modetxt').textContent=s.mode;
  $('movechip').textContent=s.move?`${s.move.label} · ${s.move.left_s.toFixed(1)} s`:'idle';
  const sp=$('speed');if(document.activeElement!==sp){sp.value=s.speed;$('speedv').textContent=s.speed.toFixed(2)}
  const b=$('banner'),e=s.encoders||{};
  const lf=s.lift||{};
  if(lf.lifted){b.className='banner bad';b.textContent=`⚠ Lifted (${lf.reason}) - motors stopped, map paused. Put me down on the desk; after more than 1 s up I start a fresh map.`}
  else if(e.stuck){b.className='banner bad';b.textContent=`⚠ ${e.stuck} wheel stuck - the motors were stopped. Check the wheel, then drive again.`}
  else if(s.calibration&&s.calibration.active){b.className='banner';b.textContent='Encoder calibration in progress - driving is disabled until it finishes or is cancelled.'}
  else if(s.calibration&&/^(Calibration failed|Turning calibration failed)/.test(s.calibration.last||'')){b.className='banner bad';b.textContent=s.calibration.last}
  else if(s.nav&&s.nav.active){b.className='banner';b.textContent=`Going to ${s.nav.target}: ${s.nav.step} - Space or STOP cancels`}
  else if(s.blocked){b.className='banner';b.textContent='Last move blocked: '+s.blocked}
  else if(s.obstacles_ignored){b.className='banner bad';b.textContent='Obstacles are ignored: the sonars will not stop the robot (desk edges, lifting, tilt and bumps still do).'}
  else b.className='banner hide';
  document.querySelectorAll('#obst button').forEach(x=>x.classList.toggle('on',(x.dataset.o==='ignore')===!!s.obstacles_ignored));
  // sensors
  const L=s.limits||{};$('limits').textContent=s.obstacles_ignored?'obstacle stops OFF':`stops at ${Math.round((L.front||0)*100)} cm front/rear · ${Math.round((L.left||0)*100)} cm sides`;
  for(const n of ['front','rear','left','right']){const v=s.sonar[n];cls($('b-'+n),'beam s-'+sonarClass(v,L[n]||0));
    $('t-'+n).textContent=v===null||v===undefined?'—':Math.round(v*100)+' cm'}
  for(const n of ['front','rear']){const v=s.floor[n];cls($('ir-'+n),v===null||v===undefined?'i-unk':v?'i-ok':'i-bad')}
  let kv='';for(const n of ['front','rear']){const v=s.floor[n];
    const k=stable('ir:'+n,v===null)?' brk':'';
    kv+=`<dt class="${k}">${n} IR${s.edges_checked?'':' (ignored)'}</dt><dd class="${v===null?'t-mut':v?'t-ok':'t-bad'}${k}">${v===null?'unreadable':v?'floor':'EDGE'}</dd>`}
  const dead=['front','left','right','rear'].filter(n=>s.sonar[n]===null);
  const sk=stable('sonars-row',dead.length>0)?' brk':'';
  kv+=`<dt class="${sk}">sonars</dt><dd class="${dead.length?'t-warn':'t-ok'}${sk}">${dead.length?esc(dead.join(', '))+' silent':'all reading'}</dd>`;
  kv+=`<dt>lift</dt><dd class="${!lf.enabled?'t-mut':lf.lifted?'t-bad':'t-ok'}">${!lf.enabled?'detection off':lf.lifted?'LIFTED '+(lf.up_s||0).toFixed(0)+' s':'on the desk'}${lf.enabled?` · ${lf.resets} fresh maps`:''}</dd>`;
  const tc=s.touch||{};
  const tk=stable('touch',tc.touched==null)?' brk':'';
  kv+=`<dt class="${tk}">touch pad</dt><dd class="${tc.touched==null?'t-mut':tc.touched?'t-ok':''}${tk}" title="${esc(tc.error||'')}">${tc.touched==null?'unavailable':tc.touched?'TOUCHED':'not touched'}${tc.touched==null?'':` · ${tc.pats} pats`}</dd>`;
  kv+=`<dt>pose</dt><dd>${pose.x.toFixed(2)}, ${pose.y.toFixed(2)} m</dd><dt>heading</dt><dd>${(pose.theta*180/Math.PI).toFixed(0)}°</dd>`;
  $('senskv').innerHTML=kv;
  // encoders
  const c=e.counts,w=e.working||[false,false],dm=e.distance_m;
  [['l',0],['r',1]].forEach(([k,i])=>{
    $('w'+k+'c').textContent=c?c[i]:'—';
    $('w'+k+'s').innerHTML=!c?'unavailable':(w[i]?'<span class="t-ok">turning seen</span>':'<span class="t-mut">not seen turning yet</span>')+(dm?` · ${dm[i].toFixed(2)} m`:'');
    $('w'+k).className='wheel'+(e.stuck&&(e.stuck==='both'||e.stuck===(i?'right':'left'))?' stuck':'')});
  $('encerr').textContent=c?'':'Encoders unavailable'+(e.error?': '+e.error:'');
  $('odo').innerHTML=e.odometry?`<span class="${e.odometry.startsWith('encoders')?'t-ok':'t-warn'}">pose from ${esc(e.odometry)}</span>`:'';
  // imu
  const im=s.imu,lim=L.tilt_deg||20;
  $('imust').textContent=im?(im.ok?im.sensor:''):'off (--no-imu)';$('imust').className='r '+(im&&!im.ok?'t-bad':'hint');
  if(im&&im.ok){const t=im.tilt_deg;
    $('imuarrow').style.transform=`rotate(${-im.heading_deg}deg)`;
    const lv=$('imulvl');lv.setAttribute('stroke-dasharray',`${Math.min(100,t/lim*100)} 100`);
    cls(lv,'lvl '+(t>=lim?'bad':t>=lim/2?'warn':'ok'));
    $('imukv').innerHTML=`<dt>heading</dt><dd>${im.heading_deg.toFixed(0)}°</dd><dt>turning</dt><dd>${im.rate_dps.toFixed(0)}°/s</dd>
      <dt>tilt</dt><dd class="${t>=lim?'t-bad':t>=lim/2?'t-warn':''}">${t.toFixed(1)}°${t>=lim?' · lifted?':''}</dd>
      <dt>state</dt><dd>${im.still?'still':'moving'}</dd>
      <dt>temp</dt><dd>${im.temp_c==null?'—':im.temp_c.toFixed(1)+' °C'}</dd>
      <dt>gyro bias</dt><dd title="deg/s, x y z">${im.bias_dps.map(b=>b.toFixed(2)).join(' ')}</dd>
      <dt>level</dt><dd class="hint" title="${esc(im.level_from)}">${esc(im.level_from)}</dd>`}
  else{$('imuarrow').style.transform='';cls($('imulvl'),'lvl unk');
    $('imukv').innerHTML=`<dt>status</dt><dd class="t-mut" style="white-space:normal;text-align:left">${esc(im?im.status:'started with --no-imu')}</dd>`}
  $('imumsg').textContent=im?(im.message||`Stops moves above ${lim.toFixed(0)}° tilt and on bumps over ${(L.bump_g||0).toFixed(1)} g.`):'';
  // calibration
  const cal=s.calibration||{},sv=cal.saved,act=cal.active,mode=act&&act.mode;
  if(act)wiz=null;
  const show=(id,on)=>$(id).classList.toggle('hide',!on);
  show('calbox',!act&&!wiz);show('wiz-auto',wiz==='auto');show('wiz-spin',wiz==='spin');show('calsetup',wiz==='hand');
  show('calrun',mode==='hand');show('calauto',mode==='auto'||mode==='spin');
  $('calbox').classList.toggle('need',!sv);
  if(sv){const mm=sv.mm_per_count||[0,0];
    $('calsaved').innerHTML=`<div><b class="t-ok">✓ Calibrated</b> <span class="hint">${esc(sv.method||'hand')}${sv.calibrated_at?' · '+esc(sv.calibrated_at):''}</span></div>
      <dl class="kv" style="margin:8px 0"><dt>distance</dt><dd>${sv.measured_m?'from a '+(sv.measured_m*100).toFixed(1)+' cm drive':'Ø '+(sv.wheel_diameter_m*1000).toFixed(0)+' mm wheel'}</dd>
      <dt>mm / count</dt><dd>L ${mm[0].toFixed(3)} · R ${mm[1].toFixed(3)}</dd>
      <dt>turning</dt><dd class="${sv.track_width_m?'':'t-warn'}">${sv.track_width_m?'track '+(sv.track_width_m*100).toFixed(1)+' cm':'not calibrated'}</dd>
      <dt>file</dt><dd class="hint" title="${esc(sv.file)}">${esc(sv.file)}</dd></dl>`}
  else $('calsaved').innerHTML=`<div><b class="t-warn">Not calibrated</b></div><p class="hint" style="margin:4px 0 8px">Distances and the pose use motor timing. <b>Auto calibrate</b> drives about 25 cm by itself and asks you how far it went. It is saved and loaded on every start.</p>`;
  $('calbtn').textContent=sv?'Recalibrate (auto)':'Auto calibrate';$('calbtn').disabled=!cal.available;
  $('spinbtn').disabled=!cal.available||!sv;
  $('calnote').textContent=cal.available?(cal.last||''):'Encoders unavailable'+(cal.error?': '+cal.error:'');
  if(mode==='hand'){const side=act.side,t=act.turned;
    cls($('st1'),act.step===1?'on':'done');cls($('st2'),act.step===2?'on':'');
    $('calinstr').innerHTML=`Turn the <b>${side.toUpperCase()}</b> wheel <b>forward</b> exactly <b>${act.revolutions}</b> full turns by hand, then press <b>Done</b>.`+
      (act.results.left?`<div class="hint">Left: ${act.results.left.counts_per_rev.toFixed(1)} counts per turn</div>`:'')+
      (s.mode==='simulation'?`<div class="hint">Simulation: type <code>sim turn ${side} ${act.revolutions}</code> in the command box.</div>`:'');
    $('calcount').textContent=t===null?'—':Math.abs(t);
    const cpr=sv&&sv[side+'_counts_per_rev'];
    $('calest').textContent='counts'+(t!==null&&cpr?` ≈ ${(Math.abs(t)/cpr).toFixed(1)} turns (old calibration)`:'');
    $('calnext').textContent=act.step===1?'Done → right wheel':'Done → save'}
  if(mode==='auto'||mode==='spin'){const spin=mode==='spin',driving=act.phase==='driving';
    $('sa1').textContent=spin?'1 · Spin':'1 · Drive';$('sa2').textContent=spin?'2 · Angle':'2 · Measure';
    cls($('sa1'),driving?'on':'done');cls($('sa2'),driving?'':'on');
    const sim=s.mode==='simulation'?(spin?(act.sim_turned_deg!=null?` <span class="hint">Simulation: it really turned ${act.sim_turned_deg}°.</span>`:'')
      :(act.sim_moved_cm!=null?` <span class="hint">Simulation: it really moved ${act.sim_moved_cm} cm.</span>`:'')):'';
    $('cainstr').innerHTML=driving?(spin?'<b>Spinning…</b> stand clear.':'<b>Driving…</b> stand clear.')
      :(act.stopped?`<div class="t-warn">It stopped early (${esc(act.stopped)}). That's fine: measure what it actually did.</div>`:'')+
       (spin?'How far did it turn? <span class="hint">360 = exactly one full turn; less if it fell short.</span>'
            :'Measure from your mark to the robot\'s front edge and enter the distance.')+sim+
       (spin&&act.gyro_deg?` <button class="btn" style="padding:3px 10px" onclick="send('calibrate turned gyro')">Use the gyro: ${act.gyro_deg.toFixed(0)}°</button>`:'');
    $('cacount').textContent=act.delta?act.delta[0]+' / '+act.delta[1]:'—';
    show('carow',!driving);$('caunit').textContent=spin?'degrees':'cm';$('caval').placeholder=spin?'e.g. 340':'e.g. 24.5'}
  // camera
  $('camst').textContent=s.camera||'';const img=$('cam');
  camVideo(s,img);
  if(!s.camera_live&&!img.src)$('camph').textContent=s.camera==='off'?'Camera off (started with --no-camera)':'Camera: '+(s.camera||'starting…');
  // object detection
  const v=s.vision,db=$('detbtn');
  $('detst').textContent=v?(v.model?(v.enabled?`${v.model} · ${v.ms?v.ms.toFixed(0)+' ms':'…'}`:'detection off'):v.status):'detection off';
  $('detst').className='hint'+(v&&!v.model&&v.status.startsWith('unavailable')?' t-bad':'');
  $('dets').innerHTML=(v&&v.detections||[]).map(d=>{const b=d.bearing_deg,w=Math.abs(b)<8?'ahead':Math.abs(b).toFixed(0)+'° '+(b>0?'left':'right');
    return `<span class="chip" title="${esc(w)}"><b style="color:var(--fg)">${esc(d.label)}</b> ${(d.score*100).toFixed(0)}% · ${esc(w)}</span>`}).join('');
  $('photobtn').classList.toggle('hide',!s.camera_live);
  db.classList.toggle('hide',!v||!v.model);if(v){db.textContent=v.enabled?'Pause detection':'Resume detection';db.dataset.cmd=v.enabled?'detect off':'detect on'}
  // oled
  const o=s.oled;$('oledst').textContent=o?o.status+(o.showing_text?' · text':''):'not running';
  $('oledst').className='r '+(o&&!o.hardware&&s.mode!=='simulation'?'t-bad':'hint');
  document.querySelectorAll('#oledmodes button').forEach(b=>b.classList.toggle('on',!!o&&o.mode===b.dataset.m));
  // log
  $('log').innerHTML=s.events.slice().reverse().map(x=>{const i=x.indexOf(' ');
    return `<li class="${/STOPPED|stuck|error/i.test(x)?'stop':''}">${esc(x.slice(0,i))} <b>${esc(x.slice(i+1))}</b></li>`}).join('')||'<li>No events yet</li>';
}

// ----- camera video: reconnect when it stops (25 Nov 2026) -----
// The <img> holds one endless MJPEG connection. Before, it was set once, so after a robot restart, a Wi-Fi drop or a
// stalled connection the page kept showing the last frame forever. Now it reconnects when: the robot restarted
// (new boot id), the connection errored/ended, or the picture has not changed for CAM_STALL_MS while the robot
// says frames are arriving (checked by drawing a tiny copy of the image on a canvas every second; sensor noise makes
// consecutive camera frames differ, so an identical copy means the stream is frozen).
const CAM_STALL_MS=4000;let camBoot=null,camSig='',camSame=0,camRetry=0,camCan=null;
function camConnect(img){img.src='/stream.mjpg?t='+Date.now();camSig='';camSame=Date.now()}
function camVideo(s,img){
  if(!s.camera_live){if(img.src){img.removeAttribute('src');img.classList.add('hide');$('camph').classList.remove('hide');$('camwrap').classList.add('off')}camBoot=s.boot;return}
  if(!img.src||s.boot!==camBoot){camBoot=s.boot;camConnect(img);img.classList.remove('hide');$('camph').classList.add('hide');$('camwrap').classList.remove('off')}}
setInterval(()=>{const img=$('cam');if(!img||!img.src||!S||!S.camera_live||document.hidden)return;
  try{camCan=camCan||document.createElement('canvas');camCan.width=16;camCan.height=12;
    const g=camCan.getContext('2d',{willReadFrequently:true});g.drawImage(img,0,0,16,12);
    const sig=Array.from(g.getImageData(0,0,16,12).data).join(',');
    if(sig!==camSig){camSig=sig;camSame=Date.now();return}}
  catch(e){}                                   // nothing decoded yet: counts as "not changing"
  if(Date.now()-camSame>CAM_STALL_MS&&Date.now()-camRetry>CAM_STALL_MS){camRetry=Date.now();console.info('camera stalled, reconnecting');camConnect(img)}},1000);
$('cam').addEventListener('error',()=>setTimeout(()=>{const img=$('cam');if(S&&S.camera_live&&img.src)camConnect(img)},1500));   // the page's HTML is above this script
async function state(){try{const t0=performance.now(),r=await fetch('/api/state');S=await r.json();rtt=performance.now()-t0;pose=S.pose;failCount=0;render()}
  catch(e){if(++failCount>2){$('conndot').className='dot off';$('modetxt').textContent='disconnected'}}}

async function drawMap(){try{const m=await (await fetch('/api/map')).json();const c=$('map'),g=c.getContext('2d'),n=m.n,px=c.width/n;
  const st=getComputedStyle(document.documentElement),col=v=>st.getPropertyValue(v).trim();
  g.clearRect(0,0,c.width,c.height);
  if(MAPMODE==='conf'&&m.conf){const okc=col('--ok'),badc=col('--bad'),warnc=col('--warn');
    for(let j=0;j<n;j++)for(let i=0;i<n;i++){const ch=m.conf[j*n+i];if(ch==='-')continue;
      if(ch==='E'){g.fillStyle=badc;g.globalAlpha=1}else if(ch==='O'){g.fillStyle=warnc;g.globalAlpha=.85}
      else{const v=+ch;g.fillStyle=v>=5?badc:okc;g.globalAlpha=.12+.8*Math.abs(v-4.5)/4.5}
      g.fillRect(i*px,(n-1-j)*px,Math.ceil(px),Math.ceil(px))}g.globalAlpha=1}
  else for(let j=0;j<n;j++){const row=m.rows[j];for(let i=0;i<n;i++){const ch=row[i];if(ch===' ')continue;
    g.fillStyle=ch==='#'?col('--fg'):ch==='!'?col('--bad'):col('--free');g.fillRect(i*px,(n-1-j)*px,Math.ceil(px),Math.ceil(px))}}
  if(m.raw_trail&&m.raw_trail.length>1){g.strokeStyle=col('--warn');g.globalAlpha=.8;g.lineWidth=1.5;g.setLineDash([5,4]);g.beginPath();   // SLAM on: wheels + gyro alone
    m.raw_trail.forEach(([x,y],k)=>{const X=(x/m.cell+n/2)*px,Y=(n/2-y/m.cell)*px;k?g.lineTo(X,Y):g.moveTo(X,Y)});g.stroke();g.setLineDash([]);g.globalAlpha=1}
  if(m.trail&&m.trail.length>1){g.strokeStyle=col('--acc');g.globalAlpha=.45;g.lineWidth=2;g.beginPath();
    m.trail.forEach(([x,y],k)=>{const X=(x/m.cell+n/2)*px,Y=(n/2-y/m.cell)*px;k?g.lineTo(X,Y):g.moveTo(X,Y)});g.stroke();g.globalAlpha=1}
  g.strokeStyle=col('--line');g.lineWidth=1;const step=0.5/m.cell*px;
  for(let k=0;k<=c.width;k+=step){g.beginPath();g.moveTo(k,0);g.lineTo(k,c.height);g.stroke();g.beginPath();g.moveTo(0,k);g.lineTo(c.width,k);g.stroke()}
  const ow=px/m.cell;g.font='600 11px system-ui,sans-serif';g.textAlign='center';
  for(const o of m.objects||[]){const ox=(o.x/m.cell+n/2)*px,oy=(n/2-o.y/m.cell)*px,rr=Math.max(3,o.radius*ow);
    g.globalAlpha=0.35+0.65*Math.min(1,(o.p-0.5)*2);g.fillStyle=col('--warn');g.beginPath();g.arc(ox,oy,rr,0,7);g.fill();
    g.fillStyle=col('--fg');g.fillText(o.label,ox,oy-rr-3);g.globalAlpha=1}
  const nv=S&&S.nav;if(nv&&nv.active&&nv.x!==null){const tx=(nv.x/m.cell+n/2)*px,ty=(n/2-nv.y/m.cell)*px;
    g.strokeStyle=col('--acc');g.setLineDash([5,4]);g.lineWidth=2;g.beginPath();g.moveTo((pose.x/m.cell+n/2)*px,(n/2-pose.y/m.cell)*px);g.lineTo(tx,ty);g.stroke();g.setLineDash([])}
  $('objlist').innerHTML=(m.objects||[]).length?(m.objects.map(o=>`${esc(o.label)} ${Math.round(o.dist_m*100)} cm <button class="btn" style="padding:1px 8px;font-size:11px" onclick="send('go to ${esc(o.label)}')">go</button>`).join(' · ')):'none yet';
  const cx=(pose.x/m.cell+n/2)*px,cy=(n/2-pose.y/m.cell)*px;g.save();g.translate(cx,cy);g.rotate(-pose.theta);
  g.fillStyle=col('--acc');g.beginPath();g.moveTo(14,0);g.lineTo(-9,8);g.lineTo(-5,0);g.lineTo(-9,-8);g.closePath();g.fill();g.restore()}catch(e){}}

$('themebtn').textContent=THEME_LABEL[theme()];
document.querySelectorAll('#oledmodes button').forEach(b=>b.onclick=()=>send('oled '+b.dataset.m));
let MAPMODE=store('robot-mapmode')||'map';
function setMapMode(m){MAPMODE=m;store('robot-mapmode',m);document.querySelectorAll('#mapmode button').forEach(b=>b.classList.toggle('on',b.dataset.m===m));drawMap()}
document.querySelectorAll('#mapmode button').forEach(b=>{b.onclick=()=>setMapMode(b.dataset.m);b.classList.toggle('on',b.dataset.m===MAPMODE)});
let oledBusy=false;
function oledTick(){if(oledBusy||document.hidden)return;oledBusy=true;const n=new Image();
  n.onload=()=>{$('oledimg').src=n.src;oledBusy=false};n.onerror=()=>{oledBusy=false};n.src='/oled.png?t='+Date.now()}
setInterval(oledTick,250);
// ----- notes, presentation mode, card layout (24 Nov 2026) -----
function store(k,v){try{if(v===undefined)return JSON.parse(localStorage.getItem(k)||'null');localStorage.setItem(k,JSON.stringify(v))}catch(e){return null}}
let notesOpen=false;      // the Notes card opens from the ⚠ chip only: popping in by itself moved every card down
function renderNotes(notes){notes=notes||[];const card=$('notes');
  card.classList.toggle('hide',!notesOpen||!notes.length||(LAYOUT.hidden||[]).includes('notes'));
  $('notechip').classList.toggle('hide',!notes.length);$('notecount').textContent=notes.length;
  const icon={error:'⛔',warn:'⚠️',info:'ℹ️'};const key=JSON.stringify(notes);if(key===renderNotes.k)return;renderNotes.k=key;
  $('notelist').innerHTML=notes.map(n=>`<li class="${esc(n.level)}"><span class="lv">${icon[n.level]||'•'}</span><span><b>${esc(n.feature)}</b> - ${esc(n.msg)}</span></li>`).join('');
  document.querySelectorAll('.card h2 .r').forEach(el=>el.classList.toggle('err',/unavailable|error|failed|not answering|stopped after|can't|could not/i.test(el.textContent)))}
function togglePresent(on){const p=on===undefined?!document.documentElement.classList.contains('presenting'):on;
  document.documentElement.classList.toggle('presenting',p);$('presbtn').classList.toggle('on',p);$('presbtn').textContent=p?'■ Presenting':'▶ Present';store('robot-present',p)}
const CARDS=[...document.querySelectorAll('#grid > .card')].map(c=>c.dataset.card);
let LAYOUT=store('robot-layout')||{order:[],hidden:[],wide:null};
function applyLayout(){const g=$('grid'),all=[...g.children];const byId=Object.fromEntries(all.map(c=>[c.dataset.card,c]));
  const order=(LAYOUT.order||[]).filter(id=>byId[id]);for(const id of CARDS)if(!order.includes(id))order.splice(CARDS.indexOf(id),0,id);
  for(const id of order)g.appendChild(byId[id]);
  for(const c of all){const id=c.dataset.card;if(id!=='notes')c.classList.toggle('hide',(LAYOUT.hidden||[]).includes(id));
    if(LAYOUT.wide&&id in LAYOUT.wide)c.classList.toggle('wide',LAYOUT.wide[id])}
  if(typeof drawMap==='function')drawMap()}
function saveLayout(){LAYOUT.order=[...$('grid').children].map(c=>c.dataset.card);store('robot-layout',LAYOUT)}
function hideCard(btn){const id=btn.closest('.card').dataset.card;LAYOUT.hidden=[...new Set([...(LAYOUT.hidden||[]),id])];saveLayout();applyLayout();buildMenu()}
function toggleWide(btn){const c=btn.closest('.card');c.classList.toggle('wide');LAYOUT.wide=LAYOUT.wide||{};LAYOUT.wide[c.dataset.card]=c.classList.contains('wide');saveLayout();if(typeof drawMap==='function')drawMap()}
function toggleEdit(){const on=document.body.classList.toggle('editing');$('editbtn').classList.toggle('on',on);$('editbtn').textContent=on?'✓ Done':'✎ Layout'}
function buildMenu(){$('cardlist').innerHTML=CARDS.map(id=>{const c=document.querySelector(`[data-card="${id}"]`);
  return `<label><input type="checkbox" ${(LAYOUT.hidden||[]).includes(id)?'':'checked'} onchange="showCard('${id}',this.checked)">${esc(c.dataset.title)}</label>`}).join('')}
function showCard(id,on){LAYOUT.hidden=(LAYOUT.hidden||[]).filter(x=>x!==id);if(!on)LAYOUT.hidden.push(id);saveLayout();applyLayout()}
function toggleMenu(){const m=$('cardmenu');if(m.classList.toggle('hide'))return;buildMenu()}
function resetLayout(){LAYOUT={order:[],hidden:[],wide:null};store('robot-layout',LAYOUT);
  document.querySelectorAll('#grid > .card').forEach(c=>c.classList.toggle('wide',c.dataset.defwide==='1'));applyLayout();buildMenu()}
document.querySelectorAll('#grid > .card').forEach(c=>c.dataset.defwide=c.classList.contains('wide')?'1':'0');
// drag a card by its handle (pointer events: mouse, pen and touch)
let drag=null;
document.addEventListener('pointerdown',e=>{const gr=e.target.closest('.grip');if(!gr||!document.body.classList.contains('editing'))return;
  e.preventDefault();drag=gr.closest('.card');drag.classList.add('dragging');gr.setPointerCapture(e.pointerId)});
document.addEventListener('pointermove',e=>{if(!drag)return;const el=document.elementFromPoint(e.clientX,e.clientY);
  const over=el&&el.closest('#grid > .card');if(!over||over===drag)return;const r=over.getBoundingClientRect();
  const after=(e.clientY-r.top)/r.height>0.5||((e.clientX-r.left)/r.width>0.5&&(e.clientY-r.top)/r.height>0.25);
  over.parentNode.insertBefore(drag,after?over.nextSibling:over)});
document.addEventListener('pointerup',()=>{if(!drag)return;drag.classList.remove('dragging');drag=null;saveLayout();if(typeof drawMap==='function')drawMap()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('cardmenu').classList.add('hide');if(document.body.classList.contains('editing'))toggleEdit()}});
applyLayout();togglePresent(!!store('robot-present'));
{const qp=new URLSearchParams(location.search);              // ?present=1 (a demo screen), ?edit=1
  if(qp.has('present'))togglePresent(qp.get('present')!=='0');if(qp.get('edit')==='1')toggleEdit();
  if(['map','conf'].includes(qp.get('map')))setMapMode(qp.get('map'))}
setInterval(state,300);setInterval(drawMap,700);state();drawMap();
</script></body></html>"""


def make_handler(robot, camera):
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 keep-alive: a dashboard tab polls ~8 times a second; reusing its connections saves a TCP
        # connect + a new server thread per request. Every response has a Content-Length (the MJPEG stream
        # closes its connection instead). Idle connections are dropped after 30 s.
        protocol_version = "HTTP/1.1"
        timeout = 30

        def log_message(self, *a):  # keep the CLI clean
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if code >= 400:                      # an error may leave an unread request body: don't reuse
                self.send_header("Connection", "close")
                self.close_connection = True
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                path = self.path.split("?", 1)[0]
                if path == "/":
                    return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                if path == "/api/state":
                    s = dict(robot.status(max_age=STATUS_SHARE_S))     # a copy: the snapshot is shared
                    s["camera"], s["camera_live"] = camera.status, camera.frame is not None
                    s["https_port"] = getattr(robot, "https_port", None)
                    s["boot"] = BOOT_ID
                    s["motors_reversed"] = dict(getattr(robot.hw, "reversed", {}) or {})
                    s["camera_inverted"] = bool(robot.camera is not None and robot.camera.invert)
                    s["notes"] = collect_notes(robot, camera)
                    s["oled"] = robot.oled.info() if robot.oled else None
                    s["dance"] = robot.dance.info() if robot.dance else None    # fresh: the music syncs to it
                    return self._send(200, s)
                if path == "/api/songs":
                    return self._send(200, {"songs": robot.dance.songs() if robot.dance else []})
                if path.startswith("/songs/"):          # a music file from songs/, for the dance
                    from urllib.parse import unquote
                    name = unquote(path[len("/songs/"):])
                    f = song_file_path(name, robot.dance.song_dirs if robot.dance else None)
                    if f is None:
                        return self._send(404, {"error": "no such song"})
                    return self._send(200, f.read_bytes(), SONG_EXTS[f.suffix.lower()])
                if path == "/oled.png":
                    png = robot.oled.png_bytes() if robot.oled else b""
                    return self._send(200, png, "image/png") if png else self._send(503, {"error": "no OLED image"})
                if path == "/api/map":
                    objs = robot.objects.describe(robot.pose)
                    conf, trail = robot.map.fused(objs)
                    return self._send(200, {"n": MAP_N, "cell": CELL_M, "rows": robot.map.rows(), "objects": objs,
                                            "conf": conf, "trail": trail,
                                            "raw_trail": robot.slam.trail() if robot.slam else []})
                if path.startswith("/photos/"):         # a saved photo, for the dashboard's download
                    name = path[len("/photos/"):]
                    f = PHOTO_DIR / name
                    if not re.fullmatch(r"photo-[0-9]{8}-[0-9]{6}(-[0-9]+)?\.jpg", name) or not f.is_file():
                        return self._send(404, {"error": "no such photo"})
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if path == "/ideas.md":
                    md = robot.ideas.markdown().encode() if robot.ideas else b"# Ideas\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Length", str(len(md)))
                    self.send_header("Content-Disposition", 'attachment; filename="ideas.md"')
                    self.end_headers()
                    self.wfile.write(md)
                    return
                if path == "/snapshot.jpg":
                    jpg = camera.snapshot()
                    return self._send(200, jpg, "image/jpeg") if jpg else self._send(503, {"error": "no frame"})
                if path == "/stream.mjpg":
                    return self._stream()
                self._send(404, {"error": "not found"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # browser closed the tab
            except Exception as exc:
                log(f"[dashboard] {exc}")

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")      # endless body: this connection is not reused
            self.end_headers()
            self.close_connection = True
            last = camera.jpeg                           # possibly stale from the last viewer: wait for a new one
            camera.watch(+1)
            try:
                while not robot._stop.is_set():
                    jpg = camera.jpeg
                    if jpg is not None and jpg is not last:
                        last = jpg
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    time.sleep(0.05)
            finally:
                camera.watch(-1)

        def do_POST(self):
            try:
                path = self.path.split("?", 1)[0]
                if path == "/api/voice":             # the dashboard microphone: audio -> Groq Whisper -> ask
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 4_000_000:
                        return self._send(413, {"error": "recording too long (max ~30 s)"})
                    audio = self.rfile.read(n)
                    if robot.assistant is None:
                        return self._send(503, {"error": "no assistant"})
                    if n < 1000:
                        return self._send(200, {"error": "the recording is empty - is the microphone muted?"})
                    try:
                        heard = robot.assistant.transcribe(audio, self.headers.get("Content-Type") or "audio/webm")
                    except AiError as exc:
                        return self._send(200, {"error": str(exc)})
                    log(f"[voice] heard: {heard}")
                    return self._send(200, {"text": heard, "reply": robot.assistant.ask(heard, source="voice")})
                if path != "/api/cmd":
                    return self._send(404, {"error": "not found"})
                n = int(self.headers.get("Content-Length") or 0)
                if n > 10_000:
                    return self._send(413, {"error": "too large"})
                try:
                    cmd = str(json.loads(self.rfile.read(n) or b"{}").get("cmd", ""))
                except (ValueError, AttributeError):
                    return self._send(400, {"error": "send JSON like {\"cmd\": \"forward 1\"}"})
                reply = robot.execute(cmd)
                if reply == "quit":
                    reply = "Use the terminal to quit"
                elif reply:
                    log(f"[dashboard] {cmd} -> {reply.splitlines()[0]}")
                self._send(200, {"reply": reply})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as exc:
                log(f"[dashboard] {exc}")
                try:
                    self._send(500, {"error": str(exc)})
                except Exception:
                    pass

    return Handler


def start_dashboard(robot, camera, host, port):
    try:
        server = ThreadingHTTPServer((host, port), make_handler(robot, camera))
    except OSError as exc:
        log(f"[dashboard] could not start on port {port}: {exc} - CLI only (try --port 8081)")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="dashboard").start()
    shown = "localhost" if host in ("0.0.0.0", "") else host
    log(f"[dashboard] http://{shown}:{port}  (from another device use the Pi's address, "
        f"e.g. http://raspberrypi.local:{port})")
    return server


# =====================================================================
# Faces (24 Nov 2026): OpenCV's YuNet face detector on the camera, only while something needs it
# =====================================================================

def face_angles(face):
    """(yaw, pitch) ratios from one YuNet row (x, y, w, h, right eye, left eye, nose, right mouth, left mouth,
    score): yaw ~0 facing the camera, +-0.5 = head turned ~30 deg; pitch bigger = head tipped down
    (run_prototype hub/focus.py)."""
    rex, rey, lex, ley, nx, ny, rmx, rmy, lmx, lmy = face[4:14]
    eye_mid_x, eye_mid_y = (rex + lex) / 2, (rey + ley) / 2
    eye_d = max(1.0, ((rex - lex) ** 2 + (rey - ley) ** 2) ** 0.5)
    mouth_mid_y = (rmy + lmy) / 2
    return (nx - eye_mid_x) / eye_d, (ny - eye_mid_y) / max(1.0, mouth_mid_y - eye_mid_y)


class FaceWatcher:
    """Finds faces in the camera's newest frame at most FACE_HZ times a second, but only while a feature asks
    (`want()`: focus mode, face me). The model (230 kB) is looked for in the model folders and downloaded once
    from opencv_zoo if missing. Nothing is saved or sent anywhere.

    faces(): [{"box": [x, y, w, h], "score", "yaw", "pitch", "bearing_deg" (+ = left), "size"}], largest first,
    [] when none is seen, None when it cannot run (no camera / no model / OpenCV too old)."""

    def __init__(self, camera):
        self.camera = camera
        self.status = "idle (no feature needs faces)" if camera is not None else "off (no camera)"
        self.error = "" if camera is not None else "no camera"
        self._faces, self._t, self._wanted_until = [], 0.0, 0.0
        self.ms = None
        self._det, self._size = None, None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False

    def want(self, seconds=2.0):
        """Keep face detection running for `seconds` more (call it on every check)."""
        self._wanted_until = time.monotonic() + seconds
        if not self._started and self.camera is not None:
            self._started = True
            threading.Thread(target=self._run, daemon=True, name="faces").start()

    def faces(self):
        if self.error:
            return None
        with self._lock:
            if time.monotonic() - self._t > 1.5:          # nothing fresh yet (just started, or camera stalled)
                return [] if self._det is not None else None
            return list(self._faces)

    def _load(self):
        import cv2

        if not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError(f"OpenCV {cv2.__version__} is older than 4.5.4 (no FaceDetectorYN)")
        path = next((d / YUNET_NAME for d in MODEL_DIRS if (d / YUNET_NAME).is_file()), None)
        if path is None:
            import urllib.request

            path = next((d for d in MODEL_DIRS if d.is_dir()), MODEL_DIRS[0]) / YUNET_NAME
            log(f"[faces] downloading the face model (230 kB) to {path}")
            req = urllib.request.Request(YUNET_URL, headers={"User-Agent": "deskbot-simplified/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read(2_000_000)
            if not 100_000 < len(data) < 2_000_000:
                raise RuntimeError("the face model download looks wrong")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self._det = cv2.FaceDetectorYN.create(str(path), "", (320, 240), 0.6, 0.3, 5)
        return path

    def _run(self):
        try:
            path = self._load()
            log(f"[faces] YuNet face detector ready ({path.name})")
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            self.status = f"unavailable ({self.error})"
            log(f"[faces] {self.status} - features that use faces fall back to the object detector")
            return
        last_id = -1
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame, fid = self.camera.frame, self.camera.frame_id
            if t0 > self._wanted_until or frame is None or fid == last_id:
                self.status = "idle (no feature needs faces)" if t0 > self._wanted_until else "waiting for the camera"
                self._stop.wait(0.1)
                continue
            last_id = fid
            try:
                h, w = frame.shape[:2]
                if self._size != (w, h):
                    self._det.setInputSize((w, h))
                    self._size = (w, h)
                _, rows = self._det.detect(frame)
                found = []
                for f in ([] if rows is None else rows):
                    x, y, fw, fh = (float(v) for v in f[:4])
                    yaw, pitch = face_angles(f)
                    found.append({"box": [round(x), round(y), round(fw), round(fh)], "score": round(float(f[14]), 2),
                                  "yaw": round(yaw, 3), "pitch": round(pitch, 3),
                                  "bearing_deg": round(pixel_bearing(x + fw / 2, w), 1),
                                  "size": round(fw * fh / (w * h), 4)})
                found.sort(key=lambda d: -d["size"])
                with self._lock:
                    self._faces, self._t = found, time.monotonic()
                self.ms = (time.monotonic() - t0) * 1000
                self.status = f"running ({self.ms:.0f} ms per frame, {len(found)} face{'s' if len(found) != 1 else ''})"
            except Exception as exc:
                log(f"[faces] detection error: {exc}")
                self._stop.wait(1.0)
            self._stop.wait(max(0.0, 1.0 / FACE_HZ - (time.monotonic() - t0)))

    def close(self):
        self._stop.set()


# =====================================================================
# Face me + greeter (24 Nov 2026): turn to face the person, keep facing them, say hello to someone new
# =====================================================================
#
# From run_prototype assistant/commands.py (_face_user_once), runtime/behaviour.py (pick_user) and
# companion/greeter.py (same numbers). The continuous PID "follow" of companion/control.py is replaced by short
# gyro turns, which this file already does well.

GREET_PHRASES = ["Hi there!", "Hello! Nice to see you.", "Oh, hello!", "Hey! Good to see you."]


class People:
    def __init__(self, robot, faces=None):
        self.robot, self.faces = robot, faces
        self.keep_facing = False
        self.greet_enabled = True
        self.state = "idle"
        self.last_turn_end = -1e9
        self._off_since = None
        self._last_runs = -1
        self._last_user = None                 # (bearing, picture time, kind, when seen): bridges detector flicker
        # greeter (run_prototype companion/greeter.py)
        self.candidate, self.candidate_since, self.known = 0, None, 0
        self.fewer_since, self.last_greeting, self.greetings, self.last_phrase = None, -1e9, 0, None
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="people").start()

    # ----- who is "you" -----
    def _persons(self, dets, frame_size):
        """Person detections big and sure enough to be someone at the desk."""
        if not frame_size:
            return []
        area = frame_size[0] * frame_size[1]
        out = []
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            if d["label"] == "person" and d["score"] >= GREET_MIN_SCORE and (x2 - x1) * (y2 - y1) >= GREET_MIN_BOX * area:
                out.append(d)
        return out

    def user(self):
        """(bearing_deg, picture time, 'person'/'face') of the user now, or None. The user = the biggest person box;
        without object detection, the biggest face near the robot. A miss of up to USER_MEMORY_S (detectors
        flicker) returns the last sighting; 'keep facing' still ignores pictures taken before its own turn."""
        u = self._see_user()
        now = time.monotonic()
        if u is not None:
            self._last_user = u + (now,)
            return u
        last = self._last_user
        return last[:3] if last is not None and now - last[3] <= USER_MEMORY_S else None

    def _see_user(self):
        r, det = self.robot, self.robot.detector
        if det is not None and det.enabled and det.model:
            persons = self._persons(det.current(), det.frame_size)
            if persons:
                big = max(persons, key=lambda d: (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]))
                return big["bearing_deg"], det.det_time, "person"
        if self.faces is not None and not self.faces.error:
            self.faces.want()
            faces = [f for f in (self.faces.faces() or []) if f["size"] >= FOCUS_MIN_FACE]
            if faces:
                return faces[0]["bearing_deg"], time.monotonic(), "face"
        return None

    def _can_move(self, now):
        r = self.robot
        return (r.move is None and not r.nav.busy() and not r.cal and not r.lift["lifted"]
                and now - r.last_user_cmd >= FACE_USER_QUIET_S)

    def face_once(self):
        """'face me': turn toward the user once. Returns the reply."""
        u = self.user()
        if u is None:
            why = "" if (self.robot.detector and self.robot.detector.model) else \
                " (object detection is not running, and no face is close enough)"
            return "I can't see you right now" + why
        bearing = u[0]
        if abs(bearing) < FACE_USER_OK_DEG:
            return "I'm already looking at you"
        reply = self.robot.execute(f"turn {bearing:.0f}", source="face")
        self.last_turn_end = time.monotonic() + 3.0          # until the turn really ends (updated in _run)
        return "Turning to face you" if not reply.startswith("Not moving") else reply

    def set_keep(self, on):
        self.keep_facing = on
        self._off_since = None
        return ("I'll keep facing you ('face me off' to stop)" if on else "OK, I'll stop following you with my eyes "
                "and wheels")

    # ----- the loop: keep facing + greeter -----
    def _run(self):
        was_moving = False
        while not self._stop.wait(1.0 / PEOPLE_HZ):
            now = time.monotonic()
            r = self.robot
            try:
                moving = r.move is not None
                if was_moving and not moving:
                    self.last_turn_end = now                       # pictures before this are mid-turn
                was_moving = moving
                if self.keep_facing:
                    self._keep_facing_step(now)
                else:
                    self.state = "idle"
                det = r.detector
                if det is not None and det.enabled and det.model and det.runs != self._last_runs:
                    self._last_runs = det.runs
                    self.greet_step(now, self._persons(det.current(), det.frame_size))
            except Exception as exc:
                log(f"[people] {type(exc).__name__}: {exc}")

    def _keep_facing_step(self, now):
        if not self._can_move(now):
            self.state, self._off_since = "waiting (busy)", None
            return
        u = self.user()
        if u is None:
            self.state, self._off_since = "can't see you", None
            return
        bearing, t_pic, _ = u
        if t_pic < self.last_turn_end + OBJ_AFTER_TURN_S:          # taken during my own turn: wait for a new one
            self.state = "settling"
            return
        if abs(bearing) <= FACE_USER_KEEP_DEG:
            self.state, self._off_since = "facing you", None
            return
        if self._off_since is None:
            self._off_since = now
        self.state = f"you're {abs(bearing):.0f} deg {'left' if bearing > 0 else 'right'}"
        if now - self._off_since >= FACE_USER_CONFIRM_S:          # held long enough: not detector flicker
            self._off_since = None
            self.robot.execute(f"turn {bearing:.0f}", source="face")
            self.last_turn_end = now + 3.0

    def greet_step(self, now, persons):
        """run_prototype Greeter.step: greet when more people than known stay in view for GREET_CONFIRM_S;
        someone counts as gone only after GREET_ABSENT_S; greetings at least GREET_COOLDOWN_S apart."""
        n = len(persons)
        if n != self.candidate or self.candidate_since is None:
            self.candidate, self.candidate_since = n, now
        if now - self.candidate_since < GREET_CONFIRM_S:
            return False
        if n >= self.known:
            self.fewer_since = None
        else:                                    # someone left: forget them only after a while
            self.fewer_since = self.fewer_since if self.fewer_since is not None else now
            if now - self.fewer_since >= GREET_ABSENT_S:
                self.known, self.fewer_since = n, None
            return False
        if n == self.known:
            return False
        self.known = n
        if not self.greet_enabled or self.robot.lift["lifted"] or now - self.last_greeting < GREET_COOLDOWN_S:
            return False
        self.last_greeting = now
        self.greetings += 1
        self.last_phrase = random.choice([p for p in GREET_PHRASES if p != self.last_phrase] or GREET_PHRASES)
        self.robot.announce(self.last_phrase, "happy")
        return True

    def info(self):
        return {"keep_facing": self.keep_facing, "state": self.state, "greet": self.greet_enabled,
                "people": self.known, "greetings": self.greetings, "last_greeting": self.last_phrase}

    def line(self):
        i = self.info()
        return (f"face me: {'on - ' + i['state'] if i['keep_facing'] else 'off'} | greeter: "
                f"{'on' if i['greet'] else 'off'}, {i['people']} people in view, {i['greetings']} greetings")

    def close(self):
        self._stop.set()


# =====================================================================
# Focus timer (24 Nov 2026): 'focus 25' - a Pomodoro session with gentle nudges, then a break
# =====================================================================
#
# From run_prototype hub/focus.py (same thresholds), without the phone-notification hold and the wiggle.
# Put the robot next to or under your screen, facing you: the first FOCUS_BASELINE_S with a face in view is
# "looking at the work", so it may sit off to one side.

FOCUS_LINES = {
    "away": ["Hey, eyes back on the work!", "Psst. Your work misses you.", "Let's get back to it, you've got this.",
             "Still with me? Back to the task."],
    "down": ["Looking down a lot. Phone? Let's focus.", "Head up, champ. Back to it."],
    "phone": ["Phone down, please. Focus time!", "The phone can wait. Back to work!", "I see that phone. Let's focus."],
}


class FocusTimer:
    def __init__(self, robot, faces, log_file=None, clock=time.monotonic):
        self.robot, self.faces = robot, faces
        self.log_file = Path(log_file) if log_file else FOCUS_FILE
        self.clock = clock
        self.mode, self.until, self.minutes = "idle", 0.0, 0
        self.sessions_done = 0                 # this run, for the long break after every 4th
        self._reset_session()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="focus").start()

    def _reset_session(self):
        self.obs, self.focused_s, self.distracted_s, self.distractions = "", 0.0, 0.0, 0
        self.run_s, self.good_s, self.last_nudge, self.nudged = 0.0, 0.0, -1e9, False
        self.base, self.base_samples, self.no_face_n, self.last_line = None, [], 0, ""
        self.t_last = None

    # ----- commands -----
    def start(self, minutes=FOCUS_DEFAULT_MIN):
        if not 1 <= minutes <= 180:
            return "Focus sessions are 1-180 minutes"
        self._reset_session()
        self.mode, self.minutes = "focus", minutes
        self.started_at, self.until = time.strftime("%Y-%m-%d %H:%M"), self.clock() + minutes * 60
        how = ("I'll watch where you look" if self.faces is not None and not self.faces.error else
               "I can only check for your phone and whether you're here" if self._detector_ok() else
               "I can't see you (no camera/detection), so it's just a timer")
        self.robot.event(f"Focus: {minutes} min session started")
        if self.robot.oled is not None:
            self.robot.oled.mood("focused", 3.0)
        return (f"Focus for {minutes} minutes - go! {how}. Look at your work for the first few seconds "
                f"so I learn where that is. ('focus stop' ends it)")

    def stop(self):
        if self.mode == "idle":
            return "No focus session running"
        was = self.mode
        msg = self._finish(early=True) if was == "focus" else "Break skipped"
        self.mode = "idle"
        return msg

    def _detector_ok(self):
        d = self.robot.detector
        return d is not None and bool(d.model) and d.enabled

    # ----- watching -----
    def observe(self):
        """One of: focused, away, down, phone, absent, unknown (see the docs)."""
        dets = self.robot.detector.current() if self._detector_ok() else None
        labels = {d["label"] for d in dets or []}
        phone, person = "cell phone" in labels, "person" in labels
        faces = None
        if self.faces is not None and not self.faces.error:
            self.faces.want()
            faces = self.faces.faces()
            if faces:                                    # only a face near the robot is the person working
                faces = [f for f in faces if f["size"] >= FOCUS_MIN_FACE]
        if faces:
            self.no_face_n = 0
            f = faces[0]
            if self.base is None:
                self.base_samples.append((f["yaw"], f["pitch"]))
                if len(self.base_samples) >= FOCUS_BASELINE_S * FOCUS_HZ:
                    ys = sorted(s[0] for s in self.base_samples)
                    ps = sorted(s[1] for s in self.base_samples)
                    self.base = (ys[len(ys) // 2], ps[len(ps) // 2])
                return "phone" if phone else "focused"
            if phone:
                return "phone"
            dy, dp = f["yaw"] - self.base[0], f["pitch"] - self.base[1]
            if abs(dy) > FOCUS_YAW_TOL:
                return "away"
            if dp > FOCUS_PITCH_TOL:
                return "down"
            return "away" if dp < -2 * FOCUS_PITCH_TOL else "focused"
        if phone:
            return "phone"
        if faces == [] or dets is not None:              # we can see, and there is no face
            if person:
                self.no_face_n += 1                      # head turned right round, or face out of frame
                return "away" if self.no_face_n >= FOCUS_NO_FACE_AWAY_N else "focused"
            return "absent"
        return "unknown"

    def _tick(self, now):
        dt = 0.0 if self.t_last is None else min(2.0, now - self.t_last)
        self.t_last = now
        obs = self.obs = self.observe()
        if obs == "focused":
            self.focused_s += dt
            self.good_s += dt
            if self.good_s >= FOCUS_RESET_S:            # 3 s back on task ends a distraction
                self.run_s, self.nudged = 0.0, False
        elif obs in ("away", "down", "phone"):
            self.good_s = 0.0
            self.run_s += dt
            self.distracted_s += dt
            limit = FOCUS_PHONE_S if obs == "phone" else FOCUS_GRACE_S
            if self.run_s >= limit and now - self.last_nudge >= (FOCUS_REPEAT_S if self.nudged else 0):
                if not self.nudged:
                    self.distractions += 1
                self.nudged, self.last_nudge = True, now
                self._nudge(obs)
        # absent / unknown: the timer runs on, nothing counts either way

    def _nudge(self, kind):
        lines = [x for x in FOCUS_LINES[kind] if x != self.last_line] or FOCUS_LINES[kind]
        self.last_line = random.choice(lines)
        self.robot.announce(self.last_line, "angry" if kind == "phone" else "sad")

    def pct(self):
        seen = self.focused_s + self.distracted_s
        return None if seen < 1 else round(100 * self.focused_s / seen)

    def _finish(self, early=False):
        pct = self.pct()
        done_min = self.minutes - max(0.0, self.until - self.clock()) / 60 if early else self.minutes
        how = (f"You were focused {pct} % of {done_min:.0f} minutes" if pct is not None else
               f"{done_min:.0f} minutes done")
        how += f", with {self.distractions} distraction{'s' if self.distractions != 1 else ''}."
        self._log({"start": self.started_at, "minutes": round(done_min, 1), "planned": self.minutes,
                   "focused_pct": pct, "distractions": self.distractions, "early": early})
        if early:
            self.robot.event(f"Focus stopped early: {how}")
            return f"Focus stopped. {how}"
        self.sessions_done += 1
        long_break = self.sessions_done % 4 == 0
        brk = FOCUS_LONG_BREAK_MIN if long_break else FOCUS_BREAK_MIN
        good = pct is not None and pct >= FOCUS_GOOD * 100
        self.robot.announce(f"{'Great session! ' if good else 'Session done. '}{how} Take a {brk} minute break.",
                            "happy" if good else "normal", sound="success")
        self.mode, self.until = "break", self.clock() + brk * 60
        return how

    def _log(self, entry):
        try:
            data = json.loads(self.log_file.read_text(encoding="utf-8"))
            sessions = data.get("sessions", []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            sessions = []
        sessions = (sessions + [entry])[-FOCUS_KEEP:]
        try:
            tmp = self.log_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sessions": sessions}, indent=1), encoding="utf-8")
            os.replace(tmp, self.log_file)
        except OSError as exc:
            log(f"[focus] could not save {self.log_file}: {exc}")

    def today(self):
        """(focused minutes today, sessions today) from the log."""
        day = time.strftime("%Y-%m-%d")
        try:
            sessions = json.loads(self.log_file.read_text(encoding="utf-8")).get("sessions", [])
        except (OSError, ValueError, AttributeError):
            return 0, 0
        mine = [s for s in sessions if str(s.get("start", "")).startswith(day)]
        mins = sum(s.get("minutes", 0) * (s.get("focused_pct") if s.get("focused_pct") is not None else 100) / 100
                   for s in mine)
        return round(mins), len(mine)

    def _run(self):
        while not self._stop.wait(1.0 / FOCUS_HZ):
            now = self.clock()
            try:
                if self.mode == "focus":
                    if now >= self.until:
                        self._finish()
                    else:
                        self._tick(now)
                elif self.mode == "break" and now >= self.until:
                    self.mode = "idle"
                    self.robot.announce("Break's over! Ready for another round? Say 'focus' to start.", "happy")
            except Exception as exc:
                log(f"[focus] {type(exc).__name__}: {exc}")

    # ----- status -----
    def info(self):
        left = max(0.0, self.until - self.clock()) if self.mode != "idle" else 0.0
        mins, n = self.today()
        return {"mode": self.mode, "minutes": self.minutes, "left_s": round(left), "state": self.obs,
                "focused_pct": self.pct(), "distractions": self.distractions,
                "calibrating": self.mode == "focus" and self.base is None and bool(self.base_samples),
                "faces": self.faces.status if self.faces is not None else "off",
                "today_min": mins, "today_sessions": n}

    def line(self):
        i = self.info()
        if i["mode"] == "idle":
            return (f"No focus session. Today: {i['today_min']} focused minutes in {i['today_sessions']} sessions. "
                    f"Start one: 'focus 25'")
        left = f"{i['left_s'] // 60}:{i['left_s'] % 60:02d}"
        if i["mode"] == "break":
            return f"On a break: {left} left"
        pct = f"{i['focused_pct']} % focused" if i["focused_pct"] is not None else "not enough seen yet"
        return (f"Focus: {left} left of {i['minutes']} min | now: {i['state'] or '...'} | {pct}, "
                f"{i['distractions']} distraction{'s' if i['distractions'] != 1 else ''}")

    def close(self):
        self._stop.set()


# =====================================================================
# Tasks and reminders (24 Nov 2026): 'remind me in 20 minutes to drink water', 'todo buy milk by friday'
# =====================================================================
#
# The time words come from run_prototype deskbot/buddy/when.py (copied, names prefixed W_ so they don't clash);
# the list and the reminder rule from buddy/tasks.py (15 min before, when due, 1 h overdue). Standard library only.

W_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
W_SMALL = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "forty-five": 45}
W_UNITS = {"minute": 60, "min": 60, "mins": 60, "hour": 3600, "hr": 3600, "hrs": 3600, "day": 86400, "week": 604800}
W_DEFAULT_TIME = (17, 0)    # a day without a time = 5 PM (a deadline "by Friday" is a working-day deadline)
W_PARTS = {"morning": (9, 0), "afternoon": (14, 0), "evening": (18, 0), "tonight": (20, 0), "night": (20, 0)}
_W_NUM = r"(\d+(?:\.\d+)?|half an?|an?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty[ -]five)"
_W_REL = re.compile(rf"\b(?:with)?in {_W_NUM} ?(minutes?|mins?|hours?|hrs?|days?|weeks?)\b")
_W_DAY = re.compile(r"\b(?:(?:on|by|before|this|until|till)\s+)?(?:(next)\s+)?(the day after tomorrow|tomorrow|today|tonight|"
                    + "|".join(W_WEEKDAYS) + r")\b")
_W_CLOCK = re.compile(r"\b(?:(?:at|by|before|around|until|till)\s+)?(\d{1,2})(?::|\.)(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?(?!\w)"
                      r"|\b(?:(?:at|by|before|around|until|till)\s+)?(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)(?!\w)"
                      r"|\b(?:at|by|before|around|until|till)\s+(\d{1,2})(?![\d:.])(?!\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|%|percent|\d)\b)")
_W_NAMED = re.compile(r"\b(?:(?:at|by|before|around)\s+)?(noon|midday|midnight)\b"
                      r"|\b(?:(?:this|in the|by the|tomorrow|by)\s+)?(morning|afternoon|evening|night)\b"
                      r"|\b(?:by\s+)?(?:the\s+)?end of (?:the )?day\b|\beod\b")
_W_FILLER = re.compile(r"(?:\s+(?:by|at|on|before|due|until|till|for|this|next|in|the))+\s*$|^\s*(?:to|that i|i)\s+", re.I)


def _w_amount(word):
    word = word.strip()
    if word.startswith("half"):
        return 0.5
    try:
        return float(word)
    except ValueError:
        return float(W_SMALL.get(word.replace("-", " "), W_SMALL.get(word, 1)))


def _w_cut(text, m):
    return (text[:m.start()] + " " + text[m.end():]).strip()


def _w_tidy(text):
    text = re.sub(r"\s+", " ", text).strip(" ,.;:!?")
    for _ in range(3):
        text = _W_FILLER.sub("", text).strip(" ,.;:!?")
    return text


def parse_due(text, now=None):
    """(due datetime or None, the text with the time words removed). `now` is a naive local datetime.
    'in 20 minutes', 'in an hour', 'tomorrow', 'on friday', 'next monday', 'at 5', 'at 5:30 pm', 'noon',
    'this evening', 'end of day'. 'at 5' with no am/pm: 1-7 means pm; a past time with no day means tomorrow."""
    from datetime import datetime, timedelta

    now = now or datetime.now()
    rest = " ".join(text.split())
    low = rest.lower()
    m = _W_REL.search(low)
    if m:
        unit = m.group(2).rstrip("s") if m.group(2) not in ("mins", "hrs") else m.group(2)
        due = now + timedelta(seconds=_w_amount(m.group(1)) * W_UNITS[unit] + 30)   # + 30 s: round to the minute
        return due.replace(second=0, microsecond=0), _w_tidy(_w_cut(rest, m))
    day, hm, explicit_day = None, None, False
    m = _W_DAY.search(low)
    if m:
        word, nxt = m.group(2), bool(m.group(1))
        explicit_day = True
        if word == "today":
            day = now.date()
        elif word == "tonight":
            day, hm = now.date(), W_PARTS["tonight"]
        elif word == "tomorrow":
            day = now.date() + timedelta(days=1)
        elif word == "the day after tomorrow":
            day = now.date() + timedelta(days=2)
        else:
            ahead = (W_WEEKDAYS.index(word) - now.weekday()) % 7
            if nxt and ahead == 0:
                ahead = 7
            day = now.date() + timedelta(days=ahead)
        rest, low = _w_cut(rest, m), _w_cut(low, m)
    m = _W_CLOCK.search(low)
    if m:
        if m.group(1):
            h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        elif m.group(4):
            h, mi, ampm = int(m.group(4)), 0, m.group(5)
        else:
            h, mi, ampm = int(m.group(6)), 0, None
        if h <= 24 and mi < 60:
            if ampm:
                h = h % 12 + (12 if ampm.startswith("p") else 0)
            elif 1 <= h <= 7:
                h += 12
            elif 8 <= h <= 11 and day in (None, now.date()) and now.replace(hour=h, minute=mi) <= now:
                h += 12                 # "at 9" said at 10 am means 9 pm
            hm = (h % 24, mi)
            rest, low = _w_cut(rest, m), _w_cut(low, m)
    else:
        m = _W_NAMED.search(low)
        if m:
            word = m.group(1) or m.group(2)
            hm = (12, 0) if word in ("noon", "midday") else (23, 59) if word == "midnight" else \
                W_PARTS[word] if word else (18, 0)
            if "tomorrow" in m.group(0) and day is None:
                day, explicit_day = now.date() + timedelta(days=1), True
            rest, low = _w_cut(rest, m), _w_cut(low, m)
    if day is None and hm is None:
        return None, _w_tidy(rest)
    if day is None:
        day = now.date()
    due = datetime.combine(day, datetime.min.time()).replace(hour=(hm or W_DEFAULT_TIME)[0],
                                                             minute=(hm or W_DEFAULT_TIME)[1])
    if due <= now and not explicit_day:
        due += timedelta(days=1)
    return due, _w_tidy(rest)


def say_clock(due):
    h = due.hour % 12 or 12
    return f"{h}{f':{due.minute:02d}' if due.minute else ''} {'AM' if due.hour < 12 else 'PM'}"


def say_due(due, now=None):
    """'in 20 minutes', 'today at 5 PM', 'tomorrow at 9 AM', 'on Friday at 5 PM', '20 minutes ago'."""
    from datetime import datetime

    now = now or datetime.now()
    delta = (due - now).total_seconds()
    if 0 <= delta < 3600:
        mins = max(1, round(delta / 60))
        return f"in {mins} minute{'s' if mins != 1 else ''}"
    if -3600 < delta < 0:
        mins = max(1, round(-delta / 60))
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    days = (due.date() - now.date()).days
    if days == 0:
        return f"today at {say_clock(due)}"
    if days == 1:
        return f"tomorrow at {say_clock(due)}"
    if days == -1:
        return f"yesterday at {say_clock(due)}"
    if 1 < days < 7:
        return f"on {W_WEEKDAYS[due.weekday()].title()} at {say_clock(due)}"
    return f"on {due.day} {due.strftime('%B')} at {say_clock(due)}"


class TaskList:
    """The to-do list in a JSON file (TASKS_FILE), written atomically. Tasks: {id, title, due (ISO or None),
    created, done, done_at, reminded: ["soon", "due", "overdue"]}. Done tasks are kept TASKS_KEEP_DONE_DAYS."""

    def __init__(self, path=None, clock=None):
        from datetime import datetime

        self.path = Path(path) if path else TASKS_FILE
        self.clock = clock or datetime.now
        self.lock = threading.Lock()
        self.tasks, self.next_id, self.error = [], 1, ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.tasks = [t for t in data.get("tasks", []) if isinstance(t, dict) and t.get("title")]
            self.next_id = max([int(data.get("next_id", 1))] + [t["id"] + 1 for t in self.tasks])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = f"could not read {self.path} ({exc}) - starting an empty list; the file is kept as .bad"
            log(f"[tasks] {self.error}")
            try:
                self.path.replace(self.path.with_suffix(".bad"))
            except OSError:
                pass

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"next_id": self.next_id, "tasks": self.tasks}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)          # atomic: a power cut leaves the old or the new file, never half
            self.error = ""
        except OSError as exc:
            self.error = f"could not save {self.path}: {exc}"
            log(f"[tasks] {self.error}")

    @staticmethod
    def _dt(value):
        from datetime import datetime
        return datetime.fromisoformat(value) if value else None

    def add(self, text):
        """Add a task from plain words ('call mom at 6pm'). Returns (task, reply)."""
        due, title = parse_due(text, self.clock())
        title = title[:TASKS_MAX_TITLE].strip()
        if not title:
            return None, "What should the task be? e.g. 'todo buy milk by friday'"
        with self.lock:
            self._prune()
            if sum(not t["done"] for t in self.tasks) >= TASKS_MAX:
                return None, f"The list is full ({TASKS_MAX} open tasks) - finish or remove some first"
            t = {"id": self.next_id, "title": title, "due": due.isoformat(timespec="minutes") if due else None,
                 "created": self.clock().isoformat(timespec="seconds"), "done": False, "done_at": None, "reminded": []}
            self.next_id += 1
            self.tasks.append(t)
            self._save()
        when = f", {say_due(due, self.clock())}" if due else ""
        return t, f"Added #{t['id']}: {title}{when}"

    def find(self, ref, include_done=False):
        """'#3' / '3' or a few words of the title -> the task (or None). Words: the open task whose title contains
        all of them, newest first."""
        ref = ref.strip().lower().lstrip("#")
        with self.lock:
            pool = [t for t in self.tasks if include_done or not t["done"]]
            if ref.isdigit():
                return next((t for t in pool if t["id"] == int(ref)), None)
            words = [w for w in re.findall(r"[a-z0-9']+", ref) if w not in ("the", "a", "an", "my", "task", "to")]
            hits = [t for t in pool if words and all(w in t["title"].lower() for w in words)]
            return hits[-1] if hits else None

    def complete(self, ref, done=True):
        t = self.find(ref, include_done=not done)
        if t is None:
            return f"No {'open ' if done else ''}task matches '{ref}' ('tasks' lists them)"
        with self.lock:
            t["done"], t["done_at"] = done, self.clock().isoformat(timespec="seconds") if done else None
            self._save()
        return f"{'Done' if done else 'Reopened'}: #{t['id']} {t['title']}"

    def remove(self, ref):
        t = self.find(ref, include_done=True)
        if t is None:
            return f"No task matches '{ref}'"
        with self.lock:
            self.tasks = [x for x in self.tasks if x["id"] != t["id"]]
            self._save()
        return f"Removed #{t['id']} {t['title']}"

    def clear_done(self):
        with self.lock:
            n = sum(t["done"] for t in self.tasks)
            self.tasks = [t for t in self.tasks if not t["done"]]
            self._save()
        return f"Removed {n} finished task{'s' if n != 1 else ''}"

    def _prune(self):
        from datetime import timedelta
        cutoff = self.clock() - timedelta(days=TASKS_KEEP_DONE_DAYS)
        self.tasks = [t for t in self.tasks if not (t["done"] and self._dt(t["done_at"]) and self._dt(t["done_at"]) < cutoff)]

    def open_tasks(self):
        """Open tasks, the ones with a deadline first (soonest first), then the rest by number."""
        with self.lock:
            out = [dict(t) for t in self.tasks if not t["done"]]
        return sorted(out, key=lambda t: (t["due"] is None, t["due"] or "", t["id"]))

    def describe(self):
        now = self.clock()
        out = []
        for t in self.open_tasks():
            due = self._dt(t["due"])
            out.append({"id": t["id"], "title": t["title"], "due": t["due"],
                        "when": say_due(due, now) if due else "", "overdue": bool(due and due < now)})
        with self.lock:
            done = [{"id": t["id"], "title": t["title"]} for t in self.tasks if t["done"]][-5:]
        return {"open": out, "done": done, "file": str(self.path), "error": self.error}

    def lines(self, limit=12):
        tasks = self.describe()["open"]
        if not tasks:
            return "No open tasks. Add one: 'todo buy milk by friday' or 'remind me in 20 minutes to stretch'"
        rows = [f"  #{t['id']} {t['title']}" + (f" - {'OVERDUE, ' if t['overdue'] else ''}{t['when']}" if t["when"] else "")
                for t in tasks[:limit]]
        more = f"\n  ... and {len(tasks) - limit} more" if len(tasks) > limit else ""
        return f"Open tasks ({len(tasks)}):\n" + "\n".join(rows) + more

    def reminders_due(self):
        """[(task, kind)] to announce now: 'soon' (15 min before, only if it was added earlier than that),
        'due', 'overdue' (1 h after). Each kind once per task."""
        from datetime import timedelta
        now = self.clock()
        out = []
        with self.lock:
            for t in self.tasks:
                if t["done"] or not t["due"]:
                    continue
                due, created, said = self._dt(t["due"]), self._dt(t["created"]), t["reminded"]
                if now >= due + timedelta(minutes=TASKS_OVERDUE_MIN):
                    kind = "overdue"
                elif now >= due:
                    kind = "due"
                elif now >= due - timedelta(minutes=TASKS_SOON_MIN) and created <= due - timedelta(minutes=TASKS_SOON_MIN):
                    kind = "soon"
                else:
                    continue
                if kind not in said:
                    out.append((dict(t), kind))
        return out

    def mark_reminded(self, task_id, kind):
        with self.lock:
            for t in self.tasks:
                if t["id"] == task_id:
                    # a later kind also covers the earlier ones (no "soon" after "due" was said)
                    order = ["soon", "due", "overdue"]
                    t["reminded"] = sorted(set(t["reminded"]) | set(order[:order.index(kind) + 1]), key=order.index)
            self._save()


class Reminders:
    """Checks the list every TASKS_CHECK_S and announces what is due: the OLED (text + face), the Activity log,
    and the assistant chat (so a dashboard with 'Speak replies' ticked says it out loud)."""

    def __init__(self, robot, tasks):
        self.robot, self.tasks = robot, tasks
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="reminders").start()

    def _run(self):
        while not self._stop.wait(TASKS_CHECK_S):
            try:
                for t, kind in self.tasks.reminders_due():
                    text = {"soon": f"Heads up: {t['title']} in {TASKS_SOON_MIN} minutes.",
                            "due": f"Reminder: {t['title']}.",
                            "overdue": f"Still open: {t['title']} - it was due an hour ago."}[kind]
                    self.robot.announce(text, "focused" if kind == "soon" else "happy" if kind == "due" else "sad",
                                        sound="chime")
                    self.tasks.mark_reminded(t["id"], kind)
            except Exception as exc:
                log(f"[tasks] reminder check failed: {type(exc).__name__}: {exc}")

    def close(self):
        self._stop.set()


# =====================================================================
# Go to an object (24 Nov 2026): 'go to the cup' - look around, face it, drive up to it in short legs
# =====================================================================
#
# A simple, safe stand-in for run_prototype deskbot/navigation/ (A*, cost maps): no path planning. It uses the
# object map, gyro turns and encoder-measured drives, and every leg goes through Robot.execute, so all safety
# rules apply. Anything in the way ends it with the reason; any command from a person cancels it.

class Navigator:
    def __init__(self, robot):
        self.robot = robot
        self.state = {"active": False, "target": None, "step": "", "result": "", "x": None, "y": None}
        self._run_id = 0

    def info(self):
        return dict(self.state)

    def busy(self):
        return self.state["active"]

    def start(self, target, face_only=False):
        """target: an object label, or 'home' (where the map started). face_only ('find'): look around and turn
        to face it, no driving. Returns the reply at once; the work happens in its own thread."""
        r = self.robot
        target = target.strip().lower()
        for w in ("the ", "my ", "a ", "an "):
            target = target.removeprefix(w)
        if not target:
            return "Use: go to <thing> (e.g. 'go to the cup') or 'go home'"
        if r.lift["lifted"]:
            return "Not moving: robot is lifted - put it down on the desk"
        if target != "home" and (r.detector is None or not r.detector.model):
            return f"I can't look for things: object detection is not running ({r.detector.status if r.detector else 'off'})"
        if face_only and target == "home":
            return "Use: find <thing> (e.g. 'find the cup')"
        self._run_id += 1
        self.state.update(active=True, target=target, step="starting", result="", x=None, y=None)
        threading.Thread(target=self._run, args=(target, self._run_id, r.user_cmds, face_only), daemon=True,
                         name="navigator").start()
        if face_only:
            return f"Looking for the {target} ('stop' cancels)"
        return f"Going to {'where I started' if target == 'home' else 'the ' + target} ('stop' cancels)"

    # ----- helpers (all return a reason string to give up, or '' to carry on) -----
    def _cancelled(self, run_id, user_cmds):
        r = self.robot
        if run_id != self._run_id or r.user_cmds != user_cmds:
            return "cancelled"
        if r.lift["lifted"]:
            return "I was picked up"
        return ""

    def _do(self, cmd, run_id, user_cmds):
        """Run one move, wait for it to end and settle. '' when it ran to the end, else why it did not."""
        r = self.robot
        reply = r.execute(cmd, source="nav")
        if reply.startswith(("Not moving", "Bad", "Angle", "Use")):
            return reply.removeprefix("Not moving: ")
        t0 = time.monotonic()
        time.sleep(0.1)
        while r.move is not None:
            why = self._cancelled(run_id, user_cmds)
            if why:
                r.stop()
                return why
            if time.monotonic() - t0 > MAX_DURATION + 2:
                r.stop()
                return "the move did not finish"
            time.sleep(0.03)
        time.sleep(NAV_SETTLE_S)
        return r.blocked                               # set when a safety rule ended the move early

    def _look(self, label, run_id, user_cmds):
        """Stand still while the camera adds a few frames to the object map, then the landmark (or None)."""
        t_end = time.monotonic() + NAV_LOOK_S
        while time.monotonic() < t_end:
            if self._cancelled(run_id, user_cmds):
                return None
            time.sleep(0.05)
        return self.robot.objects.find(label, self.robot.pose)

    def _target(self, target):
        """(x, y, radius, label) of the goal now, or None."""
        r = self.robot
        if target == "home":
            return 0.0, 0.0, 0.0, "start"
        o = r.objects.find(target, r.pose)
        return (o["x"], o["y"], o["radius"], o["label"]) if o else None

    # ----- the run -----
    def _run(self, target, run_id, user_cmds, face_only=False):
        r = self.robot
        result = "?"
        try:
            result = self._go(target, run_id, user_cmds, face_only)
        except Exception as exc:
            result = f"failed: {type(exc).__name__}: {exc}"
            log(f"[nav] {result}")
        finally:
            if run_id == self._run_id:
                self.state.update(active=False, step="", result=result)
                r.event(f"Go to {target}: {result}")
                if r.oled is not None:
                    r.oled.mood("happy" if result.startswith(("arrived", "found")) else "sad", 3.0)

    def _go(self, target, run_id, user_cmds, face_only=False):
        r = self.robot
        st = self.state
        goal = self._target(target)
        if goal is None:                                       # 1. not on the map yet: look around
            for i in range(NAV_SCAN_STEPS):
                st["step"] = f"looking for the {target} ({i * NAV_SCAN_DEG} deg turned)"
                found = self._look(target, run_id, user_cmds)
                if found:
                    goal = self._target(target)
                    break
                why = self._cancelled(run_id, user_cmds) or self._do(f"turn {NAV_SCAN_DEG}", run_id, user_cmds)
                if why:
                    return f"stopped while looking: {why}"
            else:
                return f"couldn't find a {target} after looking all around"
            if goal is None:
                return f"lost sight of the {target}"
        for leg in range(NAV_MAX_LEGS):                        # 2. face it, drive a short leg, look again
            why = self._cancelled(run_id, user_cmds)
            if why:
                return why
            gx, gy, rad, label = goal
            st.update(x=gx, y=gy)
            x, y, th = r.pose
            dist = math.hypot(gx - x, gy - y)
            bearing = (math.degrees(math.atan2(gy - y, gx - x) - th) + 180) % 360 - 180
            # stop with the object's near side NAV_STANDOFF_M in front of the front sonar
            to_go = dist - (rad + SONAR_MOUNT["front"][1] + NAV_STANDOFF_M if target != "home" else 0.0)
            if face_only:
                if abs(bearing) > 3:
                    st["step"] = f"turning {bearing:+.0f} deg to face the {label}"
                    why = self._do(f"turn {bearing:.0f}", run_id, user_cmds)
                    if why:
                        return f"stopped while turning: {why}"
                return f"found: the {label}, {dist * 100:.0f} cm away - I'm facing it"
            if to_go <= NAV_ARRIVE_M:
                if target == "home":
                    return f"arrived back where I started ({dist * 100:.0f} cm off)"
                return f"arrived: {label} {max(0.0, dist - rad - SONAR_MOUNT['front'][1]) * 100:.0f} cm in front of me"
            if abs(bearing) > NAV_FACE_DEG:
                st["step"] = f"turning {bearing:+.0f} deg to face the {label}"
                why = self._do(f"turn {bearing:.0f}", run_id, user_cmds)
                if why:
                    return f"stopped while turning: {why}"
                if target != "home":
                    self._look(target, run_id, user_cmds)      # a straight-on view places it best
                goal = self._target(target) or goal
                continue
            step = min(NAV_LEG_M, to_go)
            st["step"] = f"driving {step * 100:.0f} cm towards the {label} ({to_go * 100:.0f} cm to go)"
            why = self._do(f"forward {max(1, round(step * 100))}cm", run_id, user_cmds)
            if why:
                front = r.readings["sonar"].get("front")
                if ("front obstacle" in why and target != "home" and abs(bearing) < 12 and front is not None
                        and front <= dist - rad - SONAR_MOUNT["front"][1] + 0.08):
                    return f"arrived: {label} {front * 100:.0f} cm in front of me (the sonar stop)"
                return f"stopped: {why} - something is in the way (I don't plan routes around things)"
            if target != "home":
                self._look(target, run_id, user_cmds)
                fresh = self._target(target)
                if fresh is None:
                    return f"lost sight of the {target}"
                goal = fresh
        return f"gave up after {NAV_MAX_LEGS} steps"


# =====================================================================
# Assistant (24 Nov 2026): typed or spoken questions -> Groq (first) / Claude (fallback) / offline rules
# =====================================================================
#
# Ported from run_prototype deskbot/pro/groq_brain.py, assistant/brain.py, assistant/claude_http.py and
# assistant/stt.py, without the tool loop, sounds and profiles. Standard library only (urllib + json).
#
#   ask <text>   ->  1. offline rules for plain commands ("turn left", "stop", "take a photo"): instant, free
#                    2. Groq chat (GROQ_API_KEY), JSON mode         -> {"speech", "mood", "commands"}
#                    3. Claude (ANTHROPIC_API_KEY), structured output -> same JSON
#                    4. nothing reachable: an offline answer that says why
#   The reply is printed, shown on the OLED (text + a face), spoken by the dashboard's browser (laptop speaker),
#   and its "commands" run one after another through Robot.execute, so every safety rule still applies.

def load_secrets(files=None):
    """Read KEY=VALUE lines from the first secrets.env found into os.environ (values already set in the
    environment win). Returns the file used, or None. Values are never logged or sent to the browser."""
    for path in files or SECRETS_FILES:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) and value:
                os.environ.setdefault(key, value)
        return path
    return None


class AiError(Exception):
    """A brain failed; the message says why in plain words (shown on the dashboard, never contains a key)."""


def _http_json(url, body, headers, timeout=AI_TIMEOUT_S, raw=None, ctype="application/json"):
    import urllib.error
    import urllib.request

    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": ctype, "User-Agent": "deskbot-simplified/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail)["error"]["message"][:200]
        except (ValueError, KeyError, TypeError):
            pass
        why = {401: "the API key was rejected", 403: "the key may not use this", 404: "wrong model name",
               429: "rate limited - wait a moment"}.get(exc.code, "the service had an error" if exc.code >= 500 else "")
        raise AiError(f"HTTP {exc.code}{' (' + why + ')' if why else ''}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AiError(f"can't reach {url.split('/')[2]} ({getattr(exc, 'reason', exc)}) - no internet?") from exc


def parse_reply_json(text):
    """The JSON object in a model's reply (a ``` fence or chatter around it is tolerated), or None."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        data = json.loads(text[a:b + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


AI_SYSTEM = """You are the voice and brain of a small two-wheeled robot that lives on a desk. You hear the user
through speech-to-text (expect transcription mistakes; guess the intended words) or they type to you.

Your reply is shown on the robot's tiny 128x64 screen and spoken aloud by a laptop, so "speech" is 1-2 short,
natural sentences (under 120 characters if you can). No emoji, markdown, lists or URLs.

You can move. Put robot commands in "commands" (run in order) ONLY when the user asks for movement or an action,
or when it clearly fits (a little wiggle when the user is excited). Otherwise use []. Allowed commands, exactly:
  "forward <N>cm"             drive forward N centimetres, 2 to 50 (prefer this when the user gives a distance)
  "back <N>cm"                drive backward N centimetres
  "forward <seconds 0.2-3>"   drive forward for a time (about 12 cm per second at the usual speed)
  "back <seconds 0.2-3>"      drive backward for a time
  "turn <degrees>"            turn on the spot, + = left, - = right, 5 to 360
  "spin"                      one full turn on the spot
  "stop"                      stop now
  "photo"                     take a photo with the camera
  "go to <thing>"             drive up to a thing the camera can recognise (e.g. "go to cup"); it looks around
                              by itself if needed. Use a COCO object name: cup, bottle, book, cell phone ...
  "go home"                   drive back to where the robot started
  "remind me <when> to <what>"  set a reminder, e.g. "remind me in 20 minutes to drink water", "remind me at 5pm
                              to call mom" (in, at, tomorrow, on friday, this evening ...)
  "todo <task> [when]"        add to the user's task list, e.g. "todo buy milk by friday"
  "done <#number>"            mark a task done (the open tasks are in the robot context with their numbers)
  "focus <minutes>"           start a focus (Pomodoro) session, default 25; "focus stop" ends it
  "face me"                   turn to face the user once; "face me on" keeps facing them, "face me off" stops
  "rps"                       start a game of rock paper scissors (first to two; the user shows a hand gesture)
  "dance"                     play a random song and dance to it (~30 s); "dance <song>" a given one; "dance stop"
Directions are from the robot's point of view; the user usually sits in front of it, facing it. The robot's
own safety rules stop it at desk edges and obstacles by themselves, so you never need to check for them, but
if the context says it is blocked or lifted, say so instead of pretending to move.

"mood" sets the face on the screen: one of happy, sad, angry, scared, focused, sleepy, normal.

Answer with exactly ONE JSON object and nothing else:
{"speech": "...", "mood": "happy", "commands": ["turn 90", "forward 1"]}

Personality: cheerful, curious and a little cheeky, but always helpful and kind."""

AI_SCHEMA = {
    "type": "object",
    "properties": {
        "speech": {"type": "string", "description": "What the robot says: 1-2 short sentences."},
        "mood": {"type": "string", "enum": list(AI_MOODS)},
        "commands": {"type": "array", "items": {"type": "string"},
                     "description": "Robot commands in order, from the allowed list. [] if no action."},
    },
    "required": ["speech", "mood", "commands"],
    "additionalProperties": False,
}


class GroqBrain:
    """Groq's OpenAI-compatible chat API, JSON mode. Model AI_GROQ_MODEL (gpt-oss: reasoning_effort low)."""
    name = "groq"

    def __init__(self, model=AI_GROQ_MODEL):
        self.model = model

    def key(self):
        return os.environ.get("GROQ_API_KEY", "")

    def think(self, system, history, user):
        messages = [{"role": "system", "content": system}]
        for q, a in history:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a)}]
        messages.append({"role": "user", "content": user})
        body = {"model": self.model, "messages": messages, "temperature": 0.6, "max_completion_tokens": 1000,
                "response_format": {"type": "json_object"}}
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        out = _http_json(f"{GROQ_URL}/chat/completions", body, {"Authorization": f"Bearer {self.key()}"})
        try:
            text = out["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AiError(f"unexpected reply from Groq: {str(out)[:120]}") from exc
        data = parse_reply_json(text)
        if data is None:
            raise AiError(f"Groq did not answer in JSON: {text[:80]!r}")
        return data


class ClaudeBrain:
    """Claude Messages API over plain HTTPS. Structured output (output_config.format) forces the JSON reply;
    effort "low" keeps spoken answers quick. Refusals fall back server-side ("fallbacks": "default")."""
    name = "claude"

    def __init__(self, model=AI_CLAUDE_MODEL):
        self.model = model

    def key(self):
        return os.environ.get("ANTHROPIC_API_KEY", "")

    def think(self, system, history, user):
        messages = []
        for q, a in history:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a)}]
        messages.append({"role": "user", "content": user})
        body = {"model": self.model, "max_tokens": 4000, "system": system, "messages": messages,
                "fallbacks": "default",
                "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": AI_SCHEMA}}}
        out = _http_json(CLAUDE_URL, body, {"x-api-key": self.key(), "anthropic-version": "2026-10-21",
                                            "anthropic-beta": "server-side-fallback-2026-07-01"})
        if out.get("stop_reason") == "refusal":
            return {"speech": "Sorry, I can't help with that one.", "mood": "sad", "commands": []}
        text = "".join(b.get("text", "") for b in out.get("content") or [] if b.get("type") == "text")
        data = parse_reply_json(text)
        if data is None:
            raise AiError(f"Claude stopped early ({out.get('stop_reason')}) without a JSON reply")
        return data


def check_ai_command(cmd):
    """A robot command from the AI as the exact text to run, or raise ValueError. Only AI_COMMANDS, with
    their numbers clamped to safe ranges; anything else (calibrate, quit, oled ..., lift off) is refused."""
    parts = str(cmd).strip().lower().split()
    if parts[:1] in (["go"], ["goto"]) and len(parts) > 1:
        thing = " ".join(w for w in parts[1:] if w not in ("to", "the", "my", "a", "an"))
        if not re.fullmatch(r"[a-z ]{2,30}", thing):
            raise ValueError(f"not something to go to: {thing!r}")
        return "go home" if thing in ("home", "back home") else f"go to {thing}"
    if not parts or parts[0] not in AI_COMMANDS:
        raise ValueError(f"not an allowed command: {str(cmd)[:40]!r}")
    if parts[0] in ("remind", "todo", "done"):
        rest = " ".join(str(cmd).strip().split()[1:])[:150]
        if not rest or not re.fullmatch(r"[\w\s.,:'#!?&()/-]+", rest):
            raise ValueError(f"bad {parts[0]} text: {rest[:40]!r}")
        return f"{parts[0]} {rest}"
    if parts[0] == "rps":
        return "rps stop" if parts[1:2] == ["stop"] else "rps"
    if parts[0] == "dance":
        if parts[1:2] in (["stop"], ["off"]):
            return "dance stop"
        song = " ".join(parts[1:]).removeprefix("to ").strip()
        if song and not re.fullmatch(r"[a-z0-9 '-]{1,40}", song):
            raise ValueError(f"bad song name: {song[:40]!r}")
        return "dance" + (f" {song}" if song and song != "random" else "")
    if parts[0] == "face":
        return "face me" + (" " + parts[-1] if parts[-1] in ("on", "off") else "")
    if parts[0] == "focus":
        if parts[1:2] in (["stop"], ["end"]):
            return "focus stop"
        mins = next((float(w) for w in parts[1:] if re.fullmatch(r"\d+(\.\d+)?", w)), FOCUS_DEFAULT_MIN)
        return f"focus {int(max(1, min(180, mins)))}"
    word, nums = parts[0], []
    for p in parts[1:]:
        try:
            v = float(p.rstrip("s°").removesuffix("deg").removesuffix("sec"))
        except ValueError:
            continue
        if math.isfinite(v):
            nums.append(v)
    if word in ("forward", "back"):
        try:
            d = parse_distance(parts[1:])
        except ValueError:
            d = AI_MAX_DRIVE_M
        if d:
            return f"{word} {max(0.02, min(AI_MAX_DRIVE_M, d)) * 100:.0f}cm"
        return f"{word} {max(0.2, min(AI_MAX_DRIVE_S, abs(nums[0]) if nums else 1.0)):.1f}"
    if word == "turn":
        if not nums or abs(nums[0]) < 1:
            raise ValueError("turn needs an angle")
        return f"turn {max(-360.0, min(360.0, nums[0])):.0f}"
    if word in ("left", "right"):              # the model sometimes says "left 45"
        deg = abs(nums[0]) if nums else 90.0
        return f"turn {min(360.0, deg) * (1 if word == 'left' else -1):.0f}"
    return word                                 # spin, stop, photo


# Offline rules: plain commands answered without any AI (instant, free, work with no internet).
_NUM = r"(\d+(?:\.\d+)?)"
OFFLINE_RULES = [       # anchored at the start: only commands match, never questions ("what's straight ahead?")
    (r"^(?:look|turn)\s+(?:at|to|towards)\s+me\b|^face\s+me$", lambda m: ("Here I am!", "happy", ["face me"])),
    (r"^(?:keep\s+(?:looking\s+at|facing|watching)|follow)\s+me\b", lambda m: ("I'll keep my eyes on you.", "happy", ["face me on"])),
    (r"^stop\s+(?:looking\s+at|facing|watching|following)\s+me\b", lambda m: ("Okay.", "normal", ["face me off"])),
    (r"^(?:go|come)\s+(?:back\s+)?home\b|^come\s+back\b", lambda m: ("Heading home.", "happy", ["go home"])),
    (r"^(?:go|drive|move)\s+(?:over\s+)?to\s+(?:the\s+|my\s+|a\s+)?([a-z]{2,15}(?: [a-z]{2,15})?)\s*$",
     lambda m: (f"Off to the {m.group(1)}!", "happy", [f"go to {m.group(1)}"])),
    (rf"^(?:go|drive|move|roll)?\s*(forward|ahead|straight|back(?:ward)?s?)\b.*?{_NUM}\s*(cm|centimet\w*|mm|millimet\w*|m|met\w*)\b",
     lambda m: ("Here I go!", "happy", [f"{'back' if m.group(1).startswith('back') else 'forward'} "
                                        f"{m.group(2)}{'cm' if m.group(3).startswith('c') else 'mm' if m.group(3).startswith('mi') or m.group(3) == 'mm' else 'm'}"])),
    (r"^(stop|halt|freeze|stay|wait)\b", lambda m: ("Stopping.", "normal", ["stop"])),
    (rf"^(?:go|drive|move|roll)?\s*(forward|ahead|straight|back(?:ward)?s?)\b(?:.*?{_NUM}\s*(?:s|sec|second))?",
     lambda m: ("Here I go!", "happy", [f"{'back' if m.group(1).startswith('back') else 'forward'} "
                                        f"{m.group(2) or 1}"])),
    (rf"^(?:turn|rotate)\s+(?:to\s+(?:the\s+|your\s+)?)?(left|right)(?:.*?{_NUM})?|^(?:turn|rotate)\s+(?:by\s+)?{_NUM}",
     lambda m: ("Turning.", "focused",
                [f"turn {float(m.group(3))}" if m.group(3) else
                 f"turn {float(m.group(2) or 90) * (1 if m.group(1) == 'left' else -1)}"])),
    (r"^(?:spin|turn\s+around|do\s+a\s+(?:spin|360))\b", lambda m: ("Wheee!", "happy", ["spin"])),
    (r"^(?:stop|quit|end)\s+dancing\b", lambda m: ("Okay, show's over.", "normal", ["dance stop"])),
    (r"^(?:(?:do\s+a|let'?s|can\s+you|please)\s+)?(dance|boogie|wiggle|celebrate|party)\b|^play\s+(?:some\s+|a\s+)?(?:music|song)\b",
     lambda m: ("Watch my moves!", "happy", ["dance"])),
    (r"^(?:take|snap|grab)\b.*\b(photo|picture|pic|selfie)\b|^(photo|picture)$",
     lambda m: ("Say cheese!", "happy", ["photo"])),
]


def offline_tasks(text, tasks):
    """Task-list sentences answered offline from the ORIGINAL text (keeps '5:30'), or None."""
    raw = re.sub(r"^\W*(?:(?:hey|hi|ok|okay)\W+)?(?:robot\W+|buddy\W+)?(?:please\s+|can you\s+|could you\s+)?", "",
                 text.strip(), flags=re.I)
    m = re.match(r"remind me\b(.*)", raw, re.I)
    if m:
        t, reply = tasks.add(m.group(1))
        if t is None:
            return reply, "sad", []
        when = say_due(TaskList._dt(t["due"]), tasks.clock()) if t["due"] else ""
        return (f"Okay, I'll remind you {when} to {t['title']}." if when else
                f"Okay, {t['title']} is on your list, but I didn't catch a time."), "happy", []
    m = re.match(r"(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:my\s+|the\s+)?(?:[a-z-]+\s+)?(?:list|tasks)\b(.*)$", raw, re.I)
    if m:
        t, reply = tasks.add(f"{m.group(1)} {m.group(2)}")
        return (f"Added {t['title']} to your list." if t else reply), "happy", []
    if re.match(r"(?:what(?:'s| is| are)\s+(?:on\s+)?my\s+(?:to-?do\s+)?(?:list|tasks)|(?:list|read)\s+my\s+tasks)", raw, re.I):
        open_tasks = tasks.describe()["open"]
        if not open_tasks:
            return "Your list is empty.", "happy", []
        items = "; ".join(t["title"] + (f", {t['when']}" if t["when"] else "") for t in open_tasks[:5])
        more = f" And {len(open_tasks) - 5} more." if len(open_tasks) > 5 else ""
        return f"You have {len(open_tasks)}: {items}.{more}", "focused", []
    m = re.match(r"(?:i\s+)?(?:finished|did|done with|completed|mark)\s+(.+?)(?:\s+(?:as\s+)?done)?\W*$", raw, re.I)
    if m and tasks.find(m.group(1)):
        reply = tasks.complete(m.group(1))
        return f"Nice work! {reply}.", "happy", []
    return None


def offline_focus(text, focus):
    """Focus-timer sentences answered offline, or None."""
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    t = re.sub(r"^(?:hey|hi|ok|okay)?\s*(?:robot|buddy)?\s*(?:please\s+|can you\s+|let s\s+|lets\s+)?", "", t).strip()
    if re.match(r"(?:stop|end|cancel|quit)\s+(?:the\s+)?(?:focus|pomodoro)", t):
        return focus.stop(), "normal", []
    m = re.match(r"(?:start\s+)?(?:a\s+)?(?:focus|pomodoro|study)(?:\s+(?:mode|session|time))?(?:\s+for)?\s*(\d+)?\s*(?:min\w*)?$", t)
    if m and (t.startswith(("start", "focus", "pomodoro", "a ")) or m.group(1)):
        return focus.start(int(m.group(1)) if m.group(1) else FOCUS_DEFAULT_MIN).split(" (")[0], "focused", []
    if re.match(r"how am i doing|how s my focus|how is my focus|how much time (?:is )?left", t) and focus.mode != "idle":
        return focus.line(), "focused", []
    return None


def offline_game(text, robot):
    """Rock paper scissors by voice, offline: start, stop, and the moves while a game waits for one."""
    t = re.sub(r"[^a-z ]+", " ", text.lower()).split()
    g = getattr(robot, "rps", None)
    if g is None or not t:
        return None
    joined = " ".join(t)
    if re.search(r"\b(?:play|start|let s play|lets play)\b.*\brock\b.*\bpaper\b.*\bscissors\b|^rps$", joined):
        return g.start(), "happy", []
    if g.waiting():
        if re.search(r"\b(?:stop|end|quit)\b.*\b(?:game|playing)\b", joined):
            return g.stop(), "normal", []
        m = re.fullmatch(r"(?:i (?:choose|pick|play|go with|throw) )?(rock|paper|scissors)", joined)
        if m:                                                   # just the move, or "I choose paper"
            return g.play(m.group(1), "voice"), "focused", []
    return None


def offline_reply(text, robot=None):
    """(speech, mood, commands) for a plain command or a simple question, else None (the AI answers)."""
    if robot is not None and getattr(robot, "ideas", None) is not None:
        hit = offline_ideas(text, robot.ideas)
        if hit:
            return hit
    if robot is not None:
        hit = offline_game(text, robot)
        if hit:
            return hit
    if robot is not None and getattr(robot, "focus", None) is not None:
        hit = offline_focus(text, robot.focus)
        if hit:
            return hit
    if robot is not None and getattr(robot, "tasks", None) is not None:
        hit = offline_tasks(text, robot.tasks)
        if hit:
            return hit
    t = re.sub(r"[^a-z0-9.' ]+", " ", text.lower()).strip()
    t = re.sub(r"^(?:hey|hi|ok|okay)?\s*(?:robot|buddy)?[ ,]*(?:please\s+|can you\s+|could you\s+)?", "", t).strip()
    for pattern, make in OFFLINE_RULES:
        m = re.search(pattern, t)
        if m:
            return make(m)
    if re.fullmatch(r"(?:hello|hi|hey|good (?:morning|afternoon|evening))(?: there)?", t):
        return "Hello! What shall we do?", "happy", []
    if re.search(r"\bwhat\b.*\btime\b", t):
        return f"It's {time.strftime('%I:%M %p').lstrip('0')}.", "normal", []
    if re.search(r"\bwhat\b.*\b(?:date|day)\b", t):
        return f"Today is {time.strftime('%A, %d %B')}.", "normal", []
    if robot is not None and re.search(r"\bwhat\b.*\b(?:see|seeing|in front)\b|\blook\b", t):
        return robot.execute("see", source="assistant").replace("I see: ", "I see ") + ".", "focused", []
    return None


class Assistant:
    """One question at a time (a second 'ask' while thinking is refused, not queued)."""

    def __init__(self, robot, enabled=True, groq_model=AI_GROQ_MODEL, claude_model=AI_CLAUDE_MODEL):
        self.robot, self.enabled = robot, enabled
        self.secrets_from = load_secrets()
        self.brains = [GroqBrain(groq_model), ClaudeBrain(claude_model)]
        self.history = []                      # [(user text, reply dict)], newest last, AI turns only
        self.recent = []                       # last AI_RECENT exchanges for the dashboard
        self.errors = {}                       # brain name -> last error
        self.n = 0
        self.thinking = None                   # the question being worked on
        self._busy = threading.Lock()
        self._plan = 0                         # bumped by every new reply: an older command plan stops

    # ----- status -----
    def available(self):
        return [b for b in self.brains if b.key()] if self.enabled else []

    def info(self):
        brains = {b.name: {"model": b.model, "key": bool(b.key()), "error": self.errors.get(b.name, "")}
                  for b in self.brains}
        return {"enabled": self.enabled, "brains": brains, "stt": "groq" if os.environ.get("GROQ_API_KEY") else None,
                "secrets": str(self.secrets_from) if self.secrets_from else None, "thinking": self.thinking,
                "recent": self.recent[-AI_RECENT:], "last_id": self.n}

    def line(self):
        if not self.enabled:
            return "assistant: AI off (--no-ai): offline rules only"
        parts = []
        for b in self.brains:
            state = ("no key" if not b.key() else f"last error: {self.errors[b.name]}" if self.errors.get(b.name)
                     else "ready")
            parts.append(f"{b.name} ({b.model}): {state}")
        where = f"keys from {self.secrets_from}" if self.secrets_from else \
            f"no secrets.env found (looked in {', '.join(str(p) for p in SECRETS_FILES)})"
        return "assistant: " + " | ".join(parts) + f" | {where}"

    def announce(self, text, mood="happy"):
        """A message the robot starts itself (a reminder): shown in the chat and spoken like a reply."""
        self.n += 1
        self.recent = (self.recent + [{"id": self.n, "user": "", "source": "reminder", "speech": text, "mood": mood,
                                       "commands": [], "backend": "reminder", "ms": 0, "errors": [],
                                       "t": time.strftime("%H:%M:%S")}])[-AI_RECENT:]

    # ----- a question -----
    def context(self):
        s = self.robot.status()
        sonar = ", ".join(f"{k} {'--' if v is None else f'{v * 100:.0f} cm'}" for k, v in s["sonar"].items())
        floor = ", ".join(f"{k} {'desk' if v else 'NO desk' if v is not None else '?'}" for k, v in s["floor"].items())
        lines = [f"time: {time.strftime('%A %d %B %Y, %H:%M')}", f"mode: {s['mode']}, speed {s['speed']:.1f}",
                 f"sonar distances: {sonar}", f"edge sensors: {floor}"]
        if s["move"]:
            lines.append(f"moving: {s['move']['label']}")
        if s["blocked"]:
            lines.append(f"last stop reason: {s['blocked']}")
        if (s.get("lift") or {}).get("lifted"):
            lines.append("the robot is LIFTED off the desk: it cannot drive")
        dets = (s.get("vision") or {}).get("detections") or []
        if dets:
            lines.append("camera sees: " + ", ".join(
                f"{d['label']} ({abs(d['bearing_deg']):.0f} deg {'left' if d['bearing_deg'] > 0 else 'right'})"
                for d in dets[:6]))
        elif s.get("vision"):
            lines.append("camera sees: nothing it recognises")
        if self.robot.phone is not None and self.robot.phone.info()["phone"]:
            lines.append(f"owner's phone (Bluetooth): {self.robot.phone.state}")
        if self.robot.focus is not None and self.robot.focus.mode != "idle":
            lines.append(self.robot.focus.line())
        if self.robot.tasks is not None:
            open_tasks = self.robot.tasks.describe()["open"]
            lines.append("open tasks: " + ("; ".join(
                f"#{t['id']} {t['title']}" + (f" ({'OVERDUE, ' if t['overdue'] else ''}{t['when']})" if t["when"] else "")
                for t in open_tasks[:10]) or "none"))
        objs = self.robot.objects.describe(self.robot.pose)
        if objs:
            lines.append("remembered on the map: " + "; ".join(f"{o['label']} {where_words(o)}" for o in objs[:8]))
        return "\n".join(lines)

    def ask(self, text, source="typed"):
        text = " ".join(str(text).split())[:500]
        if not text:
            return "Use: ask <question or command>, e.g. 'ask what can you see?'  ('assistant' shows the status)"
        if not self._busy.acquire(blocking=False):
            return f"Still thinking about \"{self.thinking}\" - one question at a time"
        try:
            self.thinking = text
            t0 = time.perf_counter()
            local = offline_reply(text, self.robot)
            errors, backend = [], "offline"
            web = ""                                  # facts fetched for this question (weather, joke, ...)
            apis = self.robot.apis
            if not local and apis is not None:
                want = apis.intent(text)
                if want is None and not self.available():   # no AI: "who is X" / "what is X" -> Wikipedia
                    m = re.match(r"^\s*(?:who|what)\s+(?:is|was|are|were)\s+(?:a\s+|an\s+|the\s+)?(.+?)\??$", text, re.I)
                    want = ("wikipedia", (m.group(1),)) if m else None
                if want is not None:
                    try:
                        web = apis.run(*want)
                    except ApiError as exc:
                        web_err = str(exc)
                        web = f"(could not get it: {web_err})"
                    else:
                        web_err = ""
                    if not self.available():
                        local = (f"Sorry, {web_err}." if web_err else web, "sad" if web_err else "happy", [])
                        backend = "web API"
            if local:
                reply = {"speech": local[0], "mood": local[1], "commands": local[2]}
                backend = backend if backend == "web API" else "offline rules"
            else:
                reply = None
                for brain in self.available():
                    try:
                        facts = f"\nfetched for this question (use it in your answer): {web}" if web else ""
                        reply = brain.think(AI_SYSTEM, self.history[-AI_HISTORY:],
                                            f"<robot_context>\n{self.context()}{facts}\n</robot_context>\n\nUser said: {text}")
                        backend = f"{brain.name} {brain.model}"
                        self.errors.pop(brain.name, None)
                        break
                    except AiError as exc:
                        self.errors[brain.name] = str(exc)
                        errors.append(f"{brain.name}: {exc}")
                        log(f"[assistant] {brain.name} failed: {exc}")
                if reply is None:
                    why = ("the AI is off (--no-ai)" if not self.enabled else
                           "I have no AI key (GROQ_API_KEY / ANTHROPIC_API_KEY in secrets.env)" if not errors else
                           "I can't reach my AI brain right now")
                    reply = {"speech": f"Sorry, {why}. I can still drive, turn, spin, stop and take photos.",
                             "mood": "sad", "commands": []}
            speech = " ".join(str(reply.get("speech") or "Hmm.").split())[:300]
            mood = reply.get("mood") if reply.get("mood") in AI_MOODS else "normal"
            commands, refused = [], []
            for c in (reply.get("commands") or [])[:AI_MAX_COMMANDS] if isinstance(reply.get("commands"), list) else []:
                try:
                    commands.append(check_ai_command(c))
                except ValueError as exc:
                    refused.append(str(exc))
            ms = round((time.perf_counter() - t0) * 1000)
            if backend != "offline rules" and backend != "offline":
                self.history.append((text, {"speech": speech, "mood": mood, "commands": commands}))
                del self.history[:-AI_HISTORY]
            self.n += 1
            entry = {"id": self.n, "user": text, "source": source, "speech": speech, "mood": mood,
                     "commands": commands, "backend": backend, "ms": ms, "errors": errors + refused,
                     "t": time.strftime("%H:%M:%S")}
            self.recent = (self.recent + [entry])[-AI_RECENT:]
            self.robot.event(f"Assistant ({backend}, {ms} ms): {speech}")
            if self.robot.oled is not None:
                self.robot.oled.mood(mood, 4.0 + len(speech) / 15)
                self.robot.oled.say(speech, min(12.0, 3.0 + len(speech) / 12))
            out = f"Robot: {speech}  [{backend}, {ms} ms]"
            if commands:
                self._plan += 1
                threading.Thread(target=self._run_plan, args=(commands, self._plan), daemon=True,
                                 name="assistant-plan").start()
                out += f"\n  doing: {', '.join(commands)}"
            for e in errors + refused:
                out += f"\n  ({e})"
            return out
        finally:
            self.thinking = None
            self._busy.release()

    def _run_plan(self, commands, plan):
        """Run the AI's commands one after another. Stops at a refused or safety-stopped move, when the user
        types/clicks any command (Robot.user_cmds changes), or when a newer reply starts its own plan."""
        r = self.robot
        user_cmds = r.user_cmds
        for i, cmd in enumerate(commands):
            if plan != self._plan or r.user_cmds != user_cmds:
                return
            reply = r.execute(cmd, source="assistant")
            if reply.startswith(("Not moving", "Could NOT", "No camera")):
                r.event(f"Assistant plan stopped at '{cmd}': {reply}")
                return
            deadline = time.monotonic() + MAX_DURATION + 2
            time.sleep(0.1)
            if cmd.startswith("go to") or cmd == "go home":
                deadline = time.monotonic() + 120          # a trip takes many moves
            while (r.move is not None or r.nav.busy()) and time.monotonic() < deadline:
                if plan != self._plan or r.user_cmds != user_cmds:
                    return
                time.sleep(0.05)
            if r.blocked and i < len(commands) - 1:
                r.event(f"Assistant plan stopped after '{cmd}': {r.blocked}")
                return
            time.sleep(0.25)                   # let it coast to a stop before the next move

    # ----- speech to text (the dashboard's microphone) -----
    def transcribe(self, audio, ctype):
        """Groq Whisper on the browser's recording (webm/ogg/mp4/wav). Returns the text; raises AiError."""
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise AiError("no GROQ_API_KEY in secrets.env, so the robot can't transcribe audio")
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3",
               "audio/wav": "wav", "audio/x-wav": "wav"}.get(ctype.split(";")[0].strip(), "webm")
        boundary = f"----deskbot{random.getrandbits(64):x}"
        parts = []
        for name, value in (("model", AI_STT_MODEL), ("response_format", "json"), ("temperature", "0")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.{ext}"\r\n'
                     f"Content-Type: {ctype.split(';')[0]}\r\n\r\n".encode() + audio + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        out = _http_json(f"{GROQ_URL}/audio/transcriptions", None, {"Authorization": f"Bearer {key}"},
                         raw=b"".join(parts), ctype=f"multipart/form-data; boundary={boundary}")
        text = " ".join(str(out.get("text") or "").split())
        # Whisper invents these on silence or noise
        if len(text) < 2 or text.lower().strip(" .!") in ("thank you", "thanks for watching", "you", "bye"):
            raise AiError("I didn't catch that - try again a little closer to the microphone")
        return text


# ----- HTTPS for the dashboard: browsers allow the microphone only on https:// (or localhost) -----

def ensure_cert(folder=TLS_DIR):
    """(cert.pem, key.pem) for a self-signed certificate naming this machine's host name and IP address, made
    once with the openssl command (on Raspberry Pi OS and in Git for Windows) and remade when the IP changes.
    Raises RuntimeError with the reason if it can't be made."""
    import shutil
    import socket
    import subprocess

    host, ip = socket.gethostname(), local_ip()
    names = sorted({f"DNS:{host}", f"DNS:{host}.local", "DNS:localhost", "IP:127.0.0.1", f"IP:{ip}"})
    cert, key, stamp = folder / "cert.pem", folder / "key.pem", folder / "names.json"
    try:
        if cert.is_file() and key.is_file() and json.loads(stamp.read_text(encoding="utf-8")) == names:
            return cert, key
    except (OSError, ValueError):
        pass
    exe = shutil.which("openssl")
    if exe is None:
        raise RuntimeError("the openssl command is not installed (sudo apt install openssl)")
    folder.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-keyout", str(key),
           "-out", str(cert), "-subj", "/CN=deskbot", "-addext", "subjectAltName=" + ",".join(names)]
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}     # Git for Windows' openssl would mangle "/CN=..."
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"openssl failed: {(res.stderr or res.stdout).strip()[-200:]}")
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    stamp.write_text(json.dumps(names), encoding="utf-8")
    log(f"[https] made a self-signed certificate for {', '.join(n.split(':', 1)[1] for n in names)}")
    return cert, key


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass                                     # plain http sent to the https port, aborted handshakes ...


def start_https(robot, camera, host, port):
    """The same dashboard on https (self-signed), so a browser on the laptop or phone may use its microphone.
    The TLS handshake runs in each request's own thread (do_handshake_on_connect=False), so a client that
    stalls during it never blocks the server."""
    import ssl

    try:
        cert, key = ensure_cert()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server = QuietHTTPServer((host, port), make_handler(robot, camera))
        server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    except Exception as exc:
        log(f"[https] not started ({type(exc).__name__}: {exc}). The dashboard works on http; only the browser "
            f"microphone needs https (or --https-port 8444 if the port is busy)")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="https").start()
    log(f"[https] https://{local_ip()}:{port}  (for the microphone; the first visit shows a certificate warning: "
        f"Advanced -> Proceed)")
    return server


# =====================================================================
# Health (24 Nov 2026): a failing feature is skipped and noted on the dashboard, never a crash
# =====================================================================

class Health:
    """Notes for the dashboard's Notes card: {feature: {level, msg, t, count}}. level: error | warn | info.
    The same note repeated only bumps its count (and is logged once)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.notes = {}

    def note(self, feature, msg, level="error"):
        msg = str(msg)[:300]
        with self.lock:
            old = self.notes.get(feature)
            if old and old["msg"] == msg:
                old["count"] += 1
                old["t"] = time.strftime("%H:%M:%S")
                return
            self.notes[feature] = {"level": level, "msg": msg, "t": time.strftime("%H:%M:%S"), "count": 1}
        log(f"[note] {feature}: {msg}")

    def clear(self, feature):
        with self.lock:
            self.notes.pop(feature, None)

    def items(self):
        with self.lock:
            return [{"feature": f, **n} for f, n in self.notes.items()]


HEALTH = Health()


def guarded(feature, fn, *args, default=None, **kwargs):
    """fn(*args, **kwargs), or `default` with a dashboard note if it raises: a feature that can't start is
    skipped, the rest of the robot runs on."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        HEALTH.note(feature, f"could not start ({type(exc).__name__}: {exc}) - running without it")
        _save_traceback(feature, exc)
        return default


def _save_traceback(where, exc):
    """Full traceback to errors.log next to the script (the dashboard only shows one line)."""
    import traceback
    try:
        with open(ERRORS_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {where}\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except OSError:
        pass


def install_crash_guards():
    """A background thread that dies of an exception becomes a dashboard note (and errors.log), not a traceback
    in the terminal and a silently missing feature."""
    def hook(args):
        if args.exc_type in (SystemExit, KeyboardInterrupt):
            return
        name = args.thread.name if args.thread is not None else "thread"
        HEALTH.note(name, f"stopped after an error ({args.exc_type.__name__}: {args.exc_value})")
        _save_traceback(f"thread {name}", args.exc_value)
    threading.excepthook = hook


def collect_notes(robot, camera):
    """Every problem worth showing, from the features' own status plus HEALTH (newest information wins)."""
    notes = []

    def add(feature, level, msg):
        notes.append({"feature": feature, "level": level, "msg": msg})

    bad = re.compile(r"unavailable|error|failed|stopped after|not answering|giving up|could not", re.I)
    hw = robot.hw
    if camera is not None and bad.search(camera.status or ""):
        add("camera", "error", camera.status)
    det = robot.detector
    if det is not None and bad.search(det.status or ""):
        add("object detection", "warn", det.status)
    if robot.oled is not None and robot.oled.device is None and hw.mode != "simulation" and robot.oled.status != "off":
        add("OLED screen", "warn", robot.oled.status)
    if robot.imu is not None and bad.search(robot.imu.status or ""):
        add("IMU", "warn", robot.imu.status)
    enc_err = getattr(hw, "encoder_error", "")
    if enc_err and not enc_err.startswith("disabled"):
        add("wheel encoders", "warn", enc_err)
    for name, msg in (getattr(hw, "ir_errors", None) or {}).items():
        add(f"{name} IR sensor", "error", msg)
    for name in SONARS:
        why = hw.sonar_reason(name) if hasattr(hw, "sonar_reason") else ""
        if why:
            add(f"{name} sonar", "warn", why)
    touch_err = getattr(hw, "touch_error", "")
    if touch_err and not touch_err.startswith("disabled"):
        add("touch pad", "warn", touch_err)
    for api in ((robot.apis.info()["apis"] if getattr(robot, "apis", None) else [])):
        if api["ok"] is False:
            add(f"{api['name']} API", "warn", f"last call failed at {api['t']}: {api['msg']}")
    ph = getattr(robot, "phone", None)
    if ph is not None and ph.error and not ph.error.startswith("off"):
        add("bluetooth phone", "warn", ph.error)
    for f in (robot.filter.faults() if getattr(robot, "filter", None) else []):
        add(f"{f} sensor", "warn", "readings are flickering or missing - treated as unsafe until clean again")
    a = robot.assistant
    if a is not None and a.enabled and not a.available():
        add("assistant", "info", "no AI key (GROQ_API_KEY / ANTHROPIC_API_KEY in secrets.env): offline commands only")
    for b in (a.brains if a is not None else []):
        if a.errors.get(b.name):
            add(f"assistant ({b.name})", "warn", a.errors[b.name])
    for n in HEALTH.items():
        add(n["feature"], n["level"], n["msg"] + (f" (x{n['count']})" if n["count"] > 1 else ""))
    return notes


# =====================================================================
# Bluetooth phone presence (24 Nov 2026, from run_prototype presence/ble.py): is the owner's phone near?
# =====================================================================

def rssi_to_m(rssi):
    """Rough distance from signal strength (log-distance path loss); expect +-50 %."""
    return None if rssi is None else round(10 ** ((BLE_TX_1M - rssi) / (10 * BLE_PATH_N)), 2)


def ibeacon_uuid(manufacturer_data):
    data = (manufacturer_data or {}).get(0x004C)            # Apple company ID: iBeacon frames
    if data and len(data) >= 23 and data[0] == 0x02 and data[1] == 0x15:
        h = bytes(data[2:18]).hex()
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    return None


class PhonePresence:
    """Listens for the owner's phone over Bluetooth LE and keeps a near / away state with hysteresis:
        near  smoothed RSSI >= BLE_NEAR_RSSI for BLE_NEAR_HOLD_S
        away  not heard for BLE_AWAY_TIMEOUT_S, or smoothed RSSI < BLE_AWAY_RSSI for BLE_AWAY_HOLD_S
    Between the thresholds nothing changes, so walking around the desk doesn't flip it. The phone is matched by
    any of: address, a part of its name, an iBeacon UUID (saved in phone.json; pick it on the dashboard)."""

    def __init__(self, robot, sim=False, enabled=True, settings_file=None):
        from collections import deque
        self.robot, self.sim, self.enabled = robot, sim, enabled
        self.file = Path(settings_file) if settings_file else PHONE_FILE
        self.match = {"address": "", "name": "", "ibeacon": ""}
        try:
            saved = json.loads(self.file.read_text(encoding="utf-8"))
            self.match.update({k: str(saved.get(k, "")) for k in self.match})
        except (OSError, ValueError, AttributeError):
            pass
        self.lock = threading.Lock()
        self.nearby = {}                       # address -> {"name", "rssi", "t", "ibeacon"}
        self.smoothed, self.last_seen, self.state = None, None, "unknown"
        self.history = deque(maxlen=60)
        self._born = time.monotonic()
        self._cond = (None, self._born)
        self.error, self.running = "", False
        self.backend = "simulated" if sim else "bleak"
        self.sim_rssi = None                   # simulation: the phone's signal, None = out of range
        self._stop = threading.Event()
        if enabled:
            threading.Thread(target=self._run_sim if sim else self._run, daemon=True, name="bluetooth").start()
        else:
            self.error = "off (--no-bluetooth)"

    # ----- samples and the near/away state -----
    def matches(self, address, name, beacon):
        m = self.match
        return bool((m["address"] and address.lower() == m["address"].lower())
                    or (m["name"] and name and m["name"].lower() in name.lower())
                    or (m["ibeacon"] and beacon and beacon.lower() == m["ibeacon"].lower()))

    def add(self, rssi, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            self.smoothed = rssi if self.smoothed is None else (1 - BLE_EMA) * self.smoothed + BLE_EMA * rssi
            self.last_seen = now
            self.history.append(round(rssi))
        self.update(now)

    def update(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.last_seen is None:
                cond = "away" if now - self._born > BLE_AWAY_TIMEOUT_S else None
            elif now - self.last_seen > BLE_AWAY_TIMEOUT_S:
                cond = "away"
            elif self.smoothed >= BLE_NEAR_RSSI:
                cond = "near"
            elif self.smoothed < BLE_AWAY_RSSI:
                cond = "weak"
            else:
                cond = None
            if cond != self._cond[0]:
                self._cond = (cond, now)
            held = now - self._cond[1]
            new = self.state
            if cond == "near" and held >= BLE_NEAR_HOLD_S:
                new = "near"
            elif cond == "away" or (cond == "weak" and held >= BLE_AWAY_HOLD_S):
                new = "away"
            old, self.state = self.state, new
        if new != old:
            self._changed(old, new)

    def _changed(self, old, new):
        r = self.robot
        if new == "near":
            r.event("Phone: you're here")
            if old == "away":
                r.announce("Welcome back!", "happy")
        elif new == "away":
            r.event("Phone: you've gone away")

    # ----- sources -----
    def _on_adv(self, device, adv):
        try:
            name = adv.local_name or device.name or ""
            beacon = ibeacon_uuid(adv.manufacturer_data)
            now = time.monotonic()
            with self.lock:
                self.nearby[device.address] = {"name": name, "rssi": adv.rssi, "t": now, "ibeacon": beacon}
                if len(self.nearby) > 200:
                    for k in sorted(self.nearby, key=lambda k: self.nearby[k]["t"])[:50]:
                        self.nearby.pop(k, None)
            if self.matches(device.address, name, beacon):
                self.add(adv.rssi, now)
        except Exception:
            pass                               # a malformed advertisement must not stop the scan

    def _run(self):
        import asyncio
        try:
            from bleak import BleakScanner
        except Exception as exc:
            self.error = f"the bleak library is not available ({type(exc).__name__}: {exc}) - pip install bleak"
            return

        async def scan():
            async with BleakScanner(detection_callback=self._on_adv):
                self.running, self.error = True, ""
                while not self._stop.is_set():
                    await asyncio.sleep(0.5)
                    self.update()

        while not self._stop.is_set():
            try:
                asyncio.run(scan())
            except Exception as exc:
                self.running = False
                fix = ("turn Bluetooth on in Windows settings" if sys.platform == "win32" else
                       "sudo systemctl start bluetooth; rfkill unblock bluetooth")
                self.error = f"Bluetooth scan failed ({type(exc).__name__}: {exc})"[:200] + f" - is Bluetooth on? ({fix})"
                self._stop.wait(BLE_RETRY_S)

    def _run_sim(self):
        self.running = True
        while not self._stop.wait(0.125):
            if self.sim_rssi is not None:
                rssi = self.sim_rssi + random.gauss(0, 1.5)
                with self.lock:
                    self.nearby["SI:MU:LA:TE:D0:01"] = {"name": "Simulated phone", "rssi": round(rssi), "t": time.monotonic(),
                                                        "ibeacon": None}
                if self.matches("SI:MU:LA:TE:D0:01", "Simulated phone", None):
                    self.add(rssi)
            self.update()

    # ----- commands -----
    def use(self, ref):
        """'phone use <address | name part | iBeacon UUID>'"""
        ref = ref.strip()
        if not ref:
            return "Use: phone use <address, part of the name, or iBeacon UUID> ('phone devices' lists them)"
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", ref.lower()):
            self.match = {"address": "", "name": "", "ibeacon": ref.lower()}
        elif re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", ref):
            self.match = {"address": ref.upper(), "name": "", "ibeacon": ""}
        else:
            self.match = {"address": "", "name": ref, "ibeacon": ""}
        with self.lock:
            self.smoothed, self.last_seen, self.state = None, None, "unknown"
            self._born = time.monotonic()
        try:
            self.file.write_text(json.dumps(self.match, indent=1), encoding="utf-8")
            where = f"saved in {self.file.name}"
        except OSError as exc:
            where = f"NOT saved ({exc})"
        return f"Listening for {ref} ({where})"

    def devices(self, max_age=30.0):
        now = time.monotonic()
        with self.lock:
            items = list(self.nearby.items())
        out = [{"address": a, "name": d["name"], "rssi": d["rssi"], "ibeacon": d["ibeacon"], "age_s": round(now - d["t"], 1),
                "match": self.matches(a, d["name"], d["ibeacon"])} for a, d in items if now - d["t"] <= max_age]
        return sorted(out, key=lambda d: -d["rssi"])[:20]

    def info(self):
        now = time.monotonic()
        with self.lock:
            sm, seen = self.smoothed, self.last_seen
            hist = list(self.history)
        chosen = self.match["name"] or self.match["address"] or self.match["ibeacon"]
        return {"state": self.state, "rssi": None if sm is None else round(sm, 1), "distance_m": rssi_to_m(sm),
                "seen_s_ago": None if seen is None else round(now - seen, 1), "history": hist,
                "phone": chosen, "backend": self.backend, "running": self.running, "error": self.error,
                "devices": self.devices()}

    def line(self):
        i = self.info()
        if not i["phone"]:
            return ("Bluetooth: no phone chosen yet. 'phone devices' lists what is nearby, then 'phone use <name or "
                    "address>'" + (f" | {i['error']}" if i["error"] else ""))
        sig = f"{i['rssi']} dBm (~{i['distance_m']} m)" if i["rssi"] is not None else "not heard yet"
        return f"Phone ({i['phone']}): {i['state']} | {sig}" + (f" | {i['error']}" if i["error"] else "")

    def close(self):
        self._stop.set()


# =====================================================================
# Gestures from the laptop camera + rock paper scissors (24 Nov 2026)
# =====================================================================
#
# The hand-gesture model (MediaPipe GestureRecognizer) runs in the BROWSER on the laptop's own camera, so it costs
# the robot nothing. The page sends 'gesture <Name>' once a gesture has been held; the robot decides what it means:
# during a game of rock paper scissors it is a move, otherwise the action set for it (gestures.json).
# From run_prototype companion/gestures.py (the gesture names) and full/rps.py (the game).

GESTURE_NAMES = ("Open_Palm", "Closed_Fist", "Thumb_Up", "Thumb_Down", "Pointing_Up", "Victory", "ILoveYou")
GESTURE_DEFAULTS = {"Open_Palm": "stop", "Closed_Fist": "", "Thumb_Up": "forward 10cm", "Thumb_Down": "back 10cm",
                    "Pointing_Up": "face me", "Victory": "photo", "ILoveYou": "rps"}
# what a gesture may be set to (the dashboard offers exactly these; anything else is refused)
GESTURE_ACTIONS = ("", "stop", "forward 10cm", "back 10cm", "left", "right", "turn 45", "turn -45", "spin", "face me",
                   "face me on", "face me off", "photo", "rps", "focus 25", "focus stop", "oled eyes", "joke", "dance")
RPS_MOVES = {"Closed_Fist": "rock", "Open_Palm": "paper", "Victory": "scissors"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}      # key beats value
RPS_HOW = {("rock", "scissors"): "Rock crushes scissors", ("paper", "rock"): "Paper covers rock",
           ("scissors", "paper"): "Scissors cut paper"}


class Gestures:
    def __init__(self, robot, settings_file=None):
        self.robot = robot
        self.file = Path(settings_file) if settings_file else GESTURES_FILE
        self.map = dict(GESTURE_DEFAULTS)
        try:
            saved = json.loads(self.file.read_text(encoding="utf-8"))
            self.map.update({k: v for k, v in saved.items() if k in GESTURE_NAMES and v in GESTURE_ACTIONS})
        except (OSError, ValueError, AttributeError):
            pass
        self.last, self.count = None, 0

    def handle(self, name):
        """A held gesture from the browser. Returns the reply."""
        if name not in GESTURE_NAMES:
            return f"Unknown gesture '{name}'"
        self.last, self.count = (name, time.strftime("%H:%M:%S")), self.count + 1
        g = self.robot.rps
        if g is not None and g.waiting() and name in RPS_MOVES:
            return g.play(RPS_MOVES[name], "gesture")
        action = self.map.get(name, "")
        if not action:
            return f"{name}: no action set"
        self.robot.event(f"Gesture {name} -> {action}")
        return self.robot.execute(action, source="user")        # a person's command: cancels plans, all safety rules

    def set(self, name, action):
        if name not in GESTURE_NAMES:
            return f"Unknown gesture '{name}' (one of {', '.join(GESTURE_NAMES)})"
        if action not in GESTURE_ACTIONS:
            return f"Not an allowed action: '{action}'"
        self.map[name] = action
        try:
            self.file.write_text(json.dumps(self.map, indent=1), encoding="utf-8")
        except OSError as exc:
            return f"{name} -> {action or 'nothing'} (NOT saved: {exc})"
        return f"{name} -> {action or 'nothing'}"

    def info(self):
        return {"map": self.map, "names": list(GESTURE_NAMES), "actions": list(GESTURE_ACTIONS),
                "last": self.last, "count": self.count}


class RockPaperScissors:
    """Best of three (first to RPS_WIN). A round: the count-down is said, then a move is taken for RPS_MOVE_S:
    a gesture, a word ('rock'), or a dashboard button. No move: asked once more, then the game ends."""

    def __init__(self, robot):
        self.robot = robot
        self.state = "idle"                  # idle | waiting | done
        self.score = [0, 0]                  # you, robot
        self.round, self.deadline, self.retries = 0, 0.0, 0
        self.history = []                    # your moves, to be a little cheeky
        self.last = ""                       # the last round's result
        self.lock = threading.Lock()
        self._pending = None                 # time the next round's count-down starts (after a result)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="rps").start()

    def waiting(self):
        return self.state == "waiting"

    def start(self):
        with self.lock:
            self.state, self.score, self.round, self.retries, self.last = "waiting", [0, 0], 0, 0, ""
            self._pending = None
            self._new_round()
        return "Let's play! First to two. ✊ rock, ✋ paper, ✌ scissors"

    def _new_round(self):
        self.round += 1
        self.deadline = time.monotonic() + RPS_MOVE_S
        self.robot.announce("Rock... paper... scissors... shoot!", "focused")

    def _robot_move(self):
        if self.history and random.random() < 0.5:           # people repeat themselves: beat their favourite
            fav = max(set(self.history), key=self.history.count)
            return next(m for m, beaten in RPS_BEATS.items() if beaten == fav)
        return random.choice(list(RPS_BEATS))

    def play(self, move, source="typed"):
        move = move.lower().strip()
        if move not in RPS_BEATS:
            return "Use: rock, paper or scissors"
        with self.lock:
            if self.state != "waiting":
                return "No game running - say 'rps' (or show 🤟) to start one"
            mine = self._robot_move()
            self.history.append(move)
            if move == mine:
                result, mood = f"We both chose {move}. A draw!", "normal"
            elif RPS_BEATS[move] == mine:
                self.score[0] += 1
                result, mood = f"I chose {mine}. {RPS_HOW[(move, mine)]}: you win this one!", "sad"
            else:
                self.score[1] += 1
                result, mood = f"I chose {mine}. {RPS_HOW[(mine, move)]}: I win this one!", "happy"
            self.last = result
            self.retries = 0
            if max(self.score) >= RPS_WIN:
                you_won = self.score[0] > self.score[1]
                self.state = "done"
                end = (f" You win the game {self.score[0]} to {self.score[1]}! Well played." if you_won else
                       f" I win the game {self.score[1]} to {self.score[0]}! Rematch?")
                self.robot.announce(result + end, "sad" if you_won else "happy")
                self.robot.event(f"Rock paper scissors: {'you' if you_won else 'robot'} won {self.score[0]}-{self.score[1]}")
                return result + end
            self.robot.announce(result + f" Score: you {self.score[0]}, me {self.score[1]}.", mood)
            self.deadline = time.monotonic() + RPS_NEXT_S + RPS_MOVE_S   # the next count-down after a pause
            self._pending = time.monotonic() + RPS_NEXT_S
            return result

    def stop(self):
        with self.lock:
            was, self.state = self.state, "idle"
        return "Game stopped" if was == "waiting" else "No game running"

    def _run(self):
        while not self._stop.wait(0.2):
            try:
                now = time.monotonic()
                with self.lock:
                    if self.state != "waiting":
                        continue
                    if self._pending is not None and now >= self._pending:
                        self._pending = None
                        self._new_round()
                    elif self._pending is None and now >= self.deadline:
                        if self.retries == 0:
                            self.retries = 1
                            self.robot.announce("I didn't see your move. Again!", "focused")
                            self.round -= 1
                            self._new_round()
                        else:
                            self.state = "idle"
                            self.robot.announce("No move again, so let's stop here. Say 'rps' to play another time.", "sleepy")
            except Exception as exc:
                log(f"[rps] {type(exc).__name__}: {exc}")

    def info(self):
        left = max(0.0, self.deadline - time.monotonic()) if self.state == "waiting" else 0.0
        return {"state": self.state, "score": list(self.score), "round": self.round, "last": self.last,
                "left_s": round(left, 1), "counting": self.state == "waiting" and self._pending is None}

    def close(self):
        self._stop.set()


# =====================================================================
# Web APIs (24 Nov 2026, from run_prototype assistant/tools.py): weather, Wikipedia, jokes, currency - free, no keys
# =====================================================================

WEATHER_CODES = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
                 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
                 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
                 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
                 82: "violent showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
                 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


BUILTIN_JOKES = [
    "Why did the robot go on holiday? ... It needed to recharge its batteries",
    "What do you call a robot that always takes the long way round? ... R2-Detour",
    "Why was the computer cold? ... It left its Windows open",
    "How do robots eat salsa? ... With microchips",
    "Why did the robot cross the desk? ... Because its sonar said it was clear",
]


class ApiError(Exception):
    """Said to the user as is ("no internet connection", "couldn't find a place called ...")."""


class WebApis:
    """Each call: a plain-words answer, or ApiError. The last result of every API is kept for the APIs card.
    Requests send a generic User-Agent and only what the question needs (a place name, a topic, currencies);
    there is no IP-location lookup: weather needs a city ('weather Delhi') or a saved home city."""

    APIS = {"weather": ("Weather", "open-meteo.com"), "wikipedia": ("Wikipedia", "wikipedia.org"),
            "jokes": ("Jokes", "official-joke-api.appspot.com"), "currency": ("Currency", "open.er-api.com")}

    def __init__(self, settings_file=None):
        self.file = Path(settings_file) if settings_file else APIS_FILE
        self.home = ""
        try:
            self.home = str(json.loads(self.file.read_text(encoding="utf-8")).get("home_city", ""))
        except (OSError, ValueError, AttributeError):
            pass
        self.home = os.environ.get("DESKBOT_CITY", "") or self.home
        self.status = {k: {"ok": None, "msg": "not used yet", "t": None, "ms": None, "calls": 0} for k in self.APIS}
        self._geo, self._rates = {}, {"t": 0.0, "base": None, "rates": None}

    def _get(self, api, url, params=None):
        import urllib.error
        import urllib.parse
        import urllib.request
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "deskbot-simplified/1.0", "Accept": "application/json"})
        t0 = time.perf_counter()
        st = self.status[api]
        st["calls"] += 1
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as r:
                data = json.loads(r.read().decode("utf-8"))
            st.update(ok=True, msg="ok", t=time.strftime("%H:%M:%S"), ms=round((time.perf_counter() - t0) * 1000))
            return data
        except urllib.error.HTTPError as exc:
            msg = f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            msg = f"no internet connection ({getattr(exc, 'reason', exc)})"
        except ValueError:
            msg = "a bad answer from the service"
        st.update(ok=False, msg=msg, t=time.strftime("%H:%M:%S"), ms=None)
        raise ApiError(msg)

    def set_home(self, city):
        self.home = city.strip()
        try:
            self.file.write_text(json.dumps({"home_city": self.home}), encoding="utf-8")
        except OSError as exc:
            return f"Home city {self.home} (NOT saved: {exc})"
        return f"Home city set to {self.home}"

    def weather(self, place=""):
        place = (place or self.home).strip()
        if not place:
            raise ApiError("which city? Say 'weather Delhi', or set a home city with 'weather home Delhi'")
        key = place.lower()
        if key not in self._geo:
            for name in dict.fromkeys([place, place.split(",")[0].strip()]):
                g = self._get("weather", "https://geocoding-api.open-meteo.com/v1/search",
                              {"name": name, "count": 1, "language": "en", "format": "json"})
                if g.get("results"):
                    r = g["results"][0]
                    self._geo[key] = (r["latitude"], r["longitude"], r.get("name") or name)
                    break
            else:
                raise ApiError(f"I couldn't find a place called {place}")
        lat, lon, name = self._geo[key]
        d = self._get("weather", "https://api.open-meteo.com/v1/forecast", {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        c, day = d["current"], d["daily"]
        rain = day["precipitation_probability_max"][0]
        return (f"In {name} it's {round(c['temperature_2m'])} degrees with {WEATHER_CODES.get(c['weather_code'], 'unknown weather')}"
                f" (feels like {round(c['apparent_temperature'])}). Today {round(day['temperature_2m_min'][0])} to "
                f"{round(day['temperature_2m_max'][0])} degrees" + (f", {rain} % chance of rain." if rain is not None else "."))

    def wikipedia(self, topic):
        import urllib.parse
        topic = topic.strip(" ?.!")
        if not topic:
            raise ApiError("what should I look up?")
        hits = self._get("wikipedia", "https://en.wikipedia.org/w/api.php",
                         {"action": "opensearch", "search": topic, "limit": 1, "namespace": 0, "format": "json"})
        if not hits or len(hits) < 2 or not hits[1]:
            raise ApiError(f"Wikipedia has nothing about {topic}")
        title = hits[1][0]
        d = self._get("wikipedia", "https://en.wikipedia.org/api/rest_v1/page/summary/" +
                      urllib.parse.quote(title.replace(" ", "_")))
        text = d.get("extract", "")
        first = re.split(r"(?<=[.!?])\s+", text)[:2]                   # two sentences: it is spoken
        return " ".join(first) or f"Wikipedia has an article on {title}, but no summary."

    def joke(self):
        """From the joke API; if it is down (it often is: a free service), one of a few built-in ones, so the
        feature still works. The APIs card still shows the API's error."""
        try:
            d = self._get("jokes", "https://official-joke-api.appspot.com/random_joke")
            return f"{d.get('setup', '')} ... {d.get('punchline', '')}".strip(" .")
        except ApiError:
            return random.choice(BUILTIN_JOKES)

    def convert(self, amount, src, dst):
        import urllib.parse
        src, dst = src.upper().strip(), dst.upper().strip()
        r = self._rates
        if r["base"] != src or time.time() - r["t"] > 3600:
            d = self._get("currency", f"https://open.er-api.com/v6/latest/{urllib.parse.quote(src)}")
            if d.get("result") != "success":
                raise ApiError(f"I don't know the currency {src}")
            r.update(t=time.time(), base=src, rates=d["rates"])
        if dst not in r["rates"]:
            raise ApiError(f"I don't know the currency {dst}")
        res = float(amount) * r["rates"][dst]
        return f"{float(amount):g} {src} is about {res:,.2f} {dst}."

    def intent(self, text):
        """(api, args) if `text` asks for one of the APIs, else None. Used before the AI (its answer gets the
        facts) and offline (the answer is said as is)."""
        t = " ".join(text.lower().strip(" ?.!").split())
        if re.search(r"\b(?:weather|temperature|forecast|raining|rain today|how hot|how cold)\b", t):
            m = re.search(r"\b(?:in|at|for)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|now|right now))?$", t)
            return "weather", (m.group(1).strip() if m else "",)
        if re.search(r"\b(?:tell|say|know)\b.*\bjoke\b|^joke$|make me laugh", t):
            return "jokes", ()
        m = re.search(r"(?:convert\s+)?(\d+(?:\.\d+)?)\s*([a-z]{3})\s+(?:to|in|into)\s+([a-z]{3})\b", t)
        if m:
            return "currency", (m.group(1), m.group(2), m.group(3))
        m = re.search(r"^(?:look up|search wikipedia for|wikipedia|wiki|search for)\s+(.+)$", t)
        if m:
            return "wikipedia", (m.group(1),)
        return None

    def run(self, api, args):
        fn = {"weather": self.weather, "wikipedia": self.wikipedia, "jokes": self.joke, "currency": self.convert}[api]
        return fn(*args)

    def info(self):
        return {"home": self.home, "apis": [{"id": k, "name": n, "host": h, **self.status[k]} for k, (n, h) in self.APIS.items()]}


# =====================================================================
# Ideas notebook (24 Nov 2026, from run_prototype hub/ideas.py): "remember this idea: ..."
# =====================================================================

class Ideas:
    def __init__(self, path=None):
        self.path = Path(path) if path else IDEAS_FILE
        self.lock = threading.Lock()
        self.ideas, self.next_id = [], 1
        self.waiting_until = 0.0             # "remember this idea" with no idea: the next thing said is it
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.ideas = [i for i in data.get("ideas", []) if isinstance(i, dict) and i.get("text")]
            self.next_id = max([int(data.get("next_id", 1))] + [i["id"] + 1 for i in self.ideas])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            HEALTH.note("ideas", f"could not read {self.path.name} ({exc}); kept as .bad, starting empty", "warn")
            try:
                self.path.replace(self.path.with_suffix(".bad"))
            except OSError:
                pass

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"next_id": self.next_id, "ideas": self.ideas}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            HEALTH.note("ideas", f"could not save {self.path.name}: {exc}")

    def add(self, text, source="typed"):
        text = " ".join(str(text).split()).strip(" :")[:IDEAS_MAX_TEXT]
        if not text:
            self.waiting_until = time.monotonic() + IDEAS_WAIT_S
            return "What's the idea? Tell me in the next minute."
        with self.lock:
            if len(self.ideas) >= IDEAS_MAX:
                return f"The notebook is full ({IDEAS_MAX} ideas) - forget some first"
            idea = {"id": self.next_id, "text": text, "created": time.strftime("%Y-%m-%d %H:%M"), "source": source}
            self.next_id += 1
            self.ideas.append(idea)
            self._save()
        self.waiting_until = 0.0
        return f"Saved idea #{idea['id']}: {text}"

    def find(self, ref):
        ref = ref.strip().lower().lstrip("#")
        with self.lock:
            if ref.isdigit():
                return next((i for i in self.ideas if i["id"] == int(ref)), None)
            words = [w for w in re.findall(r"[a-z0-9']+", ref) if w not in ("the", "a", "an", "my", "idea", "about")]
            hits = [i for i in self.ideas if words and all(w in i["text"].lower() for w in words)]
            return hits[-1] if hits else None

    def forget(self, ref):
        i = self.find(ref)
        if i is None:
            return f"No idea matches '{ref}'"
        with self.lock:
            self.ideas = [x for x in self.ideas if x["id"] != i["id"]]
            self._save()
        return f"Forgot idea #{i['id']}: {i['text']}"

    def search(self, words=""):
        words = words.strip().lower()
        with self.lock:
            items = list(self.ideas)
        return [i for i in items if not words or words in i["text"].lower()][::-1]

    def markdown(self):
        rows = [f"- **#{i['id']}** ({i['created']}) {i['text']}" for i in self.search()]
        return "# Ideas\n\n" + ("\n".join(rows) if rows else "_No ideas yet._") + "\n"

    def lines(self, n=8):
        items = self.search()
        if not items:
            return "No ideas yet. Say 'remember this idea: ...'"
        return f"Ideas ({len(items)}, newest first):\n" + "\n".join(f"  #{i['id']} {i['text']}" for i in items[:n])

    def info(self):
        return {"count": len(self.ideas), "recent": self.search()[:30], "waiting": time.monotonic() < self.waiting_until}


def offline_ideas(text, ideas):
    raw = text.strip()
    m = re.match(r"^\W*(?:please\s+)?(?:remember|save|note)\s+(?:this\s+|an?\s+|my\s+)?idea\b[\s:,-]*(.*)$", raw, re.I)
    if m:
        return ideas.add(m.group(1), "voice"), "happy", []
    if time.monotonic() < ideas.waiting_until and len(raw.split()) >= 2:
        return ideas.add(raw, "voice"), "happy", []
    t = raw.lower().strip(" ?.!")
    if re.match(r"^(?:what (?:are|were) my ideas|read (?:me )?my ideas|list my ideas|my ideas)$", t):
        items = ideas.search()
        if not items:
            return "You haven't told me any ideas yet.", "normal", []
        return "Your latest ideas: " + "; ".join(i["text"] for i in items[:3]) + ".", "focused", []
    m = re.match(r"^(?:forget|delete|remove)\s+(?:the\s+)?(.+?)\s+idea$|^(?:forget|delete|remove)\s+idea\s+(.+)$", t)
    if m:
        return ideas.forget(m.group(1) or m.group(2)), "normal", []
    return None


# =====================================================================
# Connected accounts (24 Nov 2026): which services are set up - icons only, never a key
# =====================================================================

ACCOUNTS = [  # (id, name, glyph, colour, how it is connected: env var name or "free", what it is for)
    ("groq", "Groq", "G", "#f55036", "GROQ_API_KEY", "AI brain + speech-to-text"),
    ("anthropic", "Claude", "C", "#d97757", "ANTHROPIC_API_KEY", "AI brain (fallback)"),
    ("openai", "OpenAI", "O", "#10a37f", "OPENAI_API_KEY", "not used by this script"),
    ("telegram", "Telegram", "T", "#2aabee", "TELEGRAM_BOT_TOKEN", "not used by this script"),
    ("spotify", "Spotify", "S", "#1db954", "SPOTIFY_CLIENT_ID", "not used by this script"),
    ("google", "Google", "G", "#4285f4", "GOOGLE_CLIENT_ID", "not used by this script"),
    ("weather", "Open-Meteo", "☀", "#f5a524", "free", "weather (no account needed)"),
    ("wikipedia", "Wikipedia", "W", "#6b7280", "free", "look-ups (no account needed)"),
    ("jokes", "Joke API", "☺", "#a855f7", "free", "jokes (no account needed)"),
    ("currency", "ExchangeRate", "¤", "#0ea5e9", "free", "currency rates (no account needed)"),
]


def accounts_info(robot):
    """[{id, name, glyph, colour, connected, kind, for, status}]. Only whether a key EXISTS is read; no key,
    prefix or length ever leaves this function."""
    apis = getattr(robot, "apis", None)
    api_state = {a["id"]: a for a in (apis.info()["apis"] if apis else [])}
    out = []
    for aid, name, glyph, colour, how, purpose in ACCOUNTS:
        if how == "free" and apis is None:      # web APIs not started (e.g. --basic): not usable
            connected, status = False, "off"
        elif how == "free":
            st = api_state.get(aid, {})
            connected = st.get("ok") is not False
            status = ("ok" if st.get("ok") else "error: " + st.get("msg", "") if st.get("ok") is False else "ready")
        else:
            connected = bool(os.environ.get(how))
            status = "key set" if connected else "not set up"
        out.append({"id": aid, "name": name, "glyph": glyph, "colour": colour, "connected": connected,
                    "kind": "free" if how == "free" else "key", "for": purpose, "status": status})
    ph = getattr(robot, "phone", None)
    if ph is not None:
        i = ph.info()
        out.append({"id": "phone", "name": "Phone (Bluetooth)", "glyph": "📱", "colour": "#64748b",
                    "connected": bool(i["phone"]) and i["state"] == "near", "kind": "device",
                    "for": "presence", "status": i["state"] if i["phone"] else "not chosen"})
    return out


# =====================================================================
# SOUND EFFECTS + DANCE (24 Nov 2026)
# =====================================================================
# The laptop is the speaker for now (no speaker on the Pi yet), so the robot only DECIDES what to play: a sound
# effect or a song gets a numbered entry in its status, and the dashboard page (the browser on the laptop) makes the
# sound with the Web Audio API. Nothing is downloaded: the effects and the built-in songs are synthesized in the
# browser from the note lists below. Your own music files can go in songs/ (see SONG_DIRS).
#
# Dance: 'dance' picks a random song; the robot moves to its beat in pre-coded routines of 8 beats each (DANCE_ROUTINES),
# chained at random until the song ends. Sync: the robot owns the clock. The song's beat 0 is DANCE_LEAD_S after
# 'dance'; /api/state carries the dance's elapsed time, and the page starts the music at that position (corrected
# by half the request's round trip), so a page opened mid-dance joins in on the beat.

SFX_NAMES = ("boot", "blip", "happy", "sad", "alarm", "bump", "landed", "pat", "hold", "notify", "chime",
             "shutter", "success", "tada", "grumble", "sleepy")
SFX_RECENT = 10             # effects kept for the dashboard (a page plays the ones newer than it has seen)
SFX_REPEAT_S = 0.3          # the same effect again within this long is dropped (no machine-gun beeps)
SFX_WATCH_HZ = 10.0         # how often robot state is checked for things that make a sound
MOOD_SFX = {"happy": "happy", "sad": "sad", "angry": "grumble", "scared": "alarm", "focused": "notify",
            "sleepy": "sleepy", "normal": "notify"}
SONG_DIRS = [_HERE / "songs", Path.home() / "deskbot" / "songs"]   # .mp3/.ogg/.wav/.m4a, 'name_120bpm.mp3' sets bpm
SONG_EXTS = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".m4a": "audio/mp4"}
SONG_FILE_BPM = 120.0       # a music file without '_<n>bpm' in its name
SONG_FILE_S = 32.0          # a music file is danced to for this long (its length is not known without decoders)
DANCE_LEAD_S = 1.0          # 'dance' -> first beat: time for the page to see it and start the music
DANCE_DUTY = 0.8            # motors run this share of each step (a short pause keeps the moves crisp on the beat)
DANCE_MAX_S = 45.0

# Built-in songs (original tunes). Each bar is 8 eighth notes: a note (C5, F#4, Bb3), '.' rest, '-' hold the last.
# bass: one root note per bar, played in the song's bass style; drums: one bar of K kick, S snare, H hi-hat, . rest.
BUILTIN_SONGS = [
    {"id": "desk-disco", "title": "Desk Disco", "bpm": 120, "repeat": 2, "wave": "square",
     "melody": ["C5 . E5 G5 . E5 C5 .", "D5 . F5 A5 . F5 D5 .", "E5 . G5 C6 . G5 E5 G5", "F5 - E5 - D5 - . .",
                "C5 . E5 G5 . E5 C5 .", "A4 . C5 E5 . C5 A4 .", "F4 A4 C5 F5 E5 D5 C5 B4", "C5 - - - . . . ."],
     "bass": ["C3", "D3", "E3", "F3", "C3", "A2", "F2", "C3"], "bass_style": "octave", "drums": "K.H.SKH.S"},
    {"id": "robot-shuffle", "title": "Robot Shuffle", "bpm": 104, "repeat": 2, "wave": "triangle",
     "melody": ["A4 . C5 . E5 D5 C5 .", "G4 . B4 . D5 C5 B4 .", "F4 . A4 . C5 B4 A4 G4", "E4 - G#4 - B4 - . .",
                "A4 . C5 . E5 D5 C5 .", "G4 . B4 . D5 E5 F5 .", "E5 D5 C5 B4 A4 B4 C5 B4", "A4 - - - . . . ."],
     "bass": ["A2", "G2", "F2", "E2", "A2", "G2", "F2", "A2"], "bass_style": "offbeat", "drums": "K.HSK.HS"},
    {"id": "bleep-bop-boogie", "title": "Bleep Bop Boogie", "bpm": 132, "repeat": 2, "wave": "square",
     "melody": ["G4 G4 B4 D5 . D5 B4 .", "C5 C5 E5 G5 . G5 E5 .", "D5 . B4 . A4 . G4 .", "A4 B4 A4 G4 F#4 - D4 .",
                "G4 G4 B4 D5 . D5 B4 .", "C5 C5 E5 G5 . G5 A5 .", "B5 A5 G5 E5 D5 B4 A4 F#4", "G4 - . G5 - . . ."],
     "bass": ["G2", "C3", "G2", "D3", "G2", "C3", "D3", "G2"], "bass_style": "pump", "drums": "KHSHKHSH"},
    {"id": "moonlit-bloops", "title": "Moonlit Bloops", "bpm": 92, "repeat": 2, "wave": "sine",
     "melody": ["F4 . A4 C5 - . A4 .", "Bb4 . D5 F5 - . D5 .", "C5 . E5 G5 - . E5 C5", "F5 - E5 - C5 - . .",
                "F4 . A4 C5 - . A4 .", "D5 . C5 A4 - . G4 .", "Bb4 A4 G4 F4 E4 G4 C5 E5", "F5 - - - . . . ."],
     "bass": ["F2", "Bb2", "C3", "F2", "F2", "D2", "C3", "F2"], "bass_style": "octave", "drums": "K..HS..H"},
]

# Dance routines: (move, beats). L/R turn on the spot, F/B drive, SL/SR a longer spin, '-' a pause. Every routine
# is 8 beats and ends where it started (as much turning left as right, as much forward as back), so a whole dance
# leaves the robot roughly where it was. At speed 0.5 one beat of turning at 120 bpm is ~50 deg.
DANCE_ROUTINES = {
    "wiggle": [("L", 1), ("R", 1), ("L", 1), ("R", 1), ("L", .5), ("R", .5), ("L", .5), ("R", .5), ("-", 2)],
    "cha-cha": [("F", 1), ("B", 1), ("F", .5), ("B", .5), ("F", .5), ("B", .5), ("L", 1), ("R", 1), ("-", 2)],
    "spin": [("SL", 2), ("-", 1), ("SR", 2), ("-", 1), ("L", .5), ("R", .5), ("L", .5), ("R", .5)],
    "robot": [("L", .5), ("-", .5), ("L", .5), ("-", .5), ("R", .5), ("-", .5), ("R", .5), ("-", .5),
              ("F", .5), ("-", .5), ("B", .5), ("-", .5), ("-", 2)],
    "shimmy": [("F", .5), ("L", .5), ("B", .5), ("R", .5), ("F", .5), ("R", .5), ("B", .5), ("L", .5),
               ("F", .5), ("L", .5), ("B", .5), ("R", .5), ("F", .5), ("R", .5), ("B", .5), ("L", .5)],
    "twist": [("L", 1.5), ("R", 1.5), ("L", 1.5), ("R", 1.5), ("-", 2)],
}
DANCE_MOVES = {"L": ("left", "Dance: left"), "R": ("right", "Dance: right"), "F": ("forward", "Dance: forward"),
               "B": ("backward", "Dance: back"), "SL": ("left", "Dance: spin"), "SR": ("right", "Dance: spin")}


def song_beats(song):
    """Quarter-note beats in a built-in song (8 eighths = 4 beats per bar)."""
    return len(song["melody"]) * 4 * song.get("repeat", 1)


def find_song_files(dirs=None):
    """Music files the user added: [{id, title, bpm, file, ...}], sorted by name."""
    out, seen = [], set()
    for d in (dirs if dirs is not None else SONG_DIRS):
        try:
            files = sorted(Path(d).iterdir())
        except OSError:
            continue
        for f in files:
            if f.suffix.lower() not in SONG_EXTS or not f.is_file() or f.name in seen:
                continue
            if not re.fullmatch(r"[\w .()'&+-]{1,80}", f.name):     # served by name: keep it a plain name
                continue
            seen.add(f.name)
            m = re.search(r"[_ -](\d{2,3})\s?bpm", f.stem, re.I)
            bpm = float(m.group(1)) if m and 50 <= int(m.group(1)) <= 220 else SONG_FILE_BPM
            title = re.sub(r"[_ -]+\d{2,3}\s?bpm", "", f.stem, flags=re.I).replace("_", " ").strip() or f.stem
            out.append({"id": "file:" + f.name, "title": title, "bpm": bpm, "file": f.name, "path": str(f),
                        "seconds": min(DANCE_MAX_S, SONG_FILE_S)})
    return out


def song_file_path(name, dirs=None):
    """The music file for a /songs/<name> request, or None (only files find_song_files() would list)."""
    for s in find_song_files(dirs):
        if s["file"] == name:
            return Path(s["path"])
    return None


def dance_plan(beats, rng=random):
    """A random chain of routines filling `beats`: [(routine name, [(move, beats), ...]), ...]. No routine twice in
    a row; the last one is cut short to fit."""
    plan, left, last = [], beats, None
    while left > 0:
        name = rng.choice([n for n in DANCE_ROUTINES if n != last])
        steps, total = [], 0.0
        for mv, b in DANCE_ROUTINES[name]:
            if total + b > left + 1e-9:
                break
            steps.append((mv, b))
            total += b
        if not steps:
            break
        plan.append((name, steps))
        left -= total
        last = name
    return plan


class Sounds:
    """Sound effects. The robot queues them (play()); every dashboard page with 'Sound effects' ticked plays the
    ones newer than it has already seen. A watcher thread turns robot state changes into effects, like the OLED's
    face reacts to them (blocked, lifted, put down, pats, moves, calibration), so the core needs no extra hooks."""

    def __init__(self, robot):
        self.robot = robot
        self.on = True
        self.n = 0
        self.recent = []
        self._last = {}
        self.lock = threading.Lock()
        self._seen = None
        self._stop = threading.Event()
        threading.Thread(target=self._watch, daemon=True, name="sounds").start()
        self.play("boot")

    def play(self, name):
        """Queue one effect. Returns the reply for 'sound <name>'."""
        if name not in SFX_NAMES:
            return f"Unknown sound '{name}' (one of {', '.join(SFX_NAMES)})"
        if not self.on:
            return "Sound effects are off ('sounds on')"
        now = time.monotonic()
        with self.lock:
            if now - self._last.get(name, -1e9) < SFX_REPEAT_S:
                return f"Sound: {name}"
            self._last[name] = now
            self.n += 1
            self.recent = (self.recent + [{"id": self.n, "name": name}])[-SFX_RECENT:]
        return f"Sound: {name}"

    def mood(self, mood):
        return self.play(MOOD_SFX.get(mood, "notify"))

    def _snapshot(self):
        r = self.robot
        mv = r.move
        return {"blocked": r.blocked, "lifts": r.lift["lifts"], "lifted": r.lift["lifted"],
                "pats": r.touch["pats"], "holds": r.touch["holds"], "cal": r.cal_message,
                "move": None if mv is None else mv.get("t0")}

    def _changes(self, old, new):
        """The effects for one state change (pure: tested on its own)."""
        out = []
        dancing = bool(getattr(self.robot, "dance", None) and self.robot.dance.active())
        if new["lifts"] > old["lifts"]:
            out.append("alarm")
        elif old["lifted"] and not new["lifted"]:
            out.append("landed")
        elif new["blocked"] and new["blocked"] != old["blocked"] and not new["blocked"].startswith("lifted"):
            b = new["blocked"]
            kind = ("sad" if "stuck" in b else "alarm" if ("edge" in b or "tilted" in b) else
                    "hold" if "touch" in b else "bump" if ("obstacle" in b or "bump" in b) else "grumble")
            if not dancing or kind in ("sad", "alarm"):        # during a dance a skipped step is not news
                out.append(kind)
        if new["pats"] > old["pats"]:
            out.append("pat")
        if new["holds"] > old["holds"]:
            out.append("hold")
        if new["cal"] != old["cal"] and new["cal"]:
            out.append("success" if new["cal"].startswith(("Calibrated", "Turning calibrated")) else
                       "sad" if "failed" in new["cal"] else "notify")
        if new["move"] is not None and new["move"] != old["move"] and not dancing and not out:
            out.append("blip")
        return out

    def _watch(self):
        while not self._stop.wait(1.0 / SFX_WATCH_HZ):
            try:
                new = self._snapshot()
                if self._seen is not None:
                    for name in self._changes(self._seen, new):
                        self.play(name)
                self._seen = new
            except Exception as exc:
                log(f"[sounds] {type(exc).__name__}: {exc}")

    def set(self, on):
        self.on = on
        return "Sound effects on" if on else "Sound effects off (the dashboard stays quiet; music still plays)"

    def info(self):
        with self.lock:
            return {"on": self.on, "last_id": self.n, "recent": list(self.recent), "names": list(SFX_NAMES)}

    def close(self):
        self._stop.set()


class Dance:
    """'dance [song]': plays a song (in the dashboard browser) and moves to its beat. Every step is an ordinary
    timed move through Robot.start(), so all the safety rules apply; a step that is not safe is skipped (the
    robot dances on the spot), and the dance ends on 'stop', any command from a person, or being lifted."""

    def __init__(self, robot, song_dirs=None, rng=None):
        self.robot = robot
        self.song_dirs = song_dirs
        self.rng = rng or random.Random()
        self.state = {"active": False, "run": 0, "song": None, "title": "", "bpm": 0.0, "seconds": 0.0,
                      "routine": "", "step": "", "skipped": 0, "result": "", "t0": None}
        self._last_song = None
        self.lock = threading.Lock()

    def songs(self):
        """Every song: the built-in ones (with their notes, for the page's synthesizer) and the music files."""
        built = [dict(s, kind="synth", seconds=round(song_beats(s) * 60.0 / s["bpm"], 2)) for s in BUILTIN_SONGS]
        files = [{k: v for k, v in s.items() if k != "path"} | {"kind": "file"}
                 for s in find_song_files(self.song_dirs)]
        return built + files

    def _pick(self, want):
        songs = self.songs()
        if want:
            w = want.lower().strip()
            hit = next((s for s in songs if s["id"] == w), None) or next(
                (s for s in songs if w in s["title"].lower() or w in s["id"]), None)
            return hit
        pool = [s for s in songs if s["id"] != self._last_song] or songs
        return self.rng.choice(pool)

    def active(self):
        return self.state["active"]

    def start(self, want=""):
        r = self.robot
        if r.lift["lifted"]:
            return "Not dancing: I'm lifted - put me down on the desk"
        if r.cal:
            return "Not dancing: encoder calibration in progress"
        song = self._pick(want)
        if song is None:
            return f"No song called '{want}'. Songs: " + ", ".join(s["title"] for s in self.songs())
        r.nav.state["active"] = False                    # a dance replaces a trip
        r.nav._run_id += 1
        seconds = min(DANCE_MAX_S, song["seconds"])
        beats = int(seconds * song["bpm"] / 60.0)
        plan = dance_plan(beats, self.rng)
        with self.lock:
            self.state["run"] += 1
            run = self.state["run"]
            self.state.update(active=True, song=song["id"], title=song["title"], bpm=song["bpm"], seconds=seconds,
                              routine="", step="get ready", skipped=0, result="",
                              t0=time.monotonic() + DANCE_LEAD_S)
        self._last_song = song["id"]
        r.event(f"Dance: {song['title']} ({song['bpm']:.0f} bpm, {seconds:.0f} s)")
        if r.oled is not None:
            r.oled.say(f"Dancing to\n{song['title']}", 3.0)
            r.oled.mood("happy", seconds + DANCE_LEAD_S)
        threading.Thread(target=self._run, args=(run, r.user_cmds, plan, song["bpm"]), daemon=True,
                         name="dance").start()
        where = "" if getattr(r, "dashboard_on", True) else " (no dashboard, so no music: just the moves)"
        return f"Dancing to {song['title']}!{where} ('stop' ends it)"

    def _cancelled(self, run, user_cmds):
        r = self.robot
        if run != self.state["run"] or not self.state["active"]:
            return "replaced"
        if r.user_cmds != user_cmds:
            return "stopped"
        if r.lift["lifted"]:
            return "I was picked up"
        return ""

    def _wait_until(self, t, run, user_cmds):
        while True:
            why = self._cancelled(run, user_cmds)
            left = t - time.monotonic()
            if why or left <= 0:
                return why
            time.sleep(min(0.02, left))

    def _run(self, run, user_cmds, plan, bpm):
        r = self.robot
        beat = 60.0 / bpm
        t = self.state["t0"]
        why = ""
        try:
            for name, steps in plan:
                with self.lock:
                    if run == self.state["run"]:
                        self.state["routine"] = name
                for mv, beats in steps:
                    why = self._wait_until(t, run, user_cmds)
                    if why:
                        break
                    if mv != "-":
                        way, label = DANCE_MOVES[mv]
                        reply = r.start(way, beats * beat * DANCE_DUTY, label)
                        if reply.startswith("Not moving"):
                            self.state["skipped"] += 1
                    with self.lock:
                        if run == self.state["run"]:
                            self.state["step"] = {"-": "pause"}.get(mv, DANCE_MOVES.get(mv, ("", ""))[1].split(": ")[-1])
                    t += beats * beat
                if why:
                    break
            if not why:
                why = self._wait_until(t, run, user_cmds)
        finally:
            with self.lock:
                mine = run == self.state["run"]
                if mine:
                    self.state.update(active=False, step="", routine="",
                                      result="finished" if not why else why)
            if mine:
                if r.move and str(r.move.get("label", "")).startswith("Dance"):
                    r.stop()
                if not why:
                    r.event(f"Dance finished: {self.state['title']}"
                            + (f" ({self.state['skipped']} steps skipped for safety)" if self.state["skipped"] else ""))
                    if r.sounds is not None:
                        r.sounds.play("tada")
                    if r.oled is not None:
                        r.oled.mood("happy", 3.0)
                elif why != "replaced":
                    r.event(f"Dance ended: {why}")

    def stop(self):
        with self.lock:
            was = self.state["active"]
            self.state.update(active=False, result="stopped")
        if was and self.robot.move and str(self.robot.move.get("label", "")).startswith("Dance"):
            self.robot.stop()
        return "Dance stopped" if was else "Not dancing"

    def info(self):
        with self.lock:
            s = {k: v for k, v in self.state.items() if k != "t0"}
            t0 = self.state["t0"]
        s["elapsed_s"] = round(time.monotonic() - t0, 3) if (s["active"] and t0 is not None) else None
        return s

    def line(self):
        s = self.info()
        if not s["active"]:
            last = f" (last: {s['title']}, {s['result']})" if s["title"] else ""
            return "Not dancing" + last
        skipped = f", {s['skipped']} steps skipped" if s["skipped"] else ""
        return (f"Dancing to {s['title']} ({s['bpm']:.0f} bpm): {max(0.0, s['elapsed_s']):.0f}/{s['seconds']:.0f} s, "
                f"{s['routine'] or 'starting'}{skipped}")

    def close(self):
        self.stop()


# =====================================================================
# Main
# =====================================================================

def use_project_venv(args):
    """Object detection needs OpenCV + ncnn. On the Pi only the project venv has them; the system python3 does not.
    Started with a Python that lacks them, restart this same command with the venv's Python (it also sees the
    system packages: gpiozero, picamera2, luma ...). Checked with find_spec, NOT by importing: ncnn must be
    imported only after OMP_NUM_THREADS is set. The env var stops a restart loop."""
    import importlib.util

    if args.no_detect or args.no_camera or args.no_dashboard or os.environ.get("SIMPLIFIED_VENV_TRIED"):
        return
    missing = [m for m in ("cv2", "ncnn", "numpy") if importlib.util.find_spec(m) is None]
    if not missing:
        return
    venv = next((p for p in VENV_PYTHONS if p.is_file()), None)
    if venv is None or Path(sys.prefix).resolve() == venv.parent.parent.resolve():
        return               # no venv, or already in it: detection will say what is missing
    print(f"[start] {', '.join(missing)} not installed for {sys.executable} (needed for object detection) - "
          f"restarting with the project venv: {venv}", flush=True)
    os.environ["SIMPLIFIED_VENV_TRIED"] = "1"
    try:
        os.execv(str(venv), [str(venv), *sys.argv])
    except OSError as exc:   # cannot start it: carry on without detection
        print(f"[start] could not start {venv} ({exc}) - continuing without object detection", flush=True)


BACKGROUND_NICE = 10        # Linux niceness for everything that is not motors/sensors (0 = normal, 19 = lowest)
GIL_SWITCH_S = 0.002        # Python hands the GIL to a waiting thread after this (default 5 ms)


def prioritize_motors():
    """Called by main() right after the motor/sensor threads exist (lgpio edges, sonars, IMU, the 50 Hz control
    loop). It lowers the CALLING (main) thread's priority; on Linux the nice value is per thread and every thread
    created afterwards inherits it, so the camera, detector (and NCNN's workers), dashboard, OLED, Bluetooth, AI
    and the rest all run below the motor threads. Non-root may lower priority, never raise it, so this needs no
    sudo. A shorter GIL switch interval lets the control loop get the interpreter sooner when it wakes up."""
    sys.setswitchinterval(GIL_SWITCH_S)
    if not hasattr(os, "setpriority") or not sys.platform.startswith("linux"):
        return "motor priority: not supported here (Linux only); GIL switch 2 ms"
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), BACKGROUND_NICE)
        return f"motor priority: motors/sensors at normal priority, everything else at nice {BACKGROUND_NICE}"
    except OSError as exc:
        return f"motor priority: could not lower the background threads ({exc})"


def make_hardware(sim, use_encoders=True, use_imu=True, imu_address=IMU_ADDRESS, touch_pin=TOUCH_PIN):
    if sim:
        return SimHardware(use_imu)
    try:
        return RealHardware(use_encoders, use_imu, imu_address, touch_pin)
    except Exception as exc:
        log(f"[robot] could not open the motors/GPIO: {exc}")
        log("[robot] falling back to SIMULATION - nothing on the real robot will move. "
            "Run on the Pi (check wiring / that no other robot script is running), or pass --sim.")
        return SimHardware(use_imu)


def main():
    ap = argparse.ArgumentParser(description="Simple robot CLI + dashboard (motors, obstacle stop, map, camera)")
    ap.add_argument("--sim", action="store_true", help="simulated robot (no GPIO)")
    ap.add_argument("--host", default="0.0.0.0", help="dashboard address (default all interfaces)")
    ap.add_argument("--port", type=int, default=8080, help="dashboard port (default 8080)")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--no-edge", action="store_true", help="ignore the IR edge sensors")
    ap.add_argument("--basic", action="store_true",
                    help="basic mode: only motors, sensors (sonar, IR, encoders, IMU, touch, lift), the sensor map "
                         "and obstacle stops, plus a dashboard without camera. Fastest; no camera/AI/OLED/extras")
    ap.add_argument("--reverse-motors", action="store_true",
                    help="both motors wired backwards: flip them (saved in motors.json; 'motors normal' undoes it)")
    ap.add_argument("--slam", action="store_true", help="start with SLAM on ('slam on/off' or the dashboard switch it)")
    ap.add_argument("--no-invert", action="store_true",
                    help="show the camera picture as it comes (default: rotated 180 deg, camera mounted upside down)")
    ap.add_argument("--ignore-obstacles", action="store_true",
                    help="the sonars never stop a move (edges, lift, tilt, bump still do); 'obstacles on' undoes it")
    ap.add_argument("--speed", type=float, default=0.5, help="motor speed 0.1-1.0 (default 0.5)")
    ap.add_argument("--no-encoders", action="store_true", help="do not use the wheel encoders")
    ap.add_argument("--no-oled", action="store_true", help="do not use the OLED screen")
    ap.add_argument("--oled-driver", choices=("ssd1306", "sh1106"), default="ssd1306",
                    help="ssd1306 (0.96\" and SSD1315 modules, default) or sh1106 (most 1.3\" modules)")
    ap.add_argument("--oled-address", default="0x3C", help="I2C address (default 0x3C)")
    ap.add_argument("--oled-rotate", type=int, choices=(0, 1, 2, 3), default=0, help="2 = upside down")
    ap.add_argument("--no-imu", action="store_true", help="do not use the IMU (MPU-6050)")
    ap.add_argument("--imu-address", default=hex(IMU_ADDRESS), help="IMU I2C address (default 0x68; 0x69 if AD0 high)")
    ap.add_argument("--no-lift", action="store_true", help="no lift detection (no 'picked up' stop, no fresh map)")
    ap.add_argument("--no-detect", action="store_true", help="no object detection on the camera")
    ap.add_argument("--model", default=None, help="NCNN model folder (default: models/yolo26n_ncnn_model, searched)")
    ap.add_argument("--detect-threads", type=int, default=DETECT_THREADS, help=f"NCNN threads (default {DETECT_THREADS})")
    ap.add_argument("--no-touch", action="store_true", help="do not use the touch pad")
    ap.add_argument("--touch-pin", type=int, default=TOUCH_PIN, help=f"touch pad GPIO (BCM, default {TOUCH_PIN})")
    ap.add_argument("--no-bluetooth", action="store_true", help="do not listen for the phone over Bluetooth")
    ap.add_argument("--no-ai", action="store_true", help="assistant without Groq/Claude (offline rules only)")
    ap.add_argument("--groq-model", default=AI_GROQ_MODEL, help=f"Groq chat model (default {AI_GROQ_MODEL})")
    ap.add_argument("--claude-model", default=AI_CLAUDE_MODEL, help=f"Claude model (default {AI_CLAUDE_MODEL})")
    ap.add_argument("--https-port", type=int, default=HTTPS_PORT,
                    help=f"https dashboard for the browser microphone (default {HTTPS_PORT}; 0 = off)")
    args = ap.parse_args()
    if args.basic:              # everything that is not motors, sensors, map or obstacle stops is off
        args.no_camera = args.no_detect = args.no_oled = args.no_bluetooth = args.no_ai = True
        args.https_port = 0
    use_project_venv(args)          # before any hardware is opened: execv replaces this process

    install_crash_guards()
    hw = make_hardware(args.sim, use_encoders=not args.no_encoders, use_imu=not args.no_imu,
                       imu_address=int(args.imu_address, 0), touch_pin=None if args.no_touch else args.touch_pin)
    robot = Robot(hw, check_edges=not args.no_edge)
    robot.speed = max(0.1, min(1.0, args.speed))
    robot.ignore_obstacles = args.ignore_obstacles
    if args.reverse_motors:
        log(f"[robot] {robot.execute('motors reverse')}")
    rev = getattr(hw, "reversed", {})
    if any(rev.values()):
        log(f"[robot] motors: left {'REVERSED' if rev['left'] else 'normal'}, "
            f"right {'REVERSED' if rev['right'] else 'normal'} (motors.json)")
    robot.basic = args.basic
    log(f"[robot] {prioritize_motors()}")
    robot.lift["enabled"] = not args.no_lift
    if not args.no_encoders:
        log(f"[encoders] {robot.calibration_summary()}")
    closers = []                         # everything with a close(), closed in reverse order at the end

    def start(feature, factory, *a, **k):
        obj = guarded(feature, factory, *a, **k)
        if obj is not None and hasattr(obj, "close"):
            closers.append(obj)
        return obj

    camera_on = not (args.no_camera or args.no_dashboard)
    camera = start("camera", Camera, enabled=camera_on, invert=not args.no_invert) or Camera(enabled=False)
    robot.camera = camera if camera_on else None
    if args.sim and not args.model:      # the simulated desk's objects (a real model would see the laptop's room)
        robot.detector = start("object detection", SimDetector, robot, enabled=not args.no_detect)
    else:
        robot.detector = start("object detection", Detector, camera if camera_on else None, model=args.model,
                               enabled=not args.no_detect, threads=max(1, args.detect_threads))
    server = None if args.no_dashboard else guarded("dashboard", start_dashboard, robot, camera, args.host, args.port)
    robot.oled = start("OLED screen", Oled, robot, args.port, enabled=not args.no_oled, driver=args.oled_driver,
                       address=int(args.oled_address, 0), rotate=args.oled_rotate)
    robot.slam = start("SLAM", Slam, robot, enabled=args.slam)   # mapping: also in basic mode
    if args.basic:
        log("[robot] BASIC MODE: motors, sensors, sensor map, obstacle stops and the dashboard only")
    else:
        robot.tasks = guarded("tasks", TaskList)
        if robot.tasks is not None:
            start("reminders", Reminders, robot, robot.tasks)
        faces = start("faces", FaceWatcher, camera if camera_on else None)
        robot.focus = start("focus timer", FocusTimer, robot, faces)
        robot.people = start("face me + greeter", People, robot, faces) if camera_on else None
        robot.assistant = guarded("assistant", Assistant, robot, enabled=not args.no_ai, groq_model=args.groq_model,
                                  claude_model=args.claude_model)
        if robot.assistant is not None:
            log(f"[assistant] {robot.assistant.line()}")
        extra_features(robot, args, start)   # newer features (24 Nov 2026), each guarded the same way
    https = None
    if server is not None and args.https_port:
        https = guarded("https", start_https, robot, camera, args.host, args.https_port)
    robot.https_port = args.https_port if https else None
    robot.dashboard_on = server is not None      # the dance's music plays on a dashboard page

    print("\n=== ROBOT CONTROL ===  mode:", hw.mode + (" (BASIC)" if args.basic else ""), "| type 'help' for commands, Ctrl+C or 'quit' to exit")
    try:
        while True:
            try:
                line = input("robot> ")
            except EOFError:          # stdin closed (e.g. run in the background): keep the dashboard alive
                if server is None:
                    break
                log("No terminal input - dashboard only. Ctrl+C to quit.")
                while True:
                    time.sleep(1)
            reply = robot.execute(line)
            if reply == "quit":
                break
            if reply:
                try:
                    print(reply)
                except UnicodeEncodeError:   # a terminal that can't show some character (Windows code pages)
                    print(reply.encode("ascii", "replace").decode())
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
    finally:
        robot.stop()
        for obj in reversed(closers):
            try:
                obj.close()
            except Exception:
                pass
        for srv in (server, https):
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:
                    pass
        robot.close()
        print("Motors stopped. Robot closed.")


def extra_features(robot, args, start):
    """Started after the core: filled in by the newer features below (each through `start`, so a failure is a
    dashboard note, not a crash)."""
    robot.phone = start("bluetooth phone", PhonePresence, robot, sim=args.sim, enabled=not args.no_bluetooth)
    robot.gestures = start("gestures", Gestures, robot)
    robot.rps = start("rock paper scissors", RockPaperScissors, robot)
    robot.apis = start("web APIs", WebApis)
    robot.ideas = start("ideas", Ideas)
    robot.sounds = start("sound effects", Sounds, robot)
    robot.dance = start("dance", Dance, robot)


if __name__ == "__main__":
    main()
