#!/usr/bin/env bash
# OLED screen test - STANDALONE. Copy this one file anywhere on the Pi and run it:
#
#   bash screen_test.sh                        "Hello from Pip!"
#   bash screen_test.sh "hi there" "line 2"    one argument per line (~21 characters fit per line, max 5)
#   OLED_DRIVER=sh1106 bash screen_test.sh     1.3" modules (picture shifted/garbled with ssd1306)
#   OLED_ADDR=0x3D bash screen_test.sh         if i2cdetect shows 3d instead of 3c
#   OLED_BUS=1 bash screen_test.sh             screen on the hardware I2C pins (GPIO 2/3) instead
#
# Needs no other project files. Wiring (same as hardware_tests/test_oled.py):
#   SCK/SCL -> GPIO 7 (pin 26)   SDA -> GPIO 8 (pin 24)   VDD -> 3.3 V (pin 1)   GND -> GND (pin 6)
#   driver ssd1306, address 0x3C, 128x64
# GPIO 7/8 aren't hardware I2C pins, so Linux makes a software I2C bus (bus 3) on them with the
# i2c-gpio overlay. The script adds that line to config.txt the first time and asks you to reboot.
# GPIO 7/8 are the SPI chip-selects, so SPI must stay off (sudo raspi-config nonint do_spi 1).
# luma.oled goes into its own venv (~/.venvs/oled-test) so the system Python is left alone.
set -euo pipefail

DRIVER="${OLED_DRIVER:-ssd1306}"
ADDR="${OLED_ADDR:-0x3C}"
BUS="${OLED_BUS:-3}"
SDA_GPIO=8; SCL_GPIO=7
VENV="${OLED_VENV:-$HOME/.venvs/oled-test}"

# ---- 1. I2C bus present? ----
if [ ! -e "/dev/i2c-$BUS" ]; then
  if [ "$BUS" = 3 ]; then
    CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt      # older Raspberry Pi OS
    LINE="dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=$SDA_GPIO,i2c_gpio_scl=$SCL_GPIO,i2c_gpio_delay_us=2"
    if grep -q "^dtoverlay=i2c-gpio,bus=3" "$CFG" 2>/dev/null; then
      echo "ERROR: $CFG already has the i2c-gpio bus 3 line, but /dev/i2c-3 is missing. Reboot (sudo reboot)." >&2
    else
      echo "==> Adding software I2C bus 3 on GPIO $SDA_GPIO (SDA) / GPIO $SCL_GPIO (SCL) to $CFG (needs your password)"
      echo "$LINE" | sudo tee -a "$CFG" >/dev/null
      command -v raspi-config >/dev/null && sudo raspi-config nonint do_spi 1    # SPI would claim GPIO 7/8
      sudo usermod -aG i2c "$(id -un)" || true
      echo "Done. Reboot (sudo reboot) and run this script again."
    fi
  elif [ "$BUS" = 1 ] && command -v raspi-config >/dev/null; then
    echo "==> Enabling I2C bus 1 (needs your password, then a reboot)"
    sudo raspi-config nonint do_i2c 0
    sudo usermod -aG i2c "$(id -un)" || true
    echo "I2C enabled. Reboot (sudo reboot) and run this script again."
  else
    echo "ERROR: /dev/i2c-$BUS does not exist. Enable that I2C bus first." >&2
  fi
  exit 1
fi
command -v i2cdetect >/dev/null || { echo "==> Installing i2c-tools"; sudo apt-get install -y i2c-tools; }

# ---- 2. Python + luma.oled (own venv) ----
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> Creating venv $VENV"
  python3 -m venv --system-site-packages "$VENV" || {
    echo "venv failed - installing python3-venv"; sudo apt-get install -y python3-venv
    python3 -m venv --system-site-packages "$VENV"; }
fi
PY="$VENV/bin/python"
"$PY" -c "import luma.oled" 2>/dev/null || { echo "==> Installing luma.oled"; "$PY" -m pip install -q luma.oled; }

# ---- 3a. Are the wires idle-HIGH? (bus 3 only) ----
# On the software bus a LOW clock line makes the kernel wait ~100 ms per bit, so a full
# i2cdetect scan would hang for many minutes. Read the pins first and stop early if SCL is LOW.
if [ "$BUS" = 3 ]; then
  echo "==> Line levels (an idle I2C line must read HIGH):"
  scl_low=0
  for g in "$SCL_GPIO" "$SDA_GPIO"; do
    name=$([ "$g" = "$SCL_GPIO" ] && echo "SCK/SCL GPIO $g (pin 26)" || echo "SDA     GPIO $g (pin 24)")
    if command -v pinctrl >/dev/null; then st="$(pinctrl get "$g" 2>/dev/null || true)"
    elif command -v raspi-gpio >/dev/null; then st="$(raspi-gpio get "$g" 2>/dev/null || true)"
    else st=""; fi
    if echo "$st" | grep -qiE '\| *hi|level=1'; then lvl=HIGH
    elif echo "$st" | grep -qiE '\| *lo|level=0'; then lvl=LOW; [ "$g" = "$SCL_GPIO" ] && scl_low=1
    else lvl="unknown ($st)"; fi
    echo "  $name: $lvl"
  done
  if [ "$scl_low" = 1 ]; then
    cat >&2 <<EOF
ERROR: the clock line (GPIO 7, pin 26) is LOW, so the bus can't run (this is what made i2cdetect hang).
Cause is almost always one of:
  - screen not powered: VDD -> pin 1 (3.3 V), GND -> pin 6
  - SCK wire not on pin 26 (pin 26 = outer row, 13th pin from pin 1; pin 1 has the square pad)
  - SPI still on and holding GPIO 7: sudo raspi-config nonint do_spi 1 && sudo reboot
  - a module without pull-up resistors: add 4.7k from SCK to 3.3 V and from SDA to 3.3 V
Fix with the Pi OFF, then re-run.
EOF
    exit 2
  fi
fi

# ---- 3b. Is the screen on the bus? ----
# Only probe 0x3c-0x3d (both OLED addresses) and cap the time, so a bad bus can't hang the script.
echo "==> Devices on I2C bus $BUS at 3c-3d (OLED should be ${ADDR#0x}):"
SCAN="$(timeout 15 i2cdetect -y "$BUS" 0x3c 0x3d || echo "(scan timed out after 15 s - bus is stuck, check wiring)")"
echo "$SCAN"
want="$(printf '%02x' "$((ADDR))")"
if ! echo "$SCAN" | tail -n +2 | cut -c5- | grep -qw "$want"; then
  found="$(echo "$SCAN" | tail -n +2 | cut -c5- | grep -oE '\b[0-9a-f]{2}\b' | tr '\n' ' ' || true)"
  echo
  if [ -z "$found" ]; then
    cat >&2 <<EOF
ERROR: nothing answered on bus $BUS - this is a wiring/power problem, not software.
With the Pi OFF, check:
$( [ "$BUS" = 3 ] && echo "  SDA -> pin 24 (GPIO 8)     SCK/SCL -> pin 26 (GPIO 7)   (not swapped)"                  || echo "  SDA -> pin 3 (GPIO 2)      SCL -> pin 5 (GPIO 3)        (not swapped)" )
  VCC -> pin 1 (3.3 V)       GND -> pin 6
  jumpers pushed fully in / on the right breadboard rows; header pins soldered on the module
Then re-run. 'i2cdetect -y $BUS' should show ${want}.
EOF
    # ---- diagnose: an idle I2C line sits HIGH (the module's pull-up resistors pull it to 3.3 V) ----
    if [ "$BUS" = 3 ]; then
      echo >&2; echo "==> Diagnosis" >&2
      if ls /dev/spidev0.* >/dev/null 2>&1; then
        echo "  PROBLEM: SPI is on and owns GPIO 7/8. Fix: sudo raspi-config nonint do_spi 1 && sudo reboot" >&2
      fi
      for g in "$SCL_GPIO" "$SDA_GPIO"; do
        name=$([ "$g" = "$SCL_GPIO" ] && echo "SCK (GPIO $g, pin 26)" || echo "SDA (GPIO $g, pin 24)")
        if command -v pinctrl >/dev/null; then st="$(pinctrl get "$g" 2>/dev/null || true)"
        elif command -v raspi-gpio >/dev/null; then st="$(raspi-gpio get "$g" 2>/dev/null || true)"
        else st=""; fi
        if echo "$st" | grep -qiE '\| *hi|level=1'; then
          echo "  $name reads HIGH -> wire reaches a powered screen (good)" >&2
        elif echo "$st" | grep -qiE '\| *lo|level=0'; then
          echo "  $name reads LOW  -> this wire is not connected to a powered screen (wrong pin, loose, or screen has no power)" >&2
        else
          echo "  $name: could not read ($st)" >&2
        fi
      done
      cat >&2 <<EOF
  Both LOW  -> screen has no power (VDD/GND) or both data wires are on the wrong pins.
  Both HIGH -> wiring reaches the screen; try SCK/SDA swapped, OLED_ADDR=0x3D, or the screen on pins 3/5 with OLED_BUS=1.
  Pin numbers are PHYSICAL positions: pin 1 is the square pad; pins 24 and 26 are on the outer row, 12th and 13th from pin 1.
EOF
    fi
  else
    echo "ERROR: no device at $ADDR, but found: $found" >&2
    echo "If one of those is the screen (3c/3d), re-run with OLED_ADDR=0x<that>." >&2
  fi
  exit 2
fi

# ---- 4. Draw ----
exec "$PY" - "$DRIVER" "$ADDR" "$BUS" "$@" <<'EOF'
import sys
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106, ssd1306

driver, addr, bus, *lines = sys.argv[1:]
addr, bus = int(addr, 0), int(bus)
lines = lines or ["Hello from Pip!", "OLED works :)"]
devices = {"ssd1306": ssd1306, "sh1106": sh1106}
if driver not in devices:
    sys.exit(f"OLED_DRIVER must be one of {', '.join(devices)}")

print(f"driver={driver} bus={bus} addr={hex(addr)}")
dev = devices[driver](i2c(port=bus, address=addr), width=128, height=64)
dev.persist = True            # keep the text on screen after the script exits

with canvas(dev) as draw:
    draw.rectangle(dev.bounding_box, outline="white")
    for i, line in enumerate(lines[:5]):
        draw.text((4, 4 + i * 12), line, fill="white")
print("Written:", " | ".join(lines[:5]))
EOF
