# Companion runtime (`python main.py`, 18 Nov 2026)

The assistant robot plus a body that senses and reacts: MPU-6050, PID self-correction, pick-up handling,
hand gestures, animated OLED eyes, a complete calibration and a folder of saved results. All code is in
`deskbot/companion/`; older entry points still work.

## Processes

| Process | Core | Priority | Work |
| --- | --- | --- | --- |
| motor | 0 | `SCHED_FIFO 50` | newest command, safety rules, wheel gains, `DRIVE` deadman |
| sensors | 1 | `SCHED_FIFO 40` | 4 sonars + 2 IR at 50 Hz |
| camera | 2 | nice 5 | YOLO26n + ByteTrack + optical flow |
| nav (parent) | 3 | nice 10 | maps, web server, PID loops, emotion, gestures → actions, outputs |
| **body** | 1 | nice -2 | MPU-6050 at 100 Hz, Madgwick filter, eyes at 15 fps |
| **gesture** | 3 | nice 15 | MediaPipe, 5 Hz, only while YOLO sees a person |

New shared-memory blocks are in `companion/shared.py`. Each has one writer process; threads in the nav process
serialise their writes with `nav_write` / `nav_bump`.

Changes to older modules are small hooks: `run_runtime(shared_cls, extra_children, behaviour_cls)`,
`make_setup(handler_cls, lift_cls)`, the `DRIVE` command and wheel gains in `MotorLoop`, and `WakeSignal`.
`WakeSignal` replaces `multiprocessing.Event` because `Event.set()` waits for sleepers to acknowledge, which froze
every command sender if the motor process had died.

## Libraries

| Job | Library |
| --- | --- |
| PID | `simple-pid` |
| Orientation | `ahrs` (Madgwick) |
| MPU-6050 | `adafruit-circuitpython-mpu6050` |
| OLED | `luma.oled`, `luma.core` (frame-rate regulator, in-memory device), Pillow |
| Animation easing | `pytweening` |
| Hand gestures | MediaPipe `GestureRecognizer` |
| Figures | Matplotlib (object API, Agg) |
| Calibration maths | NumPy `polyfit`, SciPy `Rotation.align_vectors`, OpenCV checkerboard calibration |

`imufusion` was rejected because its compiled module is blocked by Smart App Control on the development laptop;
`ahrs` is pure Python (about 40 µs per update there), so the same code path runs in tests and on the Pi. No Python
port of the Arduino RoboEyes library could be found, so the eyes use the libraries above with hardcoded keyframes.

## MPU-6050

Wiring: VCC → 3.3 V (pin 1), GND → GND, SDA → GPIO 2 (pin 3), SCL → GPIO 3 (pin 5). Address `0x68`. Configured for
±4 g, ±500 °/s, 44 Hz low-pass, 100 Hz. `scripts/setup.sh` enables I2C at 400 kHz; a reboot is needed the first time.

`ImuFilter` applies the calibration (gyro bias, accelerometer scale, level rotation, yaw sign), then Madgwick
(`gain` 0.033). Robot frame: x forward, y left, z up, yaw positive to the left.

- A 6-axis IMU has no absolute heading. To limit drift, the bias is updated and yaw is frozen while the robot is
  stationary (gyro < 0.04 rad/s, acceleration within 0.4 m/s² of 1 g, motors off, for 0.4 s).
- `tilt` comes straight from gravity with a light filter, so it reacts faster than the Madgwick orientation.
- `ahrs` skips its entire update for an exactly zero gyro vector, so a 1e-9 rad/s value is passed when stationary.
- Without an IMU the robot still runs: `ok=0`, wheel-time facing, IR-only lift detection.

## Self-correction

`MotionTrim` runs at 25 Hz during timed moves and writes wheel gains, which the motor process ignores after 0.3 s.

| Loop | Measured | Output | Default gains |
| --- | --- | --- | --- |
| Heading hold | gyro yaw vs yaw at move start | left/right difference, ±0.3 | 1.2 / 0.3 / 0.05 |
| Turn rate | gyro rate vs calibrated rate | speed scale −0.4…+0.8 | 0.15 / 0.35 / 0 |
| Obstacle slow-down | sonar in travel direction | scale 0.45…1 over 25 cm | proportional |

A turn producing under 15 % of the expected rate for 0.7 s is stopped and reported as a stall.

`ClosedLoopFaceUser` runs at 20 Hz. A camera bearing is added to the yaw **at the frame's capture time**, which
cancels camera latency. Yaw PID (2.2 / 0.1 / 0.08) gives a turn rate, feed-forward plus rate PID (0.08 / 0.25) gives
the wheel command, plus the calibrated dead-zone PWM. Within 3° it stops. "Keep my distance" adds a sonar PID
(1.2 / 0.1 / 0.1, target 45 cm, ±0.35) while the user is within 10° of straight ahead.

All output goes through the motor process. `DRIVE` commands use the same safety rules and expire after 0.25 s.

## Pick-up handling

Lifted when, for the confirm time: both IR sensors lose the desk (0.4 s), tilt exceeds 30° (0.3 s), or motors are off,
the robot is being moved (gyro > 0.8 rad/s or acceleration off by > 2 m/s²) and at least one IR sensor lost the desk
(0.35 s). A knock on the desk with both IR sensors on the surface doesn't count.

While lifted: motors stop, commands are cancelled, mapping pauses, facing and gestures stop, and any calibration is
cancelled. Put down means both IR sensors see the desk for 1 s while the robot is level and still.

After a lift of at least 1 s, `lift.on_place` runs in order. Default: `save_figures`, `reset_map`, `zero_heading`,
`greet`, `look_around`. `face_user` is also available.

## Eyes

`animations.py` holds 9 emotions × 5 hardcoded keyframe animations, plus 3 blink patterns. Invoking an emotion picks
one at random, never the same one twice running, and re-invokes after 8–16 s. Between keyframes, values are eased
with the named `pytweening` function. Blinks occur every 2.5–7 s. Gaze follows the upper part of the nearest person's
box, mirrored because the screen faces the user (`oled.mirror_gaze`).

Emotion priority: scared (lifted) → annoyed (safety stop) → short reactions (gestures, AI mood, dashboard) → sleepy
(asleep or 5 min idle) → happy (person appeared) → curious (moving or searching) → sad (nobody for 2 min) → neutral.

`python main.py face --preview` writes every animation to `outputs/eyes_preview/`.

## Gestures

Open Palm, Closed Fist, Pointing Up, Thumb Up, Thumb Down, Victory and I Love You map to any assistant command,
`save_figures` or `none`. Settings are in `data/gestures.json`, editable on the dashboard or with
`python main.py gestures set Victory dance --hold 1`. Each has an action, amount, hold time, cooldown and on/off
switch. Minimum confidence is 0.6. A sleeping robot wakes on any gesture instead of acting on it.

## Curiosity and greetings

Curious: any sonar reads 3–30 cm (clears at 36 cm), or a non-person detection scoring at least 0.5 fills at least 8 %
of the image. The front sonar is ignored while a person is visible. The eyes look toward the sonar's side or the
object. This ranks below being lifted, safety stops, short reactions, sleep and the first seconds of seeing someone.

`greeter.py` has no face recognition. "New" means the number of people, held for 1 s, rises above the known count.
The known count falls only after fewer people have been visible for 45 s. Greetings are at least 30 s apart and are
silent while asleep or lifted. Boxes must score at least 0.5 and fill at least 2 % of the image.

## Dances

`assistant/commands.py: DANCES` holds wiggle, shimmy, twirl, cha-cha, moonwalk and robot. Each has equal forward/backward
and left/right time. One is chosen at random, never twice running, and every step goes through the normal safety
rules. A safety stop ends the dance. The eyes show `excited` while it runs.

## 3D orientation view

The Body card draws a small robot on a plain canvas: rotation, perspective and painter's-algorithm sorting in about
70 lines of JavaScript, with no library. It polls `GET /api/companion/pose` at 10 Hz. That small endpoint also feeds
`digital_twin/twin_live.m`.

## Voices

`assistant/voice.py: apply_style` post-processes speech from any engine: chipmunk (resample by the slider factor),
natural, deep (resample × 0.78), robot (70 Hz ring modulation), radio (350–3200 Hz band with soft clipping) and cave
(three fading echoes). `voice_gender` selects espeak-ng `+f3` / `+m3` or a Windows SAPI voice. A Piper model has one fixed
voice, so gender does not change it.

## Health check

`python main.py health`, or the first question when `python main.py` opens. Sections: software, system (disk, memory,
temperature, under-voltage), processes, sonars and IR, MPU-6050, OLED, camera and detector, optional motors, gestures,
speech, speaker, microphone, Bluetooth, API keys, internet, unit tests. Off the Pi it tests the simulated robot.
A crash in one check is recorded as a failure and the rest continue. The score counts a pass as 1, a warning as 0.5
and a failure as 0; skipped checks don't count. The exit code is 1 if anything failed.

## Digital twin

`digital_twin/` is base MATLAB (see its README). `run_twin` saves graphs, GIF animations, CSV data and a summary to `digital_twin/results/latest`, and keeps the last 5 runs. `twin_run` mirrors the control timing: 100 Hz physics, 25 Hz loops,
camera results delayed 120 ms. `twin_pid` follows `simple-pid` conventions (integral clamping, derivative on the
measurement). `twin_params` reads `data/calibration.json`.

## Calibration

`python main.py calibrate` or **Run full calibration** runs every step with no sub-menu: preflight, I2C, IMU at rest,
sonars, edge sensors, camera (lens too if a 9×6 checkerboard is shown), turn rate, motor dead zone, driving, and a
90° verification. Before driving it turns to find 18 cm of room beyond the stop distance, front and rear.

Driving speed is measured with the front/rear sonar when something is 25–160 cm away. Otherwise the terminal asks
for the distance; from the dashboard the speed is reported as not measured.

Results: `data/calibration.json` (`calibration_sim.json` in simulation), `robot_shell_settings*.json`, and
`report.md`, `calibration.json`, `calibration.png` under `outputs/`.

## Outputs

See the folder layout at the top of `companion/outputs.py`. Figures are saved every 3 minutes (at most 100 per
session), before a map is cleared by a pick-up, at shutdown, and from **Save figures**. Each dashboard figure also has
its own **Save** button. `/outputs/<path>` serves only known file types inside `outputs/`. Nothing is deleted
automatically, so clear old sessions when the SD card fills up.

At shutdown the motors are stopped first and the final figures are drawn afterwards.

## Configuration

`data/companion.json` overrides any value in `companion/config.py`:

```json
{"oled": {"driver": "sh1106", "rotate": 2}, "control": {"keep_distance": true}, "lift": {"on_place": ["reset_map"]}}
```

## Testing

`python main.py test` runs everything; `tests/test_companion.py` covers this package. Simulation covers the processes,
PID loops, lift handling, calibration flow, dashboard and saved files. MPU-6050, OLED and MediaPipe need the Pi.

## Tilt and pick-up on the face

`FacePlayer.pose` receives roll and pitch from the IMU. The eyes slide downhill on a slightly under-damped spring. From
`woozy_start_deg` (12) to `woozy_full_deg` (28) they sway, droop and change size unevenly, with the dizzy effect, and recover
slowly. If they slide the wrong way on your build, flip `tilt_sign_x` or `tilt_sign_y` in `OledConfig`. Being picked up always
starts with the `gasp` animation and the `picked_up` motif. `embarrassed` is a tenth emotion, shown when a search fails.
