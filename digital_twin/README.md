# Digital twin (MATLAB)

A model of the desk robot: wheels and motor lag, desk and objects, sonars, edge sensors, gyro, safety rules and the
same PID loops as the robot. It needs base MATLAB R2021a or newer, with no toolboxes.

| Run | What it does |
| --- | --- |
| `run_twin` | Self-test, every scenario with and without control, graphs, animations, saved results |
| `twin_selftest` | Checks physics, PID conventions, safety rules and controller benefit |
| `log = twin_run('face_user'); twin_plot(log)` | One scenario's graphs: `straight`, `turn90`, `face_user`, `obstacle` |
| `twin_animate(log)` | Plays a run: robot, heading, sonar beams, path, wheel commands. `twin_animate(log, 'run.gif')` saves it |
| `twin_compare` | Replays the newest `outputs/*/telemetry.csv` through the model, plots and saves the error |
| `twin_live('http://deskbot.local:8000')` | Animates beside the live robot; saves the session when the time ends or the window closes |
| `twin_tune` | Searches yaw gains, draws a cost map and prints values for `data/companion.json` |

Everything is saved in `results/`: `results/latest` is the newest run, and the last 5 runs are kept as
`results/run_<date>_<time>`. Without opening the desktop app: `matlab -batch "cd digital_twin; run_twin"`.

`twin_params` loads `../data/calibration.json` automatically, so run `python main.py calibrate` first for a model of
your actual robot. On a laptop, copy that file from the Pi.

Limits: this is a kinematic model with first-order motors. It does not model wheel slip, the camera image or battery
discharge over time. The robot has no absolute position sensor, so `twin_compare` compares position with wheel
odometry and heading with the IMU.
