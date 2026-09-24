# encoder
- if quadrature encoder
Left A ──→ GPIO
Left B ──→ GPIO

Right A ─→ GPIO
Right B ─→ GPIO

the A/B signals tell us both:

how far the wheel moved
which direction it moved

Left encoder A	GPIO5	29 (phsyical pin)
Left encoder B	GPIO6	31
Right encoder A	GPIO13	33
Right encoder B	GPIO16	36

- If your encoder is a common 5-V encoder, do not automatically connect its output directly to the Pi GPIO. Raspberry Pi GPIO is 3.3-V logic and is not 5-V tolerant.

## left encoder
Encoder A → GPIO5  (physical pin 29)
Encoder B → GPIO6  (physical pin 31)
GND       → Pi GND
VCC       → appropriate encoder supply
## right encoder
Encoder A → GPIO13 (physical pin 33)
Encoder B → GPIO16 (physical pin 36)
GND       → Pi GND
VCC       → appropriate encoder supply

# calibrate
```bash
nano encoder_test.py
python encoder_test.py
```

Physically rotate the wheel exactly 10 revolutions.

Suppose it reports:

Left counts/rev   = 596.8
Right counts/rev  = 600.1
Average           = 598.45

Then change:

COUNTS_PER_REV = 598

test and check, then manually rotate the wheel backwards and verify that the count changes in the opposite direction if you're decoding quadrature direction.
- note the output: counts per revoltion= resolution
- measure wheel diameter
- then use distance per revolution = (pi*D)/counts per revolution

replace:
WHEEL_DIAMETER_CM = YOUR_WHEEL_DIAMETER
TRACK_WIDTH_CM = YOUR_TRACK_WIDTH (distance between)

```bash
nano motors.py
nano encoders.py
nano movement.py
```

- test:
```bash
python main.py
```

- T=distance between left and right wheel centers
- d=(θ*​π*T)/360 Each wheel needs to travel approximately d cm in opposite directions for an in place turn- The encoder tells you when that distance has been reached.

```bash
robot.turn(30)
robot.turn(45)
robot.turn(90)
```
- measure the angle turned manually using a protractor
