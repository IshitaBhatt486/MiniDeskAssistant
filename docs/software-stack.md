- GPIO Zero: the easiest starting point for this project. It is the Raspberry Pi ecosystem's high-level Python GPIO library.
  - install: `sudo apt install python3-gpiozero` (preinstalled on Raspberry Pi OS)
  - pin numbers are BCM by default

# classes used in `3Nov-latest.py`
| gpiozero class | Used for |
| --- | --- |
| `Motor(forward, backward, enable)` | each drive motor through the L298N. `enable` gives PWM speed control |
| `DistanceSensor(echo, trigger, ...)` | HC-SR04 ultrasonic obstacle sensor, `.distance` in metres |
| `DigitalInputDevice(pin)` | IR edge sensors, `.value` is 0 (floor) or 1 (edge) |

- `time.monotonic()` is used for movement timing, so system clock changes don't affect it.
- no other dependencies (standard library only besides gpiozero)

# dashboard (`dashboard/`)
- `server.py`: `http.server.ThreadingHTTPServer` serving the page + a JSON API. no Flask needed
- `robot.py`: the same pins and safety rules as `3Nov-latest.py`, in a `Robot` class. moves run in a worker thread and a background thread polls the sensors at 10 Hz
  - `GpioHardware` = real gpiozero devices, `SimHardware` = 2-D desk simulation (`--sim`)
- `static/`: plain HTML/CSS/JS, no frameworks or CDNs, so it works offline on the Pi. the page polls `/api/state` every 200 ms
- POST endpoints only accept `Content-Type: application/json`, so other websites open in the same browser can't trigger moves
- `server.py` is split into `parse_args()`, `make_robot()`, `serve()` and `Handler._read_json()` so new entry scripts can reuse them

# mapping (`dashboard/mapping.py`, entry `dashboard/server_mapping.py`)
- log-odds occupancy grid in `array('f')`, Bresenham raycasting, dead-reckoning odometry, its own 10 Hz thread
- read-only coupling to the robot: `Robot.latest_reading()` + `Robot.wheel_log`
- full details: mapping.md

# four ultrasonic sensors (`dashboard/multisonar.py`, entries `13Nov-multisonar.py` and `dashboard/server_multisonar.py`)
- subclasses `GpioHardware`, `SimHardware`, `Robot` and `Mapper`. No existing behaviour changed
- full details: multisonar.md

# convention
- every major change gets a **new entry script** (older ones keep working) and its implementation details go in `docs/`

# full app `deskbot/` (15 Nov 2026)
- one process: robot (re-uses `dashboard/robot.py` + `multisonar.py`) + vision + fusion mapping + dashboard. Entry: `python -m deskbot` / `scripts/*.sh`
- vision: **Ultralytics YOLO26n** exported to **NCNN** (fastest CPU format on the Pi), **ByteTrack** through `model.track(persist=True)`, **picamera2** at 320x240 from the ISP. Runs locally, no API costs. Details: vision.md
- mapping: **numpy** decaying log-odds grid + object-level semantic map + fused confidence heatmap. Details: fusion.md
- CLI: **questionary** (arrow-key menus) + **rich** (tables), with plain fallbacks. Details: deskbot.md
- tests: stdlib `unittest` (`tools/run_tests.sh`)
- venv with `--system-site-packages` so apt's picamera2/gpiozero are visible
