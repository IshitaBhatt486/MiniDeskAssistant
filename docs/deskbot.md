# `deskbot`: the full app, CLI and scripts (15 Nov 2026)

`deskbot/` is the organised application package. It runs the robot (4 ultrasonic + 2 IR + motors + safety loop),
the camera with YOLO26n/ByteTrack, the three fusion maps and the web dashboard, started by one command. Since the
second 15 Nov change it runs as **four processes, one per Pi core** ([runtime.md](runtime.md)).
`--single-process` keeps the original single-process app. It also has an interactive CLI.

The older entry points still work and are unchanged apart from one addition (`test_sensors.py` got a camera option; since 20 Nov 2026 all hardware tests are in `hardware_tests/hardware_test.py`):
`3Nov-latest.py`, `13Nov-multisonar.py`, `dashboard/server*.py`, `test_*.py`. `deskbot` **re-uses** their robot,
safety and simulator classes instead of copying them.

## Commands

| What | Script (one command) | Same via Python |
| --- | --- | --- |
| Install everything (once) | `scripts/setup.sh` (`--no-assistant` skips the voice parts) | |
| **Voice assistant + remote + presence** (17 Nov) | `scripts/assistant.sh` (`--sim` anywhere) | `python -m deskbot assistant` ([assistant.md](assistant.md)) |
| Copy to the Pi / hotspot / start on boot | `tools/deploy.sh`, `scripts/hotspot.sh`, `scripts/install-service.sh` | ([deploy.md](deploy.md)) |
| **Start the whole app** on the robot | `scripts/start.sh` (`--lan` for phone/laptop access) | `python -m deskbot run` |
| Start in simulation (any computer) | `scripts/sim.sh` (`--camera webcam` for real YOLO on a webcam) | `python -m deskbot run --sim` |
| **Run all tests** | `tools/run_tests.sh` (`-v` for names) | `python -m deskbot test` |
| Test sensors | `scripts/sensors.sh` (menu) or `scripts/sensors.sh front\|left\|right\|rear\|front-ir\|rear-ir\|all\|camera\|detect` | `python -m deskbot sensors` |
| Export + benchmark the model | `scripts/export-model.sh` | `python -m deskbot model export` / `bench` / `info` |
| System check | `scripts/doctor.sh` | `python -m deskbot doctor` |
| Interactive menu for all of it | `scripts/deskbot.sh` | `python -m deskbot` |
| Wiring + camera mount | `scripts/deskbot.sh pins` | `python -m deskbot pins` |
| **Benchmark** (lighting, tracking, latency) | `tools/run_benchmarks.sh [download\|images\|video\|system]` | `python -m deskbot bench …` ([benchmark.md](benchmark.md)) |
| Allow real-time priority (once, Pi) | `scripts/enable-realtime.sh` | |

Run the scripts with `bash scripts/start.sh`, or make them executable once with `chmod +x scripts/*.sh`.
`.gitattributes` forces LF line endings on `*.sh`/`*.py`; a CRLF script fails on the Pi with `$'\r': command not found`.

### `run` options

| Option | Default | |
| --- | --- | --- |
| `--sim` | off | simulated robot, desk and camera |
| `--camera` | `pi` (`sim` with `--sim`) | `pi`, `webcam`, `sim`, `none`, a webcam index, or a video file |
| `--lan` | off | bind `0.0.0.0` so other devices can open `http://<pi-ip>:8000`. **No login**: trusted networks only |
| `--host`, `--port` | 127.0.0.1, 8000 | |
| `--single-process` | off | the original one-process app (threads, no core pinning, no face-the-user) |

If the camera or model fails, the app still starts. Vision is disabled, the reason is logged and shown on the Camera card,
and the maps keep working from sonar + IR.

## Interactive CLI

`scripts/deskbot.sh` (no arguments):

```
┌─────────────────────────────────────────────────┐
│ Desk Assistant Robot  v1.0.0                    │
│ ↑/↓ to move, Enter to choose, Ctrl+C to go back │
└─────────────────────────────────────────────────┘
? What do you want to do?  (↑/↓, Enter)
 » ▶  Start the robot (dashboard + maps + vision)
   ▶  Start in simulation (no hardware needed)
   🔧 Test sensors (ultrasonic, IR, camera, detection)
   👁  Vision model: export / benchmark / info
   🩺 System check
   ✅ Run unit tests
   📌 Show wiring + camera config
   Quit
```

- Starting asks which camera to use, whether to open the dashboard to the LAN, and the port. Each question has a sensible default.
- **Test sensors** is a menu of: each ultrasonic and IR sensor (with its pins), all sensors in one live table, the camera
  preview in the terminal, and camera + detection in the terminal (boxes drawn, fps / inference / capture→result latency
  and tracked labels on a status line).
- **System check** prints a table of ✓ / ! / ✗ with a "How to fix" column. It covers Python, the venv, the board, numpy,
  OpenCV, ncnn, gpiozero, picamera2 + camera detection, the pin config, the NCNN model,
  disk space and CPU temperature.
- Libraries: **questionary** (arrow-key prompts on prompt_toolkit) + **rich** (tables, panels, live table). This was
  the commonly recommended modern pairing; InquirerPy hasn't had a release since 2022. `deskbot/ui.py` falls back to
  numbered menus and plain text when they're missing or stdin isn't a terminal, so the CLI also works piped or
  before setup. Output is forced to UTF-8 so Windows consoles don't crash on ↑ ✓ °.

## Package layout

```
deskbot/
  __init__.py        version, ROOT, MODELS_DIR; adds the repo root + dashboard/ to sys.path (re-use, no copies)
  __main__.py        python -m deskbot
  cli.py             argparse sub-commands + interactive menu
  ui.py              questionary/rich helpers with plain fallbacks
  config.py          CameraConfig, VisionConfig, MappingConfig, object sizes (pins stay in robot_config.py)
  robot.py           make_robot(sim): MultiSonarRobot on GPIO or FusionSimHardware (sim desk with COCO objects, shuffle())
  vision/            camera.py, detector.py, pipeline.py, geometry.py, model.py, bytetrack.yaml, lap_compat.py   -> vision.md
  mapping/           grid.py, semantic.py, fusion.py                                                             -> fusion.md
  runtime/           app.py, procs.py, shared.py, shm.py, sched.py, hardware.py, proxy.py, safety.py, behaviour.py -> runtime.md
  bench/             datasets.py, lighting.py, metrics.py, run.py                                                -> benchmark.md
  web/
    server.py        FusionHandler(dashboard Handler) + run_app()
    static/          cards.html (new cards), fusion.js, fusion.css
  checks/
    sensors.py       interactive sensor tests
    doctor.py        system check
scripts/             setup, start, sim, test, sensors, doctor, export-model, deskbot, benchmark, enable-realtime (+ _common.sh)
tests/               test_mapping.py (pure logic), test_system.py (sim end-to-end, HTTP API, real YOLO if installed),
                     test_runtime.py (shared memory, motor arbitration, flow, behaviour, reflections, real processes),
                     test_bench.py (AP / tracking metrics, lighting)
requirements.txt, requirements-vision.txt
models/              (git-ignored) yolo26n.pt + NCNN export
```

## Web server (`deskbot/web/server.py`)

- `FusionHandler` subclasses `dashboard/server.py`'s `Handler`. That gives the same `/api/state`, `/api/move`, `/api/stop`,
  `/api/settings` and `/api/sim/reset`, and the same rules: POST requires `Content-Type: application/json`, there is a
  body size limit, and only whitelisted static files are served. The legacy `serve()` handles Ctrl+C → motors stopped
  → GPIO released.
- **One HTML source.** `GET /` reads `dashboard/static/index.html` and splices in `cards.html` before the Ultrasonic
  card, adds `fusion.css` and `fusion.js`, and changes the title. Edits to the original page show up in both dashboards.
  The old "Occupancy map" card stays hidden, because `/api/map` returns 404 on this server.
- New routes: `GET /api/fusion` (gzip), `POST /api/fusion/reset`, `GET /api/vision`, `GET /camera.mjpg`,
  `GET /camera.jpg`, `POST /api/sim/shuffle`. `/api/sim/reset` also clears the maps.
- `run_app()` start order: robot → detector → camera → vision thread → fusion mapper → HTTP. On exit: stop MJPEG
  streams → mapper → vision (camera closed) → robot (motors stopped, GPIO released).

### Threads in one running app (`--single-process`)

The default multi-process layout is in [runtime.md](runtime.md) §2.

| Thread | Rate | Does |
| --- | --- | --- |
| robot sensor loop (`robot.py`) | 10 Hz | reads 4 sonars + 2 IR |
| move worker (`robot.py`) | 50 Hz during a move | safety checks → motors (unchanged) |
| camera (`FrameGrabber`) | camera fps (30) | newest frame only |
| vision (`VisionPipeline`) | as fast as inference allows | detect + track the newest frame |
| mapper (`FusionMapper`) | 10 Hz | odometry, geometric + semantic updates |
| HTTP (one per request) | | state, maps, MJPEG |

## Tests (`tools/run_tests.sh`)

29 tests, ~30–90 s, no hardware needed:

- `tests/test_mapping.py`: camera geometry, decaying grid, semantic map, lap fallback against brute force.
- `tests/test_system.py`: simulated robot + camera + mapper. Checks map accuracy (< 5 cm), the heatmap, that a moved
  object is forgotten, and pose interpolation. Runs the real HTTP server on a free port for every endpoint, including
  the legacy API, the gzip maps and the camera JPEG. Runs real YOLO26n + ByteTrack on Ultralytics' `bus.jpg` (skipped if
  Ultralytics or the model isn't installed).

## Install details (`scripts/setup.sh`)

1. On a Pi: `apt install python3-picamera2 python3-gpiozero python3-venv python3-pip libopenblas0` (asks for sudo).
   Warns about a 32-bit OS.
2. `.venv` created with **`--system-site-packages`**. picamera2/libcamera only exist as apt packages, so a plain venv
   couldn't see the camera.
3. `pip install -r requirements.txt` (numpy, rich, questionary) and `requirements-vision.txt` (ncnn,
   opencv-python-headless; since 20 Nov 2026 no Ultralytics/PyTorch/lap, see [ncnn-detector.md](ncnn-detector.md)).
   `--no-vision` skips the vision packages; `--no-model` skips the export.
4. `scripts/export-model.sh` (exports in a temporary venv, then benchmarks), then `deskbot doctor`.

On Windows (Git Bash), the scripts find `.venv/Scripts/python.exe` automatically (`scripts/_common.sh`).
