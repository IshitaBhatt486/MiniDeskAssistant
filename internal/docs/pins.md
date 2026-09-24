| L298N            | Raspberry Pi GPIO | Physical pin |
| ---------------- | ----------------: | -----------: |
| ENA              |           GPIO 18 |       Pin 12 |
| IN1              |           GPIO 23 |       Pin 16 |
| IN2              |           GPIO 24 |       Pin 18 |
| ENB              |           GPIO 19 |       Pin 35 |
| IN3              |           GPIO 27 |       Pin 13 |
| IN4              |           GPIO 22 |       Pin 15 |
| GND              |               GND |        Pin 6 |
| Motor supply `+` |       Battery `+` |            — |
| Motor supply `-` |       Battery `-` |            — |

- Use BCM numbering
- ENA/IN1/IN2 → LEFT MOTOR
- ENB/IN3/IN4 → RIGHT MOTOR
- remove ENA/ENB jumpers in L298N if present(That lets the Pi control motor speed.)

# wiring

## motor to L298N
- Left motor wire 1 → OUT1
- Left motor wire 2 → OUT2

- Right motor wire 1 → OUT3
- Right motor wire 2 → OUT4

## motor battery
Battery + → L298N motor power input
Battery - → L298N GND

- all the grounds(battery, pi, L298N) should be common

# notes
- ENA and ENB are the enable inputs for the two motor channels. the original jumper says "Keep this motor channel permanently enabled."