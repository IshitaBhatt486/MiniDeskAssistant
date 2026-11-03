"""
The companion runtime (18 Nov 2026): the assistant robot + a body that senses and reacts.

    python main.py                 menu for the whole project
    python main.py start [--sim]   start everything

    config.py       every tunable; data/companion.json overrides any of them
    shared.py       extra shared-memory blocks and the two extra processes' roles
    body.py         "body" process: MPU-6050 + orientation filter + OLED eyes
    imu.py          MPU-6050 / simulated IMU sources and the orientation filter
    eyes.py         draws the eyes (Pillow, luma.oled), plays animations, blinks, follows the user
    animations.py   the hardcoded animations: 9 emotions x 5
    emotion.py      decides how the robot feels from what is happening
    control.py      PID loops (simple-pid): straight driving, turn rate, facing the user, distance
    lift.py         picked up / put down (IMU + IR) and what to do afterwards
    gestures.py     MediaPipe hand gestures -> configurable robot actions
    calibration.py  the complete calibration routine
    outputs.py      the outputs/ folder: figures, telemetry, events, snapshots
    app.py          ties it together; dashboard routes
    cli.py          the single entry point behind main.py

Design and every constant: docs/companion.md
"""
