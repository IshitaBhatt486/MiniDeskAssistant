# first ssh
```bash

```
(or give a common ground for battery and )
```bash
boot pi and open terminal
python3 --version
sudo apt update
sudo apt install python3-gpiozero
```

(Note: we used gpiozero in the lab too)

# creating the project
```bash
mkdir -p ~/desk-assistant-robot/v1_step1
cd ~/desk-assistant-robot/v1_step1
nano main.py
python3 main.py

robot.forward(20) # robot should move forward
robot.stop() # should stop

robot.backward(20)
robot.stop()

robot.left(20)
robot.stop()

robot.right(20)
robot.stop()
```

if inverted direction of forward and backward: swap the motors- OUT3 ↔ OUT4

# make the interface better
```bash
nano cli.py
python3 cli.py

> forward 20
# forward at 20%

> stop
# Stopped

> left 30
# left at 30%

> stop
# Stopped
```

- to stop motor in an emergency, `CTRL + C`. the `finally` block converts it into `robot.stop()`




Notes: 
- GPIO pins operate at 3.3V logic. Connecting a 5V signal directly to a GPIO pin can
permanently damage the Raspberry Pi.
- GPIO pins cannot supply enough current to drive higher-power loads (e.g., motors) directly. Never connect a motor directly to a GPIO pin. A motor driver IC (e.g., L293D, L298N, TB6612FNG), powered from a separate supply, is required for that
- Always power off the Pi before wiring or rewiring GPIO circuits.
- PWM is commonly used to control LED brightness, motor speed, and servo position
- The Raspberry Pi supports hardware PWM on a limited number of pins (e.g., GPIO12, GPIO13, GPIO18, GPIO19) and software PWM (via libraries) on any GPIO pin, with somewhat reduced timing precision

- Logic voltage level: 3.3 V (not 5V tolerant)
- Max current per pin: ∼16 mA (recommended)
- Max total current (all GPIO): ∼50 mA
- Number of GPIO pins: 26 usable general-purpose pins
- Dedicated power pins: 3.3V (2), 5V (2), GND (8)