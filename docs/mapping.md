# Occupancy grid mapping (13 Nov 2026)

A lightweight, incremental 2-D occupancy grid built from the existing HC-SR04 ultrasonic sensor
and the two IR edge sensors. It runs asynchronously and is fully separated from motor control
and the safety loop. It is shown in the dashboard's **Occupancy map** card.

| | |
| --- | --- |
| Entry script | `dashboard/server_mapping.py` (new). `dashboard/server.py` still runs the dashboard without mapping |
| Mapping code | `dashboard/mapping.py` |
| Hooks added to existing code | `dashboard/robot.py`: `readings["t"]`, `latest_reading()`, `wheel_log` |
| Frontend | "Occupancy map" card in `dashboard/static/` (only appears when `/api/map` exists) |
| Dependencies | none (standard library: `array`, `threading`, `math`) |

```bash
python3 legacy/server_mapping.py          # on the Pi
python3 legacy/server_mapping.py --sim    # laptop, simulated desk
```

---

## 1. Architecture: how it stays separate from control and safety

```
            ┌──────────────── Robot (robot.py) ─────────────────┐
            │                                                   │
 sensor     │  _sensor_loop (10 Hz) ──► readings {distance,     │
 thread     │                             front_floor,          │
            │                             back_floor, t}  ──────┼──► latest_reading()  (copy, under lock)
            │                                                   │
 move       │  _run (20 ms safety loop)                         │
 worker     │     check_safety → drive motors                   │
            │     once at start: wheel_log.append((t, l, r)) ───┼──► wheel_log (deque, read-only for others)
            │     once at end:   wheel_log.append((t, 0, 0))    │
            └───────────────────────────────────────────────────┘
                                   ▲ read only
                                   │
            ┌──────── Mapper thread (mapping.py, 10 Hz) ────────┐
            │  odometry from wheel_log → pose                   │
            │  raycast sonar + mark IR → OccupancyGrid          │
            └─────────────────────┬─────────────────────────────┘
                                  │ snapshot(since, epoch)
                     GET /api/map ▼   (HTTP thread)
                           dashboard card
```

The rules that keep it isolated:

- **The mapper never calls hardware.** It never calls `hw.drive`, `hw.stop` or any sensor read. It
  only reads `robot.latest_reading()` (a dict copy) and `robot.wheel_log`. So mapping cannot
  move the robot, block a move, or add extra sensor reads.
- **The safety loop never calls mapping.** The only change inside `Robot._run` is two
  `deque.append` calls per move: one when the motors start and one in `finally` after they stop.
  `deque.append` is atomic in CPython and takes no lock, so it never blocks the 20 ms loop.
- **Separate locks.** The mapper has its own `threading.Lock` for the grid. It holds the robot's
  lock only for the instant `latest_reading()` copies the dict. HTTP requests for `/api/map` take
  only the mapper lock.
- **Failures are contained.** `Mapper._loop` catches every exception, prints `[MAP  ] update failed`
  and carries on. The thread is a daemon and is stopped by `on_close` when the server exits.
- **Verified:** with the mapper's `step()` patched to sleep 2 s and then raise an exception, a
  forward move still stopped on time at 19.9 cm from the obstacle (test in §8).

## 2. Pose estimation (dead reckoning)

There are no encoders yet, so the pose comes from the **commanded** wheel speeds:

```
v_left  = left_cmd  × WHEEL_SPEED_AT_FULL         (left_cmd in −1…1, e.g. ±speed)
v_right = right_cmd × WHEEL_SPEED_AT_FULL
v       = (v_left + v_right) / 2                  forward speed, m/s
ω       = (v_right − v_left) / TRACK_WIDTH        turn rate, rad/s
θ += ω·h ;  x += v·cos θ·h ;  y += v·sin θ·h      Euler integration, h ≤ 10 ms substeps
```

- **Event replay:** every update, the mapper copies `wheel_log` and goes through the entries
  between the time it last integrated up to (`_clock`) and the new reading's timestamp `t`. For each
  entry it integrates the previous wheel command up to that entry's time, then switches to the new
  command. Finally it integrates up to `t`. Entries already applied are skipped by comparing with
  `_log_t`, the timestamp of the last applied entry, so it still works if old entries have fallen
  off the 64-entry deque.
- **Frame:** the pose starts at (0, 0, θ = 0) wherever the robot was when mapping started (or when
  the map was last cleared). +x is the robot's initial forward direction and +y is to its left.
- **Limitations:**
  - Open-loop odometry ignores wheel slip, stalls (pushing against an object), battery sag and
    motor mismatch, so the pose drifts and the map smears over time. Clear the map to re-anchor it.
  - A speed change from the Configuration card in the middle of a move isn't logged. The move keeps
    the speed it started with until it ends.
  - Encoders (see `encoders.md`) can later replace `Odometry.advance` without touching anything else.

### Calibrating on the real robot

Constants at the top of `mapping.py` (the defaults match the simulator):

| Constant | Default | How to measure |
| --- | --- | --- |
| `WHEEL_SPEED_AT_FULL` | 0.25 m/s | Drive forward 2 s at speed 0.5, measure the distance *d*. Value = *d* / (2 × 0.5) |
| `TRACK_WIDTH` | 0.12 m | Distance between the wheel centres. Fine-tune: turn for 1 s at 0.5, measure the angle φ (rad). Value = 2 × 0.5 × `WHEEL_SPEED_AT_FULL` / φ |
| `SONAR_OFFSET` | 0.06 m | Distance from the robot centre (midpoint between the wheels) to the HC-SR04 face |
| `IR_OFFSET` | 0.07 m | Distance from the robot centre to each IR sensor (front and rear assumed symmetric) |

## 3. Grid

| Property | Value |
| --- | --- |
| Resolution | `RESOLUTION = 0.05` m (5 cm cells) |
| Size | `SIZE = 60` → 60 × 60 cells = 3 m × 3 m, start pose at the centre |
| Storage | `array('f')` log-odds (14 KB), `bytearray` edge flags (3.6 KB), `array('I')` per-cell version (14 KB) |
| Index | `i = row × SIZE + col`, `col = floor(x / res) + SIZE/2`, `row = floor(y / res) + SIZE/2` (row 0 = bottom) |

Anything that falls outside the grid is ignored. Rays are clipped where they leave it.

### Log-odds model

Each cell stores *l* = log(p / (1 − p)). It starts at 0 (p = 0.5, unknown). Each update is just an addition:

| Event | Δl | Constant |
| --- | --- | --- |
| Sonar beam passes through the cell | −0.40 | `L_FREE` |
| Sonar beam ends in the cell (hit < 1.2 m) | +0.85 | `L_OCC` |
| IR sensor sees floor over the cell / robot centre is on it | −0.60 | `L_IR_FLOOR` |
| Clamp after every update | [−4, +4] | `L_MIN`, `L_MAX` |

The clamp keeps cells able to change state when something moves. Classification for display:
*l* ≥ 0.85 → **occupied**, *l* ≤ −0.85 → **free**, otherwise **unknown**. A single hit is enough
to show an obstacle, and it takes about 3 beams through a cell to call it free.

**Desk edges are a separate layer** (`edge` bytearray). When an IR sensor reports *no floor*, the
cell under it is permanently flagged as an edge. Drops don't move, so the flag is never
decayed. Edge takes priority over occupied/free in the display. It is cleared only by
**Clear map**.

## 4. Sensor model and update step

Every 100 ms (`UPDATE_HZ = 10`), `Mapper.step()`:

1. Reads `robot.latest_reading()`. If its timestamp `t` hasn't changed since the last update, it does nothing.
2. Advances the odometry up to `t` (§2).
3. Starts a new batch (`grid.version += 1`). Every cell touched in this update gets this version stamp.
4. Marks the cell under the robot centre as floor (the robot is standing on it).
5. **Ultrasonic:** casts `SONAR_RAYS = 3` rays across the HC-SR04's ±7.5° cone (`SONAR_CONE_HALF`), starting
   from the sensor position (`SONAR_OFFSET` ahead of the centre):
   - range = min(distance, `SONAR_MAX_USEFUL` = 1.2 m). Long HC-SR04 readings are unreliable,
     so beyond 1.2 m only free space is recorded.
   - cells are traced with **Bresenham's line algorithm**. Every cell gets `L_FREE`, except the
     last one, which gets `L_OCC` if the reading was a real hit (< 1.2 m).
6. **IR:** the front sensor is `IR_OFFSET` ahead of the centre and the rear sensor the same distance behind.
   *Floor* → `L_IR_FLOOR`. *No floor* → edge flag.
7. Adds the pose to the trail if the robot has moved ≥ 2 cm (the last 300 points are kept).

Cost per update: about 3 rays × ≤ 25 cells plus a few single cells, under 1 ms on a Pi 4.

## 5. Incremental sync to the dashboard

- Each cell keeps the version of the last batch that changed it (`cell_version`).
- `GET /api/map?since=V&epoch=E`:
  - if `since` is 0, newer than the current version, or the client's epoch doesn't match → **full**
    grid as a 3,600-character digit string (`0` unknown, `1` free, `2` occupied, `3` edge).
  - otherwise → **delta**: `[[index, code], …]` for cells with `cell_version > since`. If more than
    a quarter of the grid changed, it sends the full grid instead.
- `epoch` goes up whenever the map is cleared (**Clear map** or **Reset position** in sim). A client
  holding a stale grid (for example, another tab cleared it) automatically gets a full resend.
- Every response also includes `version`, `epoch`, `size`, `resolution`, `pose`, `trail`, `counts`,
  `updates`, `rate_hz` and `uptime`.
- The dashboard polls every 400 ms. A normal delta is a few dozen cells (about 29 measured over 0.5 s).
- `POST /api/map/reset` (JSON body required, like the other POST endpoints) clears the grid, the pose
  and the trail. In `--sim`, **Reset position** clears the map too, because the simulated robot jumps
  back to its start.

## 6. Dashboard card

`static/app.js` → `pollMap()` / `applyMap()` / `drawMap()`:

- On load, the page requests `/api/map`. With `server.py` this returns 404, so the card stays hidden
  and polling stops. With `server_mapping.py` the card appears.
- The client keeps a local `Uint8Array` grid. It applies a full grid or a delta, then redraws a
  480 × 480 canvas: unknown/free/obstacle/edge cells (colours come from CSS variables, so light and
  dark themes both work), 1 m grid lines, the trail in blue, and the pose arrow.
- The side panel shows the pose estimate (x, y in cm from the start point, heading in degrees with
  0° = the start heading and counter-clockwise positive, so 90° = turned left), mapped area (known cells × 0.0025 m²),
  obstacle/edge cell counts, the measured update rate, and the grid size.
- The card spans two columns on desktop. On phones the canvas and side panel stack.

## 7. Files changed

| File | Change |
| --- | --- |
| `dashboard/mapping.py` | **new**: `OccupancyGrid`, `Odometry`, `Mapper` |
| `dashboard/server_mapping.py` | **new** entry script: `MappingHandler` adds `/api/map` and `/api/map/reset` and resets the map on sim reset |
| `dashboard/robot.py` | `readings` now include `t` (monotonic). Added `latest_reading()`. Added `wheel_log` (appended once at move start and once at move end) |
| `dashboard/server.py` | `main()` split into `parse_args()`, `make_robot()` and `serve()`, plus a shared `_read_json()` helper. Behaviour unchanged |
| `dashboard/static/*` | Occupancy map card, styles (`--map-free`, `--map-unknown` tokens), polling/render code |

## 8. Testing done (simulator)

- Turned to face the wall and drove forward: stopped 19.6 cm away. The odometry pose matched the
  simulator's true pose exactly (Δ = 0.000 m, 0.0°), because the simulator has no slip. The wall
  cell was classified as **occupied**.
- Reversed to the rear desk edge: rear IR stop, and **1 edge cell** marked.
- Incremental sync: 0.5 s at rest → delta of 29 cells (instead of 3,600). A wrong epoch → full grid.
- **Isolation:** mapper `step()` patched to `sleep(2)` and then raise → the safety stop still triggered
  normally (blocked at 19.9 cm), the error was logged and the mapper kept running.
- `server.py` still works: `/api/map` → 404 and the card stays hidden.
- On real hardware: **not tested yet**. Calibrate §2 first.

## 8b. Multiple sonars (added 13 Nov 2026)

`Mapper.sonar_sources(reading)` returns `(dx, dy, angle_rad, distance)` for each ultrasonic sensor in the
robot frame. The default is the single front sensor, so the behaviour above is unchanged. `MultiSonarMapper` in
`multisonar.py` returns all four. Ray origins use `Odometry.transform(dx, dy)`. See `multisonar.md`.

## 9. Known limitations / next steps

- Pose drift without encoders (biggest error source). Next step: encoder odometry, then IR/sonar-based correction.
- Because the HC-SR04 cone is wide, a thin object anywhere in the cone is drawn at the cone's edge cells too.
- Soft or angled surfaces can absorb or deflect the ultrasonic pulse (no echo → reads as free).
- The map is fixed at 3 m × 3 m and lives in memory only. It is lost when the server restarts.
