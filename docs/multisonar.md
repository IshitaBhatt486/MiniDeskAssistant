# Four ultrasonic sensors (13 Nov 2026)

The robot goes from one HC-SR04 (front) to four: **front, left, right, rear**. This adds safety
checks for reversing and turning, a **Sonar array** card on the dashboard, and four beams feeding
the occupancy map.

| | |
| --- | --- |
| Terminal script (new) | `13Nov-multisonar.py`: same menu as `3Nov-latest.py`, plus rear/side checks and a "read sensors" option |
| Dashboard script (new) | `dashboard/server_multisonar.py`: dashboard + mapping with all four sensors |
| Code (new) | `dashboard/multisonar.py` |
| Changed | `dashboard/mapping.py`: added the `sonar_sources()` hook and `Odometry.transform()` (single-sensor behaviour unchanged). `dashboard/static/*`: Sonar array card, one ray per sensor on the desk view, extra wiring rows |
| Unchanged | `3Nov-latest.py`, `server.py`, `server_mapping.py` and `robot.py` all still work with one sensor |

```bash
python3 legacy/13Nov-multisonar.py                     # terminal menu
python3 legacy/server_multisonar.py          # dashboard on the Pi
python3 legacy/server_multisonar.py --sim    # dashboard, simulated
```

---

## 1. Wiring

| Sensor | Faces | TRIG (GPIO / pin) | ECHO via divider (GPIO / pin) |
| --- | --- | --- | --- |
| Front (existing) | forward | 24 / 18 | 25 / 22 |
| Left | +90° | **4 / 7** | **18 / 12** |
| Right | −90° | **21 / 40** | **9 / 21** |
| Rear | 180° | **10 / 19** | **11 / 23** |

- **Every ECHO needs its own voltage divider** (ECHO → 1 kΩ → GPIO, GPIO → 2 kΩ → GND), because the
  HC-SR04 outputs 5 V and the Pi's pins take 3.3 V. VCC goes to 5 V, and all GNDs are common.
- Why these pins: they avoid everything already in use (motors 12/13/17/22/23/27, front sonar 24/25,
  IR 19/26) **and** the pins reserved for the encoders (5, 6, 16, 20, see `encoders.md`).
- GPIO 9/10/11 are the SPI0 pins. That's fine while SPI is disabled (the default). If you later add an SPI display
  or ADC, move the right/rear sensors to free pins and update **one place**: `SONARS` in
  `robot_config.py` (both scripts read it).
- GPIO 18 is a hardware-PWM pin. It works fine as an input, but don't use it if you later need audio or PWM there.
- 4 HC-SR04s draw about 60 mA from 5 V in total. The Pi's 5 V rail handles this.

## 2. Mounting (robot frame)

Measured from the robot centre (midpoint between the wheels); x is forward, y is to the left:

| Sensor | x (m) | y (m) | angle |
| --- | --- | --- | --- |
| front | +0.06 | 0 | 0° |
| left | 0 | +0.065 | +90° |
| right | 0 | −0.065 | −90° |
| rear | −0.06 | 0 | 180° |

These values drive the simulator, the map raycasting and the dashboard drawing. **Measure your real
mounts and update `MOUNTS` in `dashboard/multisonar.py`**, otherwise the map will place obstacles slightly wrong.

## 3. Safety rules

The checks run in this order every 20 ms. The first one that fails stops the move.

| Move | Check | Limit | Stop reason (`stop_counts` key) |
| --- | --- | --- | --- |
| Forward | front IR floor | — | `front_edge` |
| Forward | front sonar | `STOP_DISTANCE` 20 cm (slider) | `obstacle` |
| Backward | rear IR floor | — | `rear_edge` |
| Backward | **rear sonar** | `STOP_DISTANCE` 20 cm (slider) | `rear_obstacle` |
| Left / Right | both IR floor | — | `turn_edge` |
| Left / Right | **left and right sonar** | `SIDE_STOP_DISTANCE` 8 cm | `side_obstacle` |

- The original checks run first and unchanged (`MultiSonarRobot._check_safety` calls `super()` first).
- **Why 8 cm for the sides:** turning in place only sweeps the robot's own footprint (radius about 7.5 cm). An
  object 15 cm to the side is no danger to a spin, so a 20 cm limit would block turns for no reason. 8 cm means
  "something is touching or about to touch the side". It's a constant in `multisonar.py` (not a slider yet).
- The "Clear to move" panel on the dashboard uses the same function, so it always matches what the robot will do.

## 4. Code structure

`dashboard/multisonar.py` only **extends** existing classes:

| Class | Extends | What changes |
| --- | --- | --- |
| `MultiSonarGpioHardware` | `GpioHardware` | Keeps the front `DistanceSensor` and creates 3 more. `distances()` returns `{front, left, right, rear}` in metres. `close()` closes the extra three, then the parent closes everything else. If any sensor fails to open, everything opened so far is closed again |
| `MultiSonarSimHardware` | `SimHardware` | `_ray(dx, dy, angle)` ray-marches from any mount pose (4 mm steps, ±2 mm noise). `distances()` measures all four at the same instant |
| `MultiSonarRobot` | `Robot` | `_read()` adds `distances`, and keeps `distance` = front so every existing consumer (graph, mapper fallback) still works. Adds the extra `_check_safety` rules. `snapshot()` adds `sonars` (per-sensor distance, mount, pins, stop limit, used-for) and the extended `pins` |
| `MultiSonarMapper` | `Mapper` | `sonar_sources()` returns all four mounts, so each update casts 4 cones × 3 rays |

### Change to `mapping.py`

Previously `_integrate()` hard-coded one forward sensor. Now it loops over
`self.sonar_sources(reading)`, which returns `(dx, dy, angle_rad, distance)` tuples. The default
implementation returns just `(SONAR_OFFSET, 0, 0, distance)`, which is identical to before. Ray origins
use the new `Odometry.transform(dx, dy)` (robot frame → map frame). So adding or removing sensors in the
future only means overriding `sonar_sources()`.

### Reading timing

gpiozero's `DistanceSensor` runs its own background thread for each sensor that keeps pinging, and
`.distance` returns the newest value. Reading four sensors therefore doesn't block the 20 ms safety loop.
`sensor_loop` (10 Hz) and the safety loop both just read the cached values.

**Crosstalk:** each sensor pings independently, so a pulse from one can occasionally be heard by another,
mostly between sensors facing roughly the same way. With the four sensors 90° apart this is rare,
but if you see random short readings:
1. tilt the sensors slightly apart or add foam/tube shrouds, or
2. switch to sequential triggering (fire one sensor at a time, about 60 ms apart). That needs a custom
   reader in place of `DistanceSensor`, not done yet.

For more accurate timing, gpiozero recommends a hardware pin factory (`sudo apt install python3-lgpio`, which is the
default on Raspberry Pi OS Bookworm).

## 5. Dashboard

- **Sonar array card** (only appears when `/api/state` contains `sonars`):
  - Top view with forward up. Each sensor draws a 15° wedge whose length scales with distance (up to 1 m),
    labelled in cm. The wedge turns orange when the reading is inside that sensor's stop limit.
  - The list shows each sensor's GPIO pins and its reading as a tag (green = clear, orange = inside stop limit).
    Hover over the pins to see which move uses that sensor.
  - Stats: closest reading and which sensor it came from, rear-obstacle stops, side-obstacle stops.
- **Clear to move** hints change to "rear IR + sonar" and "both IR + sides".
- **Desk (sim)** draws one dashed ray per sensor, up to where it hit.
- **Wiring** card adds Left/Right/Rear ultrasonic rows with physical pin numbers.
- **Ultrasonic** card (graph) still shows the front sensor.
- Mapping covers all four directions at once, so a single spin in place maps the surroundings
  about 4 times faster than with one sensor.

## 6. Testing done (simulator)

| Test | Result |
| --- | --- |
| Reverse toward the wall | stopped with **"Rear obstacle at 19.4 cm"** |
| Park with the mug about 3.5 cm from the left sensor, then turn left | refused: **"Left obstacle at 3.4 cm"**. Clear-to-move showed left/right blocked, forward/backward clear |
| Mapping | 4 sonar sources per update, all directions mapped |
| Regression | base `Robot` + `Mapper` still use one sonar `(0.06, 0, 0)`, and the base snapshot has no `sonars` (card hidden) |
| `13Nov-multisonar.py` | syntax-checked only. gpiozero isn't installed on the dev laptop, so **run it on the Pi**: use option 5 to check all four readings before driving |

**Not tested yet on real hardware.** First run on the Pi:
0. `python3 hardware_tests/hardware_test.py sensors` (standalone: copy just that file to the Pi): pick each sensor in turn and watch its live readings
   while moving a hand in front of it. See `sensor-tests.md`.
1. `python3 legacy/13Nov-multisonar.py`, option 5: wave a hand in front of each sensor and check the right name changes.
2. If two names are swapped, the TRIG/ECHO wires are swapped between sensors. Fix the wiring or `SONARS` in `robot_config.py`.

## 7. Known limitations

- The side limit is a fixed constant (no slider).
- Sensors aren't fired in sequence, so crosstalk is possible (see §4).
- Ultrasonic beams can miss thin chair legs and angled or soft surfaces. The IR edge sensors stay the
  primary protection against falling off the desk.
