# Interactive robot shell: `robot_shell.py`

A command prompt where you type exactly what the robot should do: `forward 30cm`, `left 90`, `find cup`,
`goto bottle`, `map`, `home`, `detect 10`, `listen 5`... Each command shows its live output (sensor values,
the camera image with YOLO boxes, the map, the pose) under the prompt, then hands the prompt back.

```bash
python3 tools/robot_shell.py                 # real robot; wheels locked until `motors on`
python3 tools/robot_shell.py --motors        # wheels allowed (asks once; --yes skips the question)
python3 tools/robot_shell.py --sim           # fake robot on a fake desk, on any laptop
python3 tools/robot_shell.py --sim "forward 20; left 90; find cup"     # run a command line, then exit
```

**Standalone:** one file, no other project file needed. Copy just `robot_shell.py` to the Pi. It contains its own
copy of the hardware, camera, YOLO, map and safety code from `test_e2e.py`, plus the pins, sonar mounts, camera
geometry and odometry calibration. **After rewiring or recalibrating, update the constants at the top of
`robot_shell.py`, `test_e2e.py` and `robot_config.py`.** The copied code must also be changed in both files
if it is fixed later.

Other flags: `--camera auto|pi|webcam|sample|synthetic`, `--model PATH`, `--mic plughw:1,0`, `--out DIR`
(pictures and recordings; default `e2e_results/shell-<time>/`).

## Talking to it

- **Plain English works.** "go forward 30 cm", "please turn left 90 degrees", "find the cup", "where is the bottle",
  "go to the bottle", "what do you see", "where am i", "take a picture", "turn around", "go back home", "scan",
  "show me the map", "speed up" / "slow down". The shell prints how it understood you (`-> forward 30cm`).
- **Several steps:** `;`, `then`, `and then` or `and`: "forward 20 then left 90 and look".
- **Menu:** press Enter on an empty line for 16 numbered common actions, then type a number. (Typing `menu` also works.)
- **Short forms:** `f` `b` `l` `r` (move), `s` (stop), `q` (quit), `?` (help), `cam`, `pic`, `see`, `mic`, `scan`.
- **Missing details are asked for:** `find` with no object asks "Which object?". A piped script gets a
  clear error instead of a question that would hang.
- **Typos get a suggestion:** `fowrard 10` -> "I don't know 'fowrard'. Did you mean forward?" (difflib, cutoff 0.6).
- **Errors are plain sentences with the fix**, e.g. no gpiozero -> "only exists on the Raspberry Pi, on a laptop
  start with --sim"; a busy pin -> "is another robot script running?". Locked wheels -> "type motors on".
- **Every move says what it will do and how it went:** `→ forward 30 cm (2.4 s at speed 0.5)`, then
  `✓ done` or `⚠ STOPPED after 1.2 s: obstacle 18 cm ahead (safety stop - the robot is fine)`.
- **Welcome card** at start: simulated/real, wheels locked/unlocked, which YOLO model was found, example sentences.
- **Coloured prompt** (`robot (wheels locked) >` is yellow while the wheels are locked). On the Pi, up-arrow history is kept
  in `~/.robot_shell_history`, with Tab completion. Windows Python has no readline, so neither is available there.
- `examples` lists sentences to try. `faster` / `slower` change the speed by 0.1. A bare `motors` toggles the wheels.

### How the plain-English parsing works (`normalize()`)

Rule-based, no AI model, nothing leaves the robot:
1. File-name commands (`run`, `snap`, `play`) are passed through untouched.
2. Lower-case. Drop `? ! ,` and any `.` that is not a decimal point.
3. Whole-phrase table (`PHRASES`): "what do you see" -> `look`, and so on.
4. Number words -> digits ("thirty" -> 30, "half" -> 0.5). A number followed by a unit word is merged
   ("30 centimeters" -> `30cm`, "90 degrees" -> `90`, "half a meter" -> `0.5m`).
5. Leading filler is dropped (please, can you, robot, ok...).
6. The first matching verb rule (`VERB_RULES`, regex at the start) rewrites the verb: "go to" -> `goto`,
   "turn left" -> `left`, "where is" -> `find`... `go home` is checked before `go back`.
7. Short forms (`ALIASES`). `speed 0.4` becomes `set speed 0.4`. Filler words in the arguments are dropped (the, a, by, for, to...).

Plain commands come out unchanged, so everything in the table below still works as typed.

## Fixes after the second robot test (2026-11-15)

**"It is not considering the calibration values."** Saving and loading worked (checked across separate processes).
What went wrong is that one rate cannot describe a real robot. The motors need a moment to spin up, so a 1 s
calibration move included that start-up, but a 20 cm move at ~50 cm/s (0.4 s) is mostly start-up and falls short.
Short turns (45°) were hit the hardest. Changes:

- **Two-length calibration.** Driving is measured at 0.4 s and 1.0 s, alternating forward/back (so the robot ends near
  where it started). Turns are measured at 0.5 s and 1.2 s, alternating left/right. A straight-line fit
  `amount = rate × (t − lag)` gives the real speed **and** the start-up lag (clamped to −0.3…0.6 s; negative = coasting).
- **Moves use both:** motor-on time = amount / rate + lag (`move_time()`). Odometry counts no motion during the lag.
- **Saved after each part** (driving, then turns), so Ctrl+C half-way keeps what was finished.
- **Visible:** every move says `calibrated` or `NOT calibrated`. The welcome screen shows the settings file it loaded,
  and `calibrate show` prints the values and the file path.
- Commands: `calibrate` (all), `calibrate drive`, `calibrate turn`, `calibrate show`, `calibrate reset`.

Verified on a test robot (4× faster than the model, half-rate turns, 0.2 s spin-up lag), every move in a new process:

| Command | Before | After |
| --- | --- | --- |
| `forward 20cm` | 54.9 cm | 20.4 cm |
| `forward 10cm` | – | 10.3 cm |
| `back 20cm` | 40.8 cm | 20.5 cm |
| `left 45` | 6.8° | 46.0° |
| `left 90` | 29.0° | 90.3° |
| `right 30` | – | 30.3° |
| `spin` | – | 359.3° |

The fit recovered the lag (0.20 s) and the speeds exactly.

**"The dashboard says unable to connect."** Two causes:
1. It only listened on the Pi itself (`127.0.0.1`), so a browser on the laptop could not reach it. It now listens on the
   network by default and prints `open http://<pi-ip>:8080 on your laptop or phone`, with the no-login warning.
   `dashboard local` / `--local` keeps it to the Pi only (then use the SSH tunnel it prints).
2. The first map/camera request loaded numpy in a server thread while the main thread was waiting at the prompt.
   On Windows that deadlocks and freezes every request. numpy and OpenCV are now loaded in the main thread when the
   dashboard starts.

## Web dashboard (built into the same file)

```bash
python3 tools/robot_shell.py --motors --dashboard        # shell + dashboard: open http://<pi-ip>:8080 on your laptop/phone
python3 tools/robot_shell.py --motors --dashboard --local   # only the Pi itself (use the printed SSH tunnel from the laptop)
robot (wheels on) > dashboard 8090                 # or start it from the prompt; `dashboard stop` stops it
```

The dashboard has **no login: anyone on the same Wi-Fi can drive the robot**, and the shell says so. Private alternative:
`--local`, then on the laptop `ssh -L 8080:localhost:8080 <user>@<pi-ip>` and open http://localhost:8080.

What the page shows (one page, light/dark theme, works on a phone):

| Card | Contents |
| --- | --- |
| Header | simulation / real robot, wheels on/locked, what it's doing now ("moving forward: forward 20cm"), pose, big **STOP** |
| Drive | arrow pad (small / medium / big steps: 5 cm·15°, 10 cm·30°, 20 cm·90°), keyboard **arrows / WASD**, **Space = stop**; buttons What do you see? · Find… · Go to… · Scan map · Go home · Spin · Reset map; a command box that takes anything the shell takes, plain English included |
| Sensors | 4 sonar bars (red when closer than the stop/side distance), both IR (floor / edge), how old the reading is, hardware errors |
| Camera | live picture (~4 fps, half resolution, JPEG); **boxes (YOLO)** switch draws detections with track IDs and lists them |
| Map | occupancy map (refreshed every 1.5 s, 0.5 s while moving) + legend + objects with distance and bearing from the robot |
| Settings | speed / turn speed / stop distance sliders (sent as `set …`, so saved as defaults) + calibration status |
| Log | everything the shell prints (terminal and dashboard commands), live |

### How it works

- **Standard library only:** `http.server.ThreadingHTTPServer` in a daemon thread; the page is one inline HTML string
  (`DASH_HTML`) that polls `GET /api/state?since=<log seq>` every 300 ms. The camera and map are `<img>` tags reloaded one after the
  other (`/camera`, `/map`). Images are JPEG through OpenCV when available, otherwise a small built-in PNG encoder (`png_bytes`, zlib + struct).
- **API:**
  - `GET /`, `GET /api/state`, `GET /camera`, `GET /map`
  - `POST /api/cmd {"cmd": "..."}`
  - `POST /api/stop`
  - `POST /api/toggle {"boxes": bool}`
- **One robot, two users.** A re-entrant lock `BUSY` is held by whatever is using the hardware:
  - **Terminal command:** holds the lock while it runs. If the dashboard is busy, it waits up to 3 s, then says "Busy: the dashboard is running '…'. Wait, or type stop".
  - **Dashboard command:** runs in a `dashboard-cmd` worker thread. If something is already running, the page shows "busy with … - press Stop first".
  - **Background sampler:** every 0.25 s, only if the lock is free, it reads the sensors and grabs a camera frame (only while the page shows the camera and the camera is already open). That keeps the cards live while idle.
  - **Opening the camera / loading YOLO:** these are slow (seconds), so they run as visible commands (`opencamera`, `loadmodel`) that show as busy, not hidden inside the sampler.
- **Stop works at any time.** STOP / Space / `stop` in the terminal / Ctrl+C sets `STOP_REQ` and turns the motors off directly (no lock needed).
  `drive()` checks `STOP_REQ` every 20 ms and raises `StopRequested`, which also ends multi-step commands (`find`, `map`, `goto`, `a then b`).
- **Live data while moving:** `drive()` publishes sonars, IR, pose and direction to `TELE` each loop. Every camera frame and detection
  from any command (terminal `detect` too) goes to `LATEST`, so the page always shows the newest.
- **Output:** the module's `print` copies every line (ANSI stripped, image lines dropped) into `LOG` for the Log card.
  Output of dashboard commands goes **only** to the page, so it can't scribble over what you are typing in the terminal. Live
  redraws (`Screen`) happen only in the terminal thread; dashboard commands print a status line once a second instead.
- **Safety:** the wheels can only be unlocked in the terminal (`motors on` asks for confirmation there). Commands that ask
  questions or touch files (`calibrate`, `run`, `quit`, `dashboard`) are refused from the page ("needs the terminal").

## Calibration, safety filtering and the YOLO model (2026-11-15, after the first test on the robot)

First test on the robot found these problems, now fixed:

| Problem | Cause | Fix |
| --- | --- | --- |
| `forward 20cm` only jerks | the safety check stopped on the **first** bad reading. With 4 sonars pinging and motor noise, single false echoes (or one IR flicker) are common | a hazard must persist: sonar < stop distance for `SONAR_CONFIRM_S` = 0.10 s; IR edge on `IR_CONFIRM` = 2 readings in a row (40 ms). Before a move starts, all 3 of 3 readings must show the hazard. The stop message says which sensor fired and suggests `sensors` if nothing is there. |
| `back 20cm` goes 80 cm | moves were converted to time with the guessed `WHEEL_SPEED_AT_FULL` 0.25 m/s; the real robot is ~4× faster | **calibration** measures the real cm/s and deg/s |
| `spin 360` / `left 45` barely move | turning on the spot needs more torque than driving straight; PWM 0.5 stalls | separate `TURN_SPEED` (default 0.7, `set turn 0.8`). Calibration raises it in 0.15 steps until the robot really turns. |
| `look` says no YOLO model | only `models/` next to the script was searched, and the Pi copy has no models/ | searches the remembered path, `models/` next to the script, the current folder, `~/models` and `~/desk-assistant-robot/models`. If nothing is found, it downloads `yolo26n.pt` (~5 MB, once) into `models/` and remembers it. `model export` makes the faster NCNN version on the Pi. |

### Calibration (`calibrate`)

At startup on the real robot, if nothing is saved yet, the shell asks "Calibrate now? [Y/n]". It is about a minute of short moves:

1. **Driving speed:** Enter keeps the current one (lower = gentler and more accurate).
2. **Forward:** drives 1 s. If the front sonar sees something 25–160 cm away, it measures the distance moved itself
   (median of 7 readings before and after); otherwise it asks you to measure from a mark. You can always type
   the real value. Rate = cm / the time the motors really ran.
3. **Backward:** the same with the rear sonar.
4. **Turn left, then right:** turns 1 s and asks "How many degrees did it turn?" (90 = quarter turn, 360 = full circle).
   If under 15°, it raises `TURN_SPEED` by 0.15 and tries again, up to 1.0.

Saved in `robot_shell_settings.json` next to the script (`…_sim.json` for `--sim`, so the simulator never uses the
real robot's numbers; both git-ignored). The file also holds speed, turn speed, stop/side distances, map steps and the
YOLO model path. `set …` saves too. Loaded at every start; the welcome line shows "calibrated 2026-11-15: forward 50 cm/s @ 0.5 …".

Moves use `rate(direction)`: the calibrated cm/s or deg/s × (current PWM ÷ PWM at calibration), so after
`set speed 0.3` the rate is scaled down (re-run `calibrate` for best accuracy at a new speed). Uncalibrated, it falls back to
the wheel model. Odometry (map, `home`, `goto`) now integrates these same measured speeds (`Odometry.advance_vw`).

`calibrate forward|back|turn` redoes one part. `calibrate show` shows the values, `calibrate reset` clears them.

### Faster safety loop

Sensors and stop rules run every 20 ms (`LOOP_DT`). The screen and map, which are slow to draw on a Pi, update
every 0.15 s (`DRAW_DT`). Before this, drawing every loop made the checks slower than they should be.
Trade-off: at a fast calibrated speed (50 cm/s), the 0.1 s confirmation adds up to ~5 cm before stopping, so a
front obstacle ends ~15 cm away instead of 20. Use `set stop 25` or a lower speed if that is too close.

### Verified (sim with a deliberately wrong robot)

A test robot drove straight 4× faster than the model, turned at half rate, and its front sonar gave a false 5 cm echo 15 % of the time:
- Before calibration: `forward 20cm` moved 80.4 cm, and `left 90` turned 45.7°.
- After `calibrate`: `forward 20cm` 20.3 cm, `back 20cm` 20.3 cm, `left 90` 90.1°, `right 45` 45.6°, `spin 360` back within 1°.
- No forward move was stopped by the false echoes.

A robot that stalls when turning below 0.85 PWM:
- Calibration raised the turn speed 0.7 → 0.85 and measured 203°/s. `left 90` then turned 91.9°.
- A real wall still stopped `forward 50cm` (18 cm gap).
- The settings file reloads correctly.

## Commands

| Group | Command | What it does |
| --- | --- | --- |
| Move | `forward [20cm\|0.3m\|300mm\|2s\|30]` | drive forward. A plain number is cm; the default is 20 cm. |
| | `back [...]` (`backward`) | drive backward |
| | `left [90\|45deg\|1s]`, `right [...]` | turn on the spot. A plain number is degrees; the default is 90. |
| | `spin [360]` | turn left by that many degrees |
| | `home` | turn to face the start pose, drive there, turn back to the start heading |
| | `stop` | motors off |
| Tasks | `find <object>` | look with the camera. If the object isn't seen, turn 360/`steps` degrees and look again, up to a full turn. When seen, turn to face it. `find any` = the first object seen. Part of a name works (`find phone`). |
| | `goto <object>` | `find`, then drive forward (distance − 10 cm). The front sonar's stop rule halts the robot in front of it, which counts as arrived. |
| | `map [steps]` | spin on the spot, sweeping 4 sonars + IR + camera into the map (default 8 × 45°). With the motors off, maps from the current spot. |
| Sense | `status` | every sensor once, pose, motor state, settings, map size |
| | `sonar [front\|left\|right\|rear]`, `ir` | one reading |
| | `sensors [s]`, `camera [s]`, `detect [s]`, `listen [s]` | the live views from `test_e2e.py` (default 8 s; Ctrl+C ends early) |
| | `snap [file]` | one picture, drawn in the terminal and saved |
| | `look` | objects in view now: label, confidence, distance, bearing, ahead/left. Each one is also added to the map. |
| | `play [file]` | `aplay` a recording (default: the last `listen`) |
| Map | `showmap`, `objects`, `pose`, `resetmap` | draw the map + legend; list objects with their distance/bearing from the robot's current pose; dead-reckoned pose; clear the map and make the current spot the new origin |
| Settings | `set` | show all settings (changes are saved as the default) |
| | `set speed 0.4` | motor PWM 0.1–1 for forward/back |
| | `set turn 0.8` | motor PWM for turning on the spot |
| | `calibrate [forward\|back\|turn\|show\|reset]` | measure real speeds (see above) |
| | `model [download\|export\|<path>]` | YOLO model: show, download, export to NCNN, use a file |
| | `set stop 25` | front/rear stop distance in cm |
| | `set side 8` | side stop distance while turning, in cm |
| | `set steps 8` | headings per turn for `map` and `find` |
| | `motors on\|off` | unlock (asks once) or lock the wheels |
| Script | `a; b; c` | several commands on one line. An error or Ctrl+C cancels the rest. |
| | `repeat <n> <command>` | e.g. `repeat 4 right 90`. Only repeats the command right after it, not anything after a `;`. |
| | `run <file>` | one command per line; `#` starts a comment |
| | `wait <s>`, `pins`, `help [cmd]`, `quit` / Ctrl+D | |

Tab completion (on the Pi; Windows Python has no readline) completes command names, sonar names, setting
names and object labels for `find`/`goto`.

## How it works

- **`cmd.Cmd`** (standard library) provides the prompt, the `help <command>` docstrings and completion.
  `onecmd` is overridden to split on `;` and to catch errors per command. Both Ctrl+C (`KeyboardInterrupt`)
  and errors stop the motors and return to the prompt instead of exiting.
- **Moves → time.** There are no encoders, so distances and angles become motor-on times:
  - linear speed v = `SPEED × WHEEL_SPEED_AT_FULL` (0.5 × 0.25 = 0.125 m/s)
  - turn rate ω = 2v / `TRACK_WIDTH` (2.08 rad/s)
  - `forward 30cm` = 2.4 s, and `left 90` = 0.75 s.

  Calibrate `WHEEL_SPEED_AT_FULL` and `TRACK_WIDTH` at the top of `robot_shell.py` (docs/encoders.md has the method).
- **Every move goes through `drive()`.** It checks the safety rules before starting and every 50 ms
  while moving: front IR + front sonar ≥ stop distance going forward, rear IR + rear sonar going backward,
  side sonars ≥ side distance while turning. The same loop also updates the odometry and the map.
  `drive()` now sleeps only for the time remaining and checks the clock again before drawing, so it doesn't
  overshoot the requested time. In the sim, a 45° turn ends at 47° (the fake sonars take about 15 ms to compute).
- **Inline display.** Unlike `test_e2e.py`, which clears the whole terminal, the shell's `Screen` redraws in
  place under the prompt. It moves the cursor up the number of lines it last drew (`ESC[nF`, then `ESC[J`), so
  earlier commands stay visible.
- **Settings** are the module-level constants at the top of the file (`SPEED`, `STOP_DISTANCE`, `SIDE_STOP_DISTANCE`,
  `SPIN_STEPS`). `set` rewrites them through `globals()`, and `drive()` / `blocked()` read them on every call.
- **find / goto / home** use the same pose the map uses. Detections are robot-frame points: the sim uses
  ideal detections, the real robot uses YOLO plus the ground-plane pinhole model. Bearing = atan2(left, ahead).
  For `home`, the heading to turn = wrap(atan2(−y, −x) − θ), then distance = |(x, y)|, then a turn by wrap(−θ).
- **Motors** are locked on the real robot unless `--motors` or `motors on` is used. Unlocking asks for
  confirmation once (`--yes` skips it). On exit the motors are stopped and every device and the camera are closed.

## Verified (Windows laptop, --sim, 2026-11-15)

- Plain-English parsing: 36 phrasings checked, e.g. "please go forward thirty centimeters" -> `forward 30cm`,
  "where is the bottle?" -> `find bottle`, "go back home" -> `home`, "half a meter" -> `0.5m`, "robot, stop!" -> `stop`.
- Piped session from an empty folder:
  - Enter showed the menu, and `2` ran `look`, `3` ran `forward 20cm`.
  - "please go forward thirty centimeters then turn left 90 degrees" made two moves.
  - "where is the bottle" turned until it found the bottle and faced it.
  - `fowrard 10` got the "Did you mean forward?" suggestion.
  - `find` with no object gave a clear error, since no one was at the keyboard.
  - `99` said there is no such menu item.
  - `slower`, `set`, `examples` and `help f` all worked.
  - "go back home" returned to (−0.1, +0.1) cm.
- Real mode on the laptop: "wheels are locked" message, then the friendly gpiozero and no-model errors.


- `status; forward 10cm; left 45; look; find bottle; goto cup; objects; pose; home; pose`
  - found the bottle after 6 turns and faced it
  - `goto cup` arrived with the front sonar at 20 cm
  - objects mapped at their true positions: cup (+33, +12), bottle (+40, −18), book (−30, +27) cm
  - `home` returned to (−0.6, −0.2) cm, heading 2°
- `left 45; left 45; right 90; spin; forward 10; back 10`: headings 47 → 93 → 2 → 2°, and the robot came back to (0, 0).
- Piped session: `help`, `help goto`, `set`, `set speed 0.3`, `set stop 30`, invalid sonar name, invalid
  distance (`forward abc`), `repeat 2 right 90`, `map 4`, `showmap`, `resetmap`, `objects`, an unknown
  command, `quit`. Each error printed a message and the shell continued.

- Standalone check: `robot_shell.py` copied alone into an empty folder ran all of the above, plus `detect 3`
  (YOLO via `--model`), `snap`, `listen 2`, `camera 2` and `map 2`. pyflakes reports no undefined names.

Not yet run on the Pi with real motors, sonars, camera and mic.
