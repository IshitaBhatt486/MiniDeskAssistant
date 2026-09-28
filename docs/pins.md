# Pin map

> The pin numbers in code come from **`robot_config.py`** (repo root). This page explains the wiring; if the two ever disagree, `robot_config.py` is what runs. See config.md.

- Use BCM numbering (gpiozero default)
- ENA/IN1/IN2 → LEFT MOTOR
- ENB/IN3/IN4 → RIGHT MOTOR
- remove ENA/ENB jumpers in L298N if present (that lets the Pi control motor speed with PWM)

## L298N → Raspberry Pi

| L298N            | Raspberry Pi GPIO | Physical pin | In code |
| ---------------- | ----------------: | -----------: | ------- |
| ENA (left PWM)   |           GPIO 13 |       Pin 33 | `left_motor enable=13` |
| IN1 (left fwd)   |           GPIO 22 |       Pin 15 | `left_motor forward=22` |
| IN2 (left back)  |           GPIO 23 |       Pin 16 | `left_motor backward=23` |
| ENB (right PWM)  |           GPIO 12 |       Pin 32 | `right_motor enable=12` |
| IN3 (right fwd)  |           GPIO 27 |       Pin 13 | `right_motor forward=27` |
| IN4 (right back) |           GPIO 17 |       Pin 11 | `right_motor backward=17` |
| GND              |               GND |        Pin 6 | — |
| Motor supply `+` |       Battery `+` |            — | — |
| Motor supply `-` |       Battery `-` |            — | — |

- GPIO 12 and GPIO 13 are hardware-PWM capable pins, so they work well as enable pins.

## HC-SR04 ultrasonic sensor (front)

| HC-SR04 | Raspberry Pi | Physical pin |
| ------- | -----------: | -----------: |
| VCC     |          5 V |        Pin 2 |
| TRIG    |      GPIO 24 |       Pin 18 |
| ECHO    | GPIO 25 **through voltage divider** | Pin 22 |
| GND     |          GND |        Pin 6 / 9 / 14 |

- ECHO outputs 5 V. Use a divider (e.g. ECHO → 1 kΩ → GPIO25, with 2 kΩ from GPIO25 to GND) so the Pi sees about 3.3 V.
- Code: `DistanceSensor(echo=25, trigger=24, max_distance=2.0)`. The robot stops moving forward at `STOP_DISTANCE = 0.20` m.

## Extra HC-SR04 sensors (only for `13Nov-multisonar.py` / `server_multisonar.py`)

| Sensor | TRIG | Physical | ECHO (**via divider**) | Physical |
| ------ | ---: | -------: | ---------------------: | -------: |
| Left   | GPIO 4  | Pin 7  | GPIO 18 | Pin 12 |
| Right  | GPIO 21 | Pin 40 | GPIO 9  | Pin 21 |
| Rear   | GPIO 10 | Pin 19 | GPIO 11 | Pin 23 |

- VCC → 5 V, GND → GND for each one. Every ECHO gets its own 1 kΩ / 2 kΩ divider.
- GPIO 9/10/11 are SPI0 pins. Keep SPI disabled, or move these sensors if SPI is needed (see multisonar.md).

## IR edge sensors (bottom of chassis, facing the desk)

| Sensor    | OUT pin | Physical pin | VCC   |
| --------- | ------: | -----------: | ----- |
| Front IR  | GPIO 19 |       Pin 35 | 3.3 V (Pin 1 / 17) |
| Rear IR   | GPIO 26 |       Pin 37 | 3.3 V (Pin 1 / 17) |

- Output LOW (0) = floor detected, HIGH (1) = edge/drop (`FLOOR_VALUE = 0` in code).
- Power from 3.3 V so the output never exceeds 3.3 V. If the modules need 5 V, level-shift the OUT line.
- Adjust each module's potentiometer so that it reads LOW on the desk surface and HIGH when held over the edge.

# wiring

## motor to L298N
- Left motor wire 1 → OUT1
- Left motor wire 2 → OUT2

- Right motor wire 1 → OUT3
- Right motor wire 2 → OUT4

- if a motor spins the wrong way for "forward", swap its two wires (OUT1↔OUT2 or OUT3↔OUT4)

## motor battery
Battery + → L298N motor power input
Battery - → L298N GND

- all the grounds (battery, pi, L298N, sensors) should be common

## pins in use / free
- used (1 sonar): GPIO 12, 13, 17, 19, 22, 23, 24, 25, 26, 27
- used additionally with 4 sonars: GPIO 4, 9, 10, 11, 18, 21
- reserved for encoders: GPIO 5, 6, 16, 20
- still free: GPIO 2/3 (I2C, keep for a display), 7/8 (SPI CE), 14/15 (UART)

# notes
- ENA and ENB are the enable inputs for the two motor channels. the original jumper says "Keep this motor channel permanently enabled."
- previous pin map (ENA=GPIO18, IN1=23, IN2=24, ENB=GPIO19, IN3=27, IN4=22) is **obsolete**. GPIO 19/24 are now used by sensors.
