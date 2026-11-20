"""
TTP223 touch pad test - STANDALONE (only needs gpiozero, preinstalled on Raspberry Pi OS).

    python3 hardware_tests/test_touch.py          # shows each pad live until Ctrl+C

Wiring (same as robot_config.TOUCH), for each of the three modules:
    VCC -> 3.3 V   (pin 1 or 17)     NOT 5 V: the I/O pin would then output 5 V into the Pi
    GND -> GND     (pin 6, 9, 14, 20, 25, 30, 34 or 39)
    I/O -> top: GPIO 7 (pin 26) · left: GPIO 8 (pin 24) · right: GPIO 14 (pin 8)

GPIO 14 is the UART TX pin: turn the serial console off once (scripts/setup.sh does it):
    sudo raspi-config nonint do_serial_cons 1 && sudo raspi-config nonint do_serial_hw 1 && sudo reboot

TTP223 jumpers: A open = output HIGH when touched (what the robot expects), B open = momentary. With B closed the
pad is self-locking (each touch flips it); then set touch.mode to "toggle" on the dashboard.
The module calibrates itself for ~0.5 s after power-up: don't touch it while the Pi boots.
"""

import time

from gpiozero import DigitalInputDevice

PADS = {"top": 7, "left": 8, "right": 14}

devices = {name: DigitalInputDevice(pin, pull_up=False, bounce_time=0.02) for name, pin in PADS.items()}
counts = {name: 0 for name in PADS}
down_at = {}


def pressed(name):
    counts[name] += 1
    down_at[name] = time.monotonic()


def released(name):
    t = time.monotonic() - down_at.pop(name, time.monotonic())
    print(f"\n  {name}: released after {t:.2f} s ({'long pat' if t >= 1.2 else 'pat'})")


for name, dev in devices.items():
    dev.when_activated = lambda n=name: pressed(n)
    dev.when_deactivated = lambda n=name: released(n)

print("Touch each pad. Ctrl+C to stop.\n")
try:
    while True:
        line = "   ".join(f"{name:>5}: {'■ TOUCHED' if dev.value else '·        '} ({counts[name]})" for name, dev in devices.items())
        print("\r" + line, end="", flush=True)
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\n\nTouches:", ", ".join(f"{n} {c}" for n, c in counts.items()))
    if not any(counts.values()):
        print("Nothing seen: check VCC on 3.3 V, GND, the I/O wire, and that the serial console is off (GPIO 14).")
