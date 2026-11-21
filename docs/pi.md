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

# running the robot (current: `3Nov-latest.py`)
```bash
mkdir -p ~/desk-assistant-robot
cd ~/desk-assistant-robot
# copy 3Nov-latest.py here (scp / USB / git)
python3 legacy/3Nov-latest.py
```

menu:
```
1. Forward
2. Backward
3. Left
4. Right
0. Exit
Enter your choice: 1
Enter movement duration (seconds): 2
```

- motors run at `SPEED = 0.5` (50% PWM) for the given number of seconds, then stop
- every 20 ms the script checks:
  - forward → front IR sees floor + ultrasonic distance > 20 cm
  - backward → rear IR sees floor
  - left/right → both IR sensors see floor
- if a check fails it prints e.g. `FRONT EDGE DETECTED! STOPPING.` / `OBSTACLE DETECTED: 15.2 cm` and stops

## test checklist
1. lift the robot off the desk (wheels free) and run each direction for 1 s. check that the wheels spin the right way
   - if forward/backward is inverted on one side: swap that motor's wires (OUT1 ↔ OUT2 or OUT3 ↔ OUT4)
2. put a hand < 20 cm in front of the ultrasonic sensor → forward should refuse/stop
3. hold the robot so the front IR is over the desk edge → forward should stop. do the same with the rear IR for backward
4. if the IR sensors stop the robot on a normal surface, tune their potentiometers, or flip `FLOOR_VALUE`

- to stop the motors in an emergency, `CTRL + C`. the `finally` block calls `stop()` and closes all motors/sensors

# web dashboard
```bash
cd ~/desk-assistant-robot
python3 dashboard/server.py                  # open http://localhost:8000 on the Pi
python3 dashboard/server.py --host 0.0.0.0   # open http://<pi-ip>:8000 from a laptop on the same wifi
hostname -I                                  # find the Pi's ip
```
- copy the whole `dashboard/` folder to the Pi along with the script
- on a laptop without the robot: `python dashboard/server.py --sim`
- no login. only use `--host 0.0.0.0` on a trusted network
- don't run it at the same time as `3Nov-latest.py` (GPIO pins busy)




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

## Installing the prototype (18 Nov 2026)

Copy only `run_prototype/` to the Pi; see [run-prototype.md](run-prototype.md). Memory budget, estimated: robot processes about 350 MB, vision stack
about 360 MB, local speech-to-text a few hundred MB while it transcribes. All of it is unverified on real hardware.

**Known CPU risk:** the navigation process is pinned to core 3 and also runs the mapper, web server and speech-to-text. While speech is being
transcribed, mapping and the dashboard will compete with it, and transcription may take longer than the figures quoted for an unpinned Pi.
Measure this first with `python benchmarks/benchmarks.py speech` from the full repository, or by timing a spoken command.

