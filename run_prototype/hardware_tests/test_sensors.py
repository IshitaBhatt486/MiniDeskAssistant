"""
Sensor test for every sensor (4 ultrasonic + 2 IR + Pi camera) - no motors are touched.

    python3 hardware_tests/test_sensors.py

Pick a sensor from the menu; its reading is printed continuously until you
press Enter (or Ctrl+C). Then pick another one, or q to quit.
Only the selected sensor is opened, so other sensors can't interfere.
Pins come from robot_config.py. The camera option shows the live image in the
terminal using test_camera.py (15 Nov 2026). For camera + object detection use
`scripts/sensors.sh detect` (deskbot).
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # robot_config.py

from gpiozero import DigitalInputDevice, DistanceSensor

import robot_config as cfg

MAX_DISTANCE = 2.0   # m
INTERVAL = 0.2       # s between readings
FLOOR_VALUE = 0      # IR output LOW = floor detected

# name -> (kind, pins)
SENSORS = {f"{name} ultrasonic": ("sonar", pins) for name, pins in cfg.SONARS.items()}
SENSORS["front IR"] = ("ir", cfg.IR_FRONT)
SENSORS["rear IR"] = ("ir", cfg.IR_BACK)
SENSORS["camera"] = ("camera", None)


def pin_text(kind, pins):
    if kind == "camera":
        return "CSI ribbon (live image in the terminal)"
    if kind == "sonar":
        t, e = pins["trigger"], pins["echo"]
        return f"TRIG GPIO {t} (pin {cfg.PHYSICAL_PIN[t]}), ECHO GPIO {e} (pin {cfg.PHYSICAL_PIN[e]})"
    return f"OUT GPIO {pins} (pin {cfg.PHYSICAL_PIN[pins]})"


def wait_for_enter(stop):
    try:
        input()
    except EOFError:
        pass
    stop.set()


def stream_camera():
    """Live camera image drawn in the terminal until Enter (same renderer as test_camera.py)."""
    import time

    import test_camera  # picamera2 + numpy; exits with a checklist if no camera is found

    try:
        cam = test_camera.open_camera()
    except SystemExit as exc:  # keep the menu running if the camera is missing
        print(exc)
        return
    stop = threading.Event()
    threading.Thread(target=wait_for_enter, args=(stop,), daemon=True).start()
    sys.stdout.write("\x1b[2J\x1b[?25l")
    frames, t0 = 0, time.monotonic()
    try:
        while not stop.is_set():
            frame = test_camera.render(test_camera.grab(cam), 0, False)
            frames += 1
            fps = frames / max(time.monotonic() - t0, 1e-6)
            sys.stdout.write(f"\x1b[H{frame}\n\x1b[0mcamera  {fps:4.1f} fps  - press Enter to stop\x1b[K")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        cam.stop()
        cam.close()
    print(f"Stopped after {frames} frames.")


def stream(name):
    kind, pins = SENSORS[name]
    if kind == "camera":
        return stream_camera()
    print(f"\n{name}: {pin_text(kind, pins)}")
    print("Press Enter to stop.\n")

    if kind == "sonar":
        sensor = DistanceSensor(echo=pins["echo"], trigger=pins["trigger"], max_distance=MAX_DISTANCE, queue_len=1)

        def reading():
            cm = sensor.distance * 100
            return f">{MAX_DISTANCE * 100:.0f} cm (no echo)" if cm >= MAX_DISTANCE * 100 - 0.5 else f"{cm:6.1f} cm"
    else:
        sensor = DigitalInputDevice(pins)

        def reading():
            v = sensor.value
            return f"{v}  {'floor' if v == FLOOR_VALUE else 'EDGE / no floor'}"

    stop = threading.Event()
    threading.Thread(target=wait_for_enter, args=(stop,), daemon=True).start()
    try:
        while not stop.is_set():
            print(f"{name}: {reading()}")
            stop.wait(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()
    print("Stopped.")


def main():
    names = list(SENSORS)
    while True:
        print("\nWhich sensor?")
        for i, name in enumerate(names, 1):
            kind, pins = SENSORS[name]
            print(f"  {i}. {name:<17} {pin_text(kind, pins)}")
        print("  q. quit")
        try:
            choice = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if choice in ("q", "quit", "0"):
            break
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            try:
                stream(names[int(choice) - 1])
            except Exception as exc:  # e.g. pin busy because another robot script is running
                print(f"Could not open the sensor: {exc}")
        else:
            print("Enter a number from the list, or q.")
    print("Bye.")


if __name__ == "__main__":
    main()
