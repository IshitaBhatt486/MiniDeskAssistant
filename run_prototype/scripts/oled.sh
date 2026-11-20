#!/usr/bin/env bash
# Write some text on the OLED (quick screen test). Does the one-time setup itself.
#
#   scripts/oled.sh                      "Hello from Pip!"
#   scripts/oled.sh "hi there" "line 2"  one argument per line (about 21 characters fit per line)
#   OLED_DRIVER=sh1106 scripts/oled.sh   1.3" modules (picture shifted/garbled with ssd1306)
#   OLED_ADDR=0x3D scripts/oled.sh       if i2cdetect shows 3d instead of 3c
#
# Pins come from robot_config.py (I2C bus 1: SDA GPIO 2 / pin 3, SCL GPIO 3 / pin 5, 3.3 V pin 1, GND),
# driver/port/address defaults from deskbot/companion/config.py (OledConfig).
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

# ---- setup (each step is skipped when already done) ----
if is_pi; then
  if [ ! -e /dev/i2c-1 ]; then
    echo "==> Enabling I2C (needs your password, then a reboot)"
    sudo apt-get install -y i2c-tools
    sudo raspi-config nonint do_i2c 0
    sudo usermod -aG i2c "$(id -un)" || true
    echo "I2C enabled. Reboot (sudo reboot) and run this script again."
    exit 0
  fi
  command -v i2cdetect >/dev/null || sudo apt-get install -y i2c-tools
fi
"$PY" -c "import luma.oled" 2>/dev/null || { echo "==> Installing luma.oled"; "$PY" -m pip install luma.oled; }

if command -v i2cdetect >/dev/null; then
  echo "==> Devices on I2C bus 1 (OLED should be 3c, IMU 68):"
  i2cdetect -y 1 || true
fi

# ---- draw ----
exec "$PY" - "$@" <<'EOF'
import os, sys
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106, ssd1306
from robot_config import I2C
from deskbot.companion.config import OledConfig

cfg = OledConfig()
driver = os.environ.get("OLED_DRIVER", cfg.driver)
addr = int(os.environ.get("OLED_ADDR", hex(cfg.address)), 0)
lines = sys.argv[1:] or ["Hello from Pip!", "OLED works :)"]

print(f"driver={driver} bus={cfg.port} (SDA GPIO {I2C['sda']}, SCL GPIO {I2C['scl']}) addr={hex(addr)}")
dev = {"ssd1306": ssd1306, "sh1106": sh1106}[driver](
    i2c(port=cfg.port, address=addr), width=cfg.width, height=cfg.height, rotate=cfg.rotate)
dev.persist = True            # keep the text on screen after the script exits

with canvas(dev) as draw:
    draw.rectangle(dev.bounding_box, outline="white")
    for i, line in enumerate(lines[:5]):
        draw.text((4, 4 + i * 12), line, fill="white")
print("Written:", " | ".join(lines[:5]))
EOF
