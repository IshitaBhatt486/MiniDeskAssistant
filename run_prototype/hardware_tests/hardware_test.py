"""
Every hardware test in one file (20 Nov 2026). Replaces test_sensors.py, test_ultrasonic.py, test_camera.py,
test_microphone.py, test_oled.py, test_touch.py and screen_test.sh. No motors are touched.

    python3 hardware_tests/hardware_test.py              menu: pick a test, run it, come back, pick another
    python3 hardware_tests/hardware_test.py <test>       run one test straight away (then exit)

    sensors   4 ultrasonic + 2 IR, one at a time, live readings      (gpiozero)
    camera    live Pi camera image in the terminal, works over SSH   (picamera2 + numpy)
                --snap  one picture   --save pic.jpg   --ascii   --width 80
    mic       level meter, or record 5 s and play back               (arecord / aplay)
    oled      text + live clock on the OLED                          (luma.oled)
                --bus 1  --addr 0x3c  --sh1106   --text "hi" "line 2"
    touch     the three TTP223 pads, live                            (gpiozero)

Standalone: each test imports its library only when it runs, so a missing library only disables that test.
Pins come from robot_config.py (one folder up) when it is there. Copied to the Pi on its own, the file uses
FALLBACK_PINS below, so update those too when you rewire.

Every live test stops with Enter (or Ctrl+C) and returns to the menu.
"""

from __future__ import annotations

import argparse
import array
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------- PINS (BCM) ----------------
# Used only when robot_config.py can't be imported (this file copied to the Pi alone). Same values as robot_config.

FALLBACK_PINS = {
    "SONARS": {                                   # every ECHO goes through a 1k/2k divider (5 V -> 3.3 V)
        "front": {"trigger": 24, "echo": 25},
        "left": {"trigger": 4, "echo": 18},
        "right": {"trigger": 21, "echo": 9},
        "rear": {"trigger": 10, "echo": 11},
    },
    "IR_FRONT": 19,
    "IR_BACK": 26,
    "TOUCH": {"top": 7, "left": 8, "right": 14},
    "PHYSICAL_PIN": {2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33,
                     14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
                     24: 18, 25: 22, 26: 37, 27: 13},
}


def load_pins():
    """robot_config's pins when it is importable, else FALLBACK_PINS. Returns (pins dict, source text)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import robot_config as cfg
        return {k: getattr(cfg, k) for k in FALLBACK_PINS}, "robot_config.py"
    except (ImportError, AttributeError):
        return FALLBACK_PINS, "built-in copy (robot_config.py not found)"


PINS, PIN_SOURCE = load_pins()


def pin(bcm):
    return f"GPIO {bcm} (pin {PINS['PHYSICAL_PIN'].get(bcm, '?')})"


class Skip(Exception):
    """A test can't run here (library or device missing). The message says how to fix it."""


def need(module, fix):
    """Import a module by name, or raise Skip with the install command."""
    import importlib
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise Skip(f"{module} is not available ({exc}).\n  Fix: {fix}") from None


def enter_to_stop():
    """An Event that is set when Enter is pressed (or stdin closes)."""
    stop = threading.Event()

    def wait():
        try:
            input()
        except (EOFError, KeyboardInterrupt, OSError):
            pass
        stop.set()

    threading.Thread(target=wait, daemon=True).start()
    return stop


def ask(prompt):
    try:
        return input(prompt).strip().lower()
    except (KeyboardInterrupt, EOFError):
        return "q"


# =============================== sensors: ultrasonic + IR ===============================

MAX_DISTANCE = 2.0   # m
INTERVAL = 0.2       # s between readings
FLOOR_VALUE = 0      # IR output LOW = floor detected


def sensor_list():
    items = [(f"{n} ultrasonic", "sonar", p) for n, p in PINS["SONARS"].items()]
    return items + [("front IR", "ir", PINS["IR_FRONT"]), ("rear IR", "ir", PINS["IR_BACK"])]


def sensor_pins(kind, p):
    return f"TRIG {pin(p['trigger'])}, ECHO {pin(p['echo'])}" if kind == "sonar" else f"OUT {pin(p)}"


def stream_sensor(name, kind, p):
    gz = need("gpiozero", "sudo apt install -y python3-gpiozero")
    print(f"\n{name}: {sensor_pins(kind, p)}\nPress Enter to stop.\n")
    if kind == "sonar":
        dev = gz.DistanceSensor(echo=p["echo"], trigger=p["trigger"], max_distance=MAX_DISTANCE, queue_len=1)

        def reading():
            cm = dev.distance * 100
            return f">{MAX_DISTANCE * 100:.0f} cm (no echo)" if cm >= MAX_DISTANCE * 100 - 0.5 else f"{cm:6.1f} cm"
    else:
        dev = gz.DigitalInputDevice(p)

        def reading():
            return f"{dev.value}  {'floor' if dev.value == FLOOR_VALUE else 'EDGE / no floor'}"

    stop = enter_to_stop()
    try:
        while not stop.is_set():
            print(f"{name}: {reading()}")
            stop.wait(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    print("Stopped.")


def test_sensors(args):
    items = sensor_list()
    print(f"Pins from {PIN_SOURCE}.")
    while True:
        print("\nWhich sensor?")
        for i, (name, kind, p) in enumerate(items, 1):
            print(f"  {i}. {name:<17} {sensor_pins(kind, p)}")
        print("  b. back")
        choice = ask("> ")
        if choice in ("b", "q", "quit", "0", "back"):
            return
        match = [it for i, it in enumerate(items, 1) if choice == str(i) or choice in (it[0], it[0].split()[0])]
        if not match:
            print("Enter a number from the list, a sensor name (front, left, ...) or b.")
            continue
        try:
            stream_sensor(*match[0])
        except Skip:
            raise
        except Exception as exc:  # e.g. pin busy because the robot is running
            print(f"Could not open the sensor: {exc}  (is the robot running? stop it first)")


# =============================== camera ===============================

ASCII_RAMP = " .:-=+*#%@"   # dark -> bright
CAPTURE_SIZE = (640, 480)


def open_camera():
    """Start the first Pi camera. Raises Skip with a checklist if there is none."""
    Picamera2 = need("picamera2", "sudo apt install -y python3-picamera2").Picamera2
    cameras = Picamera2.global_camera_info()
    if not cameras:
        raise Skip("No camera detected.\n"
                   "  - Power off, reseat the ribbon cable (contacts facing the right way at both ends)\n"
                   "  - Check:  rpicam-hello --list-cameras   (older OS: libcamera-hello --list-cameras)\n"
                   "  - Make sure no other program (e.g. rpicam-hello, the robot) is using the camera")
    print(f"Camera: {cameras[0].get('Model', '?')}  (found {len(cameras)})")
    cam = Picamera2()
    # "RGB888" in picamera2 returns pixels in B, G, R byte order - flipped in grab()
    cam.configure(cam.create_preview_configuration(main={"size": CAPTURE_SIZE, "format": "RGB888"}))
    cam.start()
    time.sleep(1.0)  # let auto exposure / white balance settle
    return cam


def grab(cam):
    return cam.capture_array("main")[:, :, 2::-1]  # BGR -> RGB, drops any 4th channel


def fit(img_h, img_w, width):
    term = shutil.get_terminal_size((80, 24))
    cols = width or term.columns
    rows_avail = max(4, term.lines - 3)            # leave room for the status line
    rows = int(cols * img_h / img_w / 2)           # a terminal cell is ~2x taller than wide
    if rows > rows_avail:
        rows = rows_avail
        cols = int(rows * 2 * img_w / img_h)
    return max(cols, 1), max(rows, 1)


def render(rgb, width=0, ascii_mode=False):
    """An RGB image as terminal text. Colour: two pixels per cell with the half block (24-bit ANSI).
    Also used by deskbot (deskbot/checks/sensors.py) for the camera + detection view."""
    import numpy as np

    h, w = rgb.shape[:2]
    cols, rows = fit(h, w, width)
    xs = np.linspace(0, w - 1, cols).astype(int)
    if ascii_mode:
        ys = np.linspace(0, h - 1, rows).astype(int)
        small = rgb[ys][:, xs].astype(float)
        lum = (0.299 * small[..., 0] + 0.587 * small[..., 1] + 0.114 * small[..., 2]) / 255
        idx = (lum * (len(ASCII_RAMP) - 1)).round().astype(int)
        return "\n".join("".join(ASCII_RAMP[i] for i in row) for row in idx)
    ys = np.linspace(0, h - 1, rows * 2).astype(int)
    small = rgb[ys][:, xs]
    lines = []
    for r in range(rows):
        top, bottom = small[2 * r], small[2 * r + 1]
        lines.append("".join(f"\x1b[38;2;{t[0]};{t[1]};{t[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m▀"
                             for t, b in zip(top, bottom)) + "\x1b[0m")
    return "\n".join(lines)


def test_camera(args):
    need("numpy", "sudo apt install -y python3-numpy")
    cam = open_camera()
    try:
        if args.save:
            cam.capture_file(args.save)
            print(f"Saved {args.save}")
        if args.snap:
            print(render(grab(cam), args.width, args.ascii))
            return
        stop = enter_to_stop()
        sys.stdout.write("\x1b[2J\x1b[?25l")  # clear screen, hide cursor
        frames, t0 = 0, time.monotonic()
        try:
            while not stop.is_set():
                frame = render(grab(cam), args.width, args.ascii)
                frames += 1
                fps = frames / max(time.monotonic() - t0, 1e-6)
                sys.stdout.write(f"\x1b[H{frame}\n\x1b[0mLive view  {fps:4.1f} fps  - press Enter to stop\x1b[K")
                sys.stdout.flush()
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write("\x1b[0m\x1b[?25h\n")  # reset colours, show cursor
        print(f"Stopped after {frames} frames.")
    finally:
        cam.stop()
        cam.close()


# =============================== microphone ===============================
# A bare 2-wire electret capsule can't go on GPIO (the Pi has no analog input): it goes into a USB sound card's
# mic jack (red -> tip, black -> sleeve), which powers it. See docs/microphone.md.

RATE = 16000          # Hz - plenty for voice, supported by almost every USB card
CHUNK = RATE // 20    # samples per meter update (50 ms)
RECORD_SECONDS = 5
CLIP = "mic_test.wav"


def capture_devices():
    """[(alsa_name, description)] from `arecord -l`."""
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    return [(f"plughw:{card},{dev}", f"{cname} - {dname}")
            for card, _, cname, dev, dname in re.findall(r"card (\d+): (\S+) \[(.*?)\], device (\d+): .*?\[(.*?)\]", out)]


def choose_mic():
    devices = capture_devices()
    if not devices:
        raise Skip("No microphone / capture device found.\n"
                   "  - Is the USB sound card plugged in?  Check:  lsusb   and   arecord -l\n"
                   "  - The Pi's own 3.5 mm jack is output only - it cannot record.")
    print("\nCapture devices:")
    for i, (name, desc) in enumerate(devices, 1):
        print(f"  {i}. {desc}  ({name})")
    if len(devices) == 1:
        print("Using the only device.")
        return devices[0][0]
    while True:
        choice = ask("Device number: ")
        if choice.isdigit() and 1 <= int(choice) <= len(devices):
            return devices[int(choice) - 1][0]
        if choice == "q":
            raise Skip("No device chosen.")


def level_meter(device):
    print(f"\nLive level on {device} - speak, clap or tap the mic. Press Enter to stop.\n")
    proc = subprocess.Popen(["arecord", "-D", device, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw", "-q"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stop = enter_to_stop()
    peak_db, quietest_db = -120.0, 0.0
    width = max(20, min(60, shutil.get_terminal_size((80, 24)).columns - 30))
    try:
        while not stop.is_set():
            data = proc.stdout.read(CHUNK * 2)
            if not data:
                print(f"\narecord stopped: {proc.stderr.read().decode(errors='replace').strip() or 'no data'}")
                break
            samples = array.array("h", data)
            rms = math.sqrt(sum(s * s for s in samples) / len(samples)) or 1e-9
            db = 20 * math.log10(rms / 32768)            # dBFS: 0 = loudest possible
            peak_db, quietest_db = max(peak_db, db), min(quietest_db, db)
            filled = int(max(0.0, min(1.0, (db + 60) / 60)) * width)   # -60..0 dBFS -> bar
            clip = "  CLIPPING" if max(abs(min(samples)), max(samples)) >= 32700 else ""
            print(f"\r{db:6.1f} dBFS |{'#' * filled}{' ' * (width - filled)}|{clip:<10}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait()
    if peak_db > -120:
        print(f"\n\nQuietest {quietest_db:.1f} dBFS, loudest {peak_db:.1f} dBFS")
        print("Hardly any change - the mic may not be connected/powered, or the input is muted (alsamixer, F4)."
              if peak_db - quietest_db < 6 else "Level reacts to sound - the microphone works.")


def record_and_play(device):
    print(f"\nRecording {RECORD_SECONDS} s from {device} - talk now...")
    r = subprocess.run(["arecord", "-D", device, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-d", str(RECORD_SECONDS), CLIP],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Recording failed: {r.stderr.strip()}")
        return
    print(f"Saved {CLIP}. Playing it back...")
    p = subprocess.run(["aplay", CLIP], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"Playback failed ({p.stderr.strip()}). Copy {CLIP} to a laptop to listen:  scp pi@<pi-ip>:{CLIP} .")
    else:
        print("Done. Heard yourself? The mic works. Silence/hiss only? Check wiring and the alsamixer capture level.")


def test_mic(args):
    missing = [t for t in ("arecord", "aplay") if not shutil.which(t)]
    if missing:
        raise Skip(f"Missing {', '.join(missing)}.\n  Fix: sudo apt install -y alsa-utils")
    device = choose_mic()
    while True:
        print(f"\nMicrophone test  ({device})\n  1. live level meter\n  2. record {RECORD_SECONDS} s and play back\n"
              "  3. choose another device\n  b. back")
        choice = ask("> ")
        if choice == "1":
            level_meter(device)
        elif choice == "2":
            record_and_play(device)
        elif choice == "3":
            device = choose_mic()
        elif choice in ("b", "q", "quit", "0", "back"):
            return
        else:
            print("Enter 1, 2, 3 or b.")


# =============================== OLED ===============================
# The robot's OLED shares I2C bus 1 with the MPU-6050 (GPIO 2 SDA pin 3, GPIO 3 SCL pin 5, 3.3 V pin 1, GND pin 6).
# GPIO 7/8 now belong to the touch pads, so the old software bus 3 on them is no longer used.

def i2c_scan(bus, addr):
    """Hex addresses of the OLED range (0x3c-0x3d) that answer, or None if the scan couldn't run."""
    if not shutil.which("i2cdetect"):
        return None
    try:   # only probe 3c-3d and cap the time, so a stuck bus can't hang the test
        out = subprocess.run(["i2cdetect", "-y", str(bus), "0x3c", "0x3d"], capture_output=True, text=True, timeout=15).stdout
    except subprocess.TimeoutExpired:
        raise Skip(f"The I2C scan on bus {bus} timed out: the bus is stuck. Check the SDA/SCL wires and the screen's power.")
    return re.findall(r"\b3[cd]\b", "\n".join(line[4:] for line in out.splitlines()[1:]))


def test_oled(args):
    bus, addr = args.bus, args.addr
    if not os.path.exists(f"/dev/i2c-{bus}"):
        raise Skip(f"/dev/i2c-{bus} doesn't exist.\n  Fix: sudo raspi-config nonint do_i2c 0 && sudo reboot"
                   + ("" if bus == 1 else "  (or add the dtoverlay for that bus to /boot/firmware/config.txt)"))
    found = i2c_scan(bus, addr)
    if found is not None:
        print(f"I2C bus {bus}, 0x3c-0x3d: {' '.join(found) or 'nothing'}")
        if f"{addr:02x}" not in found:
            hint = (f"found {' '.join(found)}: re-run with --addr 0x{found[0]}" if found else
                    "nothing answered - wiring/power, not software. With the Pi OFF check: SDA -> pin 3, SCL -> pin 5,\n"
                    "  VDD -> pin 1 (3.3 V), GND -> pin 6, jumpers pushed fully in, header pins soldered on the module")
            raise Skip(f"No OLED at {hex(addr)} on bus {bus}: {hint}")
    serial = need("luma.core.interface.serial", "pip install luma.oled")
    render_mod = need("luma.core.render", "pip install luma.oled")
    oled = need("luma.oled.device", "pip install luma.oled")
    driver = oled.sh1106 if args.sh1106 else oled.ssd1306
    print(f"driver={'sh1106' if args.sh1106 else 'ssd1306'} bus={bus} addr={hex(addr)}  "
          "(picture shifted/garbled? try --sh1106)")
    dev = driver(serial.i2c(port=bus, address=addr), width=128, height=64)
    lines = args.text or ["Hello from Pip!", "OLED works :)"]
    with render_mod.canvas(dev) as draw:
        draw.rectangle(dev.bounding_box, outline="white")
        for i, line in enumerate(lines[:5]):                       # ~21 characters fit per line
            draw.text((4, 4 + i * 12), line, fill="white")
    print("Written:", " | ".join(lines[:5]))
    if args.text:                                                 # custom text: leave it on the screen
        dev.persist = True
        return
    print("Live clock in 3 s. Press Enter to stop.")
    stop = enter_to_stop()
    stop.wait(3)
    try:
        while not stop.is_set():
            with render_mod.canvas(dev) as draw:
                draw.text((34, 10), time.strftime("%H:%M:%S"), fill="white")
                x = int(time.time() * 40) % (dev.width + 20) - 20       # a little ball rolling across
                draw.ellipse((x, 40, x + 14, 54), fill="white")
            stop.wait(0.05)
    except KeyboardInterrupt:
        pass
    dev.clear()
    print("Stopped.")


# =============================== touch pads ===============================
# Each TTP223: VCC -> 3.3 V (NOT 5 V: the I/O pin would then output 5 V into the Pi), GND -> GND, I/O -> its pin.
# GPIO 14 is UART TX: the serial console must be off (scripts/setup.sh does it). Jumpers A and B open = output HIGH
# while touched (what the robot expects). The module calibrates for ~0.5 s after power-up: don't touch it then.

def test_touch(args):
    gz = need("gpiozero", "sudo apt install -y python3-gpiozero")
    pads = PINS["TOUCH"]
    for name, bcm in pads.items():
        print(f"  {name:>5}: {pin(bcm)}")
    devices = {name: gz.DigitalInputDevice(bcm, pull_up=False, bounce_time=0.02) for name, bcm in pads.items()}
    counts = {name: 0 for name in pads}
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
    print("\nTouch each pad. Press Enter to stop.\n")
    stop = enter_to_stop()
    try:
        while not stop.is_set():
            line = "   ".join(f"{n:>5}: {'■ TOUCHED' if d.value else '·        '} ({counts[n]})" for n, d in devices.items())
            print("\r" + line, end="", flush=True)
            stop.wait(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        for dev in devices.values():
            dev.close()
    print("\n\nTouches:", ", ".join(f"{n} {c}" for n, c in counts.items()))
    if not any(counts.values()):
        print("Nothing seen: check VCC on 3.3 V, GND, the I/O wire, and that the serial console is off (GPIO 14).")


# =============================== menu ===============================

TESTS = {
    "sensors": (test_sensors, "ultrasonic + IR sensors, one at a time"),
    "camera": (test_camera, "live camera image in the terminal"),
    "mic": (test_mic, "microphone level meter / record and play back"),
    "oled": (test_oled, "text and a clock on the OLED screen"),
    "touch": (test_touch, "the three touch pads"),
}
ALIASES = {"ultrasonic": "sensors", "ir": "sensors", "microphone": "mic", "screen": "oled"}


def build_parser():
    ap = argparse.ArgumentParser(description="Every hardware test of the desk robot, from one menu.")
    ap.add_argument("test", nargs="?", help=f"run one test and exit: {', '.join(TESTS)} (default: menu)")
    cam = ap.add_argument_group("camera")
    cam.add_argument("--snap", action="store_true", help="show one picture and exit")
    cam.add_argument("--save", metavar="FILE", help="also save a JPEG (e.g. pic.jpg)")
    cam.add_argument("--ascii", action="store_true", help="plain characters instead of colour blocks")
    cam.add_argument("--width", type=int, default=0, help="width in characters (default: fit terminal)")
    oled = ap.add_argument_group("oled")
    oled.add_argument("--bus", type=int, default=1, help="I2C bus (default 1: GPIO 2/3, shared with the IMU)")
    oled.add_argument("--addr", type=lambda s: int(s, 0), default=0x3C, help="I2C address (default 0x3c; some modules 0x3d)")
    oled.add_argument("--sh1106", action="store_true", help="SH1106 driver (1.3\" modules; picture shifted with ssd1306)")
    oled.add_argument("--text", nargs="+", metavar="LINE", help="write these lines (max 5) and leave them on screen")
    return ap


def run(name, args):
    try:
        TESTS[name][0](args)
        return 0
    except Skip as exc:
        print(f"\n{name}: can't run.\n  {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.test:
        name = ALIASES.get(args.test, args.test)
        if name not in TESTS:
            sys.exit(f"Unknown test {args.test!r}. Choose one of: {', '.join(TESTS)}")
        return run(name, args)
    names = list(TESTS)
    while True:
        print("\nHardware tests (no motors are touched)")
        for i, n in enumerate(names, 1):
            print(f"  {i}. {n:<8} {TESTS[n][1]}")
        print("  q. quit")
        choice = ask("> ")
        if choice in ("q", "quit", "0"):
            break
        name = names[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(names) else ALIASES.get(choice, choice)
        if name in TESTS:
            run(name, args)
        else:
            print("Enter a number from the list, a test name, or q.")
    print("Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
