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
Right encoder A	GPIO20	38
Right encoder B	GPIO16	36

> GPIO13 (pin 33) was the original choice for Right encoder A, but `3Nov-latest.py` now uses it as the left motor's ENA (PWM). Use GPIO20 (pin 38) instead. See pins.md for all pins in use.

- If your encoder is a common 5-V encoder, do not automatically connect its output directly to the Pi GPIO. Raspberry Pi GPIO is 3.3-V logic and is not 5-V tolerant.

## left encoder
Encoder A → GPIO5  (physical pin 29)
Encoder B → GPIO6  (physical pin 31)
GND       → Pi GND
VCC       → appropriate encoder supply
## right encoder
Encoder A → GPIO20 (physical pin 38)
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

# Encoders in the running robot (18 Nov 2026)

The encoders are expected on GPIO5/6 (left) and GPIO20/16 (right), at 3.3 V logic. The sensor process reads them with gpiozero
`RotaryEncoder` and publishes the counts at 50 Hz. If they can't be opened, the robot runs without them.

1. Lift the robot and run `python calibrate_encoders.py --diameter <metres> --revolutions 10`.
2. It stores counts per revolution and direction in `data/encoders.json`.

| Without calibration | With calibration |
|---|---|
| Stuck-wheel detection works | Also: the map pose uses measured wheel travel instead of motor commands |

**Stuck wheel:** a wheel commanded at 20% or more whose count changes by fewer than 2 for 0.8 s is stuck, provided that encoder has
been seen working. The robot stops, cancels its commands, says "Oops, looks like my wheel is stuck" and shows a sad face.
With gpiozero, Python handles each edge, so very high-resolution encoders may lose counts. If that happens, use `pigpio` or a hardware counter.
These paths have run in simulation and unit tests only.
