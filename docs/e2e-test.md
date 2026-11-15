# End-to-end run: `test_e2e.py`

One file that runs **every feature of the robot, one after the other, and shows its live output** in the
terminal (works over SSH). Everything is also saved to disk.

**Standalone:** it imports no project file (not `robot_config.py`, `deskbot`, `dashboard`...). Copy just this
file to the Pi. Pins, sonar mounting positions, camera geometry and odometry calibration are copied into the
top of the file. **After rewiring or recalibrating, update both this file and the originals.**

## Running it

```bash
python3 tools/test_e2e.py --motors          # everything, including driving and the map made by spinning (robot moves)
python3 tools/test_e2e.py                   # everything except the wheels: the map is made standing still
python3 tools/test_e2e.py --sim             # fake robot on a fake desk + sample photo, on any laptop
python3 tools/test_e2e.py --only vision,map --seconds 15 --camera webcam
```

| Flag | Meaning |
| --- | --- |
| `--motors` | allows `drive` and the spinning `map`. Asks `[y/N]` once before the first move (`--yes` skips the question). |
| `--sim` | `SimHardware`: 1.2 × 0.8 m desk against a wall (back and left), open edges front and right, with a cup, a bottle and a book. Sonars are ray-cast and IR checks the desk outline. "Detections" come from the objects inside the camera's field of view. The camera defaults to Ultralytics' `bus.jpg` with a slow pan, so YOLO has real things to find. |
| `--seconds N` | how long each live view runs (default 8; vision runs at least 5) |
| `--camera` | `auto` (Pi camera, then webcam; with `--sim`: the sample photo, then a test pattern), `pi`, `webcam`, `sample`, `synthetic` |
| `--model` | YOLO model (default `models/yolo26n_ncnn_model`, then `models/yolo26n.pt`) |
| `--mic` | ALSA device, e.g. `plughw:1,0` (default: the first one in `arecord -l`) |
| `--only` / `--skip` | comma-separated list of features |
| `--out DIR` | output folder (default `e2e_results/<YYYYmmdd-HHMMSS>/`, git-ignored) |

**Ctrl+C** skips to the next feature, and **Ctrl+C twice within 1.5 s** quits. The motors are stopped either
way, because every move is wrapped in `try/finally` and `hw.close()` stops them at exit.
If one feature errors (e.g. no gpiozero on a laptop), the error is shown and the next feature still runs.

## Features and what each shows

| Feature | Live output | Saved / summary |
| --- | --- | --- |
| `pins` | wiring table: signal, BCM GPIO, physical pin, duplicate check | count of signals and duplicates |
| `sensors` | all 4 sonars with distance bars (0–200 cm) and both IR sensors (floor / EDGE), 10 Hz. The readings also go into the map. | min/max and echo count per sonar; IR states seen |
| `camera` | colour image drawn with `▀` half blocks (2 pixels per character, 24-bit ANSI), plus fps and brightness | `camera.jpg`, fps |
| `vision` | the same image with coloured boxes, one colour per track ID. Below it: ID, label, confidence, ms per frame. For each object, where it is on the desk (cm ahead / left), from the bottom-centre of its box using the pinhole model. | `detections.jpg` with labels, median ms, the tracked labels |
| `mic` | dBFS meter, a scrolling history line (`▁▂▃▄▅▆▇█`), and a clipping warning. Afterwards the clip is played back with `aplay`. | `mic.wav`, quietest/loudest level, a hint if the level never changed |
| `drive` | forward 1 s, turn left 0.6 s, turn right 0.6 s, backward 1 s. While moving: pose, all sensor values, IR states and the map updating live. | each move: `done`, `refused: …` or `STOPPED after x s: …`; final odometry |
| `map` | 8 turns of 45°. After each: 0.5 s of sonar sweeps, then one detection, and the objects are placed on the map. The map and legend are drawn after each step. | `map.png` (8 px per cell), cell counts, the object list with map coordinates |

### Safety rules (same as `13Nov-multisonar.py`)

Checked before every move and every 50 ms while moving. The move stops at once when a rule fails:

- forward: front IR sees floor, and front sonar ≥ 20 cm
- backward: rear IR sees floor, and rear sonar ≥ 20 cm
- turning: left and right sonar ≥ 8 cm

Move timing: `drive()` sleeps only for the time remaining and checks the clock again before drawing, so a
move isn't stretched by a display tick. `robot_shell.py` relies on this for accurate cm and degrees.

### Map

- Log-odds grid, 80 × 80 cells of 5 cm (4 × 4 m), with the start pose in the centre. +x is the robot's
  starting forward direction, +y is left.
- **Sonar:** 3 rays across the ±7.5° cone. Cells along the beam get −0.40 (free) and the hit cell +0.85.
  Hits beyond 1.2 m are not trusted. With no echo the beam only clears up to 1.2 m. Values are clamped to ±4.
- **IR:** floor under the sensor gives −0.60, no floor marks an edge cell.
- **Pose:** dead reckoning from the commanded wheel speeds (`WHEEL_SPEED_AT_FULL` 0.25 m/s, `TRACK_WIDTH`
  0.12 m), integrated in 10 ms sub-steps. There are no encoders yet, so the real robot's map is only as good
  as this calibration.
- **Objects:** a detection's robot-frame point is transformed by the pose. The same label within 15 cm is
  merged into a running mean and counted ("seen 3x").
- Colours: red = obstacle (p > 0.7), light = free, dark = unknown, yellow = desk edge, blue = path,
  green = robot (pale green pixel = heading). The image is cropped to the explored area.

### Tracking

`ultralytics`' ByteTrack needs the `lap` package, which Smart App Control blocks on the dev laptop.
To stay standalone, this file has a small IoU tracker instead: same label and IoU > 0.3 keeps the ID,
otherwise a new ID; a track is dropped after 10 missed frames. YOLO runs on the BGR frame at imgsz 320,
conf 0.25. The first (slow) call is a warm-up and is not timed.

### Output when piped

When stdout is not a terminal (e.g. `> log.txt`), the screen is not redrawn. Instead the status text is printed
once a second, and the last image is printed at the end of each feature. The output is forced to UTF-8 so the
block characters work on Windows consoles too.

## Verified (Windows laptop, 2026-11-15)

- `--sim --seconds 4`: every feature ran.
  - Sensors: left 38 cm and rear 54 cm, matching the simulated walls.
  - Sample-photo camera: 16 fps.
  - YOLO `.pt`: 120 ms/frame; tracked bus + persons. `detections.jpg` was checked by eye.
  - The 4 drive moves completed.
  - Map: back and left walls in red, and cup / bottle / book placed at (+33, +12), (+40, −18), (−30, +27) cm.
    These match the true positions relative to the start pose. `map.png` was checked by eye.
- Real mode on the laptop: the webcam ran at 14 fps and YOLO at 159 ms, detecting a person.
  Sensors and map stopped with "No module named gpiozero" and the mic with "arecord not found", as expected
  off the Pi. Drive was skipped without `--motors`.

`robot_shell.py` (docs/robot-shell.md) contains a copy of this file's hardware/vision/map code, so it runs on its own.

Not yet run on the Pi: real sonars, IR, picamera2, NCNN, arecord/aplay and motors.
