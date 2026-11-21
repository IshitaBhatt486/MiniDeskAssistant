#!/usr/bin/env python3
"""
Print text on the OLED. Standalone: needs only luma.oled + Pillow, nothing from run_prototype/ (21 Nov 2026).

    python3 oled_print.py "Hello!"                      wraps and sizes the text to fit, keeps it on screen
    python3 oled_print.py "Hi" --driver sh1106          the common 1.3" modules
    python3 oled_print.py "Hi" --rotate 2 --seconds 5   upside down, clears after 5 s
    python3 oled_print.py --clear                       blank the screen

On the Pi: copy it over (scp tools/oled_print.py <user>@<pi>:~) and run it with the robot's Python, which has the
packages: ~/deskbot/.venv/bin/python oled_print.p]y "Hello". Stop the robot first (sudo systemctl stop deskbot):
two programs can't drive the screen at once.
Defaults match the robot: I2C bus 1, address 0x3C, 128x64, SSD1306.
"""

import argparse
import sys
import textwrap
import time


def fit(draw, text, width, height):
    """Biggest font (and line wrapping) that fits the screen."""
    from PIL import ImageFont
    for size in range(40, 7, -2):
        try:
            font = ImageFont.load_default(size=size)          # Pillow >= 10.1 has a scalable default font
        except TypeError:
            return ImageFont.load_default(), textwrap.fill(text, 21)
        chars = max(1, int(width / (size * 0.6)))
        lines = "\n".join(textwrap.fill(part, chars) or " " for part in text.split("\\n"))
        box = draw.multiline_textbbox((0, 0), lines, font=font, spacing=2)
        if box[2] - box[0] <= width and box[3] - box[1] <= height:
            return font, lines
    return font, lines


KNOWN = {0x3C: "OLED", 0x3D: "OLED", 0x68: "MPU-6050 (IMU)", 0x69: "MPU-6050 (IMU, AD0 high)"}


def scan(port):
    """Addresses that answer on the bus (what `i2cdetect -y 1` shows), or an error message."""
    try:
        from smbus2 import SMBus
    except ImportError:
        return "smbus2 is not installed, so the bus can't be scanned (pip install smbus2)"
    found = []
    try:
        with SMBus(port) as bus:
            for addr in range(0x03, 0x78):
                try:
                    bus.read_byte(addr)
                    found.append(addr)
                except OSError:
                    pass
    except (OSError, PermissionError) as exc:
        return f"can't open /dev/i2c-{port}: {exc}"
    return found


def diagnose(port, tried, error):
    """Why the OLED didn't answer, from what is (and isn't) on the bus."""
    tried_s = " or ".join(f"{t:#04x}" for t in tried)
    lines = [f"No OLED answered on I2C bus {port} at {tried_s} ({error})."]
    found = scan(port)
    if isinstance(found, str):
        lines.append(f"Bus scan: {found}")
        if "No such file" in found:
            lines.append("-> I2C is off: sudo raspi-config nonint do_i2c 0, then reboot.")
        elif "ermission" in found:
            lines.append("-> add yourself to the i2c group: sudo usermod -aG i2c $USER, then log out and in.")
        return "\n".join(lines)
    names = ", ".join(f"{f:#04x}" + (f" ({KNOWN[f]})" if f in KNOWN else "") for f in found) or "nothing"
    lines.append(f"Devices on the bus: {names}")
    others = [f for f in found if f not in tried and f not in (0x68, 0x69)]
    if not found:
        lines += ["-> Nothing at all answers, so the bus itself isn't connected to anything that works:",
                  "   - SDA to physical pin 3 (GPIO 2), SCL to physical pin 5 (GPIO 3): swapped SDA/SCL is the most common mistake",
                  "   - VCC to physical pin 1 (3.3 V), GND to physical pin 6; is the screen's power LED/board warm?",
                  "   - push every jumper wire fully on; try other wires (broken Dupont wires are common)",
                  "   - if the IMU is wired too and it also doesn't show (0x68), the shared SDA/SCL wires are the problem"]
        lines += line_levels()
    elif any(f in (0x68, 0x69) for f in found) and not others:
        lines += ["-> The IMU answers, so the bus and the Pi side are fine: the problem is the OLED itself or its 4 wires:",
                  "   - a 7-pin OLED (GND VCC D0 D1 RES DC CS) is in SPI mode and never appears on I2C;",
                  "     only 4-pin modules (GND VCC SCL SDA) are I2C (7-pin ones need resistors moved on the back)",
                  "   - check the OLED's own VCC/GND, and that its SDA/SCL wires reach the same pins 3/5 as the IMU's",
                  "   - check the pin order printed on the OLED: some modules are VCC-GND-SCL-SDA, others GND-VCC-SCL-SDA"]
    if others:
        lines.append(f"-> Something answers at {', '.join(f'{f:#04x}' for f in others)}: if that's the screen, run with "
                     f"--address {others[0]:#04x}")
    return "\n".join(lines)


def line_levels():
    """SDA/SCL voltage levels (pinctrl on Bookworm, raspi-gpio before). An idle I2C line must read high."""
    import re
    import shutil
    import subprocess
    tool = shutil.which("pinctrl") or shutil.which("raspi-gpio")
    if not tool:
        return ["   (can't read the pin levels: neither pinctrl nor raspi-gpio is installed)"]
    try:
        out = subprocess.run([tool, "get", "2,3" if tool.endswith("pinctrl") else "2-3"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"   (can't read the pin levels: {exc})"]
    levels = {}
    for line in out.splitlines():
        m = re.match(r"\s*(?:GPIO\s*)?([23])\s*:.*?\b(hi|lo)\b", line) or re.match(r"GPIO ([23]): level=([01])", line)
        if m:
            levels[m.group(1)] = "hi" if m.group(2) in ("hi", "1") else "lo"
    result = [f"Pin levels now: SDA (GPIO 2) {levels.get('2', '?')}, SCL (GPIO 3) {levels.get('3', '?')}   [{tool} get 2,3]"]
    if levels.get("2") == "lo" or levels.get("3") == "lo":
        low = " and ".join(n for n, k in (("SDA", "2"), ("SCL", "3")) if levels.get(k) == "lo")
        result += [f"-> {low} is held LOW, so something pulls it to ground. A free I2C line idles high (the Pi has pull-ups):",
                   "   - a wire on the wrong header pin: pin 6 and pin 9 are GND, right next to pins 3 and 5;",
                   "     pin 1 is the square pad, at the SD-card end of the header, in the row nearer the middle of the board",
                   "   - unplug the OLED: if the line goes back to hi, the module (or its wire order) is the problem"]
    elif levels.get("2") == "hi" and levels.get("3") == "hi":
        result += ["-> Both lines are high and free, so the Pi side is fine. The device isn't answering on them: either",
                   "   it has no power (measure 3.3 V between the OLED's own VCC and GND pins), or its SDA/SCL wires go to",
                   "   other header pins (count again: pins 3 and 5 are the 2nd and 3rd pin in the row with pin 1), or the",
                   "   module is a 7-pin SPI one, or it's damaged (e.g. after VCC/GND were swapped once)"]
    return result


def main():
    p = argparse.ArgumentParser(description="Print text on the OLED (use \\n for a line break)")
    p.add_argument("text", nargs="?", default="Hello!")
    p.add_argument("--driver", choices=["ssd1306", "sh1106"], default="ssd1306")
    p.add_argument("--address", type=lambda v: int(v, 0), default=None, help="I2C address (default: try 0x3C, then 0x3D)")
    p.add_argument("--port", type=int, default=1, help="I2C bus (default 1)")
    p.add_argument("--rotate", type=int, choices=[0, 1, 2, 3], default=0, help="quarter turns")
    p.add_argument("--seconds", type=float, default=0, help="clear after this long (default: leave it on)")
    p.add_argument("--clear", action="store_true", help="just blank the screen")
    a = p.parse_args()

    try:
        from luma.core.interface.serial import i2c
        from luma.core.render import canvas
        from luma.oled.device import sh1106, ssd1306
    except ImportError as exc:
        sys.exit(f"Missing package ({exc.name}). Run with ~/deskbot/.venv/bin/python, or: pip install luma.oled pillow")
    # 21 Nov 2026: OLEDs are at 0x3C or 0x3D, so without --address both are tried; if neither answers, the bus is
    # scanned and what's on it says what's wrong.
    addresses = [a.address] if a.address is not None else [0x3C, 0x3D]
    device, error = None, None
    for address in addresses:
        try:
            serial = i2c(port=a.port, address=address)
            device = {"ssd1306": ssd1306, "sh1106": sh1106}[a.driver](serial, rotate=a.rotate)
            break
        except Exception as exc:
            error = exc
    if device is None:
        sys.exit(diagnose(a.port, addresses, error))
    device.persist = not a.seconds and not a.clear            # keep the text after the script exits

    if a.clear:
        device.clear()
        return print("Screen cleared.")
    with canvas(device) as draw:
        font, lines = fit(draw, a.text, device.width, device.height)
        box = draw.multiline_textbbox((0, 0), lines, font=font, spacing=2)
        x = (device.width - (box[2] - box[0])) // 2 - box[0]
        y = (device.height - (box[3] - box[1])) // 2 - box[1]
        draw.multiline_text((x, y), lines, font=font, fill="white", spacing=2, align="center")
    print(f"Shown on the {a.driver} at {address:#04x}: {a.text!r}")
    if a.seconds:
        time.sleep(a.seconds)
        device.clear()


if __name__ == "__main__":
    main()
