# Sensor test scripts (updated 13 Nov 2026)

Two interactive scripts in the repo root. Neither touches the motors. Both work the same way:
**choose a sensor from the menu → its readings print continuously → press Enter to stop → back to the menu.**

| Script | Sensors | Pins from | Copy to the Pi |
| --- | --- | --- | --- |
| `test_ultrasonic.py` | 4 ultrasonic | its own `SONARS` table (**standalone**) | just this file (needs only gpiozero) |
| `test_sensors.py` | 4 ultrasonic + 2 IR | `robot_config.py` | with `robot_config.py` |

```bash
python3 hardware_tests/test_ultrasonic.py
python3 hardware_tests/test_sensors.py
```

Example session:

```
Which sensor?
  1. front ultrasonic  TRIG GPIO 24 (pin 18), ECHO GPIO 25 (pin 22)
  ...
  5. front IR          OUT GPIO 19 (pin 35)
  6. rear IR           OUT GPIO 26 (pin 37)
  q. quit
> 5

front IR: OUT GPIO 19 (pin 35)
Press Enter to stop.

front IR: 0  floor
front IR: 1  EDGE / no floor
Stopped.
```

## Behaviour

- **Menu:** choose by number. `test_ultrasonic.py` also accepts the name (`left`). `q`, `quit` or `0` exits, as do
  `Ctrl+C` and `Ctrl+D` at the menu. Invalid input reprints the menu.
- **Only the selected sensor is opened**, and it's closed again when you stop. So you're always looking at that
  sensor alone: no crosstalk from the other ultrasonics, and a faulty neighbour can't affect it.
- **Output:** one line every 0.2 s (`INTERVAL`), so you can scroll back through the history.
  - Ultrasonic: distance in cm, or `>200 cm (no echo)` when nothing came back (or it's out of range).
  - IR: raw value `0`/`1` plus its meaning (`FLOOR_VALUE = 0` → `0` = floor, `1` = edge / no floor).
- **Stop:** press **Enter**. A background thread waits on `input()` and sets a `threading.Event`, and the read loop
  waits on that event between readings, so it stops within one interval. `Ctrl+C` while streaming also
  stops and returns to the menu.
- **Errors:** in `test_sensors.py`, if a sensor can't be opened (for example, its pin is busy because the dashboard
  or `13Nov-multisonar.py` is running), the error is printed and you're back at the menu.

## What to look for

| Reading | Likely cause |
| --- | --- |
| Ultrasonic always `>200 cm (no echo)`, even with a hand at 10 cm | ECHO wire or voltage divider, VCC not on 5 V, no common GND, TRIG/ECHO swapped |
| Ultrasonic always short (a few cm) with nothing in front | sensor tilted toward the desk, an object or reflection in front |
| Ultrasonic jumps around | loose jumper; a soft or angled target; try a flat hand straight in front |
| IR stuck at `1` | not powered, OUT wire, or potentiometer turned too low; module may be active-high |
| IR stuck at `0` even over the edge | potentiometer too sensitive (sees the floor from far away) |

The IR output must not exceed 3.3 V. If the modules are powered from 5 V, measure OUT with a multimeter or add a divider.

## Changes from the previous version

- `test_ultrasonic.py` used to show all sensors at once and print a min/avg/max summary. `test_sensors.py` used to be a
  guided pass/fail run through all six. Both are now the same "pick one, watch it live" tool, as requested.
- `test_ultrasonic.py` remains standalone. **If you rewire the ultrasonics, update its `SONARS` table and `robot_config.py`.**

## Verified

Both scripts were run as real processes against a fake `gpiozero` module with timed keyboard input. Checked:
- the menu shows the right names and pins
- choosing a sensor streams readings, and they change when the simulated value changes
- Enter stops streaming and returns to the menu
- invalid input is rejected
- `q` exits with code 0
- a dead sensor shows `>200 cm (no echo)`

**Not run on the real Pi yet.**

## Camera option (15 Nov 2026)

`test_sensors.py` has a 7th entry, **camera**: it shows the live Pi camera image in the terminal (the renderer from
`test_camera.py`) until you press Enter, then returns to the menu. If no camera is found, the checklist from
`test_camera.py` is printed and you stay in the menu.

The new `scripts/sensors.sh` (deskbot) has the same tests plus **all sensors at once** (a live table) and
**camera + object detection** (YOLO26n + ByteTrack, boxes drawn in the terminal, fps / latency / tracked labels on a status
line). It works with `--camera pi|webcam|sim`. See [deskbot.md](deskbot.md).

Verified with fake `gpiozero`/`picamera2` modules: option 7 streamed 145 frames in 2 s and stopped on Enter. In a Windows
pipe (cp1252) the `▀` character can't be printed; Pi terminals are UTF-8, so this doesn't happen there.
