# Simplified one-file control: `legacy/simplified_code.py`

Added 21 Nov 2026. A single standalone script that gives:

- a typed CLI that drives the motors (forward, backward, left, right, spin, stop, speed),
- an obstacle and edge stop on every move,
- a rough obstacle map built from the four sonars,
- a web dashboard with the camera, the map, sensor readings and drive buttons.
- since 23-24 Nov 2026 also: wheel encoders + calibration, OLED eyes, IMU, lift detection, touch pad, object
  detection, photos, a talking assistant (Groq/Claude, laptop microphone and speaker), objects on the map,
  drive by distance, go to an object, tasks with reminders, a focus timer, and face me + a greeter;
  plus a performance pass (a real 50 Hz control loop, less CPU).

It needs only the Python standard library plus `gpiozero` on the Pi. The camera uses `picamera2` or OpenCV if
one of them is installed, and the dashboard still runs without a camera. Nothing in `run_prototype/` imports it,
and it does not import anything except `robot_config.py`. If that file is missing, it uses a built-in copy of the
same pins.

## Running

```bash
python3 legacy/simplified_code.py               # on the Pi
python3 legacy/simplified_code.py --sim         # laptop: simulated robot on a simulated desk
```

| Flag | Effect |
| --- | --- |
| `--sim` | simulated motors and sensors (no GPIO) |
| `--port 8080` / `--host 0.0.0.0` | dashboard address |
| `--no-dashboard` | CLI only (also turns the camera off) |
| `--no-camera` | dashboard without video |
| `--no-edge` | ignore the IR edge sensors (e.g. if one is unplugged) |
| `--speed 0.5` | starting motor speed, 0.1 to 1.0 |
| `--no-detect` / `--model DIR` / `--detect-threads 2` | object detection off / NCNN model folder / its threads. See [Object detection](#object-detection-added-24-nov-2026) |
| `--no-lift` | no lift detection. See [Lift detection](#lift-detection-added-24-nov-2026) |
| `--no-touch` / `--touch-pin 7` | do not use the touch pad / its GPIO. See [Touch pad](#touch-pad-added-24-nov-2026) |
| `--no-ai` / `--groq-model M` / `--claude-model M` | assistant with offline rules only / the AI models. See [Assistant](#assistant-added-24-nov-2026) |
| `--https-port 8443` | the https copy of the dashboard, for the browser microphone (`0` = off) |
| `--no-imu` / `--imu-address 0x68` | do not use the IMU / its I2C address. See [IMU](#imu-added-24-nov-2026) |
| `--basic` | basic mode: motors, sensors, sensor map, obstacle stops and a camera-less dashboard only. See [Basic mode](#basic-mode-ignore-obstacles-and-motor-priority-25-nov-2026) |
| `--ignore-obstacles` | start with sonar obstacle stops off (`obstacles on` turns them back on) |
| `--reverse-motors` | both motors wired backwards: flip them (saved in `motors.json`). See [Motors wired backwards](#motors-wired-backwards-25-nov-2026) |
| `--slam` | start with SLAM on. See [SLAM](#camera-upside-down-invert-and-slam-25-nov-2026) |
| `--no-invert` | camera picture as it comes (default: rotated 180 deg, camera mounted upside down) |

Open `http://raspberrypi.local:8080` (or the Pi's IP address) from a laptop or phone on the same network.
Stop any other robot script first, because two programs cannot hold the same GPIO pins.

## Commands

Typed at `robot>` or in the dashboard's command box. The dashboard buttons send the same text.

| Command | Alias | Does |
| --- | --- | --- |
| `forward [s]` | `f` | forward for *s* seconds (default 1) |
| `back [s]` | `b` | backward (default 1 s) |
| `forward 30cm`, `back 20 cm` | | drive a **distance** (`0.5m`, `150mm`, `30 cm`, 1 cm-3 m): measured by the calibrated encoders, else timed. See [Drive by distance](#drive-by-distance-added-24-nov-2026) |
| `left 45deg`, `right 30 degrees` | | turn by an angle (same as `turn 45` / `turn -30`) |
| `left [s]` / `right [s]` | `l` / `r` | turn on the spot, default 90° (gyro-measured with an IMU, else timed) |
| `spin [s] [left\|right]` | | spin on the spot, default one full turn to the left |
| `turn <deg>` | | turn by an angle, + = left, − = right (1 to 1080) |
| `stop` | `x`, `s` | stop now |
| `speed <0.1-1>` | | motor PWM; with no number it shows the speed |
| `status` | | sensors, pose, encoders, current move, last block reason |
| `encoders` | | encoder counts, which wheels have been seen turning, metres rolled, calibration file, stuck wheel |
| `calibrate [cm]` then `calibrate moved <distance>` | `cal` | automatic encoder calibration: drives ≈ 25 cm, you say how far it went. See [Wheel encoders](#wheel-encoders-added-23-nov-2026) |
| `calibrate spin` then `calibrate turned <angle>` | | optional turning calibration (track width, used for the heading) |
| `calibrate hand [diameter] [turns]`, `calibrate next` | | calibrate by turning the wheels by hand instead |
| `calibrate cancel`, `calibrate status` | | stop (motors too) / show the loaded calibration |
| `sim turn left\|right [turns]` | | simulation only: turn a wheel "by hand" during `calibrate hand` |
| `imu`, `imu zero`, `imu calibrate` | | IMU readings / zero the shown heading / measure bias and save level |
| `sim lift [on\|off]`, `sim bump` | | simulation only: tilt the robot 35° / knock it |
| `lift`, `lift on\|off` | | lift detection state / switch |
| `see` (`look`, `what do you see`) | | what the camera recognises and where |
| `ask <text>` | `hey`, `ai` | talk to the robot: a question or an instruction ("ask turn left and take a photo"). See [Assistant](#assistant-added-24-nov-2026) |
| `assistant` | | which AI brains have a key, their last error, where the keys were read from |
| `photo` | `picture`, `snap` | save the camera picture to `photos/` (also the dashboard's 📷 Take photo). See [Photos](#photos-added-24-nov-2026) |
| `detect`, `detect on\|off` | | object detection status / switch |
| `touch`, `sim touch [hold]` | | touch pad state and counts / simulation: tap or hold it |
| `objects`, `objects clear` | | what the camera has recognised and placed on the map, with distance and direction from the robot now / forget them. See [Objects on the map](#objects-on-the-map-added-24-nov-2026) |
| `where is <thing>` | `where's …` | "The cup is 46 cm away, 55 deg to the left (seen 31 s ago, 92 % sure)" |
| `go to <thing>` | `goto` | look around if needed, face it, drive up to it (stops ≈ 20 cm in front). See [Go to an object](#go-to-an-object-added-24-nov-2026) |
| `find <thing>` | | look around until it is seen and turn to face it, no driving |
| `go home` | `come back` | drive back to where the map started (0, 0) |
| `remind me <when> <what>` | | "remind me in 20 minutes to drink water", "remind me at 5:30 pm to call mom". See [Tasks and reminders](#tasks-and-reminders-added-24-nov-2026) |
| `todo <task> [when]` | `task` | add a task: "todo buy milk by friday" |
| `tasks` | | the open tasks, soonest first |
| `done <#n or words>`, `undone <#n>` | `reopen` | finish / reopen a task |
| `tasks remove <#n or words>`, `tasks clear done` | | delete one / delete the finished ones |
| `face me` | `look at me` | turn to face you once. See [Face me and the greeter](#face-me-and-the-greeter-added-24-nov-2026) |
| `face me on` / `face me off` | | keep facing you / stop |
| `greet on` / `greet off`, `people` | | the greeter switch / both features' state |
| `sim person <deg>` / `sim person off` | | simulation only: a person 60 cm away at that angle (+ = left) |
| `phone`, `phone devices`, `phone use <name or address>`, `phone forget` | | Bluetooth phone presence. See [Bluetooth phone presence](#bluetooth-phone-presence-added-24-nov-2026) |
| `sim phone near\|far\|away` | | simulation only: move the simulated phone |
| `gestures`, `gesture map <Name> <action>` | | what each laptop-camera gesture does. See [Gestures](#gestures-from-the-laptop-camera-and-rock-paper-scissors-added-24-nov-2026) |
| `rps`, `rps stop`, `rock` / `paper` / `scissors` | | rock paper scissors, first to two |
| `dance [song]`, `dance stop`, `dance status` | `boogie` | play a random song (or that one) and dance to its beat. See [Sound effects and dance](#sound-effects-and-dance-added-24-nov-2026) |
| `songs` | `dance list` | the songs it can dance to (built in + files in `songs/`) |
| `sounds`, `sounds on` / `sounds off`, `sound <name>` | `beep <name>` | sound effects (played by the dashboard page) |
| `weather [city]`, `weather home <city>`, `joke`, `wiki <topic>`, `convert 10 usd to inr` | `look up …` | free web APIs. See [Web APIs](#web-apis-ideas-and-accounts-added-24-nov-2026) |
| `idea <text>`, `ideas`, `ideas search <words>`, `ideas forget <#n or words>` | | the ideas notebook |
| `focus [minutes]` | `pomodoro` | a focus session (default 25 min, 1-180). While one runs, `focus` shows how it's going. See [Focus timer](#focus-timer-added-24-nov-2026) |
| `focus stop` | | end the session (or skip the break) |
| `map reset` | | clear the map **and the objects on it**, reset the pose to (0, 0, 0°) |
| `help`, `quit` | `?`, `q` | |

Moves are capped at 30 s. A new command replaces the current move. Moves run in the background, so the prompt
stays free and `stop` acts at once. Dashboard keys: arrow keys make short moves and Space stops.

With a working IMU the default turns are measured by the gyro (see [IMU](#imu-added-24-nov-2026)). Without one, the "≈ 90°" and "one full turn" values are time estimates:
`t = angle / (2 · speed · WHEEL_SPEED_AT_FULL / TRACK_WIDTH)`, using the same rough constants as
`dashboard/mapping.py` (0.25 m/s, 0.12 m). Moves are still timed, not measured, even with calibrated encoders
(the encoders correct the *pose*, not the move length), so the real angle depends on the floor and the battery.
Give a time (`spin 3`) if you want something exact.

## Pins

These come from `run_prototype/robot_config.py`, the same as every other script.

| Part | GPIO (BCM) |
| --- | --- |
| Left motor | forward 22, backward 23, enable 13 |
| Right motor | forward 27, backward 17, enable 12 |
| Sonars (trig/echo) | front 24/25, left 4/18, right 21/9, rear 10/11 |
| IR edge | front 19, rear 26 (LOW = floor) |
| Wheel encoders (A/B) | left 5/6, right 20/16 (`robot_config.ENCODERS`) |
| Touch pad (TTP223) | I/O GPIO 7 (physical pin 26), VCC 3.3 V (`robot_config.TOUCH["top"]`) |
| IMU (MPU-6050) | I2C bus 1: SDA GPIO 2, SCL GPIO 3, 3.3 V, GND, address 0x68 (shared with the OLED) |

## Safety rules

A control thread runs at 50 Hz. On each tick it reads every sensor, checks the current move, and drives or stops
the motors.

| Move | Blocked when |
| --- | --- |
| forward | front IR sees no floor, or front sonar ≤ 20 cm |
| backward | rear IR sees no floor, or rear sonar ≤ 20 cm |
| left / right / spin | either IR sees no floor, or left or right sonar ≤ 8 cm |
| any (IMU working) | tilted more than 20° from level (lifted / tipping) |
| any (touch pad) | touching the pad stops a running move |
| any (lift detection) | the robot is lifted (both IR dark, tilted > 30°, or handled) |
| forward / backward (IMU working) | stops on a jolt ≥ 0.6 g, from 0.3 s into the move (bump) |

- **Fail safe:** if a sensor a move needs cannot be read (it failed to open or a read raised an error), that move
  is blocked and the reason is printed. Use `--no-edge` to run with the IR sensors disconnected. There is no
  bypass for the sonars.
- **Start margin:** a move only *starts* if the sonar has 3 cm more clearance than the stop limit
  (`START_MARGIN`). Without it, sensor noise at exactly 20 cm lets the robot start, then stop on the next tick,
  over and over.
- The reason for the last block is shown by `status` and on the dashboard, and is also printed as `STOPPED: …`.

## Drive by distance (added 24 Nov 2026)

`forward 30cm`, `back 20 cm`, `forward 0.5m`, `forward 150mm` (also `30 centimetres`, `1 meter`; 1 cm to 3 m,
`parse_distance`). A bare number is still seconds (`forward 2`). On the dashboard, the **Move for** row has 5 /
10 / 20 / 30 cm buttons next to the times, and the D-pad's forward/back then drive that far.

**How it works** (`Robot.start(..., dist_m=)` and the control loop):

- With **calibrated encoders**, the move records the counts at the start (`enc0`). Every 20 ms tick the loop works
  out how far each wheel has rolled (`|Δcounts| × metres per count` from the calibration) and ends the move when
  the wheel that rolled **further** reaches the distance minus `DRIVE_LEAD_M` (0.5 cm, for coasting). The further
  wheel is used so a dead or slipping encoder can never make it overshoot. The event says "Drive done: 29.6 cm
  (encoders)". The reply says "Forward 30 cm, measured by the encoders".
- The time estimate (`distance / (speed × 0.25 m/s)`) is kept as a **backstop**: twice that time + 0.5 s. If the
  backstop ends the move, the log says the encoders did not count the distance (wheel slipping, encoder
  unplugged?).
- **Encoders lost** during the drive (they stop answering, or the calibration is removed): the move switches to
  the plain time estimate from its start ("Encoders lost during the drive - finishing it on time").
- **No calibration** (or no encoders): the move is timed from the motor model and says so: "Forward ~10 cm, timed
  (encoders not calibrated - 'calibrate')".
- Every safety rule still applies: it stops at obstacles, edges, a stuck wheel, a bump, lift and touch. Moves are
  still capped at 30 s.
- `DRIVE_LEAD_M` is a guess (0.5 cm). The simulated robot stops dead; the real one coasts a little. After a few
  `forward 30cm` with a ruler on the robot, set it to the average overshoot.

**Also:** `left 45deg` / `right 30 degrees` turn by an angle (gyro-measured with an IMU). The assistant may now
ask for `forward <N>cm` (2-50 cm, `AI_MAX_DRIVE_M`), and the offline rules understand "go forward 20 cm", "move
back 15 centimetres", "drive forward 0.3 m".

Tested 24 Nov 2026 in simulation (35 checks): parsing (8 forms, 2 refused); assistant and offline forms; with
encoders `forward 20cm` → really 19.5 cm, `forward 10 cm` → 9.6 cm, `back 15cm` → 14.8 cm (the simulator's
wheel truth; it has no coasting); seconds still work; uncalibrated → timed with the hint; encoders unplugged
mid-drive → finished on time; `forward 50cm` towards a book 29 cm away stopped at the 20 cm limit; `left 45deg`,
`right 30 degrees`; out-of-range angle and distance refused. Not yet tested on the robot.

## Wheel encoders (added 23 Nov 2026)

Ported from `run_prototype/deskbot/runtime/wheels.py` (stuck-wheel logic) and
`run_prototype/calibrate_encoders.py` (calibration), without the multi-process plumbing.

**Reading.** `RealHardware` opens one `gpiozero.RotaryEncoder(a, b, max_steps=0)` per wheel (unbounded count).
`encoders()` returns `(left, right)` steps multiplied by the calibrated sign, so forward is positive on both sides.
If either encoder fails to open, both are closed, the reason is kept in `encoder_error`, and the robot runs as
before (pose from motor timing, no stuck check). `--no-encoders` skips them entirely.

**Calibration is automatic** (the `calibrate` command, or **Auto calibrate** on the dashboard). The robot drives
by itself, and you only give feedback on how far it really went:

| Step | CLI | Dashboard |
| --- | --- | --- |
| 1. drive | put the robot down with ≈ 45 cm clear in front, mark its front edge, `calibrate [cm]` (default 25 cm) | **Auto calibrate**, then **Drive** |
| 2. feedback | measure from the mark, `calibrate moved 24.5cm` (also `245mm`, `0.245m`; a bare number = cm) | type the cm, **Save** |
| 3. optional: turning | `calibrate spin`: it spins left ≈ one turn by itself | **Calibrate turning**, then **Spin** |
| 4. optional feedback | `calibrate turned 340` (degrees; also `1 turn`, `0.9 turns`) | type the degrees, **Save** |
| by hand instead | `calibrate hand [diameter] [turns]`, then `calibrate next` per wheel (robot lifted, motors off) | **By hand…** |
| abort / show | `calibrate cancel` (stops the motors, keeps the old calibration), `calibrate status` | **Cancel**, Wheel encoders card |

How it works:

- **The drive.** This is a normal move (`self.move`), so every safety rule applies: sonar, IR edge and stuck wheel.
  The drive time is `target / (speed × 0.25 m/s)`, clamped to 0.5-8 s, using the same rough motor model as
  `forward`. The model only picks the time; the result comes from your measurement. Before starting, it runs the
  same start check as `forward` and refuses with the reason if the way is blocked. It records the **raw** counts
  (`raw_encoders()`, no sign applied) at the start.
- **End of the move.** The control loop notices that the calibration move has ended (time up, or stopped by
  safety or `stop`). It waits `CAL_SETTLE_S` (0.3 s) for the robot to coast to a stop, then reads the counts. If
  a wheel counted fewer than `MIN_CAL_COUNTS` (5), it fails with the reason: either the stop reason, or that
  wheel's GPIO pins. If it stopped early, the dashboard says so and asks you to measure what it actually did.
- **Distance maths.** Driving straight, both wheels roll the measured distance `D`, so
  `metres per count = D / |Δcounts|` per wheel. The sign of Δcounts gives each wheel's direction. To keep the file
  format that `run_prototype` also reads, this is stored as counts per revolution of the assumed wheel diameter
  (`cpr = |Δ| · π · Ø / D`). Ø cancels out when it is read back. A difference of more than 15 % between the
  wheels saves anyway, with a note that the robot probably curved.
- **Spin maths.** On a spin to the left, `θ = (d_right − d_left) / track_width`, so
  `track_width = (d_right − d_left) / θ_you_measured`. The wheel distances come from the distance calibration.
  It is saved as `track_width_m` (accepted 4-50 cm, otherwise refused). Odometry then uses it for the heading in
  place of the built-in 12 cm. A new distance calibration drops it, because it was derived from the old
  metres-per-count, and the reply suggests `calibrate spin` again.
- **Silent sonars do not abort a calibration move.** Calibration moves pass `sonar_optional=True` to
  `why_unsafe`: a sonar with no reading is ignored, but a sonar that sees an obstacle still stops it. The IR edge
  check and the stuck-wheel check are unchanged. You are standing next to a short, marked drive. Found on the
  robot on 23 Nov 2026: the front sonar dropped out mid-drive (it gives no echo on and off, even through gpiozero's
  own driver, which points to its wiring), and every calibration stopped there. Normal moves stay fully
  fail-safe. Before driving, the target is shortened so it ends 2 cm before the front stop distance, and it is
  refused if there is less than 30 cm of room.
- **While calibrating** other moves are refused. During a hand calibration the pose is frozen, because the robot
  is lifted. During an automatic drive the pose keeps updating, because the robot really moves.
- **Simulation.** The simulated robot has a "ruler": the dashboard shows "Simulation: it really moved 25.2 cm" /
  "really turned 362°", so the whole flow can be tested. Simulated results go to `encoders_sim.json`.

**Saved and loaded by default.** The result is written to `encoders.json` **next to the script** and applied at
once (no restart). After that the count baselines restart, because a changed sign would otherwise show up as a
jump. On every start the script loads the first valid file of:

1. `encoders.json` next to the script (what `calibrate` writes),
2. `run_prototype/data/encoders.json` (the full runtime's `calibrate_encoders.py`, same format).

It logs which one it used, for example `[encoders] Encoder calibration on 2026-11-23 14:20 from
/home/snu123/encoders.json: wheel 65 mm, L 40.0 / R 40.0 counts per turn ('calibrate' to redo)`. It is only
replaced when you run `calibrate` again and finish it. A file that is missing, unreadable, or has a zero or
negative value is skipped.

```json
{"method": "auto", "wheel_diameter_m": 0.065, "left_counts_per_rev": 357.4, "left_sign": 1,
 "right_counts_per_rev": 357.4, "right_sign": 1, "measured_m": 0.252, "counts": [443, 444],
 "track_width_m": 0.1207, "measured_deg": 362.0, "calibrated_at": "2026-11-23 20:13"}
```

Only `wheel_diameter_m`, `*_counts_per_rev` and `*_sign` are needed. The rest records how it was measured, plus the
optional track width. A file from `run_prototype/calibrate_encoders.py` loads as a "hand" calibration.

If the file cannot be written (read-only folder), the calibration is still used until the program exits, and the
reply says so. In simulation it is saved to `encoders_sim.json` instead, so it never mixes with the real robot's
file. Use `sim turn left 10` / `sim turn right 10` to "turn the wheels by hand" there.

**Sonars are pinged one at a time** (`SonarScanner`, added 23 Nov 2026). gpiozero's `DistanceSensor` has a lock
so two never ping at the same instant, but each fires as soon as the previous echo ends. The previous ping is
still bouncing around the desk, so the next sensor hears it. On the robot the right sonar (normally 200 cm) read
the front sonar's 16 cm 11 times in 4 s, and the rear one dropped to 18 cm 70 times. Each false reading stopped
the running move. The scanner uses one thread: trigger, time the echo with the pin factory's edge timestamps (lgpio
alerts), wait 15 ms (`GAP`), then the next sensor. A full sweep takes about 60-250 ms. Each sonar reports the
median of its last 3 readings (2 readings: the closer one; readings older than 1 s are dropped), so a single
stray echo is ignored. A sonar with no echo for 2 pings says why in the "unreadable" message (its TRIG/ECHO pins).
After the change, on the robot: left 200, right 55-57, rear 28 cm, all steady, with no false short readings.

**Odometry.** Each 50 Hz tick, when calibrated: `dl, dr = Δcounts × π·D / counts_per_rev`,
`d = (dl+dr)/2`, `dθ = (dr−dl)/track_width` (calibrated `track_width_m`, else the built-in 0.12 m), and the robot advances `d` along the mid-tick heading `θ + dθ/2`.
A jump above `MAX_STEP_M` (0.1 m in 20 ms, i.e. 5 m/s) is treated as a glitch and skipped. Without a calibration,
the pose still comes from motor timing (`v = PWM × 0.25 m/s`). `status` and the dashboard show which one is in
use ("pose from encoders" / "pose from motor timing"). `map reset` also zeroes "metres rolled".

**Stuck wheel.** `Robot._which_stuck()` compares what the motors were driven with during the last tick
(`self.applied`) with the counts:

| Rule | Constant |
| --- | --- |
| Commands weaker than this are ignored (may not overcome friction) | `STUCK_MIN_COMMAND` 0.2 |
| A wheel counts as turning after this many counts | `STUCK_MIN_COUNTS` 2 |
| Commanded but not turning for this long means stuck | `STUCK_AFTER_S` 0.8 s |
| A wheel whose encoder has **never** changed is not judged (it may be unplugged) | `wheel_working` |

On a stuck wheel the move is cancelled, the motors stop, and `blocked` / the event log say
`left wheel stuck (motor on, encoder not turning)`. The next move clears it. If both wheels are stuck it says
`both`.

**Simulation.** `SimHardware` integrates each wheel's distance from the motor command
(`PWM × 0.25 m/s × dt`) and reports counts at 360 per revolution of a 65 mm wheel (pre-calibrated), so the
simulated pose comes from the encoders, the same path as on the robot. 

Tested on 23 Nov 2026: in simulation, forward 0.5 s rolled 0.06 m on both wheels and moved the pose 0.06 m;
a jammed wheel stopped a turn after 0.8 s with "left wheel stuck" (the `sim stuck` test command has since been removed). With a mocked gpiozero: encoders
uncalibrated, encoder busy (`OSError` shown in `status`), and `--no-encoders`. On the Pi: both encoders opened
(counts 0/0 at rest, not yet calibrated). Calibration in simulation: start, a move refused, `next` with no turning
refused, both wheels turned, saved, and reloaded on restart; the pose stays at (0, 0) while the wheels are turned.
On the Pi: start, move refused, `next` with no turning refused with the GPIO 5/6 hint, cancel.
Automatic calibration in simulation: drive (stopped early by a simulated box at 20 cm, reported, measurement still
accepted), `moved` while driving refused, a move refused, `moved banana` refused. Distance gave 0.571 mm/count
from 9.6 cm and 0.569 from 25.2 cm (true 0.567). Spin gave a track width of 12.1 cm (true 12.0). The dashboard
wizard was checked in a browser in the measure step.

## OLED screen (added 23 Nov 2026)

128×64 monochrome OLED on I2C bus 1 (SDA GPIO 2, SCL GPIO 3, 3.3 V, GND), address **0x3C**, SSD1306 driver (SSD1315
modules work with it). It is drawn with `luma.oled` and Pillow, both already installed on the Pi. Laptop: Pillow
only; the screen is then simulated.

| Command | Dashboard | Shows |
| --- | --- | --- |
| `oled eyes` (default) | **Eyes** | two animated eyes that react to the robot (below) |
| `oled status` | **Status** | IP:port, mode/move/speed, the four sonars, IR, encoder counts + calibrated, last block |
| `oled off` | **Off** | blank |
| `oled <text>` or `oled say <text>` | text box, Enter | the text for 6 s in the biggest font that fits (`
` = new line; words are not split) |
| `oled ip` | **Show address** | `Dashboard http://<ip>:<port>` for 8 s; also shown for 8 s at every start |
| `oled` | header of the card | driver/address, or why the screen is unavailable |

Flags: `--no-oled`, `--oled-driver ssd1306|sh1106` (most 1.3" modules are SH1106), `--oled-address 0x3D`,
`--oled-rotate 2` (mounted upside down).

**Eyes.** `Oled._expression()` picks a face and a gaze from `robot.status()`, in this order:

| Situation | Face |
| --- | --- |
| a wheel is stuck | sad, looking down |
| calibrating | focused (narrow eyes) + "calibrating" |
| for 3 s after a block: obstacle / edge / stuck | angry / scared (tall) / sad |
| for 4 s after a calibration: success / failure | happy (^ ^) / sad |
| moving | normal, looking that way (forward up, back down, left/right sideways) |
| no command or event for `OLED_SLEEPY_AFTER_S` (90 s) | sleepy (thin lines) |
| otherwise | normal, glancing left/right every 2-5 s |

Each face is (width, height, dx, dy, eyelid tilt). Every frame the drawn pose moves 45 % of the way to the target,
so faces blend smoothly. Blinks (height 2 px for 0.12 s) come every 2-6 s. Eyelids are black triangles cut from
the top corner: the inner corner for angry, the outer corner for sad. Happy cuts away the lower half with an
ellipse.

**Threading and errors.** One `oled` thread draws at about 10 fps and is the only thing that talks to the
screen. It sends a frame only when the image changed (a full frame is ~1 KB, about 25 ms at 400 kHz). The same
frame is kept as a PNG for the dashboard mirror (`GET /oled.png`, polled every 250 ms while the tab is visible).
If the screen can't open or a write fails (loose wire), the reason is logged once and shown in the card, and the
screen is reopened every 2 s (`OLED_RETRY_S`). The robot keeps running throughout. On exit the screen is cleared. A drawing error
shows a blank frame and is logged; it never stops the robot.

**When the screen is not answering**, every `oled` reply says so ("...but NOT on the screen right now: not
answering on I2C at 0x3c - loose wire?"), and the dashboard card shows the status in red. Commands still change
what is drawn, and the dashboard mirror keeps working. Found on the robot on 23 Nov 2026: the screen came and
went on the bus (`i2cdetect -y 1` showed 0x3c, then nothing in 5 out of 5 scans; 0 of 20 writes got through)
with nothing else running and the bus lines idle-high. That is a loose VCC/GND/SDA/SCL contact, not software.

Tested 23 Nov 2026: every face, the status screen and the text screens rendered and checked as images. On the Pi:
`ssd1306 at 0x3c on I2C bus 1` opened, the mirror PNG was served, and say / status / eyes switched with no
display errors. The dashboard card was checked in a browser (simulation).

## IMU (added 24 Nov 2026)

An MPU-6050 (an MPU-6500/9250 also works) on I2C bus 1 at `0x68`, sharing GPIO 2/3, 3.3 V and GND with the OLED.
It is read with **smbus2** directly. That library is already installed because `luma.oled` needs it, so no
Adafruit/Blinka is required. The IMU is optional: if it is missing or fails, everything works as before.

**What it is used for**

| Use | How |
| --- | --- |
| Heading of the pose | the heading change on every control tick comes from the gyro, and distance still comes from the encoders (or motor timing). A wheel that slips or skids still counts, but the gyro does not care. The pose source then reads `encoders + gyro` / `motor timing + gyro`. |
| Turns by angle | `left`, `right`, `spin` with no number, and `turn <deg>`, stop when the gyro has turned the angle minus 3° (`IMU_TURN_LEAD_DEG`; the robot coasts the rest). Backstop: twice the time estimate + 0.5 s. If the IMU drops out mid-turn, the turn ends at the plain time estimate. With a number (`left 0.5`) it is still seconds. |
| Tilt stop | tilted more than 20° from level (`IMU_TILT_STOP_DEG`): no move starts and a running one stops: "robot tilted 34 deg (lifted or tipping?)". The eyes go scared. |
| Bump stop | forward/backward only: a jolt of 0.6 g or more (`IMU_BUMP_MS2`) stops the move ("bump detected"). It is ignored for the first 0.3 s of a move, because the motors starting jolt it too. A backup to the sonars, not a replacement. |
| Turning calibration | `calibrate spin` also records the gyro's angle; `calibrate turned gyro` (or the dashboard's "Use the gyro" button) uses it instead of a hand measurement. |

**Commands:** `imu` (heading, turn rate, tilt, still/moving, temperature, gyro bias, where "level" came from),
`imu zero` (sets the *shown* heading to 0; the pose is untouched, use `map reset` for that), `imu calibrate`
(robot still on a flat desk: measures the gyro bias and saves this position as level).
Flags: `--no-imu`, `--imu-address 0x69` (board with AD0 high).

**How it works** (`Mpu6050`, `Imu`)

- Set-up registers: reset, wake on the gyro PLL clock, DLPF `CONFIG=3` (~44 Hz), 100 Hz sample rate, gyro ±500 °/s
  (65.5 LSB per °/s), accel ±4 g (8192 LSB per g). Each sample is one 14-byte block read from `0x3B`. The Linux I2C
  driver makes each transfer atomic, so the IMU and OLED threads can share the bus.
- The `imu` thread reads 100 times a second. **Start-up:** the robot must be still for 1 s. The mean gyro reading
  is the bias, and the mean accel magnitude is "1 g" for this sensor (`g_ref`, which absorbs its scale error). If
  the readings spread too much (gyro > 0.06 rad/s, accel > 0.6 m/s², or motors on), it tries again for up to 5 s,
  then accepts and says so. The IMU is not used for heading or safety until this is done.
- **Any mounting works.** "Up" is the unit vector of gravity as measured while standing level. It comes from
  `legacy/imu.json` (saved by `imu calibrate`), or is taken at start-up when there is no file. Tilt = the angle
  between "up" and the low-passed accel. Turn rate = the bias-corrected gyro vector · up, which is CCW-positive
  (left), the same sign as the pose. So the board can be mounted upside down or on its side.
- **Drift control:** when the gyro is quiet (< 0.03 rad/s), the accel magnitude is within 0.3 m/s² of `g_ref`, and
  the motors are off for 0.5 s, the robot is *still*: the bias follows the raw gyro (α = 0.01 per sample, about 1 s
  time constant) and the heading is frozen. Heading only drifts while the robot moves.
- **Bump:** accel minus a ~1.7 Hz low-pass (α = 0.1). The thread keeps the peak since the control loop last asked,
  so a 20 ms knock between two 50 Hz ticks is not missed.
- **Robot side:** every tick, `Robot._read_imu` tells the IMU whether the motors are on, takes a snapshot (yaw,
  tilt, shock peak), and passes the yaw difference to `_odometry`. The raw yaw is never reset (`imu zero` only
  moves a display offset), so the pose never jumps.
- **Faults:** the IMU is looked for every 2 s. The reason is shown in `status`, `imu`, the dashboard card and the
  log ("not answering at 0x68 - loose wire?", "smbus2 not installed", "I2C bus 1 is off"). A read error or an
  all-zero accel (sensor reset or power dip) means reconnect and measure the bias again. Meanwhile heading falls
  back to the encoders, turns are timed, and the tilt and bump checks are off. A missing IMU never blocks driving.
  This is unlike the sonars, because the IMU is an extra, not the primary obstacle sensor.

`legacy/imu.json`: `{"up": [x, y, z], "gyro_bias": [...], "sensor": ..., "calibrated_at": ...}`. Simulation uses
`imu_sim.json`. The saved bias is informational: the bias is always measured fresh at start-up.

**Simulation:** `SimImuSource` gives turn rate from the wheel commands, gravity, a constant bias of
(0.23, −0.17, 0.34) °/s and noise. `sim lift [on|off]` tilts it 35°, and `sim bump` knocks it with 0.9 g for 50 ms.

Tested 24 Nov 2026 in simulation: the bias was measured as +0.24/−0.19/+0.36 °/s (true 0.23/−0.17/0.34).
`left` → "Turn done: 88 deg (gyro)", `right` 90°, `turn 45` 45°, `turn -45` 43°, `spin` 358°, and the pose heading
came back to −0.1° after all of them. A lifted robot refused `forward` ("robot tilted 34 deg"). `sim bump` while
driving stopped it ("bump detected (0.8 g jolt)"), and a bump 0.1 s into a move was ignored. `imu calibrate`
saved `imu_sim.json`. `imu zero` left the pose unchanged. `calibrate spin` → gyro 358° → `calibrate turned gyro`
gave a 12.0 cm track width (the simulated truth). `--no-imu` gave "Turn left ~90 deg, timed (no IMU)". `/api/state`
carries the `imu` block, and the page script passes `node --check`. **Not yet tested on the robot:** on 21 Nov the
MPU-6050 did not answer on bus 1 (wiring). Once `i2cdetect -y 1` shows `68`, run `imu`, then `left` and check that
the heading goes **up** (+90).

## Object detection (added 24 Nov 2026)

YOLO26n exported to NCNN, the same model and the same pre/post-processing as
`run_prototype/deskbot/vision/ncnn_detector.py`, copied into the file (`letterbox`, `decode`, `nms`,
`read_model_metadata`, `Detector`). It does not include the ByteTrack tracker.

**Needs** numpy, OpenCV and ncnn. On the Pi, the system `python3` has neither OpenCV nor ncnn, but the project
venv has both. **Since 24 Nov 2026 the script switches to the venv by itself** (`use_project_venv()`, called first
thing in `main()`): if `cv2`, `ncnn` or `numpy` is missing (checked with `importlib.util.find_spec`, *not* by
importing, because ncnn must only be imported after `OMP_NUM_THREADS` is set), it prints

```
[start] cv2, ncnn not installed for /usr/bin/python3 (needed for object detection) - restarting with the project venv: /home/snu123/deskbot/.venv/bin/python
```

and `os.execv`s the same command line with the first existing of `~/deskbot/.venv/bin/python` and
`../run_prototype/.venv/bin/python` (`VENV_PYTHONS`). That venv is created with `--system-site-packages`, so
gpiozero, picamera2 and luma stay visible. This happens before any GPIO is opened, so nothing is held twice. It
is skipped when detection cannot run anyway (`--no-detect`, `--no-camera`, `--no-dashboard`), when no venv
exists, when it is already running in that venv, and after one try (environment variable
`SIMPLIFIED_VENV_TRIED=1`, so it can never loop). If the venv also lacks a package, detection reports
"unavailable (ModuleNotFoundError …)" and everything else runs. So plain `python3 simplified_code.py` is enough;
`~/deskbot/.venv/bin/python simplified_code.py` still works too. Added after "unavailable: module not found: no
module named cv2" showed up on the robot. **Model:** `--model <folder>`, else the first folder holding a `*.param` among
`<script dir>/models/yolo26n_ncnn_model`, `../run_prototype/models/yolo26n_ncnn_model` and
`~/deskbot/models/yolo26n_ncnn_model` (where it is on the Pi). imgsz and class names come from the export's
`metadata.yaml`; without it, 320 px and the built-in 80 COCO names are used.

| What | How |
| --- | --- |
| `see` (also `look`, `what do you see`) | "I see: cup (82 %, ahead, ~29 cm by the front sonar), person (64 %, 20 deg left)". The direction comes from the box centre and the camera's horizontal field of view (`CAMERA_HFOV_DEG` 62.2°, Pi camera v2), + = left like the pose. Within 10° of straight ahead, the front sonar distance is added. |
| `detect`, `detect on\|off` | status (model, ms per frame, frames done), pause / resume |
| Dashboard | boxes + labels drawn on the video; under it the model and ms, a chip per object (label, %, direction) and Pause/Resume detection |
| Eyes | when idle they look toward the biggest object; a person coming into view gives 2 s of happy eyes |
| `/api/state` | `vision`: status, enabled, model, ms, fps, runs, detections [{label, score, box [x1, y1, x2, y2], bearing_deg, size}] |

Flags: `--no-detect`, `--model <folder>`, `--detect-threads 2`. With `--no-camera` or `--no-dashboard` there is
no camera, so no detection.

**How it works**

- The `detector` thread takes the camera's newest raw frame (`Camera.frame`, now kept next to the JPEG), skips
  frames it has already done, and runs at most every 0.3 s (`DETECT_PERIOD_S`).
- Steps: letterbox to 320 × 320 (resize keeping the shape, grey 114 padding, BGR → RGB, CHW, 0 to 1), then the NCNN
  network (input `in0`, output (84, N) = cx, cy, w, h + 80 class scores), best class per anchor, score
  > 0.35, class-aware NMS at IoU 0.5, then undo the letterbox and clip to the frame.
- `DETECT_CONF` is 0.35, not run_prototype's 0.10. That 0.10 relies on ByteTrack to filter the weak boxes;
  with no tracker, 0.35 keeps the flicker down.
- `OMP_NUM_THREADS` is set and NCNN uses 2 threads (`DETECT_THREADS`), so 2 of the Pi 4's 4 cores stay free
  for the 50 Hz control loop, sonars, IMU, camera and server.
- The camera thread calls `Detector.draw` before encoding each JPEG, so the boxes are drawn on the stream.
  They come from the last detection, so they can lag the video by up to one detection (~0.3 s). Detections
  older than 1.5 s are dropped.
- Faults: no model, a missing package, or 5 errors in a row means status "unavailable/stopped (reason)", and
  the robot, video and dashboard carry on without it.

Tested 24 Nov 2026 **on the Pi** (copied to `/tmp`, project venv): on `models/sample.jpg` it found bus 84 %,
person 83 / 76 / 74 / 39 %, the **same boxes and scores as run_prototype's `NcnnDetector.predict`** at the
same threshold, in 213 ms. The drawn boxes were checked by eye. Live camera: "141 ms per frame", 30 detections in
10 s (3.3 per s). The camera was pointing at lockers, which are not a COCO class, so it correctly saw nothing. The
first live try failed with "Pipeline handler in use by another process", because something else had the camera
at that moment; the retry worked. On the laptop: the decode/NMS step on a synthetic output kept 1 of 2
overlapping cups, the "no model" message was correct (the laptop's model folder is empty, and Windows blocks
the NCNN DLL anyway), and `see`, `detect on/off`, the eyes, the API and the page script all worked with injected
detections.

## Robustness, notes and presentation mode (added 24 Nov 2026)

**Nothing that fails stops the robot.** Every feature is started through `guarded()` in `main()`: if it raises
(a missing package, a busy port, no Bluetooth adapter), it is skipped, a note appears on the dashboard, and the
full traceback goes to `errors.log` next to the script. Shutdown closes each started feature on its own, so one
failing `close()` can't block the others.

| Where | What happens on an error |
| --- | --- |
| a feature at start-up | skipped, note "could not start (…) - running without it" |
| a background thread | `threading.excepthook` turns it into a note ("stopped after an error (…)") instead of a traceback in the terminal and a silently missing feature |
| the **50 Hz control loop** | it used to protect only the sensor read and the map; an error anywhere else (lift checks, odometry, safety rules) would have ended the thread, and with it every safety check. Now `_loop` runs `_loop_inner` in a guard: on an error the move is cancelled, the motors are stopped, a note is made, and the loop starts again 0.2 s later |
| any command (CLI, dashboard, assistant, gestures) | `execute` wraps `_execute`: the error becomes a reply ("Sorry, that command hit an error (…)") and a note |
| printing a reply the terminal can't show (Windows code pages and emoji) | printed with `?` instead of crashing the CLI |
| one dashboard card's script | each card renders in its own `try`, so a bug in one never blanks the page |

**Notes card** (`/api/state` → `notes`, `collect_notes`): the features' own status (camera, detection, OLED, IMU,
encoders, each IR and sonar, touch pad, noise-filter faults, Bluetooth, web APIs, the assistant's keys and errors)
plus everything in `HEALTH` (start-up failures, thread errors, control-loop restarts, command errors; a repeated
note just counts up). Levels: ⛔ error, ⚠️ warning, ℹ️ info. It hides itself when there is nothing to say; the
header shows ⚠ and the count.

**▶ Present** (header button, or open the page with `?present=1`): hides the Notes card, the ⚠ count, the warning
banner, error replies, red hints and every card status that says unavailable / error / failed, plus the layout
tools. The choice is remembered in the browser. Tested by injecting errors: a `ZeroDivisionError` in the control
loop mid-move stopped the motors, was noted, and the loop was ticking again within 0.5 s (25 ticks); a command
error, a dying thread and a feature that can't start all became notes with tracebacks in `errors.log`.

## Dashboard layout (added 24 Nov 2026)

- **✎ Layout** turns on edit mode: each card gets a ⠿ handle (drag it with the mouse, a pen or a finger:
  pointer events, so touch screens work), ⇔ (wide / normal) and ✕ (remove). **✓ Done** or Esc ends it.
- **＋ Cards** lists every card with a tick box to show or hide it, and **Reset layout**.
- Order, hidden cards and widths are kept per browser (`localStorage` key `robot-layout`). Cards added in later
  versions appear in their default place in an older saved layout.
- New look: a soft gradient background, layered shadows that lift on hover (separate ones for dark mode),
  16 px corners, a frosted header, a short fade-in, and `grid-auto-flow: dense` so wide cards leave no holes.
  `prefers-reduced-motion` turns the animations off.
- URL switches: `?present=1`, `?edit=1`, `?map=conf`.
- 18 cards: Notes, Camera, Assistant, Phone, Gestures, Rock paper scissors, APIs, Ideas, Accounts, Focus, Tasks,
  Drive, Sensors, IMU, Wheel encoders, OLED screen, Map (sensor fusion), Activity. Checked in a browser at 1400 px
  (normal, edit, presentation, confidence map) and at 375 px (one column, no sideways scroll).

## Noise filter and sensor fusion (added 24 Nov 2026)

**Noise filter** (`SensorFilter`, run_prototype `runtime/sensor_filter.py` numbers): every reading passes it in
the control loop before the safety rules, lift detection and the map see it.

- **Sonars**: the scanner already reports the median of 3 pings. A sonar that jumps more than 30 cm and straight
  back 4 times within its last 25 readings is "flickering": it then reports the **closest** recent reading (only
  ever more careful), until a full window is clean again (so about two windows of readings). Only new readings
  count (the scanner updates ~12 times a second, the loop asks 50). "No reading" passes through unchanged: the
  safety rules already treat it as unsafe.
- **IR edge sensors**: "no floor" is believed after 2 ticks (40 ms), "floor again" only after 5 (100 ms), so a one-tick
  glitch is ignored and a noisy edge doesn't chatter. An IR that changes 6 times in 25 ticks reads "no floor" (stops the
  robot) until it is clean. Faults appear on the Notes card.

**Sensor fusion map** (the Map card): the pose is already fused (encoder distance + gyro heading). The map now
combines all the sensors:

| Source | Into the map |
| --- | --- |
| sonars | free cells along each beam, an occupied cell at the echo (log-odds, ±12) |
| IR edge sensors | a desk-edge mark where an IR saw no floor (8 cm ahead / behind, `IR_MOUNT_M`); removed if the desk is seen there later |
| where the robot drove | the cells under it are surely free (`FOOTPRINT_M`) |
| camera objects | drawn with their size; in the confidence view, their cells |
| time | every 2 s all evidence fades by 3 % (`FUSION_DECAY`): something that was moved away fades in about 2 minutes unless the sonars see it again |

**Map / Confidence** switch on the card: the classic view (obstacles, free, desk edges in red, objects, the trail of
the last 400 positions) or a **confidence heatmap**: green = surely free, red = surely occupied, the colour's
strength = how sure; edges red, objects amber. `/api/map` → `conf` (one character per cell: `-` unknown,
`0`-`9` probability occupied, `E` edge, `O` object) and `trail`.

Tested: the filters (steady values pass, flicker → closest value, stays careful while the bounces are in the
window, clears after a clean window, repeated values aren't new samples, a 1-tick IR blip ignored, 2 ticks → edge,
5 ticks to believe the floor, a flickering IR → "no floor"); in simulation the robot drove to the desk edge and
stopped with its IR inside the desk, the edge was marked, the trail recorded, the confidence layer had free,
occupied, edge and object cells, the robot's own cell was "surely free", and evidence faded. All earlier test
suites still pass with the filter in the loop.

## Bluetooth phone presence (added 24 Nov 2026)

From run_prototype `presence/ble.py`. The robot listens for your phone with **bleak** (BlueZ on the Pi, WinRT on
Windows) and keeps a **near / away** state:

- near: smoothed signal (`BLE_EMA` 0.3) ≥ −67 dBm for 2 s; away: not heard for 25 s, or below −85 dBm for 10 s;
  in between nothing changes, so walking round the desk doesn't flip it.
- Coming back after being away: "Welcome back!" (said, OLED, chat). The state goes into the assistant's context.
- **Choosing your phone**: phones change their Bluetooth address about every 15 minutes for privacy, so the
  Phone card lists what is nearby (strongest first) with **This is mine**; `phone use <name part | address |
  iBeacon UUID>` does the same. Saved in `phone.json`. Most reliable: a fixed name, a smartwatch/band with a fixed
  address, or a beacon app.
- The card: the state, signal and a rough distance (path-loss model, ±50 %), and a sparkline of the last 60
  readings with the "near" line.
- No `bleak`, Bluetooth off, or no adapter: a note with the fix ("turn Bluetooth on in Windows settings" /
  `sudo systemctl start bluetooth; rfkill unblock bluetooth`), retried every 20 s; everything else runs.
- Simulation: `sim phone near|far|away`. `--no-bluetooth` turns it off.

Tested: the state machine with a fake clock (near after 2 s, hysteresis in between, away after 10 s weak, back
→ "Welcome back!", away after 25 s unheard), name / address / iBeacon matching and saving, iBeacon frame parsing,
the simulated phone through the commands. **On the laptop's real adapter**: Bluetooth was off, and it reported
"Bluetooth radio is not powered on" as a note, with no crash. Not yet tested on the Pi.

## Gestures from the laptop camera and rock paper scissors (added 24 Nov 2026)

**Gestures**: the Gestures card's **📷 Start laptop camera** runs Google's MediaPipe **GestureRecognizer** in
the browser on the laptop's own camera (`@mediapipe/tasks-vision@0.10.14` from jsDelivr, the float16 model from
storage.googleapis.com, about 8 MB, loaded once and then cached by the browser). Nothing but the gesture's name
leaves the laptop, and the robot does no extra work. Like the microphone it needs the https page.

- Recognised: ✋ Open_Palm, ✊ Closed_Fist, 👍 Thumb_Up, 👎 Thumb_Down, ☝ Pointing_Up, ✌ Victory, 🤟 ILoveYou
  (score ≥ 60 %), about 10 times a second. Held for 0.7 s → sent once (`gesture <Name>`), at most every 1.5 s.
- Defaults: ✋ stop, 👍 forward 10 cm, 👎 back 10 cm, ☝ face me, ✌ photo, 🤟 start rock paper scissors, ✊ nothing.
  Change them with the card's drop-downs or `gesture map <Name> <action>`; only the actions in `GESTURE_ACTIONS`
  are allowed. Saved in `gestures.json`.
- A gesture is a person's command: it cancels AI plans and trips, and every safety rule applies.
- It tries the GPU (WebGL) first and falls back to the CPU. Offline, camera refused, or a failure: the card says why
  (hidden in presentation mode); the rest of the page is unaffected.

**Rock paper scissors** (`RockPaperScissors`, from run_prototype `full/rps.py`): `rps`, 🤟, "let's play rock paper
scissors", or **Play** on its card. "Rock... paper... scissors... shoot!", then 6 s for a move: ✊ / ✋ / ✌ to the
laptop camera (during a game these are moves, not their usual actions), the words "rock" / "I choose paper", or the
card's buttons. The robot's move is random, but half the time it plays what beats your most frequent move. First
to two; no move → asked once more, then the game ends. Results are said out loud and shown on the card.

Tested: gesture actions (👍 drove 10 cm by the encoders, ✋ stopped), mapping refused for non-allowed actions,
saving and loading; a whole game started by 🤟, ✊ as rock during the game, a typed move, a 2-1 win, ✋ back to stop
afterwards; the retry and give-up; spoken moves offline (a sentence that only mentions scissors is not a move).
**The browser part was checked in headless Edge**: the module imported, the WebAssembly loaded, the recognizer was
created in video mode and `recognizeForVideo` ran on a fake camera stream (no hand → no gesture). Not yet tried
with a real hand on the laptop camera.

## Sound effects and dance (added 24 Nov 2026)

There is no speaker on the Pi yet, so the **laptop is the speaker**: the robot decides *what* to play and the
dashboard page makes the sound with the browser's Web Audio API. Nothing is downloaded and there are no audio files
to install: every effect and the four built-in songs are synthesized in the page from short note lists in the
script. With no dashboard open the robot still dances, just silently.

### Sound effects (`Sounds`)

`robot.sounds.play(name)` adds a numbered entry (`{"id", "name"}`) to a list of the last `SFX_RECENT` = 10, which is
in `/api/state` under `sounds`. Each dashboard page remembers the highest id it has played and plays newer ones (at
most 3 at once, 150 ms apart). A page that has just opened, or sees the ids go backwards (robot restarted), only
remembers the current id, so it never replays old sounds. The same effect twice within `SFX_REPEAT_S` = 0.3 s is
dropped.

| Effect | When |
| --- | --- |
| `boot` | the program starts (heard if a page was already open, e.g. after a restart) |
| `blip` | a move starts (not during a dance) |
| `bump` | a move blocked by an obstacle or an IMU bump |
| `alarm` | picked up, an edge, tilted; an announcement with the `scared` face |
| `landed` | put back down |
| `pat` / `hold` | touch pad pat / hold (or a move stopped by the touch pad) |
| `sad` | a wheel stuck, a calibration failed; `sad` announcements |
| `success` | a calibration finished; a focus session finished |
| `chime` | a task reminder (soon / due / overdue) |
| `shutter` | `photo` |
| `tada` | a dance finished |
| `happy`, `notify`, `grumble`, `sleepy` | announcements, by their face (`MOOD_SFX`): rock paper scissors results, the greeter, "welcome back", jokes, the focus nudges |

How the triggers are found: most come from a **watcher thread** (`sounds`, 10 Hz) that compares a small snapshot of
the robot's state with the previous one (blocked reason, lift count, lifted, pats, holds, calibration message, the
current move's start time), the same way the OLED's face reacts to state changes. So the control loop has no new code
and no sound can slow it down. `Sounds._changes(old, new)` is a pure function. The rest are explicit:
`Robot.announce(text, mood, sound=None)` plays the mood's effect (or `sound`), `photo` plays `shutter`, the dance
plays `tada`. During a dance, blocked steps make no sound (only stuck/edge/tilt do).

`sounds off` mutes every page (the robot stops queueing effects); dance music is not affected. On a page, the card's
**🔔 Sound effects here** and **🎵 Music here** boxes and the volume slider are that browser's own settings (kept in
`localStorage` under `robot-audio`). The row of small buttons previews each effect in that browser only.

Browsers only allow sound after the person has clicked or pressed a key on the page once. The page creates its
`AudioContext` on the first click/key; until then effects are skipped and a dance shows "Click anywhere on this page
to let it play the music" (the music then joins in on the beat).

### Dance (`Dance`)

`dance` (or "let's dance", "play some music", 💃 on the card, a gesture mapped to `dance`, or the AI) picks a random
song, never the same one twice in a row; `dance <song>` picks one by id or part of its title (`dance disco`). It
answers at once; a `dance` thread does the moves.

**Moves.** A dance is a chain of pre-coded **routines**, 8 beats each (`DANCE_ROUTINES`): `wiggle`, `cha-cha`,
`spin`, `robot`, `shimmy`, `twist`. `dance_plan(beats)` chains them at random (never the same one twice in a row)
until the song's beats are used up; the last is cut short to fit. A step is `(move, beats)`: `L`/`R` turn on the
spot, `F`/`B` drive, `SL`/`SR` a longer spin, `-` a pause. Every routine turns as much left as right and drives as
much forward as back, so a whole dance ends roughly where it started (a test checks this for every routine). At
speed 0.5 one beat of turning at 120 bpm is about 50°.

**Timing.** Step *k* starts exactly at `t0 + (beats before it) × 60/bpm` on `time.monotonic()` (an absolute
schedule, so it never drifts), and runs the motors for `DANCE_DUTY` = 80 % of its length, which leaves a short
stop that makes each move land on the beat. `t0` is `DANCE_LEAD_S` = 1 s after the command, time for the page to
notice the dance and start the music.

**Safety.** Each step is an ordinary timed move through `Robot.start()`, so every safety rule applies (sonar, edge
IR, tilt, bumps, stuck wheels, lift). A step that is not safe is skipped; the robot keeps dancing on the spot and
the card says how many steps were skipped. The dance ends on `stop` (also an AI "stop"), `dance stop`, **any command
from a person** (like a `go to` trip), being lifted, or calibration. A new `dance` replaces the old one, and a dance
cancels a running `go to` trip.

**Music sync.** `/api/state` carries `dance` built fresh for every request (not the shared 0.1 s status snapshot):
`active`, `run`, `song`, `bpm`, `seconds`, `routine`, `step`, `skipped`, `result` and `elapsed_s` (seconds since beat
0, negative during the lead-in). The page measures each `/api/state` round trip and starts the song at
`elapsed_s + round trip / 2`: notes in the past are skipped, so a page opened in the middle of a dance joins in on the
beat. When `run`/`song` changes or the dance ends, the old music fades out over ~0.3 s.

**Built-in songs** (original tunes, `BUILTIN_SONGS`): Desk Disco (120 bpm), Robot Shuffle (104), Bleep Bop Boogie
(132), Moonlit Bloops (92); 8 bars, played twice (29-42 s). Each bar is 8 eighth notes (`C5`, `F#4`, `Bb3`, `.` rest,
`-` hold); the bass is one root per bar in a style (`octave`, `offbeat`, `pump`) and the drums one bar of `K` kick,
`S` snare, `H` hi-hat. The page plays the melody on the song's wave (square/triangle/sine), the bass on a triangle
wave, the kick as a falling sine and the snare/hi-hat as filtered noise; the second time round adds a quiet octave-up
sparkle. All notes are scheduled ahead on the audio clock (320-500 per song), so playback does not depend on the
page's timers.

**Your own music.** Put `.mp3`, `.ogg`, `.wav` or `.m4a` files in `songs/` next to the script (or `~/deskbot/songs/`).
Name them with their tempo, `My Song_128bpm.mp3`, so the moves are on the beat (otherwise 120 bpm is assumed). The
robot can't read a file's length without audio libraries, so it dances to the first `SONG_FILE_S` = 32 s. Files are
served at `/songs/<name>`; only names listed by `find_song_files()` are served (letters, digits, spaces and `._-()'&+`,
no paths), anything else is a 404. `/api/songs` lists every song (the built-in ones with their notes). If the beat of a
file doesn't start at 0:00 the moves will be slightly off; trim the file's silence.

**OLED**: "Dancing to <title>" for 3 s, then happy eyes (the eyes also look the way it turns) for the whole dance.

Tested (simulation): every routine is 8 beats and balanced; songs have 8 notes per bar; `dance_plan` fills the
beats with no routine twice in a row; music files are found with their bpm and title, and odd names and `../`
paths are refused; a dance runs every kind of move, `stop` ends it with the motors off, lifting ends it, a short song
runs to the end and plays `tada`; `sounds off`; the AI check (`dance`, `dance to desk disco`, `dance stop`) and
the offline phrases. Live in `--sim`: `/api/songs`, `/api/state`, the effects for lift / put down / pat / move,
and the page in headless Edge (no console errors, the song list filled, the music started at the robot's position
and the progress bar followed it). The synthesizer was checked by building every song and effect in Edge's Web
Audio (no errors, note frequencies right: A4 = 440 Hz). **Not yet heard on a real laptop speaker or danced on the
real robot**: check the turn sizes on the desk and lower `--speed` if the moves are too big.

## Web APIs, ideas and accounts (added 24 Nov 2026)

**Web APIs** (`WebApis`, from run_prototype `assistant/tools.py`; all free, no keys):

| Ask | Service |
| --- | --- |
| `weather [city]`, "what's the weather in Delhi" | Open-Meteo (geocoding + forecast): now, feels-like, today's range, chance of rain |
| `wiki <topic>`, "look up …"; with no AI key also "who is / what is …" | Wikipedia: a two-sentence summary |
| `joke`, "tell me a joke" | Official Joke API; when it is down (it was, during testing: HTTP 503), one of a few built-in jokes |
| `convert 10 usd to inr`, "how much is 25 eur in usd" | ExchangeRate-API (daily rates, cached 1 h) |

- With an AI key, the fetched facts go into the AI's context so it answers in its own words; without one, the
  answer is said as is. Errors are a clear sentence ("Sorry, no internet connection").
- **No IP-location lookup** (run_prototype had one): the weather needs a city, or a home city set once with
  `weather home Delhi` (saved in `apis.json`; `DESKBOT_CITY` overrides).
- The **APIs card** shows each service's last result (ok / error, time, ms, number of calls), Weather and Joke
  buttons, a Wikipedia box and the home city. A failing API is also a note.

**Ideas notebook** (`Ideas`, from run_prototype `hub/ideas.py`): `idea <text>`, "remember this idea: …", or
"remember this idea" then the idea within a minute; "what are my ideas?", `ideas search`, `ideas forget <#n or
words>`. Saved in `ideas.json` (atomic writes, at most 500). The **Ideas card** lists, searches and deletes them,
and **⬇ Download as Markdown** (`/ideas.md`).

**Accounts card**: one tile per service: Groq, Claude, OpenAI, Telegram, Spotify, Google (green dot = its key
is set in `secrets.env`), the free APIs (green = working), and the Bluetooth phone. **Only whether a key exists is
read**; no key, prefix or length is ever sent to the page. Keys are changed in `secrets.env` on the robot, never
from the dashboard.

Tested **against the live services** (only a city, a topic and currency codes were sent): weather for Delhi and
the saved home city, Wikipedia, a currency conversion, unknown currency and place handled; no internet (simulated)
→ a clear answer and a note; the assistant with no AI key (a joke, "who is Ada Lovelace") and with a stand-in AI
(the weather in its context; no Wikipedia call for ordinary questions); the ideas flow including the two-step
"remember this idea"; Markdown export; with `GROQ_API_KEY` set to a dummy value, the Groq tile showed connected and
no part of the key appeared anywhere in `/api/state`.

**Speech in and out** were already there (the 🎤 button: Groq Whisper, or the browser's own speech recognition
in Chrome/Edge; "Speak replies here" reads replies, reminders, game results and greetings aloud in the laptop's
browser) and are unchanged.

## Assistant (added 24 Nov 2026)

Talk to the robot by typing (`ask …` at the prompt or the dashboard's **Assistant** card) or by voice (the card's
**🎤 Talk** button). Ported from run_prototype `deskbot/pro/groq_brain.py` (Groq first),
`assistant/brain.py` + `assistant/claude_http.py` (Claude as the fallback) and `assistant/stt.py` (Groq Whisper),
without the tool loop, sound effects, personality profiles or the robot's own speaker. Standard library only
(urllib + json), like the rest of the file.

### Setting it up

Put the keys in a `secrets.env` (never committed, never sent to the browser). The script reads the first file
that exists of: `secrets.env` **next to the script** (on the Pi: `~/secrets.env`), `~/deskbot/secrets.env` (where
run_prototype keeps it), `../run_prototype/secrets.env`. Variables already set in the environment win.

```bash
# on the Pi, next to simplified_code.py
cat > ~/secrets.env <<'EOF'
GROQ_API_KEY=gsk_...          # console.groq.com -> API keys (free tier). Chat + speech-to-text
ANTHROPIC_API_KEY=sk-ant-...  # optional: platform.claude.com -> API keys. The fallback brain
EOF
chmod 600 ~/secrets.env
```

`assistant` (or the startup log) shows what was found, for example `assistant: groq (openai/gpt-oss-120b): ready |
claude (claude-opus-5-5): no key | keys from /home/snu123/secrets.env`. On 24 Nov 2026 there was no key on the Pi
or the laptop, so the AI brains have **not** yet answered a real question. Everything was tested with recorded
responses (below).

### What happens to a question

1. **Offline rules first** (`offline_reply`, `OFFLINE_RULES`): plain commands are answered at once, free and
   without internet: `stop`, `go forward [for N seconds]`, `go back`, `turn left/right [N degrees]`, `turn N`,
   `spin` / `turn around`, `dance` / `wiggle` (turn 30, −60, 30), `take a photo`, `what time is it`, `what day is it`,
   `hello`, `what do you see` (the detector's answer). A leading `hey robot`, `please`, `can you` is ignored.
   The movement rules only match text that **starts** with the command, so questions such as "what's straight
   ahead?" or "how do I stop procrastinating" go to the AI and never move the robot.
2. **Groq** (`GroqBrain`): `POST https://api.groq.com/openai/v1/chat/completions`, model `openai/gpt-oss-120b`
   (`--groq-model`; `openai/gpt-oss-20b` is faster), JSON mode (`response_format: json_object`),
   `reasoning_effort: low`, temperature 0.6, `max_completion_tokens` 1000.
3. **Claude** (`ClaudeBrain`) if Groq has no key or fails: `POST https://api.anthropic.com/v1/messages`,
   `anthropic-version: 2026-10-21`, model `claude-opus-5-5` (`--claude-model`; run_prototype uses
   `claude-haiku-5-5`, which is cheaper), `max_tokens` 4000, `output_config: {effort: "low", format: json_schema}`
   (structured output, so the reply always has the right shape). Thinking is left at the model's default
   (adaptive), with low effort for quick spoken answers. Server-side refusal fallback is on
   (`anthropic-beta: server-side-fallback-2026-07-01`, `fallbacks: "default"`). A final `stop_reason: "refusal"`
   gets a polite "Sorry, I can't help with that one."
4. **Nothing reachable** (no keys, `--no-ai`, no internet): an offline answer that says so and lists what still
   works. The errors are shown under the reply and in `assistant`.

Both AI brains get the same system prompt (`AI_SYSTEM`: a desk robot, 1-2 short sentences for the tiny screen and
the voice, the allowed commands, the moods, and "answer with one JSON object"), the last 6 AI exchanges
(`AI_HISTORY`), and the question wrapped with the robot's current state:

```
<robot_context>
time: Tuesday 24 November 2026, 15:02
mode: robot, speed 0.5
sonar distances: front 34 cm, left --, right 61 cm, rear 120 cm
edge sensors: front desk, rear desk
camera sees: cup (12 deg left), person (3 deg right)
</robot_context>

User said: what's on my desk?
```

(plus `moving`, `last stop reason` and `the robot is LIFTED` when they apply). The reply is
`{"speech": "...", "mood": "happy", "commands": ["turn 90", "forward 1"]}`.

### What the robot does with a reply

| Part | Goes to |
| --- | --- |
| `speech` | printed (`Robot: … [groq openai/gpt-oss-120b, 640 ms]`), the dashboard chat, the Activity log, the **OLED** as text for 3-12 s (longer text stays longer), and **spoken by the browser** (below) |
| `mood` | the OLED face for 4 s or more (`Oled.mood`): happy, sad, angry, scared, focused, sleepy, normal. Lifted, stuck wheel and tilt still take priority |
| `commands` | checked, then run in order |

**Commands are checked** (`check_ai_command`). Only `forward`, `back`, `turn`, `left`, `right`, `spin`, `stop` and
`photo` are allowed (`AI_COMMANDS`). Forward/back are clamped to 0.2-3 s (`AI_MAX_DRIVE_S`), turns to ±360°,
`left 45` becomes `turn 45`, and there are at most 6 per reply. Anything else (`calibrate`, `quit`, `lift off`,
`oled …`, `speed 1`, `map reset`) is refused, and the refusal is shown under the reply.

**They run as a plan** in a background thread (`Assistant._run_plan`). Each command goes through
`Robot.execute(cmd, source="assistant")`, so every safety rule applies exactly as for a typed command. The plan
waits for each move to end, then 0.25 s for the robot to coast. It stops:
- at a refused start ("Not moving: …") or after a move that a safety rule stopped (`blocked` set),
- as soon as a **person** sends any command (typed, a dashboard button, arrow keys, Space). `Robot.execute` counts
  these in `user_cmds`, and the plan compares the count. So STOP always wins,
- when a newer reply starts its own plan.

One question at a time: asking while it is still thinking gets "Still thinking about … - one question at a time".

### Voice in, voice out (the laptop is the speaker for now)

**Speaking** happens in the browser, not on the Pi (the Pi has no speaker yet, see `docs/laptop-speaker.md`). Tick
**🔊 Speak replies here** on the dashboard. Every new reply is read out with the browser's speech synthesis
(`speechSynthesis`, pitch 1.6, a small robot voice). The tick is remembered in that browser (`localStorage`
`robot-speak`), and ticking it says "Okay, I will talk here.", which also satisfies the browser's "sound needs a
click first" rule. A page that has just opened does not read out older replies. Replies to questions typed at the
Pi's prompt are spoken too, as long as a dashboard tab has the box ticked.

**Listening** needs the microphone, and browsers allow it only on a secure page (`https://`, or `http://localhost`).
So the script also serves the same dashboard on **`https://<pi-address>:8443`** (`--https-port`) with a
self-signed certificate. Open that once and accept the warning (Advanced → Proceed). Clicking **🎤 Talk** on the
plain http page explains this and links to it.

| Has GROQ_API_KEY? | 🎤 Talk does |
| --- | --- |
| yes | records with `MediaRecorder` (webm/opus in Chrome/Edge, mp4 in Safari) until you click Stop or for 15 s at most, POSTs it to `/api/voice`. The robot sends it to Groq Whisper (`whisper-large-v3-turbo`, multipart upload, temperature 0) and asks the assistant what it heard. The card shows "Heard: “…”" |
| no, Chrome/Edge | the browser's own speech recognition (`webkitSpeechRecognition`, en-US; in Chrome and Edge it runs on the browser maker's servers) turns speech into text, which is sent as `heard <text>` (= `ask`, marked 🎤 in the chat) |
| no, other browser | says so: add the key, or use Chrome/Edge, or type |

`/api/voice` refuses bodies over 4 MB and recordings under 1 KB ("is the microphone muted?"). Whisper's usual
inventions on silence ("Thank you.", "Thanks for watching", "you", "bye") are treated as "I didn't catch that".

**The certificate** (`ensure_cert`) is made once with the `openssl` command (on Raspberry Pi OS; Git for Windows
also has it) into `tls/` next to the script: RSA 2048, 10 years, `CN=deskbot`, subjectAltName = host name,
`<host>.local`, localhost, 127.0.0.1 and the current LAN IP. `tls/names.json` remembers those names, and the
certificate is remade when the IP changes. The key file is chmod 600. The https server runs the TLS handshake in
each request's own thread (`do_handshake_on_connect=False`), so a slow client never blocks it. Failed handshakes
(for example plain http sent to 8443) are dropped silently (`QuietHTTPServer`). If openssl is missing or the port
is busy, the log says so and only the microphone is affected.

### Dashboard card, API, status

The **Assistant** card (full width, under the camera) shows the last 8 exchanges as a chat (your words right, the
robot's left, with what it is doing, the backend, the time taken and any errors), a "thinking…" bubble while it
works, the 🎤 button, the text box and the speak tick. The header shows `groq ✓ · claude (no key)`, with the model
and last error on hover.

`/api/state` → `assistant`: `enabled`, `brains` {groq/claude: model, key (true/false only, never the key), error},
`stt` ("groq" or null), `secrets` (the file used), `thinking`, `recent` [{id, user, source typed/voice, speech, mood,
commands, backend, ms, errors, t}], `last_id`. `https_port` is the https port, or null when it is off.
`POST /api/voice` (body = the audio, `Content-Type` = its type) → `{"text", "reply"}` or `{"error"}`.

| Problem | What happens |
| --- | --- |
| no key / `--no-ai` | offline rules still work; anything else gets "Sorry, I have no AI key (…)" |
| key rejected (401), rate limit (429), wrong model (404), 5xx, no internet | that brain's error is kept and shown, and the next brain is tried. Requests time out after 25 s (`AI_TIMEOUT_S`) |
| model answers outside JSON | Groq: an error, then Claude is tried; Claude cannot (structured output) |
| a command the AI may not use | not run; listed under the reply |

Tested 24 Nov 2026 with **recorded responses** (66 checks, no network): 16 offline commands and 6 questions that
must not move the robot; command checking (11 allowed with clamping, 8 refused); secrets file parsing (comments,
quotes, `export`, environment wins); no keys → offline answer and no HTTP request; Groq request (JSON mode, low
reasoning, robot context, key only in the header); Groq 429 → Claude (request shape: version header, fallback
beta, `effort: low`, json_schema, no temperature or thinking fields, history sent); a Claude refusal; a 3-step
plan ran to the end, and a person's `stop` cancelled a 2 s plan before its next step; "one question at a time".
Live in simulation on the laptop and the Pi: certificate made with openssl (Git for Windows; Pi: 1 s), the
dashboard and `/api/state` over https, plain http to the https port dropped while https kept working,
`ask take a photo` / `hey dance` / a question with no key, and `/api/voice` without a key gave the right error.
The card was checked in a browser at 1280 px and at 375 px (no sideways scroll). **Not yet tested:** a real
Groq/Claude answer (no key yet), speech-to-text with a key, and the microphone in a browser on the robot's
https page.

## Photos (added 24 Nov 2026)

**📷 Take photo** under the camera on the dashboard (shown only while the camera streams), or `photo` at the
prompt.

- The button sends `photo` to `/api/cmd`, so the CLI and the button share one code path (`Camera.save_photo`).
  The picture is the camera's latest raw BGR frame (`Camera.frame`, the one the detector uses), so the saved
  photo has **no** boxes on it even when detection draws them on the video. Full camera resolution (640 × 480),
  JPEG quality 92 (OpenCV, else Pillow).
- Saved on the robot as `photos/photo-YYYYMMDD-HHMMSS.jpg` next to the script (`PHOTO_DIR`; a second photo in
  the same second gets `-2`), and the browser downloads a copy at once. Under the button: "Saved on the robot:
  photo-….jpg · download again".
- Download route `GET /photos/<name>`: only names matching `photo-YYYYMMDD-HHMMSS[-n].jpg` that exist in
  `photos/` are served (`Content-Disposition: attachment`). Anything else, including `../` tricks, gets 404.
- Errors: no camera → "No camera (started with --no-camera or --no-dashboard)"; camera not delivering frames →
  "Could NOT take a photo: no camera picture (<camera status>)". Each saved photo is an Activity event.

Tested 24 Nov 2026 in simulation with the laptop webcam: `photo` saved a 640 × 480 JPEG, `/photos/<name>` served
it as a download, `/photos/..%2Fsimplified_code.py` and `/photos/../encoders.json` returned 404, and the page
script parses. Not yet tested on the robot.

## Lift detection (added 24 Nov 2026)

Ported from `run_prototype/deskbot/presence/lift.py` and `companion/lift.py`, with the same thresholds. It runs
in the 50 Hz control loop (`Robot._check_lift`) and needs no extra hardware: it uses the two IR edge sensors
and, when present, the IMU.

**Picked up** when any of these holds continuously for its confirm time:

| Trigger | Confirm | Notes |
| --- | --- | --- |
| both IR sensors see no desk | 0.4 s (`LIFT_CONFIRM_S`) | On a desk at most one can (the edge stop halts the robot at the first edge), so both means nothing is under it. Works without an IMU. |
| tilted more than 30° (`LIFT_TILT_DEG`) | 0.3 s | IMU |
| motors off, yet turned > 0.8 rad/s or shaken > 2 m/s² away from 1 g, and at least one IR has lost the desk | 0.35 s | IMU: the moment of picking up, before the IR loses the desk |

All three timers update on every tick (no short-circuit), so each hold time is measured honestly.

**While lifted:** the running move stops, no move starts ("Not moving: robot is lifted (…) - put it down on the
desk"), and the pose and map are frozen. Otherwise being carried would paint nonsense into the map. The eyes
look scared and down, and the dashboard shows a red banner.

**Put down** when both IR sensors see the desk for 1 s (`PLACE_CONFIRM_S`) and, with an IMU, it is level
(< 15°), still (< 0.15 rad/s) and not shaken (< 0.8 m/s²). Without working IR (`--no-edge`), "level and still"
alone counts.
- Up for less than 1 s (`LIFT_RESET_AFTER_S`): "Back on the desk (short lift): map resumed".
- Up longer: it is somewhere new. The map is cleared, the pose goes back to (0, 0, 0°), the encoder distance
  restarts, and the OLED says "New spot!", then happy eyes.

**Time off the desk** is measured from the moment the lift condition began (the earliest of the IR / tilt /
handling timers that led to "picked up") to the moment it touched down (the start of the put-down timer). run_prototype
measured from the lift *confirmation* to the *end* of the 1 s put-down confirmation, so every lift counted as ≥ 1 s
and even a blip wiped the map; that is fixed there too since 24 Nov 2026 ([run-prototype-fixes.md](run-prototype-fixes.md)).
Until 24 Nov this file measured from the confirmation (0.3-0.4 s late). Re-checked in simulation: off the desk
1.19 s → "Put down after 1.3 s: new spot" (the extra 0.1 s is the IMU settling).

Not active during `calibrate hand`, because the robot is lifted on purpose then. If both IR stay dark for
2 minutes while "lifted", it asks once whether the IR sensors are unplugged, since that looks exactly like a
permanent lift.

Commands: `lift` (state, counts, which sensors it uses), `lift on|off`. Flag: `--no-lift`. In simulation,
`sim lift on|off` now also makes both IR see no desk. `/api/state` → `lift`: enabled, lifted, reason, up_s,
lifts, resets, last.

Tested 24 Nov 2026 in simulation, with the IMU and with `use_imu=False`. A lift during `back 3` was detected
after 0.41 s / 0.44 s and stopped the move. `forward` was refused while lifted. Put down after 0.5 s and after
a 0.3 s blip: "map resumed", pose kept. Up 1.5 s: "new spot - fresh map, pose (0, 0)". Lifting during
`calibrate hand` did not trigger. `lift off/on` works. The API and page script were checked. The
"moved by hand" trigger was not simulated (the simulator has no hand). Not yet tested on the robot.

## Touch pad (added 24 Nov 2026)

One TTP223 capacitive pad: the "top" pad of `robot_config.TOUCH`.

| TTP223 pin | Raspberry Pi |
| --- | --- |
| VCC | 3.3 V (pin 1 or 17). **Not 5 V**: the I/O output would then be 5 V, which damages the Pi's GPIO |
| GND | any GND |
| I/O | **GPIO 7** (physical pin 26) |

Leave the module's A/B jumpers open (the default): the output is HIGH while touched. GPIO 7 is SPI CE1, so SPI
must be off. If it reports "busy", run `sudo raspi-config nonint do_spi 1`.

| Touch | Does |
| --- | --- |
| press while a move runs | **stops the move** ("STOPPED: touch pad pressed"). A hand on the robot's head = stop. That press does nothing else. |
| tap (released within 2 s) | a pat: happy eyes for 3 s, counted |
| hold 2 s (`TOUCH_HOLD_S`) | the OLED shows the dashboard address for 8 s |
| while touched | the eyes are happy and look up |

**How it works:** `RealHardware` opens a gpiozero `DigitalInputDevice(7, pull_up=False)`. The pull-down means an
unplugged pad reads "not touched", never a phantom touch. The 50 Hz control loop polls it in
`Robot._read_touch`, so the 20 ms polling also acts as debounce. Press, hold and release are worked out from the
time of the press. A touch that already stopped a move or triggered a hold does not also count as a pat. If the
pin cannot be opened, the reason is shown (`touch`, `status`, the dashboard Sensors card, the log) and nothing
else is affected.

Commands: `touch` (state and counts), `sim touch [hold]` (simulation). Flags: `--no-touch`, `--touch-pin N`.
`/api/state` → `touch`: `touched` (true/false/null), `presses`, `pats`, `holds`, `last`, `pin`, `error`.

Tested 24 Nov 2026 in simulation: a tap gave "Touch pad: pat" and happy eyes. A tap during `back 3` stopped it
("stopped by the touch pad") without counting as a pat. Holding gave happy eyes looking up, and after 2 s the
OLED showed `Dashboard http://…:port`. The API and the dashboard row work. Not yet tested on the robot.

## Objects on the map (added 24 Nov 2026)

What object detection recognises is placed on the obstacle map and remembered, so the robot can answer "where is
the cup?" after it has turned away, and the assistant knows what is around it. Ported from run_prototype
`deskbot/vision/geometry.py`, `mapping/fusion.py` and `mapping/semantic.py` with the same numbers, minus
ByteTrack (sightings are matched by label and distance only).

**Placing one detection** (`locate_detection`):

1. Boxes that touch the left or right edge of the picture are not placed: part of the object is outside, so the
   box centre, and with it the object's direction, is wrong. They still count as "seen" (below).
2. **Range from the front sonar** when the box centre is within 10° of straight ahead (`OBJ_SONAR_DEG`), the
   sonar reads under 1.2 m, and it agrees with the camera estimate (within 8 cm or 40 %). Variance
   (2 cm)² + (3 % of the range)².
3. Otherwise **range from the camera**: the bottom-centre of the box is where the object stands on the desk.
   That pixel's ray is intersected with the desk plane using the camera mounting (`CAMERA_X_M` 5 cm ahead of the
   centre, `CAMERA_HEIGHT_M` 9 cm up, `CAMERA_PITCH_DEG` 12° down, fields of view 62.2° × 48.8°; run_prototype's
   `CameraModel.ground_point`). Variance (2 cm + 10 % · range²)², so far things are trusted less. Not placed if the
   box touches the bottom of the picture (too close to see where it stands) or is over 1.5 m away.
4. If the camera range is more than 15 cm beyond what the sonar hears straight ahead, it is not placed: a
   reflection, or something seen through glass.
5. The point found is the object's near surface, so its half-depth is added along the bearing: `OBJ_RADIUS` per
   label (cup 4.5 cm, book 10 cm …), or `OBJ_DEPTH` for long thin things seen side-on (keyboard 5 cm, laptop 12 cm).
6. Robot frame → map frame with the current pose.
   `person`, `dining table`, `bed`, `couch` are never placed (`OBJ_SKIP`): they don't stand on the desk.

**Remembering** (`ObjectMap.update`, one call per new detection frame): each sighting, most confident first, is
matched to the nearest landmark with the same label within 15 cm + 2σ (`OBJ_GATE_M`), else it starts a new one.
The position is Kalman-updated (gain = landmark variance / (landmark + sighting variance)). Existence is
log-odds: + 1.2 × score per sighting, − 0.6 when the landmark should be in view but was not detected (in the
field of view with a 5° margin, 12 cm-1 m away, not hidden behind something the front sonar hears clearly in
front of it, and not seen cut off at the edge). It is clamped to ±4, fades with a 45 s half-life, and the
position variance grows by 0.0004 m²/s while unseen. Below log-odds −1, or after 6 half-lives without news, a
landmark is dropped. Shown and answered only at ≥ 60 % probability (`OBJ_SHOW_P`). The label shown is the one
with the most accumulated score.

**When it updates:** in the control loop's map step (every 0.2 s), only when the detector has a new frame. Not
while turning (a left/right move, or the gyro over 30°/s) and not from pictures taken up to 0.3 s after a turn
(`OBJ_AFTER_TURN_S`): those may be blurred or taken mid-turn, so the pose would not match. Not while lifted. `map
reset`, `objects clear` and "put down somewhere new" (lift detection) forget everything.

**Where it shows:** amber dots, sized by the object and labelled, on the dashboard map (fainter when less sure),
with a list under it ("Objects: book 46 cm · cup 46 cm"). `/api/map` → `objects`: [{id, label, x, y, sigma,
radius, p, age_s, hits, misses, source sonar/camera, dist_m, bearing_deg}]. The assistant's context gets
"remembered on the map: cup 46 cm away, 55 deg to the left (seen 31 s ago, 92 % sure); …".

**Simulation:** with `--sim` (and no `--model`) a `SimDetector` replaces YOLO. It "sees" the simulated desk's
labelled objects (`SimHardware.OBJECTS`: book, teddy bear, keyboard, cup, bottle, which are also the sonar's
obstacles) through the same camera model, about 3 times a second, with 10 % random misses, 2 px of noise,
hiding behind other objects and cutting at the picture edges. So the whole chain can be tried on the laptop.

**Limits:** wide things close by (a keyboard at 50 cm fills half the view) are placed only when the robot faces
them within a few degrees. Turn towards them, or step back. The camera mounting numbers come from run_prototype;
if the camera sits differently on the robot, adjust `CAMERA_HEIGHT_M` / `CAMERA_PITCH_DEG`.

Tested 24 Nov 2026 in simulation: project → ground point round trip (error 1e-16 m); a cup 40 cm ahead found at
40 cm by sonar and by the camera; seen far behind the sonar surface and cut off at the bottom → not placed.
Looking around in 30° steps (and facing the keyboard): **book 3.1 cm, teddy bear 3.2, keyboard 0.2, cup 0.3,
bottle 3.8 cm** from the truth, one landmark each, no person. `where is the cup`, `where's my phone` (unseen),
`objects`, the assistant context. The cup was taken away, then the robot turned to its spot: forgotten after
1.6-2 s. `map reset` clears. Three bugs were found and fixed on the way: an object counted as hidden by its own
sonar echo (so a moved object was never forgotten); pictures taken mid-turn fused with the pose after the turn;
edge-cut boxes placing objects 10 cm off, and then forgetting them while in view. The dashboard map was checked in
a browser. **Not yet tested on the robot** (the Pi's camera was in use by your own script, and SSH stopped
answering).

## Face me and the greeter (added 24 Nov 2026)

From run_prototype `assistant/commands.py` (`_face_user_once`), `runtime/behaviour.py` (`pick_user`) and
`companion/greeter.py` (same numbers). run_prototype's continuous PID "follow" (`companion/control.py`) is
replaced by short gyro turns, which this file already does accurately.

**Who is "you"** (`People.user`): the biggest `person` box from object detection that covers at least 2 % of the
picture with a score of at least 0.5 (`GREET_MIN_BOX`, `GREET_MIN_SCORE`). Without object detection, the biggest
face from the face detector that is near enough (`FOCUS_MIN_FACE`). Detectors flicker (a frame without you), so a
miss of up to 1 s (`USER_MEMORY_S`) returns where you were last seen.

| Use | Does |
| --- | --- |
| `face me`, "look at me", "turn towards me", 🙂 **Face me** under the camera | one gyro turn by your bearing; "I'm already looking at you" within 5°; "I can't see you right now" if nobody is in view (the camera sees ±31°; it does not search) |
| `face me on`, "keep looking at me", "follow me", **Keep facing me** | 4 times a second (`PEOPLE_HZ`): if you are more than 10° off (`FACE_USER_KEEP_DEG`) for 0.6 s (`FACE_USER_CONFIRM_S`), it turns to you |
| `face me off`, "stop looking at me" | stops |

**Keep facing never fights you:** it does nothing while a move or a `go to` trip runs, during a calibration, while
lifted, or for 2 s after any command from a person (`FACE_USER_QUIET_S`, `Robot.last_user_cmd`). It ignores
pictures taken before its own last turn ended plus 0.3 s, because they may be mid-turn. The state shows under
the camera ("facing you", "you're 14 deg left", "settling", "can't see you", "waiting (busy)").

**Greeter** (`People.greet_step`, on every new detection frame, on by default): says hello ("Hi there!",
"Hello! Nice to see you.", "Oh, hello!", "Hey! Good to see you.", never the same twice in a row) when **more**
people than before stay in view for 1 s (`GREET_CONFIRM_S`). Someone who leaves counts as gone only after 45 s
(`GREET_ABSENT_S`), so looking away and back is not a new person. Greetings are at least 30 s apart
(`GREET_COOLDOWN_S`), and there are none while lifted. It doesn't recognise faces, so "new" means "more people".
Greetings go through `Robot.announce` (OLED, log, chat, spoken by a dashboard with "Speak replies here" ticked).
`greet off` / the **Greeter** button turns it off.

`/api/state` → `people`: keep_facing, state, greet, people (how many it counts), greetings, last_greeting. The
assistant may use `face me`, `face me on`, `face me off`.

**Bearings are now exact** (`pixel_bearing`): the angle of a pixel column was a linear share of the 62.2° field
of view; a camera maps angles through `tan`. The old formula was right at the centre and the very edge, but up to
~1.3° off in between (1.2° at 20°). Now `atan(offset / focal length)` is used by object detection, the simulated
detector and the face detector, so object placement and `face me` gain too.

Tested 24 Nov 2026 in simulation (on an empty simulated desk, so nothing hides the person): `face me` with nobody
→ "can't see you"; a person 25° left → turned, ending 6° off; a second `face me` no worse; greeted. `face me on`,
person moved to −20° plus a command from a person: no turn for 1.4 s, then turned (3° off). The person then
walked 90° round in 15° steps: followed, ending 7° off after turning 86°. `face me off`: no more turning. The
greeter's rules with a simulated clock (1 s confirm, back within 45 s not greeted, after 45 s greeted, 30 s
cooldown, phrases vary, `greet off`). Offline sentences and the assistant command. **Two things found on the
way:** a person standing behind the simulated book was (correctly) hidden from the camera, which first looked like
a bug; and a single detector miss made `face me` say it couldn't see you, which led to the 1 s memory. Not yet
tested on the robot.

## Focus timer (added 24 Nov 2026)

A Pomodoro-style work session in which the robot watches whether you're paying attention and nudges you
gently. From run_prototype `hub/focus.py` with the same thresholds, minus the phone-notification hold and the
"wiggle".

**Use:** put the robot next to or under your screen, **facing you**. Then `focus` (25 min), `focus 50`, the
dashboard's **Focus 25 min / 50 min** buttons, or say "start focus mode" / "focus for 50 minutes" (offline, no AI
key needed). "How am I doing?" or `focus` tells you the time left and how focused you've been; `focus stop` or
"stop focus mode" ends it.

**What it looks at**, twice a second (`FocusTimer.observe`). Nothing is saved or sent anywhere.

| Result | When |
| --- | --- |
| focused | your face points the way it did in the first 4 s with a face in view (`FOCUS_BASELINE_S`, the median of those 8 checks: "looking at your work"), within 0.35 yaw / 0.22 pitch |
| away | head turned further than that (or tipped well up), or a person but no face for 3 checks in a row (turned right round) |
| down | head tipped down (pitch +0.22): usually reading a phone in your lap |
| phone | YOLO sees a `cell phone` |
| absent | it can see, but nobody is there (left the desk): the timer runs on, nothing counts |
| unknown | no camera and no detection: it's just a timer |

**Faces** come from OpenCV's **YuNet** face detector (`FaceWatcher`, `cv2.FaceDetectorYN`, model
`face_detection_yunet_2023mar.onnx`, 230 kB, Apache-2.0). The model is looked for in `~/deskbot/models`,
`../run_prototype/models` and `models/` next to the script, and downloaded once from github.com/opencv/opencv_zoo
if missing. It runs on the camera's newest frame at most 4 times a second (`FACE_HZ`), and **only while a feature
asks** (`FaceWatcher.want()`); otherwise it idles. From its 5 landmarks: yaw = (nose x − eye-middle x) / eye
distance (≈ 0 facing the camera, ±0.5 ≈ 30° turned), pitch = (nose y − eye-middle y) / (mouth-middle y −
eye-middle y). **Faces smaller than 0.8 % of the picture are ignored** (`FOCUS_MIN_FACE`, further than about 1 m):
on the first live test the only face found was someone across the room, and focus mode would have judged you by
them. Without OpenCV's face detector (older than 4.5.4, or the model can't be fetched) only the phone/person
checks work; without detection either, only the timer.

**Nudges** (`_tick`): distraction time adds up while away / down / phone and resets after 3 s focused again
(`FOCUS_RESET_S`). After 20 s (`FOCUS_GRACE_S`; a phone: 10 s, `FOCUS_PHONE_S`) the robot says a short line
("Hey, eyes back on the work!", "Phone down, please. Focus time!"), never the same twice in a row, with an
annoyed/sad face. While the same distraction goes on it repeats every 45 s (`FOCUS_REPEAT_S`). Each distraction
that got a nudge counts once. Nudges go through `Robot.announce`: OLED, Activity log, assistant chat, spoken by a
dashboard with "Speak replies here" ticked. Task reminders still come during a session.

**End of session:** "You were focused 86 % of 25 minutes, with 2 distractions." The percentage is focused time /
(focused + distracted) time; absent and unknown time don't count. At ≥ 80 % (`FOCUS_GOOD`) it starts with "Great
session!". Then a 5 min break (15 min after every 4th session this run) and "Break's over! Ready for another
round?" at the end. `focus stop` during a session ends it early (logged as early) and starts no break.

**Shows:** the OLED keeps its eyes, with `FOCUS 18:42` / `BREAK 4:10` in the bottom-left corner. The dashboard's
**Focus** card has a big countdown (green during a break), the current state ("Now: looking away · 86 % focused
· 1 distraction", or "Learning where your work is - look at it…" during the first 4 s), and today's focused
minutes. `/api/state` → `focus`: mode idle/focus/break, minutes, left_s, state, focused_pct, distractions,
calibrating, faces (the face detector's status), today_min, today_sessions. Sessions are logged to `focus.json`
next to the script (last 30, written atomically); "today's focused minutes" = the sum of minutes × focused %.

The assistant sees the session's state in its context and may use `focus <minutes>` / `focus stop`.

Tested 24 Nov 2026: 37 checks with a simulated clock and hand-made inputs: 60 s focused → no nudge; away 19 s → no
nudge, 21 s → one; no repeat before 45 s, then a different line; phone after 10 s; 2 s focused does not end a
distraction, 3 s does; absent/unknown count neither way; the session end (summary, log, 5 min break, 15 min after
the 4th, early stop); the classifier (baseline from 8 checks, small turn focused, turned → away, down, phone, a
person without a face → away from the 3rd check, nobody → absent, no camera → unknown, a far-away face alone →
absent); commands, offline sentences, the AI command; the OLED corner countdown. **Live on the laptop webcam:**
YuNet loaded from `run_prototype/models`, 16 ms per frame, a face in 87 of 88 checks (that is where the far-away
face problem showed up). Not yet tested on the robot.

## Tasks and reminders (added 24 Nov 2026)

A to-do list with reminders, from run_prototype `deskbot/buddy/` (`when.py` for the time words, `tasks.py` for the
list and the reminder rule), without the phone notifications, Google Calendar or the daily briefing.

| Say / type | Does |
| --- | --- |
| `remind me in 20 minutes to drink water` | adds "drink water", due in 20 min, and reminds you then |
| `remind me at 5:30 pm to call mom`, `remind me tomorrow at 9 to …` | the same with a clock time |
| `todo buy milk by friday`, `todo water the plants` | adds a task, with or without a deadline |
| `tasks` | "Open tasks (3): #4 call mom - today at 5:30 PM, #2 buy milk - on Friday at 5 PM, #3 water the plants" |
| `done milk` / `done #2`, `undone #2` | finish / reopen (`#number` or a few words of the title) |
| `tasks remove #3`, `tasks clear done` | delete |
| dashboard **Tasks** card | the open tasks (soonest first, overdue in red), a tick box to finish, × to delete, a box to add, and the last 5 finished (click one to reopen) |

Offline, through `ask` or the microphone (no AI key needed): "remind me …", "add oat milk to my shopping list",
"what's on my list?", "I finished buy milk". With an AI key the assistant also sees the open tasks with their
numbers and may use `remind …`, `todo …` and `done #n`.

**Time words** (`parse_due`, copied from `when.py`): `in 20 minutes / an hour / half an hour / 3 days / a week`,
`today`, `tonight` (8 PM), `tomorrow`, `the day after tomorrow`, `(on|by|this|next) monday…sunday`, `at 5`, `at 5pm`,
`at 5:30 pm`, `at 17:30`, `noon`, `midnight`, `this morning / afternoon / evening` (9 AM / 2 PM / 6 PM), `end of
day` (6 PM). Rules: a day with no time means 5 PM; `at 5` with no am/pm means 1-7 → PM; `at 9` said after 9 AM
means 9 PM; a time with no day that has already passed means tomorrow; a weekday means the next one (today counts
unless "next" is said). The time words are taken out of the title. Two fixes compared to `when.py`: "at 9 call
dad" (a bare hour followed by more words) was not understood there; and relative times were cut down to the
whole minute, so "in 2 minutes" read back as "in 1 minute". They are now rounded to the nearest minute.

**Reminders** (`Reminders` thread, every 5 s, `TaskList.reminders_due`): for each open task with a deadline,
once each: **"Heads up: … in 15 minutes."** 15 min before (`TASKS_SOON_MIN`, only if the task was added earlier
than that), **"Reminder: …."** when due, **"Still open: … - it was due an hour ago."** 60 min after
(`TASKS_OVERDUE_MIN`). A later kind also counts as the earlier ones said. Each goes to `Robot.announce`: the
Activity log ("Says: …"), the OLED (the text for 10 s, and a face: focused / happy / sad), and the assistant chat
(marked ⏰). So a dashboard with **🔊 Speak replies here** ticked says it out loud (the laptop is the speaker).
With no dashboard open, a reminder is still on the screen and in the log, but nobody hears it.

**Storage:** `tasks.json` next to the script (`TASKS_FILE`; on the Pi `~/tasks.json`), the same file in simulation
and on the robot. Each change is written to `tasks.tmp` and then renamed over `tasks.json` (`os.replace`), so a
power cut leaves either the old or the new list, never half. A file that can't be read is renamed to `tasks.bad`
and the list starts empty, with the reason in the card. At most 200 open tasks, titles up to 120 characters,
finished tasks are dropped after 14 days. Times are local time.

`/api/state` → `tasks`: `open` [{id, title, due (ISO), when ("in 20 minutes"), overdue}], `done` (last 5), `file`,
`error`.

Tested 24 Nov 2026 (36 checks): 9 time phrases against a fixed "now" (Tuesday 10:00) and `say_due`; add / find by
number and by words / done / reopen / remove / no match; saved and reloaded, no `.tmp` left; reminder timing
(soon at −14 min, said once, due, overdue, no "soon" for a task added 5 min before its time); a corrupt file set
aside as `.bad`; the AI command checks; through the simulated robot: `remind me in 2 minutes to stretch`, a
reminder with no time, `todo`, `tasks`, the reminder fired once (log, chat entry for speech), `done`; offline "remind
me at 5:30 pm to call mom" (keeps the 5:30), "add oat milk to my shopping list", "what's on my list?", "I
finished buy milk"; the assistant context; the dashboard card in a browser. Not yet tested on the robot.

## Go to an object (added 24 Nov 2026)

`go to the cup`, `find the bottle`, `go home`. Also from the dashboard (a **go** button next to each object
under the map) and from the assistant ("go over to my bottle" works offline; the AI may use `go to <thing>` and
`go home`). A simple, safe stand-in for run_prototype's `deskbot/navigation/` (A\*, cost maps, route planning):
there is **no path planning**. It is built from the three features before it: the object map, gyro turns and
encoder-measured drives.

**How a trip works** (`Navigator`, its own `navigator` thread, one trip at a time):

1. **Not on the map yet?** Look around: stand still 1 s (`NAV_LOOK_S`, so the camera adds about 3 frames),
   then turn 40° (`NAV_SCAN_DEG`, less than the 62° view so nothing is skipped), up to 10 times (a full turn). Not
   seen → "couldn't find a giraffe after looking all around".
2. **Face it:** if it is more than 8° off (`NAV_FACE_DEG`), turn by the bearing (gyro), then look again for 1 s:
   a straight-on view places it best.
3. **Drive a leg:** at most 25 cm (`NAV_LEG_M`), measured by the encoders (`forward Ncm`), then look again and
   re-aim. The goal is the object's near side 22 cm (`NAV_STANDOFF_M`) in front of the front sonar. The sonar's
   safety stop is 20 cm, so it is the closest it can get. Within 3 cm (`NAV_ARRIVE_M`) → "arrived: cup 22 cm in
   front of me".
4. **A leg stopped early:** if the front sonar stopped it, the target is straight ahead and the sonar distance
   matches the object, that is the object → arrived. Anything else (another obstacle, an edge, a stuck wheel, a
   bump) ends the trip: "stopped: front obstacle at 19 cm - something is in the way (I don't plan routes around
   things)".
5. **Lost it** (faded from the map while driving) → "lost sight of the cup". At most 14 steps (`NAV_MAX_LEGS`).

Every move goes through `Robot.execute(…, source="nav")`, so all safety rules apply, and nav moves don't count
as a person's command. **Cancelled** by any command from a person (`stop`, Space, a dashboard button, the
arrow keys: `Robot.user_cmds` changes) or by being lifted. Refused while lifted, and refused when object
detection isn't running (except `go home`). `find <thing>` does steps 1-2 only: "found: the bottle, 59 cm away -
I'm facing it". `go home` drives to (0, 0), where the map started or was last reset, in the same legs, without
looking.

**Where it shows:** the reply at once ("Going to the cup ('stop' cancels)"), the banner while it runs ("Going to
cup: driving 25 cm towards the cup (61 cm to go) - Space or STOP cancels"), a dashed line from the robot to the
target on the map, the result in the Activity log ("Go to cup: arrived: …"), and the eyes (happy on arrival,
sad otherwise). `/api/state` → `nav`: active, target, step, result, x, y. The assistant's command plan waits for
a trip to finish (up to 2 min) before its next command, so "go to the bottle and take a photo" works in order.

Tested 24 Nov 2026 in simulation (20 checks): "go to the cup" while looking away, so it had to search: found it
and stopped with the cup **19-22 cm** in front of the sonar, in 9-10 s. `find the bottle`: facing it within 2.5°.
`go to the giraffe`: gave up after a full look (17 s). `stop` 1.5 s into a trip: cancelled, motors stopped.
`go home`: ended **within 3 mm** of the start. "ask go to the bottle" ran offline as a plan and arrived. Refused
while lifted. The assistant/offline forms, and "go to ../../etc" refused. Not yet tested on the robot.

## Obstacle map

- 4 × 4 m grid with 5 cm cells (80 × 80). The robot starts in the centre, facing +x.
- **Pose** is dead reckoned from the motor commands, not the encoders:
  `v = (vl+vr)/2`, `ω = (vr−vl)/TRACK_WIDTH`, integrated every tick. It drifts, which is why the map is "rough".
  Use `map reset` to start again.
- Five times a second, each sonar beam is cast from its mount point (front/rear 6 cm and sides 5 cm from the
  centre). Cells along the beam get −1 (free). If the reading is under 95 % of the 2 m range, the end cell gets +3
  (hit). Values are clamped to ±12, so a cell can change state once the robot gets new evidence.
- Cells above +2 are drawn as obstacles, cells below −1 as free, and the rest as unknown. The dashboard fetches
  `/api/map` (80 strings of `#`, `.` and space) every 0.7 s and draws it on a canvas, with the robot as a triangle.

## Camera

A thread tries `picamera2` first (640 × 480, RGB888, which is already BGR byte order), then OpenCV webcam 0 (with
DirectShow on Windows). It encodes each frame as JPEG (OpenCV, or Pillow if OpenCV is missing) at about 12 fps and
keeps **only the latest frame**. The dashboard shows it as an MJPEG stream (`/stream.mjpg`). `/snapshot.jpg`
returns a single frame.

If no camera opens, the dashboard says why and everything else keeps working. If reads fail during streaming, the
camera reopens after 2 s, up to 3 times in a row, and then gives up.

## Dashboard API

| Endpoint | Returns |
| --- | --- |
| `GET /` | the page (embedded in the script) |
| `GET /api/state` | mode, speed, pose, sonar (m or null), floor (bool or null), move, blocked, events, camera, `encoders` (counts, distance_m, working, calibrated, odometry, stuck, error), `calibration` (`active` step / side / turned, `saved` file contents, `last` result, `available`), `imu` (status, ok, heading_deg, rate_dps, tilt_deg, still, temp_c, bias_dps, level_from, message; null with `--no-imu`), `limits` (stop distances, `tilt_deg`, `bump_g`) |
| `GET /api/map` | `{n, cell, rows}` |
| `GET /stream.mjpg`, `/snapshot.jpg` | camera |
| `GET /photos/<photo-….jpg>` | a saved photo, as a download |
| `GET /oled.png` | the current OLED frame (128×64 PNG), for the dashboard mirror |
| `POST /api/cmd` `{"cmd": "forward 1"}` | `{"reply": "..."}`. It uses the same parser as the CLI. `quit` is refused here. |

### Dashboard page (redesigned 23 Nov 2026)

**Theme:** the header button cycles **◐ Auto** (follows the system), **☀ Light** and **☾ Dark**. The choice is
stored in the browser (`localStorage` key `robot-theme`), and a tiny script in `<head>` applies it before the
page paints, so it doesn't flash. CSS: dark tokens apply under `@media (prefers-color-scheme: dark)` guarded by
`:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. The map canvas redraws with the
new colours at once.

One self-contained HTML string (`PAGE`), no external files or CDNs, so it works on a Pi with no internet. It polls
`/api/state` every 300 ms and `/api/map` every 700 ms. Light and dark themes follow the system setting. Cards
reflow from three columns down to one at phone width (checked at 375 px with no sideways scroll).

| Part | What it shows / does |
| --- | --- |
| Header (sticky) | mode (dot: green robot, amber simulation, red disconnected after 3 failed polls), current move with time left, big **STOP** (also Space) |
| Banner | stuck wheel (red), calibration in progress, or the last block reason |
| Camera | MJPEG stream; a short placeholder box when the camera is off |
| Drive | D-pad (spin, forward, turn, back, STOP), **speed slider** (sends `speed x` when released), **move-for** 0.3 / 1 / 2 / 4 s for forward and back, command box with the reply under it |
| Sensors | top-down robot: each sonar beam is green, amber (within 10 cm of its stop distance), red (at or under it) or grey (silent), with the distance; IR dots green floor / red edge / grey unreadable. List: IR state, which sonars are silent, pose, heading |
| Wheel encoders | per-wheel count, "turning seen", metres rolled; pose source (encoders / motor timing); calibration summary (date, Ø, counts per turn, file) and the calibration wizard |
| IMU | heading dial (arrow; 0° up, +90° left), tilt ring (fills toward the 20° limit: green, amber from half, red at the limit), turn rate, still/moving, temperature, gyro bias, where "level" came from; Zero heading, Calibrate (keep still), Turn ±90° |
| OLED screen | live mirror of the screen, Eyes / Status / Off, Show address, text box |
| Obstacle map | 4 × 4 m grid with 0.5 m lines, robot arrow, Reset map |
| Activity | last 12 events, newest first; stops and errors in red |

All text from the robot is HTML-escaped before display. The wizard keeps no state of its own beyond "setup form
open": the steps, the live count and the result all come from `/api/state`, so the CLI and the dashboard can be
mixed (start in one, finish in the other).

The server is the standard library's `ThreadingHTTPServer`. It does not log requests, so the prompt stays readable.
It has no login, so use it only on a trusted network.

## Error handling

| Problem | What happens |
| --- | --- |
| `robot_config.py` missing or invalid | uses the built-in pins and prints a note |
| GPIO/motors cannot open (not on a Pi, pins busy) | prints the reason and falls back to **simulation**, shown as `mode: simulation` in the CLI and the dashboard |
| One sensor fails to open | the others keep working; moves that need the failed sensor are blocked |
| IR fails to open (e.g. `GPIO busy`) | the reason is shown in the "Not moving" message and in the log; it is retried every 2 s, and moves resume once it opens |
| Sonar gives no echo | sonars are opened with `partial=True`, so a silent sonar never blocks the read loop; it shows as `--` (unreadable) until its first echo |
| Wheel encoders fail to open | reason shown in `status`/`encoders`; the pose comes from motor timing and there is no stuck check |
| Wheel commanded but encoder still for 0.8 s | move stopped: "left/right/both wheel stuck" |
| IMU missing, not answering or lost | reason shown (`imu`, `status`, dashboard); retried every 2 s; heading from encoders, timed turns, no tilt/bump checks; driving is never blocked by it |
| Motor command raises an error | the move is cancelled, the motors are told to stop, and an event is logged |
| Sensor read raises an error | treated as unreadable, so the move stops |
| Dashboard port busy | CLI keeps running; use `--port 8081` |
| Browser closes the stream or the tab | the connection error is ignored |
| Bad command, negative or non-numeric time, speed out of range | a message is shown and nothing moves |
| AI brain fails (no internet, bad key, rate limit) | reason shown in the reply and `assistant`; the next brain answers, then the offline answer |
| https cannot start (no openssl, port busy) | logged; the dashboard works on http, only the browser microphone is affected |
| Ctrl+C, `quit`, or end of input | motors stopped, camera and server closed, GPIO released |

If stdin closes while the dashboard is running (for example when the script runs in the background), the script
keeps running in dashboard-only mode until Ctrl+C.

## Simulation

`--sim` uses a 1.6 × 1.2 m desk with three boxes. The sonars are ray-marched in 1 cm steps with ±5 mm noise. The IR
reads "no floor" when a point 8 cm in front of or behind the robot is off the desk. Tested on the laptop:
driving at a box stops at 20 cm, driving off the desk stops at the edge, `forward` while blocked is refused,
spin/turn durations work, bad input is rejected, the map fills in, the dashboard and API respond, and the webcam
streams.

## Performance (24 Nov 2026)

Measured first, then changed. A benchmark ran the whole robot in simulation for 30 s (control loop, IMU, OLED
drawing, simulated detector, object map, assistant, task reminders, the real HTTP server) with two simulated
dashboard tabs polling like the real page (`/api/state` every 0.3 s, `/api/map` 0.7 s, `/oled.png` 0.25 s) while
the robot drove and turned. Laptop numbers; the Pi 4 is several times slower, so compare the columns, not the
absolute values.

| | before | after |
| --- | --- | --- |
| control loop rate (target 50 Hz) | 32.3 Hz | **50.0 Hz** |
| control loop tick, median | 31.2 ms | **19.8 ms** |
| `/api/state` median / p99 | 3.8 / 22.0 ms | **2.6 / 20.6 ms** |
| `/api/map` median / p99 | 5.2 / 21.9 ms | **3.1 / 11.3 ms** |
| `/oled.png` median / p99 | 3.3 / 19.8 ms | **1.8 / 15.4 ms** |
| CPU (share of one core) | 12.0 % | **10.3 %**, while doing 55 % more control ticks |
| JPEGs made with no dashboard watching (webcam, 4 s) | ~48 | **0** |

**What changed and why:**

1. **The control loop really runs at 50 Hz now** (`sleep_until`, also used by the 100 Hz IMU thread). Each tick's
   work took only 0.8 ms (2 ms at p99), but `Event.wait(0.018)` sleeps 31 ms on Windows: its timer works in
   15.6 ms steps. So in simulation the safety checks ran every 31 ms instead of 20. `time.sleep` has ~1 ms
   resolution on Windows since Python 3.11, so short waits now use it (long waits still use the stop event, so
   shutting down stays instant). The loop also keeps a fixed schedule (`next_tick += period`) instead of "sleep
   what's left", so it doesn't drift. After a stall longer than a tick it restarts the schedule instead of
   bursting to catch up, and counts that in `late_ticks`. On the Pi (Linux) the old waits were already precise;
   there the schedule just removes drift. `/api/state` → `loop`: hz, ticks, late.
2. **Camera: boxes and JPEG only while someone watches.** Before, every frame got the detection boxes drawn and a
   JPEG encoded (~12 per second) even with no dashboard open. The detector and photos only need the raw frame.
   Now `/stream.mjpg` counts its viewers (`Camera.watch`), and the camera thread draws and encodes only while
   there is one, or for 3 s after a `/snapshot.jpg` (`Camera.snapshot` asks, then waits up to 1 s for a fresh
   frame). The dashboard's "camera live" now means "frames are arriving" (`camera.frame`), not "a JPEG exists".
   Otherwise a page would never start watching. Cost of one 640×480 frame (boxes + JPEG): 0.9 ms on the laptop,
   so ~1 % of a core at 12 fps; on a Pi 4 JPEG encoding is several times slower, very roughly 5-10 % of a core
   saved whenever nobody watches the video (an estimate; not measured on the Pi yet).
3. **OLED mirror: PNG only on request** (`Oled.png_bytes`). Before, every changed frame (10 per second, the eyes
   always move) was also PNG-encoded for the dashboard, watched or not. Now the frame is stored, and encoded only
   when `/oled.png` asks and it changed since the last ask.
4. **`status()` holds the control loop's lock for less, and is shared.** The OLED (10 times a second) and every
   dashboard tab (3 times a second each) called it, and it built everything, including the task list, the
   assistant chat, the detector info and the calibration, while holding the lock the 50 Hz safety loop needs.
   Now only the robot's own fields are read under the lock; the parts with their own locks are built after
   releasing it. One snapshot up to 0.1 s old (`STATUS_SHARE_S`) is shared between the OLED and the dashboard
   tabs (the handler copies it before adding camera fields). Commands, the assistant and `status` at the prompt
   still get a fresh one.
5. **Obstacle map text cached.** `/api/map` rebuilt 80 strings from 6400 cells on every request. Now `rows()`
   is rebuilt only after the map changed (5 times a second at most).
6. **HTTP keep-alive** (`protocol_version = "HTTP/1.1"`). A dashboard tab makes about 8 requests a second; each
   used to open a new TCP connection and a new server thread. Now the browser reuses its connections. Every
   response has a Content-Length; the MJPEG stream says `Connection: close`; any error response (≥ 400) closes
   its connection, because it may have left a request body unread. Idle connections are dropped after 30 s.

**Why not more processes?** The Pi 4 has 4 cores, but Python runs one thread at a time (the GIL). The heavy work
already runs outside it: NCNN (detection, 2 threads), OpenCV (letterbox, JPEG) and Pillow's drawing are C code
that releases the GIL, so they already use the other cores. What is left in Python (control loop, IMU, sonar
bookkeeping, HTTP, JSON) used about 10 % of one core in the benchmark. Moving the detector or the server into
separate processes would mean copying every camera frame (~0.9 MB) between processes and sharing the robot
state, for no measurable gain. run_prototype has that multi-process design (`runtime/procs.py`, shared memory)
for its much heavier load. Re-measure on the Pi before changing this; the benchmark is
`python benchmarks/simplified_load.py [folder with simplified_code.py] [seconds]` (default: `legacy/`, 30 s).

Behaviour checks after the change: all 5 feature test suites pass (assistant, objects, distance, go-to, tasks);
with the laptop webcam, 0 JPEGs while nobody watched, 48 in 4 s with one viewer, 0 after it left, and
`/snapshot.jpg` still returned a fresh JPEG; a browser showed the live video; a 404 still worked over keep-alive.

## Basic mode, ignore obstacles and motor priority (25 Nov 2026)

### What was measured on the Pi first

With the robot program (`test_20261125.py`, the same code) running on the Pi 4, motors unpowered:

| | measured |
| --- | --- |
| whole Pi | **93 % of 4 cores busy**, load average 10, CPU at **80 °C**, `vcgencmd get_throttled` = `0x80000` (it has hit the soft temperature limit, so the CPU slows down) |
| the robot program | 158 % of one core: two threads ~50 % each (one started 1.4 s after launch, one at 3.1 s, next to the camera start), the camera stack ~20 % |
| Firefox on the Pi showing the dashboard | ~150 % of one core (Firefox + its content process) |
| 50 Hz control loop | healthy: 50 ticks/s, 17 late ticks in ~6 min |
| GPIO inputs | no edge storm: encoders and sonar echo pins quiet with the motors off. GPIO 11 (front sonar echo) never goes high, so every forward move was refused: `front sonar unreadable` |

So the motor loop itself kept its 50 Hz. What felt slow was the whole Pi being saturated (the dashboard in the Pi's
own browser + video + detection) and thermally throttled, plus forward moves being blocked by the dead front sonar.
Per-thread Python stacks (py-spy) were not taken: attaching to a running process needs sudo, which was not used.

### Motor priority (`prioritize_motors`)

`main()` calls it right after the hardware and the `Robot` exist, i.e. after these threads have started: lgpio's
edge thread (sonar echo + encoder timestamps), the sonar scanner, the 100 Hz IMU and the 50 Hz control loop. It:

1. Sets `sys.setswitchinterval(GIL_SWITCH_S)` = 2 ms (Python's default is 5 ms): a thread holding the GIL hands it
   over sooner, so the control loop waits less for the interpreter when it wakes up every 20 ms.
2. Lowers the **calling (main) thread** to `nice BACKGROUND_NICE` (10) with `os.setpriority(PRIO_PROCESS,
   threading.get_native_id(), 10)`. On Linux nice is a per-thread value and new threads inherit it from the thread
   that creates them, so everything created afterwards (camera + libcamera, detector and NCNN's workers, the
   dashboard's request threads, OLED, Bluetooth, AI, reminders, faces, games...) runs below the motor threads.
   Lowering priority needs no root; raising it would, which is why the motor threads are left at 0 instead.
3. Returns a line for the log: `[robot] motor priority: motors/sensors at normal priority, everything else at nice 10`.
   Windows / macOS: only the GIL interval changes.

Verified on the Pi (simulation, because the real GPIO was in use): 2 threads at nice 0 (IMU, control loop; on the
robot also lgpio's edge thread and the sonar scanner), 21 at nice 10. When the Pi is saturated the kernel now gives
the motor/sensor threads the CPU first. It does not make the Pi less busy: for that, close the dashboard in the Pi's
own browser (use the laptop or phone), cool the Pi (heatsink/fan), or use basic mode.

### Basic mode (`--basic`)

```bash
python3 simplified_code.py --basic
```

Starts only: motors (all moves, speed, distances), sensors (sonars, IR edge, encoders, IMU, touch pad, lift
detection), the obstacle map from the sensors (sensor fusion), the obstacle/edge safety stops, and the dashboard
(camera-less). It sets `--no-camera --no-detect --no-oled --no-bluetooth --no-ai --https-port 0` and skips tasks +
reminders, faces, focus timer, face me + greeter, the assistant and `extra_features` (phone, gestures, rock paper
scissors, web APIs, ideas, sounds, dance). Commands for those answer that the feature is not available (each was
already optional: `self.<feature> is None`). `/api/state` → `basic: true`, and the CLI header says `(BASIC)`.

On the Pi in simulation: 5 threads instead of 23. On the real robot the big saving is the camera + detector
(~50-70 % of a core) and the OLED.

### Ignore obstacles (`obstacles ignore`)

| command | effect |
| --- | --- |
| `obstacles` | shows whether obstacle stops are on |
| `obstacles ignore` (or `off`) | the sonars no longer stop or refuse a move; a "sonar/obstacle" block message is cleared |
| `obstacles on` (or `watch`) | back to normal |
| `--ignore-obstacles` | start with them ignored |
| dashboard | **Obstacles: Stop for them / Ignore** under the speed slider; a red banner while ignored; the sensor card says "obstacle stops OFF" |

How: `Robot.ignore_obstacles`; `why_unsafe` → `need_clear` returns "" while it is set. That covers both the check
before a move starts and the 50 Hz check during it, for every direction. **Still active:** desk edges (IR), lifted,
tilted, bump (IMU jolt), stuck wheel, the move's time/encoder limits. The sonars still feed the map. The AI cannot
change it (`obstacles` is not in `AI_COMMANDS`). `go to <thing>` relies on the front sonar to stop ~20 cm short, so
with obstacles ignored it drives until its distance/time limit: use it only with obstacle stops on.

Use case: a dead or unplugged sonar (right now GPIO 11, the front one) otherwise blocks every move in its direction.

Test (simulation, box 30 cm ahead, `forward 2`): stops on → `STOPPED: front obstacle at 20 cm` after 9 cm;
ignored → drove the full 25 cm, `blocked` empty. `tests/test_simplified_fixes.py`: 11 passed, 2 skipped.
Backup of the previous version: `legacy/simplified_code_backup_2026-11-25.py`.

### Presentation mode hides what isn't working (25 Nov 2026)

In presentation mode (**▶ Present**, or `?present=1`) the page now hides everything that is not working, on top of
the notes, banner and error texts it already hid. The normal view is unchanged (it still shows what is broken and
why, which is what you want while fixing things).

How: `renderBroken(s)` runs after every `/api/state` refresh, after `renderCore` (which resets the sonar/IR shapes'
classes). It marks whole cards with `.broken` and single readings with `.brk`; one CSS rule,
`.presenting .broken, .presenting .brk {display:none}`, hides them only while presenting.

| hidden while presenting | when |
| --- | --- |
| Camera card | no frames arriving (off, unavailable, camera busy) |
| Assistant, Phone, Gestures, Rock paper scissors, APIs, Ideas, Focus, Tasks, Dance & sounds cards | the feature was not started (e.g. `--basic`) or failed to start; Phone also when Bluetooth has an error |
| IMU card | no IMU or it is not answering |
| Wheel encoders card | encoders unavailable |
| OLED screen card | disabled, error, or no real screen on the robot |
| Accounts | tiles that are not connected (no key / web APIs not started); the whole card if none is |
| a sonar's beam + distance | that sonar has no reading (e.g. the dead front sonar, GPIO 11) |
| an IR dot + its row | that IR sensor is unreadable |
| "sonars … silent" row, touch pad row | a sonar is silent / the touch pad is unavailable |
| object detection line + button (camera card) | no detection model |
| AI brains in the Assistant header | brains without a key or with an error |

Tested in simulation with the front sonar and rear IR patched to "no reading": normal view showed them, presentation
view hid the beam, the IR dot and both rows; with `--basic` every card of a feature that is not started was hidden.

### Camera video reconnects by itself (25 Nov 2026)

**Bug:** the dashboard's camera picture froze ("not updating") and stayed frozen. The page set the video
(`<img src="/stream.mjpg">`, one endless MJPEG connection) only once. When that connection ended (the robot program
was restarted with the tab still open, a Wi-Fi drop, a stalled connection) the browser kept the last frame and
nothing ever reconnected, while the rest of the page (polled every 0.3 s) kept updating. On the Pi the robot side
was fine: 92 distinct frames in 8 s on `/stream.mjpg`, detection at 3.3/s.

**Fix (page only, `camVideo`):** the video reconnects (`/stream.mjpg?t=<now>`, a fresh connection) when
1. the robot restarted: `/api/state` now carries `boot` (`BOOT_ID`, the start time), and a new value reconnects;
2. the `<img>` reports an error: retry after 1.5 s;
3. the picture has not changed for `CAM_STALL_MS` (4 s) while `camera_live` is true: once a second the page draws a
   16x12 copy of the image on a canvas and compares it with the last one. Real camera frames always differ a little
   (sensor noise), so an identical copy means the stream is stuck. At most one reconnect per 4 s; skipped while the
   tab is hidden.
When the camera stops (`camera_live` false) the video is removed and the placeholder shown again.

**Test** (headless Edge driven over the DevTools protocol, fake camera with a moving bar, `scratchpad cdp_test.py`):

| | old version | new version |
| --- | --- | --- |
| streaming normally (6 s) | 5 picture changes | 5 |
| after restarting the robot program (10 s) | **0** (frozen for good) | 9 (back within ~1 s) |
| stream connection stalled (10 s) | 0 | 6 (reconnected after ~4 s) |

## Camera upside down (invert) and SLAM (25 Nov 2026)

### Invert (on by default)

The camera is mounted upside down, so every frame is rotated 180 deg **at the source** (`Camera._run` ->
`rotate180`, `cv2.flip(img, -1)`; numpy fallback): the dashboard video, photos, object detection, face finding and
the object bearings (left/right) all see it upright. 0.13 ms per 640x480 frame on the laptop.

| | |
| --- | --- |
| `invert` / `invert on` / `invert off` (also `flip`, `camera invert`) | toggle / set it while running |
| `--no-invert` | start with the picture as the camera gives it |
| dashboard | **⟲ Upside down** button in the Camera card (blue while inverted); `/api/state` → `camera_inverted` |

Test (fake camera with a white block in the sensor's top-left corner): `invert=True` → block at the bottom-right of
`camera.frame`, `False` → top-left, `invert` toggled it both ways, frames stay contiguous (needed by NCNN and JPEG).

### SLAM (`slam on`, `--slam`, dashboard)

Sonar **correlative scan matching** (`class Slam`, its own thread, started after `prioritize_motors` so it runs at
nice 10 and never delays the motors). Off by default; also available in basic mode (it is mapping).

1. Every 0.1 s (`SLAM_COLLECT_S`) it turns the current sonar echoes (closer than 1.9 m) into world points using the
   current pose. Not while turning: one sensor pings only every ~0.3 s, so at 90 deg/s an echo would be placed with a
   heading up to ~27 deg newer than the one it was measured at (smeared ~10 cm).
2. Points older than 2 s (`SLAM_WINDOW_S`) leave the scan and are added to SLAM's own **reference grid** (5 cm
   cells, count per cell, capped at 30). The scan is therefore matched against older evidence only; matching against
   the live map would always say "no shift", because the newest echoes have just been painted into it.
3. Every 0.5 s (`SLAM_MATCH_S`), with at least 6 points: try every shift of +-4 cm in x and y (1 cm steps) and every
   heading change of -3, -1.5, 0, +1.5, +3 deg (about the robot): 405 candidates. Score = points landing on reference
   cells with >= 3 older echoes. Ties go to the smallest correction.
4. Apply only if the best beats "no shift" by at least max(2 points, 15 % of the points) and puts >= 30 % of the
   points on obstacles. Then **half** of it (`SLAM_GAIN`) is applied to `robot.pose` under the robot lock (the 50 Hz
   loop keeps integrating from the corrected pose) and to the buffered scan points.
5. It tracks the uncorrected pose too ("wheels + gyro alone": each odometry step since the last sample, applied
   without corrections), for comparison.
6. `map reset` and being put down somewhere new clear the scan, reference grid and comparison path.

Commands: `slam` (status line), `slam on`, `slam off`. Dashboard, Map card: **SLAM Off / On**, the status
("pose agrees with the map", "corrected 1.5 cm, -0.8 deg", match %, corrections and their total), and on the map a
dashed orange line = the path from wheels + gyro alone next to the normal (SLAM-corrected) path, with how far apart
they are now. `/api/state` → `slam`; `/api/map` → `raw_trail`.

**Limits.** Four sonars see very little: it can only correct while known obstacles are in sonar range, and on an
empty desk it does nothing (status "waiting for echoes"). It corrects slow drift (wheel slip, encoder error, gyro
drift), not a big jump (the search is +-4 cm / +-3 deg per 0.5 s). It can make small false corrections of 1-2 cm.

**Test** (simulation with a TRUE pose integrated from the simulated wheels, sonars computed from the truth, and an
injected drift of 2 cm/s sideways in the robot's estimate while moving; 24 short moves: turns, forward, back):

| | SLAM off | SLAM on |
| --- | --- | --- |
| drift 2 cm/s | 23.9 cm off | **5.3 cm** off (28 corrections in 58 matches) |
| no drift | 0.0 cm | 1.1-1.9 cm (small false corrections) |
| time per match (laptop) | | 2-10 ms |

Before the "not while turning" and "15 % better" rules the no-drift case had 3.2 cm of false corrections.

## Motors wired backwards (25 Nov 2026)

**Symptom:** pressing Forward drove the robot backwards while the sensors read right. All the code, and the Pi's
`deskbot/robot_config.py`, use the same pins (left IN1/IN2 = GPIO 22/23, right IN3/IN4 = GPIO 27/17), so both
motors' leads are the other way round on the L298N outputs. Besides being confusing it was unsafe: a "forward" move
is guarded by the FRONT sonar and IR while the robot actually drives backwards.

**Fix:** `RealHardware.drive` flips the sign of a side marked reversed, at the very last step before the pins. Every
layer above (directions, the safety checks, odometry from the commanded motion, turns) stays in the robot's own
frame, so after the fix the front sensors guard the direction the robot really moves.

| | |
| --- | --- |
| `motors` | shows each side; hints: Forward goes backwards -> `motors reverse`; Forward spins -> one side |
| `motors reverse` / `motors normal` / `motors flip` [`left`\|`right`] | set or toggle both sides or one; stops any move first |
| `--reverse-motors` | sets both reversed at start (and saves it) |
| dashboard, Drive card | **Motors: Normal / Reversed** |
| `motors.json` (next to the script) | `{"left": true, "right": true}`, written atomically, loaded at start |

The simulator's motors are never miswired: the setting is kept there but not applied. The encoders are not flipped:
they already count the real wheel direction (the pose was right). If, after reversing the motors, the pose moves
backwards while the robot drives forwards, the encoder A/B wires are swapped too.

Test (stand-in motors recording the pin calls): normal forward -> both `forward`; both reversed -> both `backward`,
and a left turn becomes left `forward` / right `backward`; one side reversed flips only that side; `motors reverse`
/ `normal right` / `normal` wrote and read back `motors.json` correctly. On the Pi `~/motors.json` was created with
both sides reversed (25 Nov).

## Threads

| Thread | Job |
| --- | --- |
| main | `input()` loop and command parser |
| control | 50 Hz: sensors, safety, motors, pose; map every 0.2 s |
| camera | grab, keep the raw frame, draw the detection boxes, then JPEG |
| detector | YOLO26n on the newest frame, at most every 0.3 s, 2 NCNN threads (`--sim`: SimDetector, the simulated desk's objects) |
| imu | 100 Hz: read the MPU-6050, bias, tilt, shock peak, heading (its own lock) |
| dashboard | HTTP server, one thread per request |
| https | the same dashboard on https (`--https-port`, for the browser microphone), one thread per request |
| faces | YuNet face detector on the newest camera frame, ≤ 4 per second, only while focus mode (or face me) asks |
| focus | the focus timer: twice a second, observe → nudge; session end → break |
| people | 4 times a second: keep facing you (if on) and the greeter |
| reminders | every 5 s: tasks due soon / now / overdue → `announce` (OLED, log, chat → browser speech) |
| navigator | one `go to` / `find` / `go home` trip: look, turn, drive a leg, look again (one at a time) |
| assistant-plan | runs one AI reply's commands in order, waiting for each move to end (one per reply; an older plan stops) |
| sounds | 10 Hz: robot state changes → sound effects for the dashboard pages |
| dance | one dance: starts each step's move on the beat (one at a time; a new dance replaces it) |

The shared robot state is guarded by one `RLock`, and the map has its own lock.
