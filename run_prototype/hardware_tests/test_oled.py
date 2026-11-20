"""
0.96" OLED test (SSD1306, 128x64, I2C) - STANDALONE (only needs luma.oled, no other project files).

    python3 hardware_tests/test_oled.py            # text, a box, then a live clock until Ctrl+C
    python3 hardware_tests/test_oled.py --sh1106   # if the picture is shifted/garbled (1.3" modules use SH1106)
    python3 hardware_tests/test_oled.py --bus 1    # screen on the normal I2C pins (GPIO 3 = SCK, GPIO 2 = SDA)

Wiring (the 4-pin module is I2C, even though the pins say SCK/SDA):
    GND -> GND      (pin 6)
    VDD -> 3.3 V    (pin 1)     3.3 V is safest; most modules also take 5 V
    SCK -> GPIO 7   (pin 26)    = I2C clock (SCL)
    SDA -> GPIO 8   (pin 24)    = I2C data

GPIO 7/8 are free on the robot (they're the SPI chip-selects, and SPI stays off: sudo raspi-config nonint do_spi 1).

GPIO 7/8 aren't hardware I2C pins, so Linux makes a software I2C bus (bus 3) on them. Once:
    echo 'dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=8,i2c_gpio_scl=7,i2c_gpio_delay_us=2' | sudo tee -a /boot/firmware/config.txt
    sudo reboot                     (older Raspberry Pi OS: /boot/config.txt)
    pip install luma.oled
Check: i2cdetect -y 3   should show 3c (some modules: 3d, use --addr 0x3d)
"""

import argparse
import os
import sys
import time

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106, ssd1306

ap = argparse.ArgumentParser()
ap.add_argument("--addr", type=lambda s: int(s, 0), default=0x3C)
ap.add_argument("--sh1106", action="store_true")
ap.add_argument("--bus", type=int, default=3, help="3 = software I2C on GPIO 7/8 (default), 1 = GPIO 3/2")
args = ap.parse_args()

if not os.path.exists(f"/dev/i2c-{args.bus}"):
    sys.exit(f"/dev/i2c-{args.bus} doesn't exist: add the dtoverlay line from the top of this file and reboot")

device = (sh1106 if args.sh1106 else ssd1306)(i2c(port=args.bus, address=args.addr))   # 128x64

with canvas(device) as draw:
    draw.rectangle(device.bounding_box, outline="white")
    draw.text((10, 12), "Hello from Pip!", fill="white")
    draw.text((10, 32), "OLED works :)", fill="white")
time.sleep(3)

try:
    while True:
        with canvas(device) as draw:
            draw.text((34, 10), time.strftime("%H:%M:%S"), fill="white")
            x = int(time.time() * 40) % (device.width + 20) - 20        # a little ball bouncing across
            draw.ellipse((x, 40, x + 14, 54), fill="white")
        time.sleep(0.05)
except KeyboardInterrupt:
    device.clear()
