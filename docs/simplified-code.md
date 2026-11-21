# Simplified one-file control: `legacy/simplified_code.py`

Added 21 Nov 2026. A single standalone script that gives:

- a typed CLI that drives the motors (forward, backward, left, right, spin, stop, speed),
- an obstacle and edge stop on every move,
- a rough obstacle map built from the four sonars,
- a web dashboard with the camera, the map, sensor readings and drive buttons.

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

Open `http://raspberrypi.local:8080` (or the Pi's IP address) from a laptop or phone on the same network.
Stop any other robot script first, because two programs cannot hold the same GPIO pins.

## Commands

Typed at `robot>` or in the dashboard's command box. The dashboard buttons send the same text.

| Command | Alias | Does |
| --- | --- | --- |
| `forward [s]` | `f` | forward for *s* seconds (default 1) |
| `back [s]` | `b` | backward (default 1 s) |
| `left [s]` / `right [s]` | `l` / `r` | turn on the spot, default ≈ 90° |
| `spin [s] [left\|right]` | | spin on the spot, default ≈ one full turn to the left |
| `stop` | `x`, `s` | stop now |
| `speed <0.1-1>` | | motor PWM; with no number it shows the speed |
| `status` | | sensors, pose, current move, last block reason |
| `map reset` | | clear the map, reset the pose to (0, 0, 0°) |
| `help`, `quit` | `?`, `q` | |

Moves are capped at 30 s. A new command replaces the current move. Moves run in the background, so the prompt
stays free and `stop` acts at once. Dashboard keys: arrow keys make short moves and Space stops.

The "≈ 90°" and "one full turn" values are time estimates:
`t = angle / (2 · speed · WHEEL_SPEED_AT_FULL / TRACK_WIDTH)`, using the same rough constants as
`dashboard/mapping.py` (0.25 m/s, 0.12 m). There are no encoders in this script, so the real angle depends on the
floor and the battery. Give a time (`spin 3`) if you want something exact.

## Pins

These come from `run_prototype/robot_config.py`, the same as every other script.

| Part | GPIO (BCM) |
| --- | --- |
| Left motor | forward 22, backward 23, enable 13 |
| Right motor | forward 27, backward 17, enable 12 |
| Sonars (trig/echo) | front 24/25, left 4/18, right 21/9, rear 10/11 |
| IR edge | front 19, rear 26 (LOW = floor) |

## Safety rules

A control thread runs at 50 Hz. On each tick it reads every sensor, checks the current move, and drives or stops
the motors.

| Move | Blocked when |
| --- | --- |
| forward | front IR sees no floor, or front sonar ≤ 20 cm |
| backward | rear IR sees no floor, or rear sonar ≤ 20 cm |
| left / right / spin | either IR sees no floor, or left or right sonar ≤ 8 cm |

- **Fail safe:** if a sensor a move needs cannot be read (it failed to open or a read raised an error), that move
  is blocked and the reason is printed. Use `--no-edge` to run with the IR sensors disconnected. There is no
  bypass for the sonars.
- **Start margin:** a move only *starts* if the sonar has 3 cm more clearance than the stop limit
  (`START_MARGIN`). Without it, sensor noise at exactly 20 cm lets the robot start, then stop on the next tick,
  over and over.
- The reason for the last block is shown by `status` and on the dashboard, and is also printed as `STOPPED: …`.

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
| `GET /api/state` | mode, speed, pose, sonar (m or null), floor (bool or null), move, blocked, events, camera |
| `GET /api/map` | `{n, cell, rows}` |
| `GET /stream.mjpg`, `/snapshot.jpg` | camera |
| `POST /api/cmd` `{"cmd": "forward 1"}` | `{"reply": "..."}`. It uses the same parser as the CLI. `quit` is refused here. |

The server is the standard library's `ThreadingHTTPServer`. It does not log requests, so the prompt stays readable.
It has no login, so use it only on a trusted network.

## Error handling

| Problem | What happens |
| --- | --- |
| `robot_config.py` missing or invalid | uses the built-in pins and prints a note |
| GPIO/motors cannot open (not on a Pi, pins busy) | prints the reason and falls back to **simulation**, shown as `mode: simulation` in the CLI and the dashboard |
| One sensor fails to open | the others keep working; moves that need the failed sensor are blocked |
| Motor command raises an error | the move is cancelled, the motors are told to stop, and an event is logged |
| Sensor read raises an error | treated as unreadable, so the move stops |
| Dashboard port busy | CLI keeps running; use `--port 8081` |
| Browser closes the stream or the tab | the connection error is ignored |
| Bad command, negative or non-numeric time, speed out of range | a message is shown and nothing moves |
| Ctrl+C, `quit`, or end of input | motors stopped, camera and server closed, GPIO released |

If stdin closes while the dashboard is running (for example when the script runs in the background), the script
keeps running in dashboard-only mode until Ctrl+C.

## Simulation

`--sim` uses a 1.6 × 1.2 m desk with three boxes. The sonars are ray-marched in 1 cm steps with ±5 mm noise. The IR
reads "no floor" when a point 8 cm in front of or behind the robot is off the desk. Tested on the laptop:
driving at a box stops at 20 cm, driving off the desk stops at the edge, `forward` while blocked is refused,
spin/turn durations work, bad input is rejected, the map fills in, the dashboard and API respond, and the webcam
streams.

## Threads

| Thread | Job |
| --- | --- |
| main | `input()` loop and command parser |
| control | 50 Hz: sensors, safety, motors, pose; map every 0.2 s |
| camera | grab, then JPEG, then keep the latest frame |
| dashboard | HTTP server, one thread per request |

The shared robot state is guarded by one `RLock`, and the map has its own lock.
