"""
Pin configuration for the desk assistant robot - the single place to change wiring.

All numbers are BCM GPIO numbers (what gpiozero uses), not physical header pins.
Physical pins are listed in the comments and in PHYSICAL_PIN below.

Read by:
    13Nov-multisonar.py
    dashboard/robot.py, dashboard/multisonar.py  (all dashboard servers)
Not read by:
    3Nov-latest.py  - kept unchanged as the known-working reference; its pins match MOTOR_*/FRONT_SONAR/IR_*

Check the file after editing:
    python3 robot_config.py
"""

# ---------------- MOTORS (L298N) ----------------

LEFT_MOTOR = {
    "forward": 22,   # IN1  - physical pin 15
    "backward": 23,  # IN2  - physical pin 16
    "enable": 13,    # ENA  - physical pin 33 (hardware PWM)
}

RIGHT_MOTOR = {
    "forward": 27,   # IN3  - physical pin 13
    "backward": 17,  # IN4  - physical pin 11
    "enable": 12,    # ENB  - physical pin 32 (hardware PWM)
}

# ---------------- ULTRASONIC (HC-SR04) ----------------
# Every ECHO goes through a 1k/2k voltage divider (5 V -> 3.3 V).

SONARS = {
    "front": {"trigger": 24, "echo": 25},   # TRIG pin 18, ECHO pin 22(echo goes through resistsance))
    "left": {"trigger": 4, "echo": 18},     # TRIG pin 7,  ECHO pin 12
    "right": {"trigger": 21, "echo": 9},    # TRIG pin 40, ECHO pin 21  (SPI0 MISO)
    "rear": {"trigger": 10, "echo": 11},    # TRIG pin 19, ECHO pin 23  (SPI0 MOSI/SCLK)
}

# ---------------- IR EDGE SENSORS ----------------
# Output LOW = floor detected. Power from 5 V for front and 3.3 for back.

IR_FRONT = 19   # physical pin 35
IR_BACK = 26    # physical pin 37

# ---------------- I2C BUS 1 (MPU-6050 IMU + SSD1306 OLED) ----------------
# Both devices share these two pins, 3.3 V (pin 1) and GND. Enable with: sudo raspi-config nonint do_i2c 0
# Addresses: MPU-6050 0x68 (AD0 low), OLED 0x3C. Check with: i2cdetect -y 1

I2C = {
    "sda": 2,   # physical pin 3
    "scl": 3,   # physical pin 5
}

# ---------------- WHEEL ENCODERS ----------------
# Quadrature encoders, 3.3 V logic - see docs/encoders.md. Read by the sensor process.

ENCODERS = {
    "left_a": 5,    # physical pin 29
    "left_b": 6,    # physical pin 31
    "right_a": 20,  # physical pin 38
    "right_b": 16,  # physical pin 36
}

# ---------------- TOUCH PADS (3x TTP223, 20 Nov 2026) ----------------
# VCC -> 3.3 V (pin 1 or 17; NOT 5 V: the I/O output would then be 5 V), GND -> GND, I/O -> the pin below.
# Default TTP223 jumpers (A and B open): momentary, output HIGH while touched. Read by deskbot/pro/touch.py.
# GPIO 14 is UART TX: the serial console must be off (scripts/setup.sh does it: raspi-config nonint do_serial_cons 1).
# Pin-saving alternatives (diode-OR on one pin, PCF8574 on the I2C bus): docs/pro.md.

TOUCH = {
    "top": 7,       # physical pin 26 (SPI CE1, SPI is off)
    "left": 8,      # physical pin 24 (SPI CE0)
    "right": 14,    # physical pin 8  (UART TX)
}

# ---------------- REFERENCE ----------------

# BCM GPIO -> physical header pin (Raspberry Pi 40-pin header)
PHYSICAL_PIN = {
    2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33,
    14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
    24: 18, 25: 22, 26: 37, 27: 13,
}


def all_pins(include_reserved=True):
    """[(label, bcm)] for every configured pin."""
    pins = [(f"left motor {k}", v) for k, v in LEFT_MOTOR.items()]
    pins += [(f"right motor {k}", v) for k, v in RIGHT_MOTOR.items()]
    for name, cfg in SONARS.items():
        pins += [(f"{name} sonar trigger", cfg["trigger"]), (f"{name} sonar echo", cfg["echo"])]
    pins += [("front IR", IR_FRONT), ("rear IR", IR_BACK)]
    pins += [(f"I2C {k.upper()} (IMU + OLED)", v) for k, v in I2C.items()]
    pins += [(f"touch pad {k}", v) for k, v in TOUCH.items()]
    if include_reserved:
        pins += [(f"encoder {k} (reserved)", v) for k, v in ENCODERS.items()]
    return pins


def validate():
    """Raise ValueError on duplicate or invalid pins. Called on import by the robot code."""
    seen = {}
    for label, pin in all_pins():
        if pin not in PHYSICAL_PIN:
            raise ValueError(f"{label}: GPIO {pin} is not a usable BCM pin")
        if pin in seen:
            raise ValueError(f"GPIO {pin} is used twice: {seen[pin]} and {label}")
        seen[pin] = label


validate()


if __name__ == "__main__":
    print(f"{'Signal':<28}{'GPIO':>6}{'Pin':>6}")
    print("-" * 40)
    for label, pin in all_pins():
        print(f"{label:<28}{pin:>6}{PHYSICAL_PIN[pin]:>6}")
    used = {p for _, p in all_pins()}
    free = sorted(p for p in PHYSICAL_PIN if p not in used)
    print(f"\nNo conflicts. Free GPIO: {', '.join(map(str, free))}")
