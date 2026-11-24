# Runtime: four processes on four cores (15 Nov 2026)

`python -m deskbot run` (= `scripts/start.sh` / `scripts/sim.sh`) starts the robot as **four processes**, one pinned to
each core of the Raspberry Pi 4. The earlier one-process version is still there:
`python -m deskbot run --single-process`.

| | |
| --- | --- |
| Code | `deskbot/runtime/`: `app.py` (supervisor + nav process + HTTP), `procs.py` (motor / sensor / camera processes), `shared.py` (shared-memory layout), `shm.py` (seqlock blocks, rings, frame ring), `sched.py` (pinning + priority), `hardware.py` (GPIO split, shared simulator), `proxy.py` (robot / vision stand-ins in the nav process), `safety.py` (re-uses the proven rules), `behaviour.py` (face the user) |
| Optical flow | `deskbot/vision/flow.py` |
| Config | `deskbot/config.py` → `RuntimeConfig`, `VisionConfig.detect_every` / `flow_points` |
| Permission | `scripts/enable-realtime.sh` (once, on the Pi) |
| Tests | `tests/test_runtime.py` |
| Measure | `tools/run_benchmarks.sh system` and the dashboard's **Processes** card |

## 1. Research behind the choices (brief)

| Choice | Why |
| --- | --- |
| **Processes, not threads** | CPython's GIL lets only one thread run Python at a time. In the single-process app the busy terminal viewer once slowed inference from 0.6 s to 1.9 s ([vision.md](vision.md) §2). Separate processes each get their own interpreter and core |
| **`multiprocessing`, spawn start method** | Same behaviour on the Pi and on Windows. With spawn, children don't inherit the parent's threads or locks (forking a process that has threads is unsafe) |
| **One core each, `sched_setaffinity`** | The camera's 100 % load stays on core 2 and can't delay the motor process. Each process's caches stay warm |
| **`SCHED_FIFO` only for motor and sensors** | A runnable `SCHED_FIFO` task preempts all normal tasks, so a busy one can starve the system. These two block between bursts (a few % CPU). The CPU-bound camera stays on normal scheduling (`nice 5`) |
| **RT throttling left on** | The kernel default `sched_rt_runtime_us = 950000` of `1000000` keeps 5 % of every second for normal tasks even if a real-time loop runs away. Setting it to `-1` would remove that safety net, so it isn't touched |
| **Permission via `limits.d`** | An unprivileged process may only *lower* its priority. `RLIMIT_RTPRIO` / `RLIMIT_NICE` in `/etc/security/limits.d/` grant exactly "may use RT priority ≤ 60 / nice ≥ −10" to one user. `setcap` on the Python binary would be wider: it applies to *every* script run by that interpreter |
| **Shared memory + seqlock, not queues** | `multiprocessing.RawArray` + numpy view: a read is a ~4 µs memcpy with no pickling. A `Queue` round trip is ~260 µs (both measured on the laptop, `bench system`), and queues hold *old* messages, which is the opposite of "newest command wins" |
| **Detect every N frames + Lucas-Kanade in between** | Standard embedded pattern: a CPU tracker propagates boxes between detector runs (e.g. arXiv 2007.04942 pairs YOLO with sparse LK; MedianFlow / KCF are the usual alternatives; AROD adapts N to object speed). Running only every 3rd frame is the usual Pi advice. LK on ~12 points per box costs ~1–2 ms at 320×240 |

## 2. The processes

| Core | Process | Scheduling | Loop | Owns |
| --- | --- | --- | --- | --- |
| 0 | `motor` (`procs.motor_main`) | `SCHED_FIFO 50` → fallback `nice -10` → `nice 0` | wakes on a new command or a sensor sample (≤ 20 ms timeout) | motor pins (gpiozero `Motor` ×2) |
| 1 | `sensors` (`procs.sensors_main`) | `SCHED_FIFO 40` → `nice -5` → `nice 0` | 50 Hz | `SonarScanner` (the 4 sonars one at a time, since 24 Nov 2026), 2 × IR |
| 2 | `camera` (`procs.camera_main`) | `nice 5`, NCNN 1 thread | every camera frame (30 fps) | camera, YOLO26n, ByteTrack, optical flow |
| 3 | `nav` (the parent, `app.run_runtime`) | `nice 10` | mapper 10 Hz, behaviour 5 Hz, HTTP on demand | maps, behaviour, dashboard |

`sched.apply()` is called **before** a process starts any thread. On Linux, affinity and nice are per thread, and
only threads created afterwards inherit them. The nav process applies its own `nice 10` **after** spawning the
children: children inherit nice, and an unprivileged child could not lower it back to 0.

All children also get `OPENBLAS_NUM_THREADS=1` (etc.). Without it, every process started a BLAS thread pool per
core. On the 8 GB laptop with little free memory, that made a child fail with *"OpenBLAS error: Memory allocation
still failed"*.

## 3. Shared memory (`shared.py`, `shm.py`)

```
nav ──command (1 slot, seq)──▶ motor ◀──sensors (50 Hz)── sensors
 ▲          settings            │
 │◀──── motor status, wheel_log ┘
 │◀──── frames (3 slots), latest result, last 8 detections ── camera
 └───── vision_ctl (reset tracks, detect_every) ─────────────▶ camera
```

- **SeqBlock**: named float64 fields in one `RawArray`. Each block has exactly one writer. The writer increments
  the sequence number (odd = writing), writes, and increments it again; a reader retries if the number was odd or
  changed. Readers never block the writer. Unwritten fields are NaN ("no value yet").
- **Ring**: a fixed number of rows, used for the wheel-command log (odometry) and detection results.
- **FrameRing**: 3 image slots, so the camera never overwrites the frame the dashboard is copying.
- **Events**: `wake` is set by nav on a new command and by sensors on every sample, so the motor process reacts at
  once. `stop` is shutdown. Human-readable log lines travel through a `Queue`, which is not a hot path.

## 4. Newest command wins (`procs.MotorLoop`)

1. The dashboard or the behaviour writes the command slot (`t`, `kind`, `direction`, `duration`, `source`) and sets
   `wake`.
2. The motor process wakes, sees a new sequence number, reads the slot (always the **newest** command, even if two
   arrived between wake-ups), and:
   - `STOP`: motors off, counted as a user stop if a move was running.
   - `MOVE`: any running move is **preempted** (counted), the new one starts.
3. Every iteration while moving it runs the safety rules (`safety.SafetyRules` = `MultiSonarRobot._check_safety`,
   the same code as the single-process robot) on the newest sensor sample. It stops on an IR edge, front, rear or
   side obstacle, or if the **sample is older than 0.25 s** (sensor process stalled or dead).
4. Wheel changes go to `wheel_log` for the mapper's odometry, as before.
5. Every ~0.5 s it checks that the parent is alive. If the nav process died, it stops the motors and exits. The
   motor pins are released in `finally`.

User vs. robot: commands carry a `source`. A dashboard command (user) also sets `last_user_command`. The behaviour
stays passive for `user_hold_s` (8 s) after one, and any user command replaces an autonomous turn instantly.

## 5. Camera process: detect every N frames (`procs.CameraLoop`, `vision/flow.py`)

```
frame k:  k - last_detection >= detect_every (3)  or no boxes  ->  YOLO26n + ByteTrack  -> re-seed flow points
otherwise                                                      ->  Lucas-Kanade: median shift + median scale
```

- Detection results (and only those) go to the `detections` ring. **The map only uses real detections**, because
  propagated boxes are not new evidence. Every frame's result (detected or propagated) goes to `latest`, for the
  dashboard and the behaviour.
- If inference takes longer than N frame periods, the loop simply detects as often as it can. Flow runs on the
  frames in between, so it adapts by itself.
- A box whose points can't be followed (textureless, blurred) is **held** until the next detection, at most N−1
  frames away, rather than flickering out.
- `VisionConfig.detect_every` (3) can be changed live through `vision_ctl`. `tools/run_benchmarks.sh video` measures
  N = 1, 3, 5.

## 6. Face the user (`behaviour.py`)

The camera is fixed to the chassis, so the robot turns in place. It runs at 5 Hz in the nav process, only when the
robot is idle, no dashboard command has come for 8 s, and a frame **captured after the last turn** is available:

| Situation | Action |
| --- | --- |
| a person is in view | turn toward the nearest (largest box) if more than 8° off centre. Turn time = 0.7 × angle ÷ turn rate. The turn rate is from the odometry calibration; gain < 1 avoids overshoot |
| lost for < 2 s | nothing (a missed detection must not start a search) |
| not in view, but the semantic map has a `person` | turn toward that position if more than 20° away |
| never seen | look around in 35° steps, pausing 1.2 s each, up to one full turn; then wait 60 s |

Turns are ordinary `auto` commands, so every safety rule applies, and the dashboard can switch the behaviour off.
In simulation a user sits across the desk (`deskbot/robot.py` `SIM_USER`); **Move the user** seats them elsewhere.
Verified in sim: the robot found the user, turned until they were within the 8° deadband, and found them again
after they moved to the left side of the desk.

## 7. Dashboard and API

- **Processes** card: per process its core, priority (`FIFO 50` / `nice 10`), loop rate, CPU %, plus command →
  motor latency, sensor-sample age at the safety check, and preemptions. It also has the **Face the user** switch.
- `GET /api/runtime`, `POST /api/behaviour {"face_user": bool}`, `POST /api/sim/shuffle {"label": "User"}`.
- Everything else (drive, maps, camera) is the same API as before. `proxy.RobotProxy.snapshot()` returns the same
  JSON as `MultiSonarRobot.snapshot()`.

## 8. Measured (laptop, simulated hardware, `bench system`)

| | p50 | p95 | max |
| --- | --- | --- | --- |
| command → motor process | 0.35 ms | 0.95 ms | 4.3 ms |
| sensor sample age at the safety check | 0.5 ms | 23 ms | 42 ms |
| shared-memory read | 4.3 µs | | |
| `multiprocessing.Queue` round trip (comparison) | 260 µs | | |

Windows has no pinning or RT, and its sleep granularity is ~15 ms, which explains the p95 sample age. **Not
measured on the Pi yet.** Run `tools/run_benchmarks.sh system` there after `scripts/enable-realtime.sh`.

## 9. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Processes card shows `nice 0` for motor/sensors | `scripts/enable-realtime.sh`, log out and in, `ulimit -r` → 60 |
| `motor process failed to start` | GPIO busy (another robot script running?) or not on a Pi: use `--sim` |
| Robot keeps turning on its own | that's *face the user*: switch it off on the Processes card, or `RuntimeConfig.face_user = False` |
| Detection fps low | camera has one core: raise `detect_every` to 4–5, or give the camera two cores in `RuntimeConfig.cores` + `camera_threads = 2` (the nav process then shares) |
| Stops with "Sensor data … ms old" | the sensor process is stalled: check `scripts/doctor.sh` CPU temperature and the Processes card |

## Adaptive detection and sensor conditioning (18 Nov 2026)

`vision/adaptive.py` runs the detector every 2 frames while turning, 3 while driving, and backs off to 10 (objects in view) or 15 (nothing
in view) in a still scene. A picture change above 6 grey levels or a lost track triggers a detection at once. Setting `detect_every` in
`vision_ctl` restores a fixed interval. `runtime/sensor_filter.py` runs in the sensor process before samples reach the safety loop: a 3-sample sonar median,
IR debounce (edge after 2 samples, floor after 5) and fault detection. Faults resolve toward stopping. The dashboard reports them through alerts.
