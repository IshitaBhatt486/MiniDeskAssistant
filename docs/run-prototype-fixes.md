# Fixes ported from the simplified version into run_prototype (24 Nov 2026)

`legacy/simplified_code.py` (the one-file version, [simplified-code.md](simplified-code.md)) was built and tested
feature by feature, partly on the robot. Several bugs found there also existed in `run_prototype/`. Each one was
checked against run_prototype's code, and fixed only where run_prototype really had it. Tests:
`tests/test_simplified_fixes.py` (new) and one new test in `tests/test_companion.py`. Each fails on the old code.

## Fixed

| # | Where | Bug | Fix |
| --- | --- | --- | --- |
| 1 | `runtime/hardware.py`, new `runtime/sonar_scanner.py` | The four sonars were four gpiozero `DistanceSensor`s, each pinging from its own thread, so they heard each other's echoes. Measured on the robot on 23 Nov 2026: the right sonar (normally 200 cm) read 16.3 cm 11 times in 4 s, the rear one 18 cm 70 times, and each false reading stopped the move. | `SonarScanner` pings one sonar at a time from one thread: trigger, time the echo with the pin factory's edge timestamps (lgpio, microseconds), wait 15 ms for the echoes to fade, then the next. `GpioSensors.distances()` returns each sonar's newest reading. |
| 2 | `companion/lift.py`, `presence/lift.py` | Time in the air was measured to the **end** of the 1 s put-down confirmation, and "new spot" starts at 1 s, so every lift, even a blip, reset the map (and ran the `on_place` actions). | Measured from when it left the desk (the start of the condition that confirmed the lift) to the moment it touched down (the start of the put-down timer). |
| 3 | `assistant/brain.py` (`OfflineBrain`) | With no AI key, or when the AI fails, the movement words matched **anywhere**: "that's right" turned right, "what's on my left?" turned left, "I'll be back" reversed, "what's ahead?" drove forward, "what is a spin bowler" spun. (With an AI the `local_command` path was already strict.) | Movement rules now need the sentence to start with a command (`OFFLINE_START`: the local-command verbs plus "do a little dance", "keep looking at me", "forward" …), with a leading "hey <name>" ignored, and no question words (`OFFLINE_QUESTION`). "stop" still works anywhere: stopping is always safe. |
| 4 | `buddy/when.py` | "at 9 call dad": a bare hour followed by more words wasn't understood (it had to end the sentence). | The bare-hour form only refuses a following number or a duration unit ("at 9 minutes"). |
| 5 | `buddy/when.py` | Relative times dropped the seconds, so "in 2 minutes" said 40 s into a minute read back as "in 1 minute". | Rounded to the nearest minute. |
| 6 | `mapping/fusion.py` | A detection box cut off at the left/right edge of the picture was still placed; its centre, so its direction, is wrong (~10 cm off in the simplified version). | It counts as a sighting (keeps the landmark alive by track ID) but is not placed. |
| 7 | `mapping/fusion.py`, `config.py` | Long thin things (keyboard, laptop) are seen side-on, but their centre was put a whole *radius* (half their length) behind the front face: a keyboard ~10 cm too far. | New `OBJECT_DEPTH` / `object_depth()` for locating sightings. `OBJECT_RADIUS` stays the footprint for the maps and the navigation cost map. |
| 8 | `hub/focus.py` | Focus mode used the largest face in view, however far away: on a live test the only face found was someone across the room. | Faces smaller than 0.8 % of the picture (`MIN_FACE`, further than ~1 m) are ignored. |
| 9 | `assistant/stt.py` | Whisper's inventions on near-silence ("Thank you.", "Thanks for watching") went to the assistant as if said. | Rejected with "I didn't catch that", raised straight to the user (not treated as a broken backend). |

**Behaviour change to know about (fix 1):** gpiozero reports a sonar that gives **no echo** as its maximum
distance, which reads as "all clear". The scanner reports "no reading" instead, which `sensor_filter.py` turns
into a fault after 10 samples (0.2 s), and that stops the robot. That is safer, but a sonar that is unplugged or
miswired now blocks the moves that need it, as it already did in the simplified version. On 24 Nov 2026 the
**left sonar was silent** on the robot, so turns will be refused until it is fixed. `python main.py` shows sensor
faults; `hardware_tests/hardware_test.py` tests each sonar.

## Checked, not a bug in run_prototype

| Found in the simplified version | run_prototype |
| --- | --- |
| Detections taken mid-turn fused with the pose after the turn | Already uses the pose at each frame's capture time (`FusionMapper.pose_at(res.t_capture)`) |
| An object counted as hidden by its own echo, so a moved object was never forgotten | Its "hidden" check uses the camera's own sightings, and an object detected in a frame is matched before the miss check |
| Pixel → angle by a linear share of the field of view (~1.3° off) | Already exact (`CameraModel.bearing` uses `atan`) |
| Camera JPEG-encoded every frame with nobody watching | Already encodes only while someone watches (`web/server.py`) |
| `Event.wait` loops running at 33 Hz instead of 50 on Windows | Its fixed-rate loops use `time.sleep` with a deadline, which is precise |
| `.venv` not used when started with the system Python | `recovery.use_project_venv()` already does it |

## Not ported

HTTP keep-alive and the shared status snapshot (the gains in the simplified version were a few milliseconds per
request; run_prototype's server has long-poll and streaming routes that would need care), and the simplified
version's own features (it has its own implementations of most of them).

## Tests

`tests/test_simplified_fixes.py` (14 tests) + `TestLift.test_a_short_lift_resumes_instead_of_resetting`:
the time words, the offline brain (6 conversational sentences don't move, 7 commands still do, "stop" anywhere),
Whisper's inventions rejected and real speech kept, object depth, an edge-cut box not placed but a whole one is,
far faces ignored in focus mode, and the sonar scanner on gpiozero's mock pins (two sonars at 30 / 80 cm read
within 2 cm; a silent one reads "no reading" with a wiring hint). The scanner tests need gpiozero and are
skipped without it (it is on the Pi). On the laptop they were run with gpiozero installed into a temporary folder.
Two test-only details: gpiozero's mock pins timestamp edges with `time.monotonic`, which ticks every 15.6 ms on
Windows, so the test points them at `perf_counter`; and the mock echo's falling edge is stamped exactly rather
than after a `sleep`, which overshoots by a varying 0.5-2 ms on Windows (8-35 cm). The full suite passed after
the changes (see below). **Not yet run on the robot** (SSH to the Pi was down).
