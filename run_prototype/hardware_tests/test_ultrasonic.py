"""
Ultrasonic sensor test - STANDALONE (only needs gpiozero, no other project files).
No motors are touched.

    python3 hardware_tests/test_ultrasonic.py

Pick a sensor from the menu; its distance is printed continuously until you
press Enter (or Ctrl+C). Then pick another one, or q to quit.

Pins are copied here so this file can be run on its own. If you rewire,
update SONARS below AND robot_config.py.
"""

import threading

from gpiozero import DistanceSensor

# ---------------- PINS (BCM) ----------------
# Every ECHO goes through a 1k/2k voltage divider (5 V -> 3.3 V). VCC = 5 V, common GND.

SONARS = {
    #          TRIG  ECHO      physical pins (TRIG, ECHO)
    "front": (24, 25),   # 18, 22
    "left": (4, 18),     # 7, 12
    "right": (21, 9),    # 40, 21
    "rear": (10, 11),    # 19, 23
}

PHYSICAL_PIN = {4: 7, 9: 21, 10: 19, 11: 23, 18: 12, 21: 40, 24: 18, 25: 22}

MAX_DISTANCE = 2.0   # m
INTERVAL = 0.2       # s between readings


def wait_for_enter(stop):
    try:
        input()
    except EOFError:
        pass
    stop.set()


def stream(name):
    trig, echo = SONARS[name]
    print(f"\n{name}: TRIG GPIO {trig} (pin {PHYSICAL_PIN[trig]}), ECHO GPIO {echo} (pin {PHYSICAL_PIN[echo]})")
    print("Press Enter to stop.\n")

    sensor = DistanceSensor(echo=echo, trigger=trig, max_distance=MAX_DISTANCE, queue_len=1)
    stop = threading.Event()
    threading.Thread(target=wait_for_enter, args=(stop,), daemon=True).start()
    try:
        while not stop.is_set():
            cm = sensor.distance * 100
            text = f">{MAX_DISTANCE * 100:.0f} cm (no echo)" if cm >= MAX_DISTANCE * 100 - 0.5 else f"{cm:6.1f} cm"
            print(f"{name}: {text}")
            stop.wait(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()
    print("Stopped.")


def main():
    names = list(SONARS)
    while True:
        print("\nWhich ultrasonic sensor?")
        for i, name in enumerate(names, 1):
            print(f"  {i}. {name}")
        print("  q. quit")
        try:
            choice = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if choice in ("q", "quit", "0"):
            break
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            stream(names[int(choice) - 1])
        elif choice in SONARS:
            stream(choice)
        else:
            print("Enter a number from the list, a sensor name, or q.")
    print("Bye.")


if __name__ == "__main__":
    main()
