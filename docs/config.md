# Pin configuration: `robot_config.py` (13 Nov 2026)

Every GPIO pin the robot uses is defined in **one file**, `robot_config.py` in the repo root. To change the
wiring, edit that file only, then run `python3 robot_config.py` to check it.

## What's in it

| Name | Contents |
| --- | --- |
| `LEFT_MOTOR`, `RIGHT_MOTOR` | `forward` / `backward` / `enable` (L298N IN1–IN4, ENA/ENB) |
| `SONARS` | `front`, `left`, `right`, `rear` → `trigger` / `echo` |
| `IR_FRONT`, `IR_BACK` | IR edge sensor outputs |
| `ENCODERS` | reserved pins for the planned encoders (not wired yet, but checked for conflicts) |
| `PHYSICAL_PIN` | BCM → physical header pin lookup for every usable GPIO |
| `all_pins()` | list of `(label, bcm)` for everything above |
| `validate()` | raises `ValueError` if a pin is used twice or isn't a valid BCM GPIO. Runs automatically on import |

The motor dicts use the same key names as gpiozero's `Motor(...)`, so the code can call `Motor(**cfg.LEFT_MOTOR)` directly.

`python3 robot_config.py` prints a table of every signal with its GPIO and physical pin, plus the GPIOs that are still free.

## Who reads it

| File | How |
| --- | --- |
| `13Nov-multisonar.py` | `import robot_config as cfg` (same folder) |
| `dashboard/robot.py` | adds the repo root to `sys.path`, imports `robot_config`, and builds `PINS` / `PHYSICAL_PIN` from it |
| `dashboard/multisonar.py` | pins from `cfg.SONARS`, merged with its own `MOUNTS` (mounting position and angle, which are geometry, not wiring) |
| every dashboard server | indirectly, via `robot.py` / `multisonar.py` |
| dashboard page | the Wiring card gets `physical_pins` from `/api/state`, so it no longer has its own copy of the table |
| `hardware_tests/hardware_test.py` | reads it when it is one folder up; copied to the Pi alone it uses its own `FALLBACK_PINS` (sonars, IR, touch), so update both when rewiring (`tests/test_hardware_test.py` checks they match) |
| `3Nov-latest.py` | **does not read it**. Kept byte-for-byte as the known-working reference. Its hard-coded pins match the config's motor, front sonar and IR values; if you rewire those, update that script by hand or use `13Nov-multisonar.py` |

## Why a Python file (not JSON/YAML/TOML)

- It allows comments, so each pin keeps its physical-pin note right next to it.
- No parser or extra package is needed, and it works on any Python version on the Pi (TOML parsing is only built in from 3.11).
- It can check itself (`validate()` runs on import), so a typo stops the program **before** any GPIO is driven.

## Checks done

- `python3 robot_config.py` → 20 signals, no conflicts, free GPIO: 2, 3, 7, 8, 14, 15.
- `robot.PINS` and `multisonar.SONARS` produce the same values as before the change.
- The dashboard snapshot carries `physical_pins`, and the Wiring card renders from it.
- Setting the rear echo to GPIO 22 → `ValueError: GPIO 22 is used twice: left motor forward and rear sonar echo`.
