# Hardware tests in one file: `hardware_test.py` (20 Nov 2026)

`run_prototype/hardware_tests/hardware_test.py` holds every hardware test. It replaces seven files:

| Old file | Now |
| --- | --- |
| `test_sensors.py` | `hardware_test.py sensors` |
| `test_ultrasonic.py` | `hardware_test.py sensors` (same tool, the only difference was where the pins came from) |
| `test_camera.py` | `hardware_test.py camera` |
| `test_microphone.py` | `hardware_test.py mic` |
| `test_oled.py` | `hardware_test.py oled` |
| `screen_test.sh` | `hardware_test.py oled --text "line 1" "line 2"` |
| `test_touch.py` | `hardware_test.py touch` |

The old files are in git history (commit `1e817f0` and earlier) if you ever need one back:
`git show 1e817f0:run_prototype/hardware_tests/test_oled.py > test_oled.py`.

## Use

```bash
python3 hardware_tests/hardware_test.py                  # menu
python3 hardware_tests/hardware_test.py sensors          # one test, then exit
python3 hardware_tests/hardware_test.py camera --snap    # camera: --snap, --save pic.jpg, --ascii, --width 80
python3 hardware_tests/hardware_test.py oled --sh1106    # oled: --bus 1, --addr 0x3d, --sh1106, --text ...
python main.py test-hardware                             # the same menu through the robot CLI
python main.py test-camera --snap                        # test-sensors / -ultrasonic / -camera / -mic / -oled / -touch
```

Aliases: `ultrasonic` and `ir` → `sensors`, `microphone` → `mic`, `screen` → `oled`. At the menu, type a number or a name.

```
Hardware tests (no motors are touched)
  1. sensors  ultrasonic + IR sensors, one at a time
  2. camera   live camera image in the terminal
  3. mic      microphone level meter / record and play back
  4. oled     text and a clock on the OLED screen
  5. touch    the three touch pads
  q. quit
```

## Design

- **One runner, five tests.** `TESTS` maps a name to `(function, description)`. Every test function takes the parsed
  `argparse` namespace, so per-test options (`--snap`, `--bus`, ...) live in one parser in option groups. `main()`
  runs one test if a name is given, otherwise loops on the menu.
- **Lazy imports.** Nothing outside the standard library is imported at the top. Each test calls
  `need(module, fix)`, which imports the module or raises `Skip` with the install command. So the menu works on a
  laptop, or on a Pi without `luma.oled`, and a missing library only disables the test that needs it.
- **`Skip`.** Missing library, missing device (`/dev/i2c-1`, no camera, no capture card), or nothing at the OLED
  address: the test raises `Skip("what's wrong + how to fix")`. `run()` prints it and returns exit code 1, and the
  menu carries on. A Ctrl+C in a test returns 130 and also goes back to the menu.
- **Stopping.** All live tests stop with Enter. `enter_to_stop()` starts a daemon thread that waits on `input()` and
  sets a `threading.Event`; the loops `wait()` on that event between updates, so they stop within one update.
  (`test_oled.py` and `test_touch.py` used to need Ctrl+C.)
- **Pins.** `load_pins()` puts the parent folder on `sys.path` and imports `robot_config`. If that works, the
  sonar, IR and touch pins and the BCM → physical table come from it. If not (the file was copied to the Pi on its
  own), it uses `FALLBACK_PINS`, a copy of the same values. The menu prints which source is used.
  `tests/test_hardware_test.py` fails if `FALLBACK_PINS` and `robot_config.py` differ, so the copy can't go stale
  without anyone noticing.

### sensors
The old `test_sensors.py` behaviour (see [sensor-tests.md](sensor-tests.md)): one sensor opened at a time with
gpiozero (`DistanceSensor`, `max_distance` 2 m, `queue_len` 1, or `DigitalInputDevice` for IR), one reading every
0.2 s, closed on stop. A pin that's busy (robot running) prints the error and stays in the sensor menu. Choose
by number, by full name (`front IR`) or by the first word (`left`).

### camera
The old `test_camera.py` (see [camera.md](camera.md)): picamera2 at 640×480 `RGB888` (really BGR, flipped in
`grab()`), 1 s settle, then the image drawn in the terminal. Colour mode packs two pixels per cell with `▀`
(foreground = top pixel, background = bottom pixel, 24-bit ANSI). ASCII mode maps luminance
(0.299 R + 0.587 G + 0.114 B) onto `" .:-=+*#%@"`. `render()` is also what `deskbot/checks/sensors.py`
(`scripts/sensors.sh`) uses for its camera + detection view: it imports `from hardware_test import render`;
`deskbot/__init__.py` already puts `hardware_tests/` on `sys.path`.

### mic
The old `test_microphone.py` (see [microphone.md](microphone.md)): capture devices from `arecord -l`; a level meter
that reads 50 ms chunks of 16 kHz S16_LE from `arecord`, computes RMS in dBFS and draws −60..0 dBFS as a bar
(`CLIPPING` at |sample| ≥ 32700; < 6 dB between quietest and loudest = probably not connected); or record 5 s
to `mic_test.wav` and play it back with `aplay`.

### oled
Changed on purpose: the default is **I2C bus 1** (GPIO 2 SDA / GPIO 3 SCL, shared with the MPU-6050), the bus the
robot uses (`OledConfig.port = 1`). The old `test_oled.py` and `screen_test.sh` defaulted to a software bus 3 on
GPIO 7/8, but those pins have been the touch pads since 20 Nov 2026. `--bus 3` still works if you set that overlay up.

Steps: `/dev/i2c-<bus>` must exist (otherwise: `raspi-config nonint do_i2c 0`). If `i2cdetect` is installed, only
0x3c–0x3d are probed, with a 15 s cap so a stuck bus can't hang the test (taken from `screen_test.sh`). Nothing
there → wiring checklist; a different address → "re-run with `--addr 0x3d`". Then luma.oled draws a border and up
to 5 lines, and either leaves them on screen (`--text`, `persist = True`) or shows a clock with a rolling ball at
20 fps until Enter. Dropped from `screen_test.sh`: making its own venv and editing `config.txt` (setup.sh handles I2C).

### touch
The old `test_touch.py`: three `DigitalInputDevice(pin, pull_up=False, bounce_time=0.02)` from `TOUCH`, a live
line with each pad's state and count, the press length on release ("long pat" from 1.2 s), and a checklist if
nothing was touched. The devices are now closed on exit, so you can run the test again from the menu.

## Robot CLI
`deskbot/companion/cli.py`: every `test-*` tool points at `hardware_tests/hardware_test.py`, and the new
`TOOL_ARGS` dict adds the test name in front of the user's arguments (`test-camera --snap` →
`hardware_test.py camera --snap`). New: `test-hardware` (the menu), `test-oled`, `test-touch`.

## Verified (laptop, 20 Nov 2026)
- `tests/test_hardware_test.py` (8 tests): pins match `robot_config.py`, CLI tools point at real tests, unknown test
  exits, aliases resolve, a missing gpiozero is reported (not a crash), the menu rejects bad input and quits,
  `render()` output size and colour codes. Whole suite: 334 passed, 1 skipped.
- Run by hand on Windows: menu, `touch` (gpiozero missing), `oled` (`/dev/i2c-1` missing), `mic` (no arecord),
  unknown name. Copied alone to an empty folder: it reports `built-in copy (robot_config.py not found)`.

**Not run on the Pi yet.** Do this on the robot: each of the five tests once from the menu.

## Quick OLED text: `tools/oled_print.py` (21 Nov 2026)

Standalone, with nothing imported from `run_prototype/`: it only needs `luma.oled` + Pillow. Deploy doesn't copy
`tools/`, so copy it over yourself:

```bash
scp tools/oled_print.py snu123@raspberrypi.local:~          # from the laptop
sudo systemctl stop deskbot                                 # on the Pi: one program at a time on the screen
~/deskbot/.venv/bin/python ~/oled_print.py "Hello!"          # stays on screen after the script exits
~/deskbot/.venv/bin/python ~/oled_print.py 'Line one\nline two' --driver sh1106 --rotate 2 --seconds 5
~/deskbot/.venv/bin/python ~/oled_print.py --clear
```

- **Defaults** match the robot (`companion/config.py` `OledConfig`): I2C bus 1, address 0x3C, SSD1306, 128×64.
- **Text fitting:** tries Pillow's scalable default font from 40 px down to 8 px. At each size it wraps the text to
  about `width / (0.6 × size)` characters per line and keeps the first size whose `multiline_textbbox` fits the
  screen. The text is centred.
- **Staying on screen:** `device.persist = True` stops luma from blanking the screen when the script exits.
- **Finding the screen (21 Nov 2026):** without `--address`, it tries 0x3C, then 0x3D. If neither answers, it scans
  the bus with smbus2 (`read_byte` on 0x03–0x77, like `i2cdetect`) and explains from what it finds:
  - nothing at all → wiring or power: SDA/SCL swapped, VCC on pin 1, loose Dupont wires;
  - only the IMU (0x68) → the bus works, so it's the OLED or its own wires: a 7-pin module is in SPI mode, or the pin
    order printed on the module differs;
  - another address → run with `--address` set to it;
  - no `/dev/i2c-1` → I2C is off; permission denied → the i2c group.
- **Errors:** a missing package gets one line saying what to install.
- **Tested** on the laptop against a stand-in luma module that saves the frame as a PNG.
